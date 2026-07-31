#!/usr/bin/env python
"""Robustness checks for the RQ2/RQ3 sign findings.

The concern: larger contracts carry more annotated vulnerabilities, skewed
toward common easy-to-find types (arithmetic is 716 of 1,829 instances). If the
negative complexity slopes are really "big contracts have more arithmetic
labels", they are an artefact of label density, not a property of the detectors.

Four independent checks, each of which would break the finding if it were
spurious:

  A. control for the number of annotated bugs in the contract
  B. restrict to contracts with exactly one annotated bug (no density to confound)
  C. estimate the slope separately within each vulnerability category
  D. re-run on the arithmetic-excluded annotation set Salzano ships

A finding that survives all four is not a label-density artefact.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, TABLES  # noqa: E402
from sccomplex.model import (  # noqa: E402
    fit_failure_model,
    per_group_slopes,
    select_metrics,
    standardise,
)
from sccomplex.panel import attach_metrics, build_detection_panel  # noqa: E402

pd.set_option("display.width", 200)

FOCUS = "LLOC"  # the metric whose sign is under scrutiny


def _prep(det: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    d = det[det["detected_category"].notna()].copy()
    d["missed"] = (~d["detected_category"].astype(bool)).astype(int)
    # Label density: how many distinct annotated bugs does this contract carry?
    density = (
        d.drop_duplicates(["contract", "category"])
        .groupby("contract")
        .size()
        .rename("n_bugs")
    )
    d = d.merge(density, left_on="contract", right_index=True, how="left")
    return standardise(d, metrics)


def main() -> int:
    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    per_contract = det.drop_duplicates("contract")
    metrics = select_metrics(per_contract, threshold=0.9)

    d = _prep(det, metrics)
    baseline_tools = per_group_slopes(d, "missed", FOCUS, "tool").set_index("tool")

    print("=" * 78)
    print("BASELINE  per-tool LLOC slope on detection failure")
    print("=" * 78)
    print(baseline_tools[["n", "events", "coef", "p"]].dropna().round(4).to_string())

    results: dict[str, pd.Series] = {"baseline": baseline_tools["coef"]}

    # ------------------------------------------------------------------ A
    print("\n" + "=" * 78)
    print("CHECK A  control for number of annotated bugs per contract")
    print("=" * 78)
    dA = d.copy()
    dA["n_bugs_z"] = (
        np.log1p(dA["n_bugs"]) - np.log1p(dA["n_bugs"]).mean()
    ) / np.log1p(dA["n_bugs"]).std()

    tblA, resA, _ = fit_failure_model(dA, "missed", metrics + ["n_bugs_z"])
    tblA.to_csv(TABLES / "robust_a_bugdensity_control.csv")
    print(tblA.sort_values("coef", ascending=False).round(4).to_string())
    print(f"\n  label-density term itself: coef={tblA.loc['n_bugs_z', 'coef']:+.4f} "
          f"p={tblA.loc['n_bugs_z', 'p']:.4f}")

    rowsA = []
    for tool, sub in dA.groupby("tool", observed=True):
        s = per_group_slopes(sub.assign(_t=tool), "missed", FOCUS, "_t")
        rowsA.append({"tool": tool, "coef": s["coef"].iloc[0]})
    results["A: +density ctrl"] = pd.DataFrame(rowsA).set_index("tool")["coef"]

    # ------------------------------------------------------------------ B
    print("\n" + "=" * 78)
    print("CHECK B  contracts with exactly one annotated bug")
    print("=" * 78)
    dB = d[d["n_bugs"] == 1]
    print(f"rows {len(dB):,} | contracts {dB['contract'].nunique():,} "
          f"| miss rate {dB['missed'].mean():.1%}")
    sB = per_group_slopes(dB, "missed", FOCUS, "tool").set_index("tool")
    sB.to_csv(TABLES / "robust_b_single_bug.csv")
    print(sB[["n", "events", "coef", "p"]].dropna().round(4).to_string())
    results["B: single-bug"] = sB["coef"]

    # ------------------------------------------------------------------ C
    print("\n" + "=" * 78)
    print("CHECK C  slope within each vulnerability category")
    print("=" * 78)
    sC = per_group_slopes(d, "missed", FOCUS, "category").set_index("category")
    sC.to_csv(TABLES / "robust_c_by_category.csv")
    print(sC[["n", "events", "coef", "p"]].round(4).to_string())

    # ------------------------------------------------------------------ D
    print("\n" + "=" * 78)
    print("CHECK D  arithmetic-excluded annotation set")
    print("=" * 78)
    metrics_df = pd.read_parquet(DATA_DERIVED / "metrics.parquet")
    detD = attach_metrics(build_detection_panel(exclude_arithmetic=True), metrics_df)
    dD = _prep(detD, metrics)
    print(f"rows {len(dD):,} | contracts {dD['contract'].nunique():,} "
          f"| miss rate {dD['missed'].mean():.1%}")
    sD = per_group_slopes(dD, "missed", FOCUS, "tool").set_index("tool")
    sD.to_csv(TABLES / "robust_d_no_arithmetic.csv")
    print(sD[["n", "events", "coef", "p"]].dropna().round(4).to_string())
    results["D: no arithmetic"] = sD["coef"]

    # --------------------------------------------------------------- verdict
    print("\n" + "=" * 78)
    print("VERDICT  LLOC slope on detection failure across specifications")
    print("=" * 78)
    comp = pd.DataFrame(results).dropna(how="all")
    comp["sign_stable"] = comp.apply(
        lambda r: len({np.sign(v) for v in r.dropna() if v == v}) == 1, axis=1
    )
    print(comp.round(4).to_string())

    stable = comp[comp["sign_stable"]].index.tolist()
    flipped = comp[~comp["sign_stable"]].index.tolist()
    print(f"\nsign stable across all specifications : {stable}")
    print(f"sign flips somewhere (do not report)   : {flipped}")

    comp.to_csv(TABLES / "robust_verdict.csv")
    print(f"\ntables written to {TABLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
