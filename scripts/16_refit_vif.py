#!/usr/bin/env python
"""Re-fit the core models on a properly collinearity-screened metric set.

NEW-2 showed that rank-correlation screening at |rho| >= 0.9 leaves the entered
set with VIFs up to 58 -- the models carrying RQ2 and RQ3 were fitted on a set
that is still severely collinear, which is exactly the instability the
screening was meant to prevent. This script repeats the analysis on a set
pruned to VIF < 5 and reports what changes.

Two consequences beyond coefficient stability:

  * the multiple-comparison families shrink, so the Benjamini-Hochberg penalty
    applied in NEW-4 is smaller and is recomputed here on the pruned set;
  * any conclusion that survives both the pruning and the correction is
    considerably better evidenced than one that only survived the original
    specification.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.stats.multitest import multipletests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, TABLES  # noqa: E402
from sccomplex.model import (  # noqa: E402
    fit_failure_model,
    select_metrics,
    standardise,
    vif_prune,
)

pd.set_option("display.width", 200)
READ = dict(keep_default_na=False, na_values=[""])


def _hdr(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def main() -> int:
    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    run = pd.read_parquet(DATA_DERIVED / "run_panel.parquet")

    rho_set = select_metrics(det.drop_duplicates("contract"), threshold=0.9)
    base = standardise(det.drop_duplicates("contract"), rho_set)
    kept, vifs = vif_prune(base, rho_set, threshold=5.0)

    _hdr("Collinearity-pruned metric set")
    print(f"rho-screened ({len(rho_set)}): {rho_set}")
    print(f"VIF-pruned   ({len(kept)}): {kept}")
    print(f"dropped      ({len(rho_set) - len(kept)}): "
          f"{[m for m in rho_set if m not in kept]}")
    print("\nfinal VIFs:")
    print(vifs.round(3).to_string(index=False))
    vifs.to_csv(TABLES / "new2_vif_pruned.csv", index=False)

    families = {}

    # ------------------------------------------------ RQ2 / RQ3 re-fitted
    for label, panel, outcome, controls, old_csv, new_csv in (
        ("RQ2 detection", det, "missed", ("tool", "category"),
         "rq2_detection_failure.csv", "rq2_detection_failure_vif.csv"),
        ("RQ3 analysis", run, "failed", ("tool",),
         "rq3_analysis_failure.csv", "rq3_analysis_failure_vif.csv"),
    ):
        _hdr(f"{label}: re-fitted on the VIF-pruned set")
        d = panel.copy()
        if outcome == "missed":
            d = d[d["detected_category"].notna()].copy()
            d["missed"] = (~d["detected_category"].astype(bool)).astype(int)
        else:
            d["failed"] = d["analysis_failed"].astype(int)
            d["category"] = "any"
        d = standardise(d, kept)

        tbl, _, _ = fit_failure_model(d, outcome, kept, controls=controls)
        tbl = tbl.sort_values("coef", ascending=False)
        tbl.to_csv(TABLES / new_csv)

        old = pd.read_csv(TABLES / old_csv, index_col=0, **READ)
        old[["coef", "p"]] = old[["coef", "p"]].astype(float)
        cmp = tbl[["coef", "p", "odds_ratio"]].join(
            old[["coef", "p"]].rename(columns={"coef": "coef_old", "p": "p_old"}),
            how="left")
        cmp["sig_new"] = cmp["p"] < 0.05
        cmp["sig_old"] = cmp["p_old"] < 0.05
        cmp["changed"] = cmp["sig_new"] != cmp["sig_old"]
        print(cmp.round(4).to_string())
        ch = cmp.index[cmp["changed"].fillna(False)].tolist()
        print(f"\nsignificance changes after pruning: {ch or 'none'}")
        families[label] = tbl["p"]

    # ------------------------------------------------ RQ5 interaction re-fitted
    _hdr("RQ5 interaction: re-fitted on the VIF-pruned set")
    dmet = pd.read_parquet(DATA_DERIVED / "dappscan_metrics.parquet")
    myth = pd.read_parquet(DATA_DERIVED / "dappscan_mythril.parquet")[["contract", "status"]]
    slith = pd.read_parquet(DATA_DERIVED / "dappscan_slither.parquet")[["contract", "status"]]
    myth["tool"], slith["tool"] = "mythril", "slither"

    both = pd.concat([myth, slith], ignore_index=True)
    both = both[both["status"] != "unresolved_import"]
    both["analysis_failed"] = (both["status"] != "ok").astype(int)
    panel = both.merge(dmet, on="contract", how="inner")

    d_rho = select_metrics(dmet, threshold=0.9)
    d_kept, d_vifs = vif_prune(standardise(dmet, d_rho), d_rho, threshold=5.0)
    print(f"DAppSCAN rho-screened ({len(d_rho)}) -> VIF-pruned ({len(d_kept)}): {d_kept}")

    p = standardise(panel, d_kept)
    rows = []
    for m in d_kept:
        dd = p[["analysis_failed", m, "tool", "contract"]].dropna()
        mod = smf.logit(f"analysis_failed ~ {m} * C(tool, Treatment('slither'))", data=dd)
        try:
            r = mod.fit(disp=0, maxiter=200, cov_type="cluster",
                        cov_kwds={"groups": dd["contract"].astype("category").cat.codes.to_numpy()})
            names = list(mod.exog_names)
            i = [k for k in names if k.startswith(m) and ":" in k][0]
            rows.append({"metric": m,
                         "slither_slope": float(np.asarray(r.params)[names.index(m)]),
                         "mythril_minus_slither": float(np.asarray(r.params)[names.index(i)]),
                         "p_interaction": float(np.asarray(r.pvalues)[names.index(i)])})
        except Exception:
            rows.append({"metric": m, "slither_slope": np.nan,
                         "mythril_minus_slither": np.nan, "p_interaction": np.nan})

    inter = pd.DataFrame(rows).sort_values("p_interaction")
    inter.to_csv(TABLES / "dappscan_c2_interaction_vif.csv", index=False)
    print(inter.round(4).to_string(index=False))
    families["RQ5 interaction"] = inter.set_index("metric")["p_interaction"]

    # ------------------------------------------------ BH on the pruned families
    _hdr("Benjamini-Hochberg on the VIF-pruned families")
    out = []
    for label, pvals in families.items():
        pv = pd.to_numeric(pvals, errors="coerce").dropna()
        adj = multipletests(pv.to_numpy(), method="fdr_bh")[1]
        t = pd.DataFrame({"family": label, "metric": pv.index, "p_raw": pv.to_numpy(),
                          "p_bh": adj})
        t["sig_raw"], t["sig_bh"] = t["p_raw"] < 0.05, t["p_bh"] < 0.05
        out.append(t)
        print(f"\n--- {label} ({len(pv)} tests) ---")
        print(t.sort_values("p_raw").round(4).to_string(index=False))
        lost = t.loc[t["sig_raw"] & ~t["sig_bh"], "metric"].tolist()
        print(f"stars lost to BH: {lost or 'none'}")

    res = pd.concat(out, ignore_index=True)
    res.to_csv(TABLES / "new4_bh_adjusted_vif.csv", index=False)

    _hdr("VERDICT: what survives pruning AND correction")
    for label in families:
        sub = res[res["family"] == label]
        surv = sub.loc[sub["sig_bh"], "metric"].tolist()
        print(f"  {label:<18} -> {surv or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def gauntlet() -> pd.DataFrame:
    """What survives VIF pruning AND two-way clustering AND BH, together.

    Each filter alone is defensible; a coefficient that survives all three is
    the only kind this study is willing to advance.
    """
    import statsmodels.formula.api as smf

    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    run = pd.read_parquet(DATA_DERIVED / "run_panel.parquet")
    rho = select_metrics(det.drop_duplicates("contract"), threshold=0.9)
    kept, _ = vif_prune(standardise(det.drop_duplicates("contract"), rho), rho, 5.0)

    rows = []
    for label, panel, outcome, controls in (
        ("RQ2 detection", det, "missed", ("tool", "category")),
        ("RQ3 analysis", run, "failed", ("tool",)),
    ):
        d = panel.copy()
        if outcome == "missed":
            d = d[d["detected_category"].notna()].copy()
            d["missed"] = (~d["detected_category"].astype(bool)).astype(int)
        else:
            d["failed"] = d["analysis_failed"].astype(int)
            d["category"] = "any"
        d = standardise(d, kept)

        cols = list(dict.fromkeys([outcome, "contract", "tool", *kept, *controls]))
        dd = d[cols].dropna().copy()
        dd[outcome] = dd[outcome].astype(int)
        for c in controls:
            v = dd.groupby(c, observed=True)[outcome].mean()
            dd = dd[~dd[c].isin(v.index[(v == 0) | (v == 1)])]

        terms = list(kept) + [f"C({c})" for c in controls if dd[c].nunique() > 1]
        m = smf.logit(f"{outcome} ~ " + " + ".join(terms), data=dd)
        g = np.column_stack([dd["contract"].astype("category").cat.codes.to_numpy(),
                             dd["tool"].astype("category").cat.codes.to_numpy()])
        r = m.fit(disp=0, maxiter=200, cov_type="cluster", cov_kwds={"groups": g})
        names = list(m.exog_names)
        pv = {k: float(np.asarray(r.pvalues)[names.index(k)]) for k in kept if k in names}
        co = {k: float(np.asarray(r.params)[names.index(k)]) for k in kept if k in names}
        adj = multipletests(list(pv.values()), method="fdr_bh")[1]
        for (k, p), a in zip(pv.items(), adj):
            rows.append({"family": label, "metric": k, "coef": co[k],
                         "p_2way": p, "p_2way_bh": a, "survives": a < 0.05})

    res = pd.DataFrame(rows)
    res.to_csv(TABLES / "new_gauntlet.csv", index=False)
    _hdr("FULL GAUNTLET: VIF-pruned + two-way clustered + BH-corrected")
    for fam in res["family"].unique():
        s = res[res["family"] == fam].sort_values("p_2way_bh")
        print(f"\n--- {fam} ---")
        print(s[["metric", "coef", "p_2way", "p_2way_bh", "survives"]]
              .round(4).to_string(index=False))
        surv = s.loc[s["survives"], "metric"].tolist()
        print(f"survives everything: {surv or 'nothing'}")
    return res


if __name__ != "__main__":
    pass
