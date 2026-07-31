"""Loader for FORGE (Shen et al., ICSE 2026).

Third corpus, used to settle one specific question: does detector reliability
for **reentrancy** degrade or improve with complexity? The main corpus says
degrade (+0.278, p=0.0001), DAppSCAN says improve (-0.834, p=0.041), and the
DAppSCAN estimate rests on only 9 misses. FORGE has 351 projects with a
reentrancy finding, which is enough to break the tie.

FORGE differs from the other two corpora in ways that matter:

* Labels are extracted from real audit reports by an LLM pipeline, with
  reported 95.6% extraction precision. Noisier than DAppSCAN's human
  extraction, far larger.
* Findings carry a free-text `location` ("Functions `withdraw` and `claim`"),
  **not line numbers**. Only category-level matching is possible, which is this
  study's primary semantics anyway.
* The unit is the *project*, not the file: `project_path` maps a project name
  to a directory of contracts, and a finding refers to the project. Detection
  is therefore scored as "did the tool report this category anywhere in the
  project", a deliberately generous criterion.

Reentrancy is identified from finding titles and descriptions rather than from
the CWE hierarchy, because FORGE's CWE assignment for reentrancy is spread
across several high-level classes (CWE-691, CWE-664, CWE-841) that also cover
unrelated defects. Matching the text is more precise here, and the regex is
reported for auditability.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from sccomplex.config import FORGE_DIR

RESULTS = FORGE_DIR / "dataset" / "results"
CONTRACTS = FORGE_DIR / "dataset" / "contracts"

# Text patterns per DASP-10 class. Only classes we can identify reliably from
# audit-report prose are included; a class absent here is simply not analysed
# on this corpus rather than being scored as "not found".
CATEGORY_PATTERNS: dict[str, re.Pattern] = {
    "reentrancy": re.compile(r"re-?entran", re.I),
    "arithmetic": re.compile(r"\b(overflow|underflow|integer overflow)\b", re.I),
    "access_control": re.compile(
        r"\b(access control|unauthori[sz]ed|privilege escalation|missing (only)?owner|"
        r"unprotected)\b", re.I
    ),
    "unchecked_low_calls": re.compile(
        r"\bunchecked (return|call|low-level|send|transfer)\b", re.I
    ),
    "time_manipulation": re.compile(
        r"\b(block\.timestamp|timestamp dependen|miner manipulat)\w*", re.I
    ),
    "bad_randomness": re.compile(
        r"\b(weak random|predictable random|insecure random|blockhash)\w*", re.I
    ),
}


def _finding_text(finding: dict) -> str:
    return " ".join(
        str(finding.get(k) or "") for k in ("title", "description", "location")
    )


def load_ground_truth() -> pd.DataFrame:
    """One row per (project, DASP category) with an audit finding.

    Columns: report, project, project_path, category, n_findings, severities.
    """
    if not RESULTS.is_dir():
        raise FileNotFoundError(
            f"{RESULTS} not found. Run:\n"
            "  ./run.sh scripts/01_fetch_data.py --with-forge"
        )

    rows = []
    for f in sorted(RESULTS.glob("*.json")):
        try:
            doc = json.load(f.open())
        except (json.JSONDecodeError, OSError):
            continue

        info = doc.get("project_info") or {}
        paths = info.get("project_path") or {}
        if not paths:
            continue

        hits: dict[str, list[str]] = {}
        for finding in doc.get("findings") or []:
            text = _finding_text(finding)
            for cat, pat in CATEGORY_PATTERNS.items():
                if pat.search(text):
                    hits.setdefault(cat, []).append(str(finding.get("severity") or ""))

        for project, path in paths.items():
            for cat, sevs in hits.items():
                rows.append(
                    {
                        "report": f.stem,
                        "project": project,
                        "project_path": path,
                        "category": cat,
                        "n_findings": len(sevs),
                        "severities": ",".join(sorted(set(s for s in sevs if s))),
                    }
                )

    return pd.DataFrame(rows)


def project_files(project_path: str, limit: int | None = None) -> list[Path]:
    """The .sol files belonging to one project, if fetched."""
    root = FORGE_DIR / "dataset" / project_path
    if not root.is_dir():
        return []
    files = sorted(root.rglob("*.sol"))
    return files[:limit] if limit else files


def available_projects(categories: list[str] | None = None) -> pd.DataFrame:
    """Ground truth restricted to projects whose sources are on disk."""
    gt = load_ground_truth()
    if categories:
        gt = gt[gt["category"].isin(categories)]
    have = {p for p in gt["project_path"].unique() if project_files(p, limit=1)}
    return gt[gt["project_path"].isin(have)].copy()
