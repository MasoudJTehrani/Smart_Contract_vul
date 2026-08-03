#!/usr/bin/env python
"""S2: is the linear form of the two surviving coefficients an artefact?

CLOC (detection) and AvgNOS (analysis) are the only coefficients surviving VIF
pruning, two-way clustering and BH correction, so they carry the paper's entire
positive content. Both are count metrics with many zeros entered under a
log(1+x) then z-score transform.

The assumption at risk is not normality of the predictor -- logistic regression
makes no such assumption -- but *linearity of the logit* in the transformed
predictor. If the true relationship bends, a significant linear coefficient can
be a functional-form artefact.

Three checks:
  1. Box-Tidwell: add x*ln(x) and test it. Significance indicates non-linearity.
     Applied on the log1p scale shifted to be strictly positive, since the
     z-scored predictor takes negative values and ln is undefined there.
  2. Natural cubic spline (4 knots at data quantiles) versus the linear term,
     compared by likelihood-ratio test.
  3. Whether the metric's effect stays same-signed and significant under the
     flexible form -- the question that actually matters for the claim.

The LR test uses unclustered likelihoods, because a likelihood ratio is not
defined for a cluster-robust fit. It is therefore anti-conservative about
non-linearity, which is the safe direction here: it makes it *easier* to detect
a functional-form problem, not harder.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, FIGURES, TABLES  # noqa: E402
from sccomplex.model import select_metrics, standardise, vif_prune  # noqa: E402

pd.set_option("display.width", 200)
SPLINE_DF = 4


def _hdr(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def _prep(panel: pd.DataFrame, outcome: str, kept: list[str],
          controls: tuple[str, ...]) -> pd.DataFrame:
    d = panel.copy()
    if outcome == "missed":
        d = d[d["detected_category"].notna()].copy()
        d["missed"] = (~d["detected_category"].astype(bool)).astype(int)
    else:
        d["failed"] = d["analysis_failed"].astype(int)
        d["category"] = "any"
    d = standardise(d, kept)
    cols = list(dict.fromkeys([outcome, "contract", *kept, *controls]))
    d = d[cols].dropna().copy()
    d[outcome] = d[outcome].astype(int)
    for c in controls:
        var = d.groupby(c, observed=True)[outcome].mean()
        d = d[~d[c].isin(var.index[(var == 0) | (var == 1)])]
    return d


def _empirical_logit_plot(d: pd.DataFrame, metric: str, outcome: str,
                          path: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"  (plot skipped: {type(e).__name__})", file=sys.stderr)
        return

    q = pd.qcut(d[metric], 20, duplicates="drop")
    g = d.groupby(q, observed=True).agg(x=(metric, "mean"), y=(outcome, "mean"),
                                        n=(outcome, "size"))
    # Haldane-Anscombe correction keeps the logit finite in all-0/all-1 bins
    p = (g["y"] * g["n"] + 0.5) / (g["n"] + 1)
    g["logit"] = np.log(p / (1 - p))

    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(g["x"], g["logit"], s=g["n"] / g["n"].max() * 90 + 10,
               color="#3b6ea5", alpha=0.85, label="binned empirical logit")
    try:
        from statsmodels.nonparametric.smoothers_lowess import lowess
        lo = lowess(g["logit"], g["x"], frac=0.6, return_sorted=True)
        ax.plot(lo[:, 0], lo[:, 1], color="#c0392b", lw=2, label="LOESS")
    except Exception:
        pass
    z = np.polyfit(g["x"], g["logit"], 1)
    xs = np.linspace(g["x"].min(), g["x"].max(), 50)
    ax.plot(xs, np.polyval(z, xs), "--", color="0.4", lw=1.2, label="linear fit")
    ax.set_xlabel(f"{metric} (log1p, z-scored)")
    ax.set_ylabel("empirical logit")
    ax.set_title(f"Linearity of logit: {metric}")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  figure -> {path}")


def check(d: pd.DataFrame, metric: str, outcome: str, kept: list[str],
          controls: tuple[str, ...], model_label: str) -> dict:
    _hdr(f"S2  {metric} in the {model_label} model")
    others = [m for m in kept if m != metric]
    fe = [f"C({c})" for c in controls if d[c].nunique() > 1]
    base_terms = " + ".join(others + fe) if (others or fe) else "1"
    groups = d["contract"].astype("category").cat.codes.to_numpy()

    # ---- linear reference (clustered, as in the paper) ----
    lin = smf.logit(f"{outcome} ~ {metric} + {base_terms}", data=d)
    rlin = lin.fit(disp=0, maxiter=200, cov_type="cluster",
                   cov_kwds={"groups": groups})
    i = list(lin.exog_names).index(metric)
    lin_coef = float(np.asarray(rlin.params)[i])
    lin_p = float(np.asarray(rlin.pvalues)[i])
    print(f"linear (clustered): coef {lin_coef:+.4f}, p {lin_p:.4f}")

    # ---- Box-Tidwell ----
    # ln() needs a strictly positive argument; the z-scored predictor is
    # signed, so shift it onto (1, inf) before forming x*ln(x).
    dd = d.copy()
    shift = 1.0 - dd[metric].min()
    dd["_bt_x"] = dd[metric] + shift
    dd["_bt"] = dd["_bt_x"] * np.log(dd["_bt_x"])
    try:
        bt = smf.logit(f"{outcome} ~ {metric} + _bt + {base_terms}", data=dd)
        rbt = bt.fit(disp=0, maxiter=200, cov_type="cluster",
                     cov_kwds={"groups": groups})
        bt_p = float(np.asarray(rbt.pvalues)[list(bt.exog_names).index("_bt")])
    except Exception as e:
        bt_p = float("nan")
        print(f"  Box-Tidwell failed: {type(e).__name__}")
    print(f"Box-Tidwell x*ln(x) term: p = {bt_p:.4f} "
          f"({'non-linearity indicated' if bt_p < 0.05 else 'no non-linearity indicated'})")

    # ---- spline vs linear, likelihood-ratio ----
    lin_ll = lin.fit(disp=0, maxiter=200)
    sp = smf.logit(f"{outcome} ~ bs({metric}, df={SPLINE_DF}) + {base_terms}", data=d)
    rsp_ll = sp.fit(disp=0, maxiter=200)
    lr = 2 * (rsp_ll.llf - lin_ll.llf)
    ddf = int(rsp_ll.df_model - lin_ll.df_model)
    lr_p = float(stats.chi2.sf(lr, ddf)) if ddf > 0 else float("nan")
    print(f"spline (df={SPLINE_DF}) vs linear: LR = {lr:.2f} on {ddf} df, p = {lr_p:.4f} "
          f"({'non-linearity indicated' if lr_p < 0.05 else 'linear form adequate'})")

    # ---- does the effect survive the flexible form? ----
    rsp = sp.fit(disp=0, maxiter=200, cov_type="cluster", cov_kwds={"groups": groups})
    sp_idx = [k for k, nm in enumerate(sp.exog_names) if nm.startswith("bs(")]
    wald = rsp.wald_test(np.eye(len(sp.exog_names))[sp_idx], scalar=True)
    sp_p = float(wald.pvalue)

    # average marginal direction of the spline across the observed range
    lo, hi = d[metric].quantile([0.10, 0.90])
    grid = d.iloc[[0] * 2].copy()
    grid[metric] = [lo, hi]
    for c in controls:
        grid[c] = d[c].mode().iloc[0]
    for m in others:
        grid[m] = d[m].mean()
    pred = np.asarray(rsp.predict(grid))
    sp_dir = float(np.sign(pred[1] - pred[0]))
    same_sign = bool(sp_dir == np.sign(lin_coef))

    print(f"spline joint Wald (clustered): p = {sp_p:.4f}")
    print(f"spline direction p10->p90: {'increasing' if sp_dir > 0 else 'decreasing'}"
          f"  |  same sign as linear: {same_sign}")

    verdict = ("survives a flexible form" if (same_sign and sp_p < 0.05)
               else "DOES NOT survive a flexible form")
    print(f"\n-> {metric}: {verdict}")

    _empirical_logit_plot(d, metric, outcome, FIGURES / f"s2_{metric}_logit.png")

    return {"metric": metric, "model": model_label, "boxtidwell_p": bt_p,
            "spline_lr_p": lr_p, "linear_coef": lin_coef, "linear_p": lin_p,
            "spline_effect_same_sign": same_sign,
            "spline_effect_significant": bool(sp_p < 0.05), "spline_wald_p": sp_p}


def main() -> int:
    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    run = pd.read_parquet(DATA_DERIVED / "run_panel.parquet")
    rho = select_metrics(det.drop_duplicates("contract"), threshold=0.9)
    kept, _ = vif_prune(standardise(det.drop_duplicates("contract"), rho), rho, 5.0)

    rows = [
        check(_prep(det, "missed", kept, ("tool", "category")), "CLOC", "missed",
              kept, ("tool", "category"), "detection"),
        check(_prep(run, "failed", kept, ("tool",)), "AvgNOS", "failed",
              kept, ("tool",), "analysis"),
    ]
    out = pd.DataFrame(rows)
    out.to_csv(TABLES / "s2_logit_linearity.csv", index=False)

    _hdr("S2 VERDICT")
    for r in rows:
        ok = r["spline_effect_same_sign"] and r["spline_effect_significant"]
        print(f"  {r['metric']:<8} ({r['model']}): "
              f"{'survives' if ok else 'DOES NOT SURVIVE'} a flexible form  "
              f"[Box-Tidwell p={r['boxtidwell_p']:.4f}, spline LR p={r['spline_lr_p']:.4f}]")
    print(f"\n-> {TABLES / 's2_logit_linearity.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
