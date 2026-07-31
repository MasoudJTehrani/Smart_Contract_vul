"""Loader for DAppSCAN (Zheng et al., TSE 2024).

External-validity corpus. Where the Salzano corpus is mostly single-file
Etherscan contracts, DAppSCAN is 682 real DApp *projects* audited by 29
professional security teams, with weaknesses extracted from 1,199 audit reports
and labelled against the SWC registry.

Two properties make it the right replication target:

  * contracts are far larger and genuinely multi-contract, so complexity has
    real range rather than the narrow band of curated benchmarks;
  * ground truth comes from human auditors reading the code for money, not from
    pattern matching, so it is not biased toward what static tools can see.

Label format, one JSON per labelled contract:

    {"filePath": "DAppSCAN-source/contracts/<team>-<project>/.../X.sol",
     "SWCs": "[{'category': 'SWC-107-Reentrancy',
                'function': 'withdraw', 'lineNumber': 'L142'}]"}

`SWCs` is a Python-literal string, not JSON, so it is parsed with
`ast.literal_eval` rather than `json.loads`.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pandas as pd

from sccomplex.config import DAPPSCAN_DIR

SWC_ROOT = DAPPSCAN_DIR / "DAppSCAN-source" / "SWCsource"

_LINE = re.compile(r"L?(\d+)")

# SWC -> DASP-10, so results are directly comparable with the main corpus.
# Only genuine vulnerability classes are mapped; code-quality findings
# (floating pragma, unused variables, outdated compiler) map to None and are
# excluded from the detection analysis rather than silently folded into
# "other", which would inflate the miss rate with things no security tool is
# expected to report as a vulnerability.
SWC_TO_DASP: dict[str, str | None] = {
    "SWC-101": "arithmetic",
    "SWC-107": "reentrancy",
    "SWC-104": "unchecked_low_calls",
    "SWC-113": "denial_service",
    "SWC-128": "denial_service",
    "SWC-114": "front_running",
    "SWC-116": "time_manipulation",
    "SWC-120": "bad_randomness",
    "SWC-105": "access_control",
    "SWC-106": "access_control",
    "SWC-115": "access_control",
    "SWC-112": "access_control",
    "SWC-100": "access_control",
    "SWC-108": "access_control",
    # code quality / not a DASP vulnerability class
    "SWC-102": None, "SWC-103": None, "SWC-109": None, "SWC-110": None,
    "SWC-111": None, "SWC-117": None, "SWC-118": None, "SWC-119": None,
    "SWC-121": None, "SWC-122": None, "SWC-123": None, "SWC-124": None,
    "SWC-125": None, "SWC-126": None, "SWC-127": None, "SWC-129": None,
    "SWC-130": None, "SWC-131": None, "SWC-132": None, "SWC-133": None,
    "SWC-134": None, "SWC-135": None, "SWC-136": None,
}


def _parse_swcs(raw) -> list[dict]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = ast.literal_eval(str(raw))
        return parsed if isinstance(parsed, list) else []
    except (ValueError, SyntaxError):
        return []


def _swc_id(category: str) -> str:
    m = re.match(r"(SWC-\d+)", str(category))
    return m.group(1) if m else ""


def load_ground_truth(include_unmapped: bool = False) -> pd.DataFrame:
    """One row per SWC label.

    Columns: contract, project, sol_path, swc, category, line.
    `category` is the DASP-10 class; rows whose SWC has no vulnerability
    counterpart are dropped unless `include_unmapped`.
    """
    if not SWC_ROOT.exists():
        raise FileNotFoundError(
            f"{SWC_ROOT} not found. Run:\n"
            "  ./run.sh scripts/01_fetch_data.py --with-dappscan"
        )

    rows = []
    for f in sorted(SWC_ROOT.rglob("*.json")):
        try:
            doc = json.load(f.open())
        except (json.JSONDecodeError, OSError):
            continue

        sol_path = doc.get("filePath", "")
        stem = Path(sol_path).stem
        # <team>-<project> is the second path component under contracts/
        parts = Path(sol_path).parts
        project = parts[2] if len(parts) > 2 else "unknown"

        for swc in _parse_swcs(doc.get("SWCs")):
            swc_id = _swc_id(swc.get("category", ""))
            dasp = SWC_TO_DASP.get(swc_id, None)
            if dasp is None and not include_unmapped:
                continue

            m = _LINE.search(str(swc.get("lineNumber", "")))
            rows.append(
                {
                    "contract": stem,
                    "project": project,
                    "sol_path": sol_path,
                    "swc": swc_id,
                    "swc_name": swc.get("category", ""),
                    "category": dasp,
                    "function": swc.get("function", ""),
                    "line": int(m.group(1)) if m else pd.NA,
                }
            )

    return pd.DataFrame(rows)


def contract_paths() -> dict[str, Path]:
    """Map contract stem -> on-disk .sol path, for files actually fetched."""
    out = {}
    for rec in load_ground_truth(include_unmapped=True).itertuples():
        p = DAPPSCAN_DIR / rec.sol_path
        if p.exists():
            out[rec.contract] = p
    return out
