"""S3: is the symbolic-executor effect a budget artefact?

RQ5 claims inheritance defeats symbolic executors via state-space explosion.
That rests on an "analysis failure" outcome pooling wall-clock timeouts (the
60s symbolic budget / 150s hard timeout) with genuine solver or tool crashes.
If deep-inheritance contracts differentially *time out* rather than genuinely
fail, the mechanism is budget exhaustion under state growth, not a crash-level
explosion, and should be renamed.

One asymmetry shapes what is testable. Slither records no timeouts at all on
this corpus -- every one of its non-completions is a genuine error, and none of
their diagnostics mention a timeout. A timeout-only *interaction* is therefore
not estimable: the outcome is constant zero within one of the two tools, which
is the degenerate case that produces a singular Hessian rather than a finding.
We report that explicitly and substitute the Mythril-only timeout model, which
answers the confound question directly.

`unresolved_import` is excluded throughout, matching the paper's existing
analysis-failure definition: a dependency that was never vendored is a build
failure, not an analysis outcome.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, TABLES  # noqa: E402
from sccomplex.model import standardise  # noqa: E402

pd.set_option("display.width", 200)
INHERITANCE = ["NOA", "DIT"]


def _hdr(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def _load() -> pd.DataFrame:
    met = pd.read_parquet(DATA_DERIVED / "dappscan_metrics.parquet")
    frames = []
    for tool, f in (("mythril", "dappscan_mythril.parquet"),
                    ("slither", "dappscan_slither.parquet")):
        df = pd.read_parquet(DATA_DERIVED / f)[["contract", "status"]].copy()
        df["tool"] = tool
        frames.append(df)
    both = pd.concat(frames, ignore_index=True)
    return both.merge(met, on="contract", how="inner")


def _interaction(d: pd.DataFrame, metric: str, outcome: str) -> tuple[float, float, float]:
    """(slither slope, mythril - slither, p) for the tool interaction."""
    dd = d[[outcome, metric, "tool", "contract"]].dropna().copy()
    if dd["tool"].nunique() < 2:
        return (np.nan, np.nan, np.nan)
    for t, sub in dd.groupby("tool", observed=True):
        if sub[outcome].nunique() < 2:  # degenerate within a tool
            return (np.nan, np.nan, np.nan)
    m = smf.logit(f"{outcome} ~ {metric} * C(tool, Treatment('slither'))", data=dd)
    try:
        r = m.fit(disp=0, maxiter=200, cov_type="cluster",
                  cov_kwds={"groups": dd["contract"].astype("category").cat.codes.to_numpy()})
    except Exception:
        return (np.nan, np.nan, np.nan)
    names = list(m.exog_names)
    inter = [n for n in names if n.startswith(metric) and ":" in n][0]
    return (float(np.asarray(r.params)[names.index(metric)]),
            float(np.asarray(r.params)[names.index(inter)]),
            float(np.asarray(r.pvalues)[names.index(inter)]))


def main() -> int:
    raw = _load()

    # ------------------------------------------------------------ breakdown
    _hdr("S3.1  Non-completion breakdown")
    tab = raw.pivot_table(index="tool", columns="status", values="contract",
                          aggfunc="count", fill_value=0)
    print(tab.to_string())

    analysable = raw[raw["status"] != "unresolved_import"].copy()
    myth = analysable[analysable["tool"] == "mythril"]
    n_to = int((myth["status"] == "timeout").sum())
    n_err = int((myth["status"] == "error").sum())
    n_ok = int((myth["status"] == "ok").sum())
    share_to = n_to / max(n_to + n_err, 1)
    print(f"\nMythril, excluding unresolved imports: ok {n_ok}, error {n_err}, timeout {n_to}")
    print(f"  timeouts as a share of non-completions: {share_to:.1%}")
    sl = analysable[analysable["tool"] == "slither"]
    print(f"Slither: ok {int((sl['status']=='ok').sum())}, "
          f"error {int((sl['status']=='error').sum())}, "
          f"timeout {int((sl['status']=='timeout').sum())}")
    print("\nSlither records no timeouts on this corpus, so a timeout-only")
    print("interaction is not estimable (constant outcome within one tool).")

    pd.DataFrame([{"tool": "mythril", "ok": n_ok, "error": n_err, "timeout": n_to,
                   "timeout_share_of_noncompletion": share_to},
                  {"tool": "slither", "ok": int((sl['status']=='ok').sum()),
                   "error": int((sl['status']=='error').sum()), "timeout": 0,
                   "timeout_share_of_noncompletion": 0.0}]).to_csv(
        TABLES / "s3_mythril_breakdown.csv", index=False)

    # -------------------------------------------- timeout vs inheritance
    _hdr("S3.2  Does timeout propensity itself rise with inheritance?")
    m = analysable[analysable["tool"] == "mythril"].copy()
    m["timeout"] = (m["status"] == "timeout").astype(int)
    m = standardise(m, INHERITANCE + ["SLOC"])

    rows = []
    for metric in INHERITANCE:
        q = pd.qcut(m[metric], 4, duplicates="drop")
        by_q = m.groupby(q, observed=True)["timeout"].agg(["mean", "size"])
        print(f"\ntimeout rate by {metric} quartile:")
        print(by_q.rename(columns={"mean": "timeout_rate", "size": "n"})
              .round(4).to_string())
        d = m[["timeout", metric, "contract"]].dropna()
        r = smf.logit(f"timeout ~ {metric}", data=d).fit(
            disp=0, maxiter=200, cov_type="cluster",
            cov_kwds={"groups": d["contract"].astype("category").cat.codes.to_numpy()})
        coef, p = float(np.asarray(r.params)[1]), float(np.asarray(r.pvalues)[1])
        print(f"logit(timeout) ~ {metric}: coef {coef:+.4f}, p {p:.4f}")
        rows.append({"metric": metric, "timeout_logit_coef": coef,
                     "timeout_logit_p": p,
                     "q1_rate": float(by_q["mean"].iloc[0]),
                     "q4_rate": float(by_q["mean"].iloc[-1])})
    pd.DataFrame(rows).to_csv(TABLES / "s3_timeout_by_inheritance.csv", index=False)

    # ------------------------------------- interaction by failure mode
    _hdr("S3.3  RQ5 interaction re-estimated by failure mode")
    out = []
    for metric in INHERITANCE:
        pooled = analysable.copy()
        pooled["y"] = (pooled["status"] != "ok").astype(int)
        p_sl, p_int, p_p = _interaction(standardise(pooled, INHERITANCE), metric, "y")

        crash = analysable[analysable["status"].isin(["ok", "error"])].copy()
        crash["y"] = (crash["status"] == "error").astype(int)
        c_sl, c_int, c_p = _interaction(standardise(crash, INHERITANCE), metric, "y")

        to = analysable[analysable["status"].isin(["ok", "timeout"])].copy()
        to["y"] = (to["status"] == "timeout").astype(int)
        t_sl, t_int, t_p = _interaction(standardise(to, INHERITANCE), metric, "y")

        out.append({"metric": metric, "slither_slope": p_sl,
                    "interaction_pooled": p_int, "p_pooled": p_p,
                    "interaction_crashonly": c_int, "p_crashonly": c_p,
                    "interaction_timeoutonly": t_int, "p_timeoutonly": t_p})

    res = pd.DataFrame(out)
    res.to_csv(TABLES / "s3_interaction_by_failuremode.csv", index=False)
    print(res.round(4).to_string(index=False))
    print("\n(timeout-only columns are NaN by construction: Slither never times out)")

    _hdr("S3 VERDICT")
    for r in res.itertuples():
        pooled_sig = r.p_pooled < 0.05
        crash_sig = (r.p_crashonly == r.p_crashonly) and r.p_crashonly < 0.05
        same = (r.interaction_crashonly == r.interaction_crashonly) and \
               np.sign(r.interaction_crashonly) == np.sign(r.interaction_pooled)
        if crash_sig and same:
            v = "holds within genuine crashes -- NOT a budget artefact"
        elif same:
            v = ("same sign within genuine crashes but no longer significant "
                 "-- underpowered, budget explanation not excluded")
        else:
            v = "** does not hold within genuine crashes -- budget artefact likely **"
        print(f"  {r.metric}: pooled {r.interaction_pooled:+.4f} (p={r.p_pooled:.4f})"
              f"  ->  crash-only {r.interaction_crashonly:+.4f} "
              f"(p={r.p_crashonly:.4f})\n      {v}")
    print(f"\nMythril timeouts are {share_to:.1%} of its non-completions "
          f"({n_to} of {n_to + n_err}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
