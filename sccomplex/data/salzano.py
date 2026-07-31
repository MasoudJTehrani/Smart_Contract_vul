"""Loader for the Salzano et al. (EMSE 2026) replication package.

Supplies the detection layer of this study: 19 tools run over 2,182 contracts,
with findings already normalised to the DASP-10 label space, plus manual
line-level ground truth.

Data provenance: the detection outcomes and ground-truth annotations are theirs
and must be cited as such. What this study adds is the complexity modelling on
top of them.

Encoding used throughout their CSVs, for both ground truth (`tag`) and tool
output (`Mapped_findings`):

    "no"                    -> nothing reported / contract annotated as safe
    "Error/Fail;"           -> the tool crashed, timed out, or failed to run
    "none: reentrancy;"     -> category reported, no line information
    "65: access_control;"   -> category at a single line
    "95-98: reentrancy;"    -> category over a line range

The `Error/Fail` case is kept distinct rather than collapsed into "not found":
a tool that never ran has failed in a different way from one that ran and
missed the bug, and the two are modelled separately.
"""
from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from sccomplex.config import SALZANO_DIR

csv.field_size_limit(sys.maxsize)

_TOKEN = re.compile(r"([^:;]+):\s*([^;]+);")
_RANGE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_EMPTY = "empty"


@dataclass(frozen=True)
class Finding:
    category: str
    lines: frozenset[int]  # empty when the tool gave no line information

    @property
    def has_lines(self) -> bool:
        return bool(self.lines)


def parse_findings(raw: str | float | None) -> tuple[str, list[Finding]]:
    """Parse one `tag` / `Mapped_findings` cell into (status, findings)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return STATUS_EMPTY, []

    text = str(raw).strip()
    if not text or text.lower().rstrip(";") == "no":
        return STATUS_EMPTY, []
    if "error" in text.lower() or "fail" in text.lower():
        return STATUS_ERROR, []

    findings: list[Finding] = []
    for line_part, cat_part in _TOKEN.findall(text):
        category = cat_part.strip().lower().replace(" ", "_")
        if not category:
            continue

        key = line_part.strip()
        lines: set[int] = set()
        if key.isdigit():
            lines.add(int(key))
        elif (m := _RANGE.match(key)) is not None:
            lo, hi = int(m.group(1)), int(m.group(2))
            if 0 <= hi - lo <= 10_000:  # guard against malformed spans
                lines.update(range(lo, hi + 1))
        # anything else ("none", "None", tool-specific junk) -> no line info

        findings.append(Finding(category=category, lines=frozenset(lines)))

    return (STATUS_OK if findings else STATUS_EMPTY), findings


# --------------------------------------------------------------------- files


def _path(*parts: str) -> Path:
    p = SALZANO_DIR.joinpath(*parts)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. Run scripts/01_fetch_data.py to clone the "
            "Salzano replication package into data/raw/."
        )
    return p


def load_ground_truth(exclude_arithmetic: bool = False) -> pd.DataFrame:
    """One row per annotated vulnerability instance.

    Columns: contract, corpus, category, lines (frozenset), is_safe.
    Contracts annotated as safe appear once with category NaN and is_safe True,
    so that they remain available for false-positive analysis.

    `exclude_arithmetic` mirrors Salzano's secondary analysis: pre-0.8 Solidity
    has no overflow checks, so arithmetic annotations are dense and dominate
    the label distribution.
    """
    src = _path("csvs", "sample_of_interest.csv")
    rows = []
    with src.open() as fh:
        for rec in csv.DictReader(fh):
            contract = rec["contract"].strip()
            corpus = rec["label"].strip()
            status, findings = parse_findings(rec["tag"])

            if not findings:
                rows.append(
                    {
                        "contract": contract,
                        "corpus": corpus,
                        "category": pd.NA,
                        "lines": frozenset(),
                        "is_safe": True,
                    }
                )
                continue

            for f in findings:
                if exclude_arithmetic and f.category == "arithmetic":
                    continue
                rows.append(
                    {
                        "contract": contract,
                        "corpus": corpus,
                        "category": f.category,
                        "lines": f.lines,
                        "is_safe": False,
                    }
                )

    return pd.DataFrame(rows)


def load_detections(exclude_arithmetic: bool = False) -> pd.DataFrame:
    """One row per (tool, contract) run.

    Columns: tool, contract, status, categories (frozenset), lines_by_category.
    `status` is one of ok / error / empty -- see module docstring.
    """
    name = (
        "vulnerabilities_log_without_arithmetic.csv"
        if exclude_arithmetic
        else "vulnerabilities_log.csv"
    )
    src = _path(name)

    rows = []
    with src.open() as fh:
        for rec in csv.DictReader(fh):
            status, findings = parse_findings(rec["Mapped_findings"])

            by_cat: dict[str, set[int]] = {}
            for f in findings:
                by_cat.setdefault(f.category, set()).update(f.lines)

            rows.append(
                {
                    "tool": rec["Tool"].strip().lower(),
                    "contract": rec["File name"].strip(),
                    "status": status,
                    "categories": frozenset(by_cat),
                    "lines_by_category": {k: frozenset(v) for k, v in by_cat.items()},
                }
            )

    return pd.DataFrame(rows)


def load_sources() -> pd.DataFrame:
    """Contract source code, keyed by contract id.

    Read from `sample_of_interest_with_code.csv` rather than the loose .sol
    files so that the code analysed is exactly the code the tools were run on.
    """
    src = _path("csvs", "sample_of_interest_with_code.csv")
    rows = []
    with src.open() as fh:
        for rec in csv.DictReader(fh):
            rows.append(
                {
                    "contract": rec["contract"].strip(),
                    "corpus": rec["label"].strip(),
                    "source": rec.get("contract_code") or "",
                }
            )
    return pd.DataFrame(rows)


def materialise_sources(dest: Path) -> list[Path]:
    """Write each contract's source to dest/<contract>.sol and return paths.

    The metric extractor works on files; this keeps that interface while the
    canonical source stays the CSV the tools were actually run against.
    """
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for rec in load_sources().itertuples():
        if not rec.source.strip():
            continue
        p = dest / f"{rec.contract}.sol"
        p.write_text(rec.source, encoding="utf8")
        paths.append(p)
    return paths
