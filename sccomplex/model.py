"""Statistical models relating complexity to detector failure.

Design decisions, and why:

* Tool fixed effects are mandatory. Detection rates range from 82% (conkas) to
  0% (teether); without conditioning on tool, any complexity coefficient mostly
  reflects which tools happen to run on which contracts.

* Vulnerability-category fixed effects are mandatory for the same reason:
  categories differ enormously in detectability, and category composition
  varies with contract size.

* Standard errors are clustered by contract. The same contract contributes up
  to 19 rows (one per tool) and several rows per vulnerability; treating those
  as independent would understate standard errors severely.

* Metrics are standardised so coefficients are comparable across metrics on
  very different scales, and are screened for collinearity first: Paper 1
  established that these 21 metrics are highly redundant, and feeding all of
  them to one model produces uninterpretable, unstable coefficients.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from sccomplex.config import SOLMET_METRICS


def spearman_redundancy(df: pd.DataFrame, metrics=None, threshold: float = 0.9):
    """Pairs of metrics whose rank correlation exceeds `threshold`.

    Replicates the RQ1 analysis of Paper 1 on this corpus. Returns the full
    correlation matrix and the redundant pairs.
    """
    metrics = list(metrics or SOLMET_METRICS)
    corr = df[metrics].corr(method="spearman")

    pairs = [
        {"a": metrics[i], "b": metrics[j], "rho": corr.iloc[i, j]}
        for i in range(len(metrics))
        for j in range(i + 1, len(metrics))
        if abs(corr.iloc[i, j]) >= threshold
    ]
    redundant = pd.DataFrame(pairs).sort_values("rho", ascending=False) if pairs else pd.DataFrame(columns=["a", "b", "rho"])
    return corr, redundant


def select_metrics(df: pd.DataFrame, metrics=None, threshold: float = 0.9) -> list[str]:
    """Greedily drop one metric from each strongly correlated pair.

    Retains the metric with the larger marginal variance, which is the more
    informative of a redundant pair. Deterministic given the input ordering.
    """
    metrics = list(metrics or SOLMET_METRICS)
    corr = df[metrics].corr(method="spearman").abs()

    keep = list(metrics)
    while True:
        worst = None
        for i, a in enumerate(keep):
            for b in keep[i + 1 :]:
                rho = corr.loc[a, b]
                if rho >= threshold and (worst is None or rho > worst[2]):
                    worst = (a, b, rho)
        if worst is None:
            return keep
        a, b, _ = worst
        drop = a if df[a].std() < df[b].std() else b
        keep.remove(drop)


def standardise(df: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    """Log1p-then-z-score. Count metrics are heavily right-skewed; the log
    keeps a handful of 2,500-line contracts from dominating the fit."""
    out = df.copy()
    for m in metrics:
        v = np.log1p(out[m].clip(lower=0).astype(float))
        sd = v.std()
        out[m] = 0.0 if sd == 0 else (v - v.mean()) / sd
    return out


def fit_failure_model(
    panel: pd.DataFrame,
    outcome: str,
    metrics: list[str],
    controls: tuple[str, ...] = ("tool", "category"),
    cluster: str = "contract",
):
    """Logistic model of a failure outcome on complexity, with fixed effects.

    `outcome` must be a 0/1 column where 1 means *failure* (bug missed, or
    analysis crashed), so positive coefficients mean "more complexity, more
    failure" and read the way a reader expects.
    """
    cols = [outcome, cluster, *metrics, *controls]
    data = panel[cols].dropna().copy()
    data[outcome] = data[outcome].astype(int)

    # Drop fixed-effect levels with no outcome variation. A tool that detects
    # nothing (or everything) is perfectly predicted by its own dummy, which
    # makes the Hessian singular and the whole fit fail. Such a level carries
    # no information about how complexity modulates the outcome, so it is
    # excluded and reported rather than allowed to break the model. This --
    # not any complexity threshold -- is the real source of the "perfect
    # separation" warnings seen in naive fits of this data.
    excluded: dict[str, list] = {}
    for c in controls:
        var = data.groupby(c, observed=True)[outcome].agg(["mean", "size"])
        degenerate = var.index[(var["mean"] == 0) | (var["mean"] == 1)].tolist()
        if degenerate:
            excluded[c] = degenerate
            data = data[~data[c].isin(degenerate)]

    if data.empty:
        raise ValueError("no rows left after removing degenerate fixed-effect levels")

    terms = list(metrics) + [f"C({c})" for c in controls if data[c].nunique() > 1]
    formula = f"{outcome} ~ " + " + ".join(terms)

    groups = data[cluster].astype("category").cat.codes.to_numpy()
    model = smf.logit(formula, data=data)
    res = model.fit(
        disp=0,
        maxiter=200,
        cov_type="cluster",
        cov_kwds={"groups": groups},
    )

    table = pd.DataFrame(
        {
            "coef": np.asarray(res.params),
            "std_err": np.asarray(res.bse),
            "z": np.asarray(res.tvalues),
            "p": np.asarray(res.pvalues),
            "odds_ratio": np.exp(np.asarray(res.params)),
        },
        index=model.exog_names,
    )
    # Fixed-effect dummies are nuisance parameters; report only the metrics.
    res.excluded_levels = excluded
    return table.loc[[m for m in metrics if m in table.index]], res, data


def per_group_slopes(
    panel: pd.DataFrame,
    outcome: str,
    metric: str,
    group: str,
    min_n: int = 200,
    min_events: int = 20,
):
    """Complexity slope estimated separately within each group.

    Groups with too few rows or too few events are reported as skipped rather
    than silently returning an unidentified coefficient -- that failure mode
    produced the spurious 'perfect separation' reading in the prototype.
    """
    rows = []
    for name, sub in panel.groupby(group, observed=True):
        d = sub[[outcome, metric, "contract", "category"]].dropna().copy()
        d[outcome] = d[outcome].astype(int)
        events = int(d[outcome].sum())
        n = len(d)

        if n < min_n or events < min_events or events == n:
            rows.append(
                {
                    group: name, "n": n, "events": events,
                    "coef": np.nan, "p": np.nan,
                    "note": "insufficient variation" if events in (0, n) else "too few observations",
                }
            )
            continue

        # Within a single group, some categories are again perfectly predicted
        # (a tool that never finds any front-running bug). Drop those levels
        # here too, otherwise the fit dies with a singular Hessian.
        if d["category"].nunique() > 1:
            var = d.groupby("category", observed=True)[outcome].mean()
            keep_cats = var.index[(var > 0) & (var < 1)]
            if len(keep_cats) >= 1:
                d = d[d["category"].isin(keep_cats)]

        if len(d) < min_n or not (0 < int(d[outcome].sum()) < len(d)):
            rows.append(
                {group: name, "n": n, "events": events, "coef": np.nan,
                 "p": np.nan, "note": "no variation after dropping degenerate categories"}
            )
            continue

        terms = [metric] + (["C(category)"] if d["category"].nunique() > 1 else [])
        try:
            m = smf.logit(f"{outcome} ~ " + " + ".join(terms), data=d)
            r = m.fit(
                disp=0,
                maxiter=200,
                cov_type="cluster",
                cov_kwds={"groups": d["contract"].astype("category").cat.codes.to_numpy()},
            )
            idx = m.exog_names.index(metric)
            rows.append(
                {
                    group: name, "n": n, "events": events,
                    "coef": float(np.asarray(r.params)[idx]),
                    "p": float(np.asarray(r.pvalues)[idx]),
                    "note": "",
                }
            )
        except Exception as e:  # non-convergence, separation
            rows.append(
                {group: name, "n": n, "events": events,
                 "coef": np.nan, "p": np.nan, "note": f"fit failed: {type(e).__name__}"}
            )

    return pd.DataFrame(rows).sort_values("coef", na_position="last")
