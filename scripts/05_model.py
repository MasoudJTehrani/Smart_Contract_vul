#!/usr/bin/env python
"""RQ1-RQ3: does complexity predict detector failure?

RQ1  metric redundancy on this corpus (replicates Paper 1's RQ1)
RQ2  does complexity predict *detection* failure (tool ran, missed the bug)
RQ3  does complexity predict *analysis* failure (tool crashed or timed out)

Both outcomes are coded so that 1 == failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, SOLMET_METRICS, TABLES  # noqa: E402
from sccomplex.model import (  # noqa: E402
    fit_failure_model,
    per_group_slopes,
    select_metrics,
    spearman_redundancy,
    standardise,
)

pd.set_option("display.width", 160)


def main() -> int:
    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    run = pd.read_parquet(DATA_DERIVED / "run_panel.parquet")

    # ---------------------------------------------------------------- RQ1
    print("=" * 72)
    print("RQ1  Metric redundancy on this corpus")
    print("=" * 72)
    per_contract = det.drop_duplicates("contract")
    corr, redundant = spearman_redundancy(per_contract, threshold=0.9)
    corr.to_csv(TABLES / "metric_correlation.csv")

    print(f"contracts: {len(per_contract):,}")
    print(f"pairs with |rho| >= 0.9: {len(redundant)}")
    if len(redundant):
        print(redundant.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    metrics = select_metrics(per_contract, threshold=0.9)
    dropped = [m for m in SOLMET_METRICS if m not in metrics]
    print(f"\nretained {len(metrics)}: {metrics}")
    print(f"dropped  {len(dropped)}: {dropped}")

    # ---------------------------------------------------------------- RQ2
    print("\n" + "=" * 72)
    print("RQ2  Complexity vs DETECTION failure (tool ran, missed the bug)")
    print("=" * 72)
    d = det[det["detected_category"].notna()].copy()
    d["missed"] = (~d["detected_category"].astype(bool)).astype(int)
    d = standardise(d, metrics)

    print(f"rows {len(d):,} | miss rate {d['missed'].mean():.1%} "
          f"| contracts {d['contract'].nunique():,} | tools {d['tool'].nunique()}")

    tbl_det, res_det, _ = fit_failure_model(d, "missed", metrics)
    if res_det.excluded_levels:
        print("\nexcluded (no outcome variation, cannot inform a complexity effect):")
        for k, v in res_det.excluded_levels.items():
            print(f"  {k}: {sorted(v)}")
    tbl_det = tbl_det.sort_values("coef", ascending=False)
    tbl_det.to_csv(TABLES / "rq2_detection_failure.csv")
    print("\ncoefficients (positive => more complexity, more misses),")
    print("tool and category fixed effects absorbed, SEs clustered by contract:")
    print(tbl_det.round(4).to_string())
    print(f"\npseudo R2 {res_det.prsquared:.4f}" if hasattr(res_det, "prsquared") else "")

    # ---------------------------------------------------------------- RQ3
    print("\n" + "=" * 72)
    print("RQ3  Complexity vs ANALYSIS failure (tool crashed or timed out)")
    print("=" * 72)
    r = run.copy()
    r["failed"] = r["analysis_failed"].astype(int)
    r["category"] = "any"  # no per-bug category at the run level
    r = standardise(r, metrics)

    print(f"rows {len(r):,} | failure rate {r['failed'].mean():.1%}")

    tbl_run, res_run, _ = fit_failure_model(r, "failed", metrics, controls=("tool",))
    if res_run.excluded_levels:
        print("\nexcluded (no outcome variation):")
        for k, v in res_run.excluded_levels.items():
            print(f"  {k}: {sorted(v)}")
    tbl_run = tbl_run.sort_values("coef", ascending=False)
    tbl_run.to_csv(TABLES / "rq3_analysis_failure.csv")
    print("\ncoefficients (positive => more complexity, more crashes),")
    print("tool fixed effects absorbed, SEs clustered by contract:")
    print(tbl_run.round(4).to_string())

    # ------------------------------------------------- per-tool heterogeneity
    print("\n" + "=" * 72)
    print("Per-tool complexity slope (LLOC) -- is the effect universal?")
    print("=" * 72)
    for label, panel, outcome in (
        ("detection failure", d, "missed"),
        ("analysis failure", r, "failed"),
    ):
        slopes = per_group_slopes(panel, outcome, "LLOC", "tool")
        slopes.to_csv(TABLES / f"slopes_by_tool_{outcome}.csv", index=False)
        print(f"\n--- {label} ---")
        print(slopes.round(4).to_string(index=False))

    print("\n" + "=" * 72)
    print("Per-detector-class complexity slope (LLOC)")
    print("=" * 72)
    for label, panel, outcome in (
        ("detection failure", d, "missed"),
        ("analysis failure", r, "failed"),
    ):
        slopes = per_group_slopes(panel, outcome, "LLOC", "detector_class")
        slopes.to_csv(TABLES / f"slopes_by_class_{outcome}.csv", index=False)
        print(f"\n--- {label} ---")
        print(slopes.round(4).to_string(index=False))

    print(f"\ntables written to {TABLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
