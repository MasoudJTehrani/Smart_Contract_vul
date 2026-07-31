"""Run Slither over a corpus and normalise its output to DASP-10.

Used for the DAppSCAN replication, where -- unlike the Salzano corpus -- no
detection outcomes ship with the data.

Two decisions worth stating:

* The tool-check -> DASP mapping is Salzano's, loaded from their replication
  package rather than re-derived. Using a different mapping would make the two
  corpora incomparable, and the mapping is the part of their work this study
  most depends on.

* Run outcomes are three-valued, not two. DAppSCAN files belong to real
  multi-file projects that import npm packages the dataset does not vendor
  (`@openzeppelin/contracts/...`). Those runs are `unresolved_import`: the tool
  was never handed the code, so this is an artefact of the harness, not a
  detector limitation. Only genuine crashes, timeouts and compiler errors are
  `error`. Collapsing the two would be doubly wrong -- larger projects import
  more, so the artefact correlates with complexity and would manufacture
  exactly the association this study is testing.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from sccomplex.config import SALZANO_DIR

PRAGMA = re.compile(r"pragma\s+solidity\s*([^;]+);")
VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_UNRESOLVED = "unresolved_import"

# Slither exits non-zero when it *finds* issues, so the return code says
# nothing about success. Only the JSON payload does.
_MISSING_IMPORT = re.compile(r'Source "([^"]+)" not found', re.I)
_BAD_VERSION = re.compile(
    r"different compiler version|requires different compiler|source file requires", re.I
)


def classify_error(stderr: str) -> tuple[str, str]:
    """Separate artefacts of our setup from genuine analysis failures.

    A contract that fails because an npm dependency was never vendored has not
    defeated the tool -- it was never handed the code. Counting that as an
    analysis failure would be doubly wrong here: larger projects import more,
    so the artefact correlates with complexity and would manufacture exactly
    the association this study is testing.
    """
    if not stderr:
        return STATUS_ERROR, "no output"
    if (m := _MISSING_IMPORT.search(stderr)) is not None:
        return STATUS_UNRESOLVED, f"missing import: {m.group(1)[:80]}"
    if _BAD_VERSION.search(stderr):
        return STATUS_ERROR, "compiler version mismatch"
    return STATUS_ERROR, stderr.strip()[-200:]


@dataclass
class SlitherResult:
    contract: str
    status: str
    categories: set[str] = field(default_factory=set)
    lines_by_category: dict[str, set[int]] = field(default_factory=dict)
    solc: str = ""
    error: str = ""


def load_dasp_mapping(tool: str = "slither") -> dict[str, str]:
    """check name -> DASP category, from Salzano's mapping table."""
    path = SALZANO_DIR / "smartbugs-results" / "metadata" / "vulnerabilities_mapping_DASP.csv"
    mapping: dict[str, str] = {}
    with path.open() as fh:
        for rec in csv.DictReader(fh):
            if rec["Tools"].strip().lower() != tool:
                continue
            for col, val in rec.items():
                if col in ("Tools", "Vulnerability name"):
                    continue
                if str(val).strip().lower() != "true":
                    continue
                cat = col.strip()
                if cat in ("Ignore", "Other"):
                    continue
                mapping[rec["Vulnerability name"].strip()] = cat.lower()
    return mapping


def pick_solc(sol: Path, available: list[str]) -> str | None:
    """Choose an installed solc satisfying the file's pragma.

    Only the lower bound is honoured (`^0.8.0` -> the lowest installed 0.8.x).
    Full semver range solving is not worth it here: a mis-picked version shows
    up as a compile error, which is recorded rather than silently dropped.
    """
    try:
        text = sol.read_text(errors="ignore")
    except OSError:
        return None

    m = PRAGMA.search(text)
    if not m:
        return None
    v = VERSION.search(m.group(1))
    if not v:
        return None

    want = tuple(int(x) for x in v.groups())
    parsed = sorted(
        (tuple(int(x) for x in s.split(".")), s) for s in available
    )
    # same major.minor, version >= the pragma's patch
    same_line = [s for t, s in parsed if t[:2] == want[:2] and t >= want]
    if same_line:
        return same_line[0]
    any_line = [s for t, s in parsed if t[:2] == want[:2]]
    return any_line[-1] if any_line else None


