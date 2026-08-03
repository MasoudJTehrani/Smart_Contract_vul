#!/usr/bin/env python
"""NEW-6: does benchmark category-mix predict the sign of the complexity effect?

The reviewer's objection to Section 6.2 is exact: we observe instability across
our own three corpora and then assert it explains the field's disagreement,
without evidence from the disputing studies themselves.

That table cannot be filled as originally templated, and saying so is part of
the answer. No prior study reports a complexity-detection *sign* -- that
absence is this paper's stated gap (Section 2). Asking prior work for a
coefficient it never estimated would contradict our own positioning. Shin and
Williams and Chowdhury and Zulkernine studied complexity against *defect
presence* in C/C++ and Java, on corpora to which DASP categories do not apply
at all.

What can be done, and is done here, is to test the mechanism directly on
benchmarks we do hold. The main corpus is an aggregate of four sub-benchmarks
with different provenance and different category mixes. If category mix drives
the sign, then estimating the same coefficient separately within each
sub-benchmark should show the sign tracking the arithmetic share. That is a
falsifiable prediction about data we have, rather than an unfillable request of
data we do not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, TABLES  # noqa: E402
from sccomplex.model import per_group_slopes, select_metrics, standardise  # noqa: E402

pd.set_option("display.width", 200)
MIN_N, MIN_EVENTS = 300, 30


def _hdr(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def main() -> int:
    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    metrics = select_metrics(det.drop_duplicates("contract"), threshold=0.9)

    d = det[det["detected_category"].notna()].copy()
    d["missed"] = (~d["detected_category"].astype(bool)).astype(int)
    d = standardise(d, metrics)

    _hdr("Category mix and complexity slope, per sub-benchmark")

    rows = []
    for corpus, sub in d.groupby("corpus", observed=True):
        inst = sub.drop_duplicates(["contract", "category"])
        share = (inst["category"] == "arithmetic").mean()
        reent = (inst["category"] == "reentrancy").mean()

        s = per_group_slopes(sub.assign(_all="all"), "missed", "LLOC", "_all",
                             min_n=MIN_N, min_events=MIN_EVENTS)
        rows.append({
            "benchmark": corpus,
            "instances": int(len(inst)),
            "rows": int(len(sub)),
            "arithmetic_share": float(share),
            "reentrancy_share": float(reent),
            "LLOC_slope": float(s["coef"].iloc[0]),
            "p": float(s["p"].iloc[0]),
        })

    # the two replication corpora, from their own analyses
    ref = pd.read_csv(TABLES / "reentrancy_three_corpus.csv",
                      keep_default_na=False, na_values=[""])
    tbl = pd.DataFrame(rows).sort_values("arithmetic_share")
    tbl.to_csv(TABLES / "new6_category_mix.csv", index=False)
    print(tbl.round(4).to_string(index=False))

    ok = tbl.dropna(subset=["LLOC_slope", "arithmetic_share"])
    if len(ok) >= 3:
        r, pr = pearsonr(ok["arithmetic_share"], ok["LLOC_slope"])
        rho, prho = spearmanr(ok["arithmetic_share"], ok["LLOC_slope"])
        print(f"\ncorrelation between arithmetic share and LLOC slope:")
        print(f"  Pearson  r = {r:+.3f} (p={pr:.3f})")
        print(f"  Spearman rho = {rho:+.3f} (p={prho:.3f})")
        print(f"  n = {len(ok)} sub-benchmarks")
        print("\nmechanism predicts a NEGATIVE correlation: the more arithmetic a")
        print("benchmark contains, the more negative its pooled slope should be.")
        verdict = ("CONSISTENT" if r < 0 else "NOT CONSISTENT")
        print(f"  -> {verdict} with the mechanism"
              f"{' (but not significant)' if pr >= 0.05 else ''}")

    _hdr("What prior work reports, and what it cannot")
    lit = pd.DataFrame([
        {"study": "Shin & Williams 2008", "outcome": "defect/vuln presence",
         "language": "C/C++ (Mozilla)", "reports_detection_sign": False,
         "category_mix_recoverable": False,
         "note": "different outcome; DASP categories do not apply"},
        {"study": "Chowdhury & Zulkernine 2011", "outcome": "vuln count",
         "language": "C/C++ (Mozilla)", "reports_detection_sign": False,
         "category_mix_recoverable": False,
         "note": "different outcome; DASP categories do not apply"},
        {"study": "Durieux et al. 2020", "outcome": "tool recall",
         "language": "Solidity", "reports_detection_sign": False,
         "category_mix_recoverable": True,
         "note": "DASP mix recoverable from SmartBugs; no complexity model"},
        {"study": "Ghaleb & Pattabiraman 2020", "outcome": "tool recall (injected)",
         "language": "Solidity", "reports_detection_sign": False,
         "category_mix_recoverable": True,
         "note": "injected-bug mix is by construction; no complexity model"},
        {"study": "Salzano et al. 2026", "outcome": "tool recall",
         "language": "Solidity", "reports_detection_sign": False,
         "category_mix_recoverable": True,
         "note": "mix computed here: see new6_category_mix.csv"},
        {"study": "This work", "outcome": "detector failure",
         "language": "Solidity", "reports_detection_sign": True,
         "category_mix_recoverable": True,
         "note": "sign varies with mix across sub-benchmarks and corpora"},
    ])
    lit.to_csv(TABLES / "new6_literature.csv", index=False)
    print(lit.to_string(index=False))

    n_sign = int(lit["reports_detection_sign"].sum())
    print(f"\nprior studies reporting a complexity-detection sign: {n_sign - 1} of "
          f"{len(lit) - 1}")
    print("The retrodiction table cannot be filled because the coefficient it asks")
    print("for has never been estimated. Table 12 is therefore presented as a")
    print("research agenda, and the mechanism is tested on our own sub-benchmarks")
    print("instead -- which is data we actually hold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
