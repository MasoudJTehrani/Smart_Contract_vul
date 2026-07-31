#!/usr/bin/env python
"""Build the analysis panels and write them to data/derived/.

Produces two tables:

  detection_panel.parquet : one row per (vulnerability instance, tool).
                            Outcome = did this tool find this specific bug.
  run_panel.parquet       : one row per (contract, tool) run.
                            Outcome = did the tool crash / time out.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, SOLMET_METRICS  # noqa: E402
from sccomplex.panel import (  # noqa: E402
    attach_metrics,
    build_detection_panel,
    build_run_panel,
)


def main() -> int:
    metrics = pd.read_parquet(DATA_DERIVED / "metrics.parquet")

    print("building detection panel ...")
    det = attach_metrics(build_detection_panel(), metrics)
    det.to_parquet(DATA_DERIVED / "detection_panel.parquet", index=False)

    print("building run panel ...")
    run = attach_metrics(build_run_panel(), metrics)
    run.to_parquet(DATA_DERIVED / "run_panel.parquet", index=False)

    print("\n=== detection panel ===")
    print(f"rows            : {len(det):,}")
    print(f"vulnerabilities : {det.groupby(['contract', 'category']).ngroups:,}")
    print(f"contracts       : {det['contract'].nunique():,}")
    print(f"tools           : {det['tool'].nunique()}")

    usable = det[det["detected_category"].notna()]
    print(f"\nrows with a completed run : {len(usable):,} "
          f"({len(usable) / len(det):.1%})")
    print(f"detected (category match) : {usable['detected_category'].mean():.1%}")
    print(f"detected (line match, +-5): {usable['detected_line'].mean():.1%}")

    print("\nper-corpus detection rate (category match):")
    print(
        usable.groupby("corpus")["detected_category"]
        .agg(["mean", "size"])
        .rename(columns={"mean": "detected", "size": "n"})
        .round(3)
        .to_string()
    )

    print("\nper-tool detection rate (category match), top and bottom:")
    by_tool = (
        usable.groupby("tool")["detected_category"]
        .agg(["mean", "size"])
        .rename(columns={"mean": "detected", "size": "n"})
        .sort_values("detected", ascending=False)
        .round(3)
    )
    print(by_tool.to_string())

    print("\n=== run panel ===")
    print(f"rows              : {len(run):,}")
    print(f"analysis failures : {run['analysis_failed'].mean():.1%}")
    print("\nanalysis-failure rate by tool:")
    print(
        run.groupby("tool")["analysis_failed"]
        .agg(["mean", "size"])
        .rename(columns={"mean": "fail_rate", "size": "n"})
        .sort_values("fail_rate", ascending=False)
        .round(3)
        .to_string()
    )

    # First look at the central question, before any modelling.
    print("\n=== raw signal check: outcome by SLOC quartile ===")
    run = run.copy()
    run["sloc_q"] = pd.qcut(run["SLOC"], 4, duplicates="drop")
    print("\nanalysis-failure rate:")
    print(run.groupby("sloc_q", observed=True)["analysis_failed"].mean().round(3).to_string())

    usable = usable.copy()
    usable["sloc_q"] = pd.qcut(usable["SLOC"], 4, duplicates="drop")
    print("\ndetection rate (category match):")
    print(
        usable.groupby("sloc_q", observed=True)["detected_category"]
        .mean()
        .round(3)
        .to_string()
    )

    missing = [m for m in SOLMET_METRICS if m not in det.columns]
    if missing:
        print(f"\nWARNING: metrics missing from panel: {missing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
