#!/usr/bin/env python
"""C2 revisited: does complexity predict *symbolic* analysis failure?

The main corpus found complexity predicting analysis failure with NOI odds
ratio 2.49, driven almost entirely by symbolic executors (manticore +1.03,
ethor-2023 +1.36) while the static analyser Slither ran *counter* to it
(-0.384). The first DAppSCAN replication used Slither only and therefore could
not test the claim at all. This script tests it with Mythril, a symbolic
executor, on the same contracts.

Outcome: `analysis_failed` = the run did not complete -- a timeout (state
explosion, the mechanism under test) or a crash. Runs that failed because a
dependency could not be resolved are excluded: the tool never saw the code.

The comparison that matters is Mythril vs Slither on *identical* contracts, so
the two are also modelled side by side. If complexity drives symbolic failure
specifically, Mythril's slope should be positive where Slither's is not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, TABLES  # noqa: E402
from sccomplex.model import per_group_slopes, select_metrics, standardise  # noqa: E402

pd.set_option("display.width", 200)
EXCLUDED = {"unresolved_import"}


def load(path: Path, tool: str) -> pd.DataFrame:
    df = pd.read_parquet(path)[["contract", "status"]].copy()
    df["tool"] = tool
    return df


def main() -> int:
    myth_path = DATA_DERIVED / "dappscan_mythril.parquet"
    if not myth_path.exists():
        print("ERROR: run scripts/11_dappscan_mythril.py first", file=sys.stderr)
        return 1

    metrics_df = pd.read_parquet(DATA_DERIVED / "dappscan_metrics.parquet")
    myth = load(myth_path, "mythril")
    slither = load(DATA_DERIVED / "dappscan_slither.parquet", "slither")

    both = pd.concat([myth, slither], ignore_index=True)
    both = both[~both["status"].isin(EXCLUDED)]
    both["analysis_failed"] = (both["status"] != "ok").astype(int)

    panel = both.merge(metrics_df, on="contract", how="inner")
    print("=" * 78)
    print("C2 revisited -- symbolic vs static analysis failure on DAppSCAN")
    print("=" * 78)
    print(
        panel.groupby("tool")["analysis_failed"]
        .agg(["mean", "size"])
        .rename(columns={"mean": "failure_rate", "size": "runs"})
        .round(3)
        .to_string()
    )

    print("\nMythril status breakdown (raw, before exclusions):")
    raw = pd.read_parquet(myth_path)
    print(raw["status"].value_counts().to_string())

    metrics = select_metrics(metrics_df, threshold=0.9)
    # per_group_slopes expects a category column for its within-group fixed
    # effects; at the run level there is no per-bug category.
    p = standardise(panel.assign(category="any"), metrics)

    print("\n" + "=" * 78)
    print("Complexity slopes on analysis failure, per tool")
    print("=" * 78)
    frames = []
    for metric in metrics:
        s = per_group_slopes(p, "analysis_failed", metric, "tool",
                             min_n=100, min_events=15)
        s["metric"] = metric
        frames.append(s)
    slopes = pd.concat(frames)

    wide = slopes.pivot(index="metric", columns="tool", values="coef")
    pvals = slopes.pivot(index="metric", columns="tool", values="p")
    out = wide.join(pvals, rsuffix="_p").sort_values(
        "mythril" if "mythril" in wide.columns else wide.columns[0], ascending=False
    )
    print(out.round(4).to_string())
    out.to_csv(TABLES / "dappscan_c2_symbolic_vs_static.csv")

    # Two separate slopes with opposite signs is suggestive, not a test. The
    # claim "symbolic executors degrade with complexity where static analysers
    # do not" is a statement about the *difference* of slopes, so it needs an
    # interaction term. Both tools ran on the same contracts, so standard
    # errors are clustered by contract.
    print("\n" + "=" * 78)
    print("Interaction test: does the complexity slope DIFFER by tool?")
    print("=" * 78)
    import statsmodels.formula.api as smf

    rows = []
    for metric in metrics:
        d = p[["analysis_failed", metric, "tool", "contract"]].dropna().copy()
        if d["tool"].nunique() < 2:
            continue
        try:
            m = smf.logit(
                f"analysis_failed ~ {metric} * C(tool, Treatment('slither'))", data=d
            )
            r = m.fit(
                disp=0, maxiter=200, cov_type="cluster",
                cov_kwds={"groups": d["contract"].astype("category").cat.codes.to_numpy()},
            )
            names = list(m.exog_names)
            inter = [n for n in names if n.startswith(metric) and ":" in n]
            if not inter:
                continue
            i = names.index(inter[0])
            rows.append({
                "metric": metric,
                "slither_slope": float(np.asarray(r.params)[names.index(metric)]),
                "mythril_minus_slither": float(np.asarray(r.params)[i]),
                "p_interaction": float(np.asarray(r.pvalues)[i]),
            })
        except Exception as e:
            rows.append({"metric": metric, "slither_slope": np.nan,
                         "mythril_minus_slither": np.nan, "p_interaction": np.nan})

    inter_tbl = pd.DataFrame(rows).sort_values("p_interaction")
    inter_tbl.to_csv(TABLES / "dappscan_c2_interaction.csv", index=False)
    print(inter_tbl.round(4).to_string(index=False))
    sig = inter_tbl[inter_tbl["p_interaction"] < 0.05]
    print(f"\nmetrics where symbolic and static differ significantly: "
          f"{sig['metric'].tolist() or 'none'}")

    print("\n" + "=" * 78)
    print("Comparison with the main corpus")
    print("=" * 78)
    # keep_default_na=False: one metric is literally named "NA" (number of
    # attributes) and pandas otherwise reads it back as a missing value.
    ref = pd.read_csv(TABLES / "rq3_analysis_failure.csv", index_col=0,
                      keep_default_na=False)
    ref[["coef", "p"]] = ref[["coef", "p"]].astype(float)
    ref_tool = pd.read_csv(TABLES / "slopes_by_tool_failed.csv")

    main_myth = ref_tool.loc[ref_tool["tool"] == "mythril", "coef"]
    main_slith = ref_tool.loc[ref_tool["tool"] == "slither", "coef"]
    print("main corpus, LLOC slope on analysis failure:")
    print(f"  mythril {float(main_myth.iloc[0]):+.4f}" if len(main_myth) else "  mythril n/a")
    print(f"  slither {float(main_slith.iloc[0]):+.4f}" if len(main_slith) else "  slither n/a")

    if "LLOC" in out.index:
        d_myth = out.loc["LLOC"].get("mythril", np.nan)
        d_slith = out.loc["LLOC"].get("slither", np.nan)
        print("\nDAppSCAN, LLOC slope on analysis failure:")
        print(f"  mythril {d_myth:+.4f}")
        print(f"  slither {d_slith:+.4f}")

        if len(main_myth) and not np.isnan(d_myth):
            agree = np.sign(float(main_myth.iloc[0])) == np.sign(d_myth)
            print(f"\nmythril sign agreement across corpora: {'YES' if agree else 'NO'}")

    print("\nmain-corpus pooled coefficients for reference:")
    print(ref[["coef", "p"]].round(4).to_string())
    print(f"\ntables written to {TABLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
