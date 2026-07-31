#!/usr/bin/env python
"""External-validity replication of the main findings on DAppSCAN.

Everything up to this point rests on one corpus of mostly single-file Etherscan
contracts, labelled by researchers. DAppSCAN is different in every way that
matters: 682 real DApp projects, multi-file, labelled by professional auditors
reading the code for money. If a finding is a property of detectors rather than
of one benchmark, it should reappear here.

Three claims are tested, in order of how much the paper depends on them:

  C1  the category-specific mechanism -- reentrancy detection degrades with
      complexity while arithmetic detection improves. This is the main claim.
  C2  complexity predicts analysis failure (crashes, not misses).
  C3  metric redundancy structure is stable across corpora.

A fourth question is forced on us by the data and is worth reporting in its own
right: whether a contract can be compiled at all is itself complexity-dependent,
which means every source-based tool evaluation on real projects carries a
survivorship bias that the literature does not discuss.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, SOLMET_METRICS, TABLES  # noqa: E402
from sccomplex.data import dappscan  # noqa: E402
from sccomplex.detect.slither_runner import (  # noqa: E402
    STATUS_OK,
    STATUS_UNRESOLVED,
)
from sccomplex.metrics.solmet import extract_corpus  # noqa: E402
from sccomplex.model import (  # noqa: E402
    per_group_slopes,
    select_metrics,
    spearman_redundancy,
    standardise,
)

pd.set_option("display.width", 200)
FOCUS = "LLOC"
METRICS_PATH = DATA_DERIVED / "dappscan_metrics.parquet"


def load_metrics() -> pd.DataFrame:
    """Per-contract complexity for the labelled DAppSCAN files."""
    if METRICS_PATH.exists():
        return pd.read_parquet(METRICS_PATH)

    paths = dappscan.contract_paths()
    print(f"extracting metrics for {len(paths)} contracts ...")
    df = extract_corpus(paths.values())

    # One row per file: DAppSCAN labels are file-level, so declarations within
    # a file are aggregated the same way as in the main study.
    df["contract"] = df["file"].map(lambda p: Path(p).stem)
    sums = ["SLOC", "LLOC", "CLOC", "NF", "WMC", "NL", "NLE", "NUMPAR", "NOS", "NA", "NOI"]
    maxs = ["DIT", "NOA", "NOD", "CBO"]
    avgs = [m for m in SOLMET_METRICS if m.startswith("Avg")]

    agg = {c: "sum" for c in sums} | {c: "max" for c in maxs} | {c: "mean" for c in avgs}
    out = df.groupby("contract").agg(agg).reset_index()
    out.to_parquet(METRICS_PATH, index=False)
    return out


def main() -> int:
    gt = dappscan.load_ground_truth()
    metrics = load_metrics()

    det_path = DATA_DERIVED / "dappscan_slither.parquet"
    if not det_path.exists():
        print("ERROR: run scripts/08_dappscan_detect.py first", file=sys.stderr)
        return 1
    det = pd.read_parquet(det_path)
    det["categories"] = det["categories"].map(list)

    print("=" * 78)
    print("DAppSCAN corpus")
    print("=" * 78)
    print(f"labels {len(gt):,} | contracts {gt.contract.nunique():,} "
          f"| projects {gt.project.nunique():,}")
    print(f"slither runs {len(det):,}")
    print(det["status"].value_counts().to_string())

    # ------------------------------------------------- compilability bias
    print("\n" + "=" * 78)
    print("SURVIVORSHIP CHECK  is compilability itself complexity-dependent?")
    print("=" * 78)
    comp = det.merge(metrics, on="contract", how="inner")
    comp["analysable"] = comp["status"].eq(STATUS_OK).astype(int)
    print(f"contracts with metrics + a run: {len(comp):,}")

    if comp["analysable"].nunique() > 1:
        for m in ("SLOC", "LLOC", "NOI", "CBO", "NF"):
            a = comp.loc[comp["analysable"] == 1, m]
            b = comp.loc[comp["analysable"] == 0, m]
            from scipy.stats import mannwhitneyu

            try:
                _, p = mannwhitneyu(a, b)
            except ValueError:
                p = np.nan
            print(f"  {m:<6} analysable median {a.median():8.1f} | "
                  f"not {b.median():8.1f} | Mann-Whitney p={p:.2e}")
        print("\nIf analysable contracts are systematically simpler, every")
        print("source-based tool evaluation on real projects is biased toward")
        print("simple code -- including this one. Reported as a threat to validity.")

    # ------------------------------------------------------------- C2
    print("\n" + "=" * 78)
    print("C2  complexity vs ANALYSIS failure (genuine errors only)")
    print("=" * 78)
    real = comp[comp["status"] != STATUS_UNRESOLVED].copy()
    real["failed"] = (real["status"] != STATUS_OK).astype(int)
    print(f"rows {len(real):,} (unresolved-import runs excluded) | "
          f"failure rate {real['failed'].mean():.1%}")

    if real["failed"].nunique() > 1 and len(real) > 50:
        sel = select_metrics(real, threshold=0.9)
        r = standardise(real, sel).assign(contract_id=real["contract"], category="any")
        r["contract"] = real["contract"]
        rows = []
        for m in sel:
            s = per_group_slopes(r.assign(_all="all"), "failed", m, "_all", min_n=50, min_events=10)
            rows.append({"metric": m, "coef": s["coef"].iloc[0], "p": s["p"].iloc[0]})
        tblC2 = pd.DataFrame(rows).sort_values("coef", ascending=False)
        tblC2.to_csv(TABLES / "dappscan_c2_analysis_failure.csv", index=False)
        print(tblC2.round(4).to_string(index=False))
    else:
        print("insufficient variation to model")

    # ------------------------------------------------------------- C1
    print("\n" + "=" * 78)
    print("C1  category-specific detection -- the main claim")
    print("=" * 78)
    ok = det[det["status"] == STATUS_OK][["contract", "categories"]]
    panel = (
        gt.merge(ok, on="contract", how="inner")
        .merge(metrics, on="contract", how="inner")
    )
    panel["missed"] = [
        0 if c in set(cats) else 1
        for c, cats in zip(panel["category"], panel["categories"])
    ]
    print(f"vulnerability instances on analysable contracts: {len(panel):,}")
    print(f"overall miss rate: {panel['missed'].mean():.1%}")
    print("\nmiss rate by category:")
    print(
        panel.groupby("category")["missed"]
        .agg(["mean", "size"])
        .rename(columns={"mean": "miss_rate", "size": "n"})
        .round(3)
        .to_string()
    )

    sel = select_metrics(panel, threshold=0.9) if len(panel) > 30 else []
    if FOCUS not in sel:
        sel = sel + [FOCUS]
    p = standardise(panel, sel)
    slopes = per_group_slopes(p, "missed", FOCUS, "category", min_n=30, min_events=5)
    slopes.to_csv(TABLES / "dappscan_c1_by_category.csv", index=False)
    print(f"\n{FOCUS} slope on detection failure, within category:")
    print(slopes.round(4).to_string(index=False))

    print("\nSalzano corpus, same analysis, for comparison:")
    ref = pd.read_csv(TABLES / "robust_c_by_category.csv")
    print(ref[["category", "n", "coef", "p"]].round(4).to_string(index=False))

    merged = slopes.merge(ref, on="category", how="inner", suffixes=("_dapp", "_salz"))
    if len(merged):
        both = merged.dropna(subset=["coef_dapp", "coef_salz"])
        agree = (np.sign(both["coef_dapp"]) == np.sign(both["coef_salz"])).sum()
        print(f"\ncategories estimable in both corpora: {len(both)}")
        print(f"sign agreement: {agree}/{len(both)}")
        print(both[["category", "coef_dapp", "p_dapp", "coef_salz", "p_salz"]]
              .round(4).to_string(index=False))
        merged.to_csv(TABLES / "dappscan_c1_comparison.csv", index=False)

    # ------------------------------------------------------------- C3
    print("\n" + "=" * 78)
    print("C3  metric redundancy structure")
    print("=" * 78)
    _, redundant = spearman_redundancy(metrics, threshold=0.9)
    print(f"pairs with |rho| >= 0.9: {len(redundant)}")
    if len(redundant):
        print(redundant.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    redundant.to_csv(TABLES / "dappscan_c3_redundancy.csv", index=False)

    print(f"\ntables written to {TABLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
