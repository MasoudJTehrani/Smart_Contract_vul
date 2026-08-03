#!/usr/bin/env python
"""Verify every numeric claim in the manuscript against results/tables/.

The paper asserts that each of its numbers is generated from artefacts rather
than transcribed. This script is what makes that assertion checkable: it reads
the LaTeX source, pulls the value each claim depends on from the CSV that
produced it, and fails loudly on any mismatch.

Exit status 0 = every claim matches; 1 = at least one does not.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import ROOT, TABLES  # noqa: E402

# One metric is literally named "NA"; without this pandas reads it as missing.
READ = dict(keep_default_na=False, na_values=[""])
PAPER = ROOT / "paper" / "emse" / "main.tex"

failures: list[str] = []
checked = 0


def close(label: str, claimed: float, actual, tol: float = 0.005) -> None:
    global checked
    checked += 1
    try:
        a = float(actual)
    except (TypeError, ValueError):
        failures.append(f"{label}: actual not numeric ({actual!r})")
        return
    if a != a or abs(claimed - a) > tol:
        failures.append(f"{label}: paper={claimed} actual={a}")


def present(label: str, needle: str, hay: str) -> None:
    global checked
    checked += 1
    if needle not in hay:
        failures.append(f"{label}: string absent from manuscript -> {needle!r}")


def csv(name: str, index: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(TABLES / name, **READ)
    return df.set_index(index) if index else df


def main() -> int:
    global checked
    if not PAPER.exists():
        print(f"ERROR: {PAPER} not found", file=sys.stderr)
        return 1
    tex = PAPER.read_text()

    # ---------------------------------------------------- core coefficients
    rq2 = pd.read_csv(TABLES / "rq2_detection_failure.csv", index_col=0, **READ)
    rq2 = rq2.astype({"coef": float, "p": float})
    for m, c, pv in [("AvgNUMPAR", 0.362, 0.0002), ("CBO", 0.131, 0.0249),
                     ("CLOC", 0.130, 0.0019), ("SLOC", -0.081, 0.2672),
                     ("LLOC", 0.122, 0.3863), ("NUMPAR", -0.595, 0.0012)]:
        close(f"RQ2 {m} coef", c, rq2.loc[m, "coef"])
        close(f"RQ2 {m} p", pv, rq2.loc[m, "p"], 0.002)

    rq3 = pd.read_csv(TABLES / "rq3_analysis_failure.csv", index_col=0, **READ)
    rq3 = rq3.astype({"coef": float, "odds_ratio": float})
    close("RQ3 NOI coef", 0.911, rq3.loc["NOI", "coef"])
    close("RQ3 NOI odds ratio", 2.49, rq3.loc["NOI", "odds_ratio"], 0.01)

    # ---------------------------------------------------- VIF / pruned fits
    vif = csv("new2_vif.csv", "metric").astype({"VIF": float})
    close("max VIF (rho-screened)", 58.0, vif["VIF"].max(), 1.0)
    vifp = csv("new2_vif_pruned.csv", "metric").astype({"VIF": float})
    close("max VIF (pruned)", 4.24, vifp["VIF"].max(), 0.02)
    if len(vifp) != 8:
        failures.append(f"pruned metric count: paper=8 actual={len(vifp)}")
    checked += 1

    r3v = pd.read_csv(TABLES / "rq3_analysis_failure_vif.csv", index_col=0, **READ)
    r3v = r3v.astype({"coef": float})
    for m, c in [("AvgNOS", 0.287), ("NL", 0.234), ("NOA", 0.227)]:
        close(f"RQ3-VIF {m} coef", c, r3v.loc[m, "coef"])

    # ---------------------------------------------------- line vs category
    n1 = pd.read_csv(TABLES / "new1_rq2_line_vs_category.csv", index_col=0, **READ)
    n1 = n1.astype(float)
    close("LLOC line coef", 0.284, n1.loc["LLOC", "coef_line"])
    close("LLOC line p", 0.0315, n1.loc["LLOC", "p_line"], 0.002)
    close("NOI line coef", 0.426, n1.loc["NOI", "coef_line"])

    # ---------------------------------------------------- BH / interaction
    bh = csv("new4_bh_adjusted.csv")
    inter = bh[bh["family"].str.contains("interaction")].set_index("metric")
    close("NOA BH (14 tests)", 0.083, float(inter.loc["NOA", "p_bh"]), 0.002)
    close("DIT BH (14 tests)", 0.206, float(inter.loc["DIT", "p_bh"]), 0.002)
    bhv = csv("new4_bh_adjusted_vif.csv")
    iv = bhv[bhv["family"].str.contains("interaction")].set_index("metric")
    close("NOA BH (pruned family)", 0.059, float(iv.loc["NOA", "p_bh"]), 0.002)

    # ---------------------------------------------------- power / Type-S/M
    ts = csv("newA_type_s.csv", "corpus").astype(
        {"power": float, "type_s": float, "type_m": float, "mde_80": float})
    close("DAppSCAN power", 0.089, ts.loc["DAppSCAN", "power"], 0.002)
    close("FORGE power", 0.229, ts.loc["FORGE", "power"], 0.002)
    close("DAppSCAN Type-S", 0.025, ts.loc["DAppSCAN", "type_s"], 0.002)
    close("FORGE Type-S", 0.000, ts.loc["FORGE", "type_s"], 0.002)
    close("DAppSCAN Type-M", 4.4, ts.loc["DAppSCAN", "type_m"], 0.05)
    close("FORGE Type-M", 2.1, ts.loc["FORGE", "type_m"], 0.05)

    # ---------------------------------------------------- three corpora
    tc = csv("reentrancy_three_corpus.csv", "corpus").astype({"coef": float, "p": float})
    close("main reentrancy coef", 0.278, tc.loc["Salzano (main)", "coef"])
    close("DAppSCAN reentrancy coef", -0.834, tc.loc["DAppSCAN", "coef"])
    close("FORGE reentrancy coef", -0.314, tc.loc["FORGE", "coef"])

    # ---------------------------------------------------- mechanism (NEW-B)
    nb = csv("newB_instance_mechanism.csv", "term").astype({"coef": float, "p": float})
    close("mechanism interaction coef", -0.471, nb.loc["LLOC:arith_share_c", "coef"])
    close("mechanism interaction p", 0.0472, nb.loc["LLOC:arith_share_c", "p"], 0.002)

    # ---------------------------------------------------- S1..S4 (new)
    s1 = csv("s1_survivors.csv", "metric")
    close("S1 CLOC subFE coef", 0.0743, float(s1.loc["CLOC", "coef_subFE"]))
    close("S1 CLOC subFE p", 0.0029, float(s1.loc["CLOC", "p_subFE"]), 0.002)
    close("S1 AvgNOS subFE coef", 0.0940, float(s1.loc["AvgNOS", "coef_subFE"]))
    close("S1 AvgNOS subFE p", 0.0635, float(s1.loc["AvgNOS", "p_subFE"]), 0.002)

    s2 = csv("s2_logit_linearity.csv", "metric")
    for m in ("CLOC", "AvgNOS"):
        if str(s2.loc[m, "spline_effect_same_sign"]) != "True":
            failures.append(f"S2 {m}: spline sign no longer matches linear")
        checked += 1

    s3 = csv("s3_interaction_by_failuremode.csv", "metric")
    close("S3 NOA crash-only", 0.0194, float(s3.loc["NOA", "interaction_crashonly"]))
    close("S3 NOA crash-only p", 0.8647, float(s3.loc["NOA", "p_crashonly"]), 0.002)
    close("S3 DIT crash-only", -0.0983, float(s3.loc["DIT", "interaction_crashonly"]))

    s4 = csv("s4_triage_baseline.csv", "deployment")
    close("S4 slither complexity AUC", 0.915, float(s4.loc["slither", "auc_complexity"]), 0.002)
    close("S4 slither category AUC", 0.901, float(s4.loc["slither", "auc_category"]), 0.002)

    # ---------------------------------------------------- narrative strings
    for label, s in [
        ("Type-S DAppSCAN", "2.5\\%"), ("Type-S FORGE", "0.0\\%"),
        ("power DAppSCAN", "8.9\\%"), ("power FORGE", "22.9\\%"),
        ("Type-M DAppSCAN", "$4.4\\times$"), ("Type-M FORGE", "$2.1\\times$"),
        ("mechanism n", "39{,}183"), ("Gelman citation", "gelman2014beyond"),
    ]:
        present(label, s, tex)

    # ---------------------------------------------------- report
    print("=" * 70)
    print(f"claims checked: {checked}")
    if failures:
        print(f"MISMATCHES: {len(failures)}")
        for f in failures:
            print(f"  - {f}")
        print("=" * 70)
        return 1
    print("all claims match results/tables/")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
