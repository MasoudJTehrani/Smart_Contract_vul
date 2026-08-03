#!/usr/bin/env python
"""NEW-A and NEW-B from the v2 review.

NEW-A (required). Section 5.4.4 argued that low power "inflates false
negatives, not sign errors". That is not strictly correct. Conditional on
reaching significance, an underpowered design can return the wrong sign at an
appreciable rate -- Gelman and Carlin's Type-S error. Since the central claim
rests on DAppSCAN's *significant negative* estimate contradicting a
well-powered positive one, the Type-S rate is exactly the quantity that decides
how much that contradiction is worth. We compute it from the same simulation
that produced the power figures rather than argue about it.

NEW-B (optional). The mechanism test in Section 6.2 rests on a rank correlation
over four aggregated sub-benchmark points, which is weak. An instance-level
version is available on data we already hold: if benchmark category mix drives
the pooled slope, then the LLOC slope should vary with the arithmetic share of
the benchmark an instance belongs to. That is an interaction, estimable on
51,090 rows rather than four points.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, TABLES  # noqa: E402
from sccomplex.model import select_metrics, standardise  # noqa: E402

pd.set_option("display.width", 200)
RNG = 20260802
READ = dict(keep_default_na=False, na_values=[""])


def _hdr(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


# --------------------------------------------------------------------- NEW-A
def type_s(n: int, n_events: int, beta: float, n_sim: int = 4000,
           alpha: float = 0.05, seed: int = RNG) -> dict:
    """Power, Type-S (sign) and Type-M (exaggeration) rates for a logistic slope.

    Type-S is the probability that a *significant* estimate carries the wrong
    sign; Type-M is the average magnitude exaggeration among significant
    estimates. Both are conditional on significance, which is the quantity a
    reader of a published significant result actually faces.
    """
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n)
    base = n_events / n

    def rate(b0: float) -> float:
        return float(np.mean(1 / (1 + np.exp(-(b0 + beta * x)))))

    lo, hi = -20.0, 20.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if rate(mid) < base:
            lo = mid
        else:
            hi = mid
    b0 = (lo + hi) / 2

    p_true = 1 / (1 + np.exp(-(b0 + beta * x)))
    X = np.column_stack([np.ones(n), x])
    sig_coefs, fitted = [], 0
    for _ in range(n_sim):
        y = rng.binomial(1, p_true)
        if y.sum() in (0, n):
            continue
        try:
            r = sm.Logit(y, X).fit(disp=0, maxiter=100)
            co, pv = float(r.params[1]), float(r.pvalues[1])
        except Exception:
            continue
        if not np.isfinite(co) or abs(co) > 20:
            continue
        fitted += 1
        if pv < alpha:
            sig_coefs.append(co)

    sig = np.array(sig_coefs)
    n_sig = len(sig)
    wrong = int(np.sum(np.sign(sig) != np.sign(beta))) if n_sig else 0
    return {
        "n": n, "events": n_events, "beta": beta, "fitted": fitted,
        "power": n_sig / max(fitted, 1),
        "n_significant": n_sig,
        "type_s": wrong / n_sig if n_sig else float("nan"),
        "type_m": float(np.mean(np.abs(sig)) / abs(beta)) if n_sig else float("nan"),
    }


def new_a() -> pd.DataFrame:
    _hdr("NEW-A  Type-S (sign) error rate under the main-corpus effect")

    beta = float(pd.read_csv(TABLES / "reentrancy_three_corpus.csv", **READ)
                 .query("corpus == 'Salzano (main)'")["coef"].iloc[0])
    print(f"assumed true effect: beta = {beta:+.3f} (the main-corpus estimate)")
    print("Type-S = P(estimate is negative | estimate is significant)\n")

    rows = [type_s(62, 9, beta) | {"corpus": "DAppSCAN"},
            type_s(133, 102, beta) | {"corpus": "FORGE"}]
    # Minimum detectable effect at 80% power, from the same simulation, so the
    # power table and the Type-S table cannot disagree.
    for r in rows:
        lo, hi = 0.05, 4.0
        for _ in range(14):
            mid = (lo + hi) / 2
            if type_s(r["n"], r["events"], mid, n_sim=600)["power"] < 0.80:
                lo = mid
            else:
                hi = mid
        r["mde_80"] = (lo + hi) / 2

    res = pd.DataFrame(rows)[
        ["corpus", "n", "events", "power", "n_significant", "type_s", "type_m",
         "mde_80"]]
    res.to_csv(TABLES / "newA_type_s.csv", index=False)
    # Supersede the earlier power table so the manuscript has one source.
    res[["corpus", "n", "events", "power", "mde_80"]].assign(beta=beta).to_csv(
        TABLES / "new5_power.csv", index=False)

    for r in res.itertuples():
        print(f"{r.corpus:<10} n={r.n:>4}  power={r.power:.1%}  "
              f"significant replicates={r.n_significant:>4}  "
              f"Type-S={r.type_s:.1%}  Type-M={r.type_m:.2f}x")

    _hdr("What this means for the central claim")
    d = res.set_index("corpus")
    ts = float(d.loc["DAppSCAN", "type_s"])
    if ts < 0.05:
        print(f"DAppSCAN Type-S = {ts:.1%} (< 5%).")
        print("A significant negative estimate is therefore very unlikely to arise")
        print("from an underlying positive effect of the main-corpus magnitude.")
        print("The sign-reversal argument stands as written.")
    else:
        print(f"DAppSCAN Type-S = {ts:.1%} -- NOT negligible.")
        print("A significant estimate from this design can carry the wrong sign at")
        print("an appreciable rate. The claim must therefore rest on the")
        print("main-corpus positive estimate PLUS the failure of two independent")
        print("corpora to reproduce its sign, and the DAppSCAN negative should be")
        print("treated as suggestive rather than dispositive.")
    print(f"\nType-M: significant estimates are exaggerated "
          f"{float(d.loc['DAppSCAN','type_m']):.1f}x (DAppSCAN) and "
          f"{float(d.loc['FORGE','type_m']):.1f}x (FORGE), which is why we treat")
    print("the reversal of sign and not the magnitude as the finding.")
    return res


# --------------------------------------------------------------------- NEW-B
def new_b() -> pd.DataFrame:
    _hdr("NEW-B  Instance-level test of the category-mix mechanism")

    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    metrics = select_metrics(det.drop_duplicates("contract"), threshold=0.9)

    d = det[det["detected_category"].notna()].copy()
    d["missed"] = (~d["detected_category"].astype(bool)).astype(int)

    # arithmetic share of the sub-benchmark each instance belongs to
    inst = d.drop_duplicates(["contract", "category"])
    share = (inst.assign(is_arith=inst["category"].eq("arithmetic"))
             .groupby("corpus")["is_arith"].mean().rename("arith_share"))
    print("arithmetic share per sub-benchmark:")
    print(share.round(4).to_string())

    d = d.merge(share, left_on="corpus", right_index=True, how="inner")
    d = standardise(d, metrics)
    d["arith_share_c"] = d["arith_share"] - d["arith_share"].mean()

    # Same degenerate-level guard as the main models: tools that detect
    # nothing (and categories nothing detects) are perfectly predicted by
    # their own dummy and make the Hessian singular.
    for c in ("tool", "category"):
        var = d.groupby(c, observed=True)["missed"].mean()
        drop = var.index[(var == 0) | (var == 1)]
        if len(drop):
            print(f"  excluded {c} levels with no outcome variation: {sorted(drop)}")
            d = d[~d[c].isin(drop)]

    print(f"\nrows {len(d):,} | contracts {d['contract'].nunique():,} "
          f"| sub-benchmarks {d['corpus'].nunique()}")

    # The mechanism predicts a NEGATIVE interaction: a benchmark with a higher
    # arithmetic share should have a more negative LLOC slope.
    m = smf.logit("missed ~ LLOC * arith_share_c + C(tool) + C(category)", data=d)
    r = m.fit(disp=0, maxiter=200, cov_type="cluster",
              cov_kwds={"groups": d["contract"].astype("category").cat.codes.to_numpy()})
    names = list(m.exog_names)
    out = []
    for term in ("LLOC", "arith_share_c", "LLOC:arith_share_c"):
        if term in names:
            i = names.index(term)
            out.append({"term": term,
                        "coef": float(np.asarray(r.params)[i]),
                        "se": float(np.asarray(r.bse)[i]),
                        "p": float(np.asarray(r.pvalues)[i])})
    tbl = pd.DataFrame(out)
    tbl.to_csv(TABLES / "newB_instance_mechanism.csv", index=False)
    print("\ninstance-level interaction (tool + category fixed effects,")
    print("SEs clustered by contract):")
    print(tbl.round(4).to_string(index=False))

    inter = tbl[tbl["term"] == "LLOC:arith_share_c"]
    if len(inter):
        c, p = float(inter["coef"].iloc[0]), float(inter["p"].iloc[0])
        direction = "NEGATIVE (as predicted)" if c < 0 else "POSITIVE (contrary)"
        verdict = "supported" if (c < 0 and p < 0.05) else (
            "directionally consistent, not significant" if c < 0 else "not supported")
        print(f"\ninteraction is {direction}, p={p:.4f}  -> mechanism {verdict}")
        print(f"n = {len(d):,} instances, versus n = 4 for the rank correlation")
    return tbl


def main() -> int:
    new_a()
    new_b()
    print(f"\ntables written to {TABLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
