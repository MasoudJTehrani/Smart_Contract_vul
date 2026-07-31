"""Solmet-compatible extraction of the 21 complexity metrics, per contract.

Why not Solmet itself: Solmet (Hegedus 2019) is a Java tool built against an
older Solidity grammar and fails to parse a large share of modern real-world
contracts. Slither-based extraction is not an option either -- it requires
successful compilation, which biases the sample toward contracts that compile,
and compilability is itself correlated with complexity.

This module parses with tree-sitter-solidity, which is compilation-free and
version-agnostic, and computes the same 21 metrics. Definitions follow Solmet /
SourceMeter conventions; every deviation is flagged in DEVIATIONS below and
must be reported as a threat to validity.

Unit of analysis is the *contract*, not the file: a .sol file may declare
several contracts, and Paper 1 analysed contracts individually.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_solidity as tss
from tree_sitter import Language, Parser

log = logging.getLogger(__name__)

DEVIATIONS = """
1. McCC counts if / for / while / do-while / catch / ternary / case labels.
   Boolean operators (&& ||) are NOT counted, matching McCabe rather than
   'strict' cyclomatic complexity, consistent with Solmet's Avg. McCC.
2. CBO is resolved against contract names declared in the same compilation
   unit. Types reached through uninlined external imports are not counted,
   making CBO a lower bound on true coupling.
3. NOD / NOA / DIT are computed per compilation unit, not corpus-wide: name
   collisions across projects are pervasive (every corpus has many `Ownable`s)
   and a global graph inflates NOD by orders of magnitude. A contract whose
   parent is declared outside the file contributes an edge to an unresolved
   node, counted in NOA but not expandable further.