def build_remaps(sol: Path, vendor_dir: Path) -> list[str]:
    """solc import remappings for the vendored OpenZeppelin family.

    OpenZeppelin's major versions track compiler generations, so the version is
    chosen from the file's pragma. A wrong pick surfaces as a compile error and
    is recorded; it is never silently treated as a detector miss.
    """
    if not vendor_dir.exists():
        return []

    text = ""
    try:
        text = sol.read_text(errors="ignore")
    except OSError:
        pass

    minor = (0, 8)
    if (m := PRAGMA.search(text)) and (v := VERSION.search(m.group(1))):
        minor = (int(v.group(1)), int(v.group(2)))

    if minor <= (0, 4):
        oz, ozu = "2.5.1", "3.4.2"
        legacy = "1.12.0"
    elif minor == (0, 5):
        oz, ozu, legacy = "2.5.1", "3.4.2", "2.5.1"
    elif minor in ((0, 6), (0, 7)):
        oz, ozu, legacy = "3.4.2", "3.4.2", "2.5.1"
    else:
        oz, ozu, legacy = "4.9.6", "4.9.6", "2.5.1"

    def d(pkg: str, ver: str) -> Path:
        return vendor_dir / f"{pkg.replace('/', '__')}@{ver}"

    candidates = {
        "@openzeppelin/contracts": d("@openzeppelin/contracts", oz),
        "@openzeppelin/contracts-upgradeable": d("@openzeppelin/contracts-upgradeable", ozu),
        "@openzeppelin/contracts-ethereum-package": d(
            "@openzeppelin/contracts-ethereum-package", "3.0.0"
        ),
        "@openzeppelinV3/contracts": d("@openzeppelin/contracts", "3.4.2"),
        "openzeppelin-solidity": d("openzeppelin-solidity", legacy),
        "openzeppelin-solidity-2.3.0": d("openzeppelin-solidity", "2.3.0"),
        "zeppelin-solidity": d("zeppelin-solidity", "1.12.0"),
    }

    return [f"{prefix}={path}" for prefix, path in candidates.items() if path.exists()]


def installed_solc(solc_select: str) -> list[str]:
    out = subprocess.run([solc_select, "versions"], capture_output=True, text=True)
    return [
        line.split()[0].strip()
        for line in out.stdout.splitlines()
        if VERSION.fullmatch(line.split()[0].strip() or "x")
    ]


def run_one(
    sol: Path,
    contract_id: str,
    mapping: dict[str, str],
    solc_versions: list[str],
    slither_bin: str,
    solc_select_bin: str,
    timeout: int = 180,
    remaps: list[str] | None = None,
) -> SlitherResult:
    res = SlitherResult(contract=contract_id, status=STATUS_ERROR)

    version = pick_solc(sol, solc_versions)
    if version:
        res.solc = version
        subprocess.run(
            [solc_select_bin, "use", version], capture_output=True, timeout=60
        )

    cmd = [slither_bin, str(sol), "--json", "-"]
    if remaps:
        cmd += ["--solc-remaps", " ".join(remaps)]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=sol.parent
        )
    except subprocess.TimeoutExpired:
        res.status, res.error = STATUS_ERROR, "timeout"
        return res
    except OSError as e:
        res.status, res.error = STATUS_ERROR, f"exec:{e}"
        return res

    # Slither writes JSON to stdout; a crash leaves it empty or unparseable.
    payload = None
    for chunk in (proc.stdout, proc.stderr):
        if not chunk:
            continue
        start = chunk.find("{")
        if start == -1:
            continue
        try:
            payload = json.loads(chunk[start:])
            break
        except json.JSONDecodeError:
            continue

    if payload is None or not payload.get("success", False):
        # A plain run surfaces the compiler diagnostics that --json swallows.
        diag = proc.stderr or ""
        if not diag.strip():
            try:
                plain = subprocess.run(
                    [slither_bin, str(sol)],
                    capture_output=True, text=True, timeout=timeout, cwd=sol.parent,
                )
                diag = plain.stderr or ""
            except (subprocess.TimeoutExpired, OSError):
                diag = "timeout while diagnosing"
        res.status, res.error = classify_error(diag)
        return res

    res.status = STATUS_OK
    for det in (payload.get("results") or {}).get("detectors", []) or []:
        cat = mapping.get(det.get("check", ""))
        if not cat:
            continue
        lines: set[int] = set()
        for el in det.get("elements", []) or []:
            lines.update((el.get("source_mapping") or {}).get("lines") or [])
        res.categories.add(cat)
        res.lines_by_category.setdefault(cat, set()).update(lines)

    return res
