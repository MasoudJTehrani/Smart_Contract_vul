#!/usr/bin/env python
"""S1: do the two surviving coefficients survive sub-benchmark fixed effects?

The main corpus aggregates four sub-benchmarks (smartbugs_curated, zeus_safe,
zeus_vulnerable, smartbugs_results) that differ in provenance and category mix.
Section 6.2's own mechanism test shows arithmetic share -- which varies by
sub-benchmark -- moderates the LLOC slope. If that level structure is real, the
two coefficients the paper stakes its positive content on (CLOC for detection,
AvgNOS for analysis) must survive its inclusion.

Two design cautions, both load-bearing:

* Sub-benchmark enters as a FIXED EFFECT, not a third clustering dimension.
  Cluster-robust variance is unreliable below roughly 40 clusters and there are
  four; clustering on them would produce confidently wrong standard errors.
  Where inference on the sub-benchmark dimension itself is wanted we use a wild
  cluster bootstrap and label it as such.

* Sub-benchmark FE is never combined with the Section 6.2
  LLOC x arithmetic-share interaction. Arithmetic share is constant within a
  sub-benchmark, so the two are collinear by construction.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, TABLES  # noqa: E402
from sccomplex.model import select_metrics, standardise, vif_prune  # noqa: E402

pd.set_option("display.width", 200)
READ = dict(keep_default_na=False, na_values=[""])
SEED = 20260802
N_BOOT = 999


def _hdr(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def _fit(d: pd.DataFrame, outcome: str, metrics: list[str],
         controls: tuple[str, ...]) -> pd.DataFrame:
    cols = list(dict.fromkeys([outcome, "contract", *metrics, *controls]))
    dd = d[cols].dropna().copy()
    dd[outcome] = dd[outcome].astype(int)
    for c in controls:
        var = dd.groupby(c, observed=True)[outcome].mean()
        dd = dd[~dd[c].isin(var.index[(var == 0) | (var == 1)])]

    terms = list(metrics) + [f"C({c})" for c in controls if dd[c].nunique() > 1]
    m = smf.logit(f"{outcome} ~ " + " + ".join(terms), data=dd)
    r = m.fit(disp=0, maxiter=200, cov_type="cluster",
              cov_kwds={"groups": dd["contract"].astype("category").cat.codes.to_numpy()})
    names = list(m.exog_names)
    return pd.DataFrame(
        {"coef": [float(np.asarray(r.params)[names.index(k)]) for k in metrics],
         "p": [float(np.asarray(r.pvalues)[names.index(k)]) for k in metrics]},
        index=metrics), len(dd)


def _wild_bootstrap(d: pd.DataFrame, outcome: str, metrics: list[str],
                    focus: str, controls: tuple[str, ...],
                    cluster: str = "corpus") -> float:
    """Wild cluster bootstrap p-value for `focus`, resampling by sub-benchmark.

    With four clusters the analytic cluster-robust variance is not trustworthy;
    the wild bootstrap (Cameron, Gelbach and Miller) is the standard remedy.
    Rademacher weights are applied at the cluster level under the null that the
    focal coefficient is zero.
    """
    rng = np.random.default_rng(SEED)
    cols = list(dict.fromkeys([outcome, "contract", cluster, *metrics, *controls]))
    dd = d[cols].dropna().copy()
    dd[outcome] = dd[outcome].astype(int)
    for c in controls:
        var = dd.groupby(c, observed=True)[outcome].mean()
        dd = dd[~dd[c].isin(var.index[(var == 0) | (var == 1)])]

    others = [m for m in metrics if m != focus]
    terms = others + [f"C({c})" for c in controls if dd[c].nunique() > 1]

    full = smf.logit(f"{outcome} ~ {focus} + " + " + ".join(terms), data=dd)
    rf = full.fit(disp=0, maxiter=200)
    t_obs = abs(float(np.asarray(rf.tvalues)[list(full.exog_names).index(focus)]))

    # restricted model: focal coefficient constrained to zero
    restricted = smf.logit(f"{outcome} ~ " + " + ".join(terms), data=dd)
    rr = restricted.fit(disp=0, maxiter=200)
    p_hat = np.asarray(rr.predict(dd))

    codes = dd[cluster].astype("category").cat.codes.to_numpy()
    n_cl = codes.max() + 1
    count = 0
    for _ in range(N_BOOT):
        w = rng.choice([-1.0, 1.0], size=n_cl)[codes]
        # impose the null, perturb residuals at cluster level, re-binarise
        resid = dd[outcome].to_numpy() - p_hat
        y_star = (p_hat + w * resid > 0.5).astype(int)
        if y_star.sum() in (0, len(y_star)):
            continue
        try:
            b = smf.logit(f"y_star ~ {focus} + " + " + ".join(terms),
                          data=dd.assign(y_star=y_star)).fit(disp=0, maxiter=100)
            t_b = abs(float(np.asarray(b.tvalues)[list(full.exog_names).index(focus)]))
        except Exception:
            continue
        if t_b >= t_obs:
            count += 1
    return (count + 1) / (N_BOOT + 1)


def main() -> int:
    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    run = pd.read_parquet(DATA_DERIVED / "run_panel.parquet")

    rho = select_metrics(det.drop_duplicates("contract"), threshold=0.9)
    kept, _ = vif_prune(standardise(det.drop_duplicates("contract"), rho), rho, 5.0)

    _hdr("S1  Sub-benchmark fixed effects")
    print(f"entered metrics (VIF-pruned, {len(kept)}): {kept}")
    print(f"sub-benchmarks: {sorted(det['corpus'].unique())}")
    print("\nNOTE: sub-benchmark enters as a fixed effect. With only four clusters,")
    print("cluster-robust SEs on that dimension would be unreliable; the wild")
    print("cluster bootstrap below is used where sub-benchmark inference is wanted.")

    specs = [
        ("detection", det, "missed", ("tool", "category"), "CLOC",
         "rq2_detection_failure_vif.csv", "s1_subbenchmark_detection.csv"),
        ("analysis", run, "failed", ("tool",), "AvgNOS",
         "rq3_analysis_failure_vif.csv", "s1_subbenchmark_analysis.csv"),
    ]

    summary = {}
    for label, panel, outcome, controls, focus, base_csv, out_csv in specs:
        d = panel.copy()
        if outcome == "missed":
            d = d[d["detected_category"].notna()].copy()
            d["missed"] = (~d["detected_category"].astype(bool)).astype(int)
        else:
            d["failed"] = d["analysis_failed"].astype(int)
            d["category"] = "any"
        d = standardise(d, kept)

        _hdr(f"S1  RQ{'2' if outcome=='missed' else '3'} {label}: base vs + sub-benchmark FE")
        base, n_base = _fit(d, outcome, kept, controls)
        sub, n_sub = _fit(d, outcome, kept, tuple(controls) + ("corpus",))

        cmp = base.rename(columns={"coef": "coef_base", "p": "p_base"}).join(
            sub.rename(columns={"coef": "coef_subFE", "p": "p_subFE"}))
        cmp["significance_change"] = (
            (cmp["p_base"] < 0.05) != (cmp["p_subFE"] < 0.05)
        ).map({True: "FLIPS", False: ""})
        cmp = cmp.sort_values("p_subFE")
        cmp.reset_index(names="metric").to_csv(TABLES / out_csv, index=False)

        print(f"n base {n_base:,} | n with sub-FE {n_sub:,}")
        print(cmp.round(4).to_string())
        flips = cmp.index[cmp["significance_change"] == "FLIPS"].tolist()
        print(f"\nsignificance conclusions that change: {flips or 'none'}")

        if focus in cmp.index:
            r = cmp.loc[focus]
            verdict = ("SURVIVES" if r["p_subFE"] < 0.05
                       and np.sign(r["coef_subFE"]) == np.sign(r["coef_base"])
                       else "** DOES NOT SURVIVE **")
            print(f"\nsurvivor {focus}: base {r['coef_base']:+.4f} (p={r['p_base']:.4f})"
                  f"  ->  +subFE {r['coef_subFE']:+.4f} (p={r['p_subFE']:.4f})  {verdict}")
            wb = _wild_bootstrap(d, outcome, kept, focus, controls)
            print(f"wild cluster bootstrap p (4 sub-benchmark clusters, {N_BOOT} reps): {wb:.4f}")
            summary[focus] = {
                "model": label, "coef_base": float(r["coef_base"]),
                "p_base": float(r["p_base"]), "coef_subFE": float(r["coef_subFE"]),
                "p_subFE": float(r["p_subFE"]), "wild_bootstrap_p": wb,
                "verdict": "survives" if "SURVIVES" == verdict else "does not survive",
            }

    pd.DataFrame(summary).T.reset_index(names="metric").to_csv(
        TABLES / "s1_survivors.csv", index=False)
    _hdr("S1 VERDICT")
    for k, v in summary.items():
        print(f"  {k:<8} ({v['model']}): {v['verdict']}  "
              f"[clustered p={v['p_subFE']:.4f}, wild-bootstrap p={v['wild_bootstrap_p']:.4f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