4. NA counts state variable declarations (Solmet's 'number of attributes').
"""

# ---------------------------------------------------------------- grammar map

DECL_TYPES = {"contract_declaration", "interface_declaration", "library_declaration"}

FUNCTION_TYPES = {
    "function_definition",
    "constructor_definition",
    "modifier_definition",
    "fallback_receive_definition",
}

# Control structures that add a decision point (McCabe) and open a nesting level.
BRANCH_TYPES = {
    "if_statement",
    "for_statement",
    "while_statement",
    "do_while_statement",
    "catch_clause",
    "ternary_expression",
    "conditional_expression",
}

# Nesting is measured over real control structures only (a catch clause or a
# ternary does not open a nesting level in Solmet's sense).
NESTING_TYPES = {"if_statement", "for_statement", "while_statement", "do_while_statement"}

STATEMENT_SUFFIX = "_statement"
NON_STATEMENT = {"block_statement"}  # a block is not itself a statement

CALL_TYPES = {"call_expression", "function_call_expression"}
STATE_VAR_TYPES = {"state_variable_declaration"}
COMMENT_TYPES = {"comment", "line_comment", "block_comment"}

_LANGUAGE = Language(tss.language())


def _parser() -> Parser:
    return Parser(_LANGUAGE)


# ------------------------------------------------------------------ container


@dataclass
class ContractRaw:
    """Per-contract measurements taken before the corpus-wide graph is known."""

    contract_id: str
    file: str
    name: str
    kind: str
    parents: list[str] = field(default_factory=list)
    referenced: set[str] = field(default_factory=set)

    SLOC: int = 0
    LLOC: int = 0
    CLOC: int = 0
    NF: int = 0
    WMC: int = 0
    NL: int = 0
    NLE: int = 0
    NUMPAR: int = 0
    NOS: int = 0
    NA: int = 0
    NOI: int = 0


# ------------------------------------------------------------------ traversal


def _walk(node, skip: set[str] | None = None):
    """Depth-first walk, optionally pruning whole subtrees by node type."""
    skip = skip or set()
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        for c in n.children:
            if c.type not in skip:
                stack.append(c)


def _text(node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf8", errors="replace")


def _child_of_type(node, types: set[str] | str):
    types = {types} if isinstance(types, str) else types
    for c in node.children:
        if c.type in types:
            return c
    return None


def _nesting_depth(fn_node) -> int:
    """Deepest nesting level of control structures inside one function."""
    best = 0

    def rec(node, depth):
        nonlocal best
        for c in node.children:
            d = depth + 1 if c.type in NESTING_TYPES else depth
            best = max(best, d)
            rec(c, d)

    rec(fn_node, 0)
    return best


def _else_if_depth(fn_node) -> int:
    """Deepest nesting counting only if / else-if chains (Solmet's NLE)."""
    best = 0

    def rec(node, depth):
        nonlocal best
        for c in node.children:
            d = depth + 1 if c.type == "if_statement" else depth
            best = max(best, d)
            rec(c, d)

    rec(fn_node, 0)
    return best


def _count_params(fn_node) -> int:
    """Formal input parameters only.

    The grammar emits `parameter` for return values and for try/catch bindings
    as well, so those subtrees are pruned -- otherwise NUMPAR is inflated by
    roughly the number of returning functions.
    """
    skip = {"return_type_definition", "function_body"}
    return sum(
        1
        for node in _walk(fn_node, skip=skip)
        if node.type in ("parameter", "function_parameter")
    )


def _mccabe(fn_node) -> int:
    """McCabe cyclomatic complexity of a single function."""
    decisions = 0
    for node in _walk(fn_node):
        if node.type in BRANCH_TYPES:
            decisions += 1
        # switch/case does not exist in Solidity; kept for grammar robustness.
        elif node.type in ("case_clause", "switch_case"):
            decisions += 1
    return decisions + 1


def _count_statements(node) -> int:
    return sum(
        1
        for n in _walk(node)
        if n.type.endswith(STATEMENT_SUFFIX) and n.type not in NON_STATEMENT
    )


def _line_metrics(node, src: bytes) -> tuple[int, int, int]:
    """SLOC, LLOC, CLOC over the contract's own source span."""
    start, end = node.start_point[0], node.end_point[0]
    lines = src.decode("utf8", errors="replace").splitlines()[start : end + 1]
    sloc = len(lines)

    comment_lines: set[int] = set()
    for n in _walk(node):
        if n.type in COMMENT_TYPES:
            for ln in range(n.start_point[0], n.end_point[0] + 1):
                comment_lines.add(ln - start)

    cloc = len(comment_lines)
    lloc = sum(
        1
        for i, raw in enumerate(lines)
        if raw.strip() and i not in comment_lines
    )
    return sloc, lloc, cloc


# ------------------------------------------------------------------ per-file


def parse_file(path: Path, parser: Parser | None = None) -> list[ContractRaw]:
    """Extract raw per-contract measurements from one .sol file."""
    parser = parser or _parser()
    try:
        src = path.read_bytes()
    except OSError as e:  # unreadable file
        log.warning("cannot read %s: %s", path, e)
        return []

    tree = parser.parse(src)
    out: list[ContractRaw] = []

    for node in _walk(tree.root_node):
        if node.type not in DECL_TYPES:
            continue

        name_node = node.child_by_field_name("name") or _child_of_type(node, "identifier")
        name = _text(name_node, src) if name_node else "<anonymous>"

        raw = ContractRaw(
            contract_id=f"{path.stem}:{name}",
            file=str(path),
            name=name,
            kind=node.type.replace("_declaration", ""),
        )
        raw.SLOC, raw.LLOC, raw.CLOC = _line_metrics(node, src)

        # Inheritance: names appearing in inheritance specifiers.
        for n in _walk(node):
            if n.type in ("inheritance_specifier", "base_contract"):
                ident = _child_of_type(n, {"identifier", "user_defined_type"})
                target = ident if ident is not None else n
                raw.parents.append(_text(target, src).split("(")[0].strip())

        body = node.child_by_field_name("body") or _child_of_type(node, "contract_body")
        scope = body if body is not None else node

        nl_sum = nle_sum = 0
        for n in _walk(scope):
            if n.type in FUNCTION_TYPES:
                raw.NF += 1
                raw.WMC += _mccabe(n)
                nl_sum += _nesting_depth(n)
                nle_sum += _else_if_depth(n)
                raw.NUMPAR += _count_params(n)
            elif n.type in STATE_VAR_TYPES:
                raw.NA += 1
            elif n.type in CALL_TYPES:
                raw.NOI += 1

            if n.type == "identifier":
                raw.referenced.add(_text(n, src))

        raw.NL, raw.NLE = nl_sum, nle_sum
        raw.NOS = _count_statements(scope)
        out.append(raw)

    return out


# ------------------------------------------------------------- corpus passes


def _inheritance_metrics_one_file(raws: list[ContractRaw]) -> dict[str, dict[str, int]]:
    """DIT, NOA, NOD within a single compilation unit.

    Scoped per file, not per corpus. Solidity resolves inheritance within a
    compilation unit, and these contracts are flattened single-file sources, so
    a global name-keyed graph is simply wrong: it merges every `Ownable` in the
    corpus into one node and reports hundreds of descendants for each.
    """
    parents_of = {r.name: set(r.parents) for r in raws}
    children_of: dict[str, set[str]] = {}
    for r in raws:
        for p in r.parents:
            children_of.setdefault(p, set()).add(r.name)

    def ancestors(name: str) -> set[str]:
        seen, q = set(), deque(parents_of.get(name, ()))
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            q.extend(parents_of.get(cur, ()))
        return seen

    def descendants(name: str) -> set[str]:
        seen, q = set(), deque(children_of.get(name, ()))
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            q.extend(children_of.get(cur, ()))
        return seen

    def depth(name: str) -> int:
        best, q = 0, deque([(name, 0)])
        visited = set()
        while q:
            cur, d = q.popleft()
            if cur in visited:
                continue
            visited.add(cur)
            best = max(best, d)
            for p in parents_of.get(cur, ()):
                q.append((p, d + 1))
        return best

    return {
        r.contract_id: {
            "DIT": depth(r.name),
            "NOA": len(ancestors(r.name)),
            "NOD": len(descendants(r.name)),
        }
        for r in raws
    }


def _by_file(raws: list[ContractRaw]) -> dict[str, list[ContractRaw]]:
    out: dict[str, list[ContractRaw]] = {}
    for r in raws:
        out.setdefault(r.file, []).append(r)
    return out


def _inheritance_metrics(raws: list[ContractRaw]) -> dict[str, dict[str, int]]:
    """DIT, NOA, NOD, computed independently within each compilation unit."""
    out: dict[str, dict[str, int]] = {}
    for group in _by_file(raws).values():
        out.update(_inheritance_metrics_one_file(group))
    return out


def _cbo(raws: list[ContractRaw]) -> dict[str, int]:
    """Coupling between contracts: distinct sibling contract types referenced.

    Scoped per file for the same reason as the inheritance metrics.
    """
    out = {}
    for group in _by_file(raws).values():
        declared = {r.name for r in group}
        for r in group:
            coupled = (r.referenced & declared) | (set(r.parents) & declared)
            coupled.discard(r.name)
            out[r.contract_id] = len(coupled)
    return out


def extract_corpus(paths, progress=True):
    """Run both passes over a corpus and return a DataFrame of 21 metrics.

    Returns one row per contract with the columns in config.SOLMET_METRICS.
    """
    import pandas as pd

    paths = list(paths)
    parser = _parser()
    raws: list[ContractRaw] = []

    it = paths
    if progress:
        try:
            from tqdm import tqdm

            it = tqdm(paths, desc="parsing contracts")
        except ImportError:
            pass

    for p in it:
        raws.extend(parse_file(Path(p), parser))

    if not raws:
        return pd.DataFrame()

    inh = _inheritance_metrics(raws)
    cbo = _cbo(raws)

    rows = []
    for r in raws:
        nf = r.NF or 1  # averages are undefined for contracts with no functions
        rows.append(
            {
                "contract_id": r.contract_id,
                "file": r.file,
                "name": r.name,
                "kind": r.kind,
                "SLOC": r.SLOC,
                "LLOC": r.LLOC,
                "CLOC": r.CLOC,
                "NF": r.NF,
                "WMC": r.WMC,
                "NL": r.NL,
                "NLE": r.NLE,
                "NUMPAR": r.NUMPAR,
                "NOS": r.NOS,
                "DIT": inh[r.contract_id]["DIT"],
                "NOA": inh[r.contract_id]["NOA"],
                "NOD": inh[r.contract_id]["NOD"],
                "CBO": cbo[r.contract_id],
                "NA": r.NA,
                "NOI": r.NOI,
                "AvgMcCC": r.WMC / nf,
                "AvgNL": r.NL / nf,
                "AvgNLE": r.NLE / nf,
                "AvgNUMPAR": r.NUMPAR / nf,
                "AvgNOS": r.NOS / nf,
                "AvgNOI": r.NOI / nf,
            }
        )

    return pd.DataFrame(rows)
