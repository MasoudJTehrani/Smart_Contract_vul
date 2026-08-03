#!/usr/bin/env python
"""S4: how much of the triage AUC is complexity, and how much is category mix?

The triage model reaches AUC 0.915 for a Slither-only deployment using
complexity features. Arithmetic contracts are both more detectable and
complexity-correlated, so part of that AUC may be recovering *vulnerability
category composition* rather than complexity. A category-only model attributes
the difference.

Interpretive caution, which must carry into the paper: in a real deployment you
do not know a contract's vulnerability category before running the tool -- that
is what the tool is for. The category-only model is therefore an **attribution
diagnostic, not a deployable baseline**. Its AUC is an upper bound on what
category information could contribute if it were somehow known in advance.

Same grouped 5-fold-by-contract CV and seed as scripts/07_triage.py, so the
complexity-only column reproduces the published figure exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, TABLES  # noqa: E402
from sccomplex.model import select_metrics  # noqa: E402

pd.set_option("display.width", 200)
RNG = 20260731  # identical to scripts/07_triage.py
TOOL_SETS = {
    "slither": ["slither"],
    "slither+mythril": ["slither", "mythril"],
    "combo3": ["slither", "conkas", "smartcheck"],
    "all19": None,
}


def _hdr(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def build(det: pd.DataFrame, metrics: list[str], tools) -> pd.DataFrame:
    d = det if tools is None else det[det["tool"].isin(tools)]
    d = d.copy()
    d["found"] = d["detected_category"].fillna(False).astype(bool)

    per_bug = d.groupby(["contract", "category"])["found"].any().rename("found_by_set")
    per_contract = (per_bug.reset_index().groupby("contract")
                    .agg(n_bugs=("found_by_set", "size"),
                         n_found=("found_by_set", "sum")))
    per_contract["blind"] = ((per_contract["n_bugs"] - per_contract["n_found"]) > 0).astype(int)

    cols = list(dict.fromkeys(["contract", "SLOC", *metrics]))
    cx = det[cols].drop_duplicates("contract").set_index("contract")

    # category-composition features: does this contract carry a bug of class c
    cat = (det.drop_duplicates(["contract", "category"])
           .assign(v=1).pivot_table(index="contract", columns="category",
                                    values="v", fill_value=0))
    cat.columns = [f"cat_{c}" for c in cat.columns]

    return per_contract.join(cx, how="inner").join(cat, how="left").fillna(0).reset_index()


def cv_auc(tab: pd.DataFrame, feats: list[str], n_splits: int = 5):
    """Grouped-by-contract 5-fold CV AUC, plus per-fold values for pairing."""
    X, y = tab[feats].to_numpy(), tab["blind"].to_numpy()
    oof = np.full(len(tab), np.nan)
    per_fold = []
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=RNG)
    for tr, te in skf.split(X, y):
        clf = GradientBoostingClassifier(random_state=RNG).fit(X[tr], y[tr])
        p = clf.predict_proba(X[te])[:, 1]
        oof[te] = p
        if len(np.unique(y[te])) > 1:
            per_fold.append(roc_auc_score(y[te], p))
    return roc_auc_score(y, oof), np.array(per_fold)


def main() -> int:
    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    metrics = select_metrics(det.drop_duplicates("contract"), threshold=0.9)

    _hdr("S4  Complexity vs category-composition attribution of the triage AUC")
    print("CAUTION: the category-only model is an ATTRIBUTION DIAGNOSTIC.")
    print("A deployment does not know a contract's vulnerability category before")
    print("running the tool, so this is not a baseline anyone could deploy.\n")

    rows = []
    for label, tools in TOOL_SETS.items():
        tab = build(det, metrics, tools)
        cat_feats = [c for c in tab.columns if c.startswith("cat_")]
        if tab["blind"].nunique() < 2 or tab["blind"].sum() < 30:
            print(f"{label}: too few blind contracts to model -- skipped")
            continue

        a_cx, f_cx = cv_auc(tab, metrics)
        a_cat, f_cat = cv_auc(tab, cat_feats)
        a_both, _ = cv_auc(tab, metrics + cat_feats)

        n = min(len(f_cx), len(f_cat))
        if n >= 2:
            t, p = stats.ttest_rel(f_cx[:n], f_cat[:n])
            diffs = f_cx[:n] - f_cat[:n]
            half = stats.t.ppf(0.975, n - 1) * diffs.std(ddof=1) / np.sqrt(n)
            ci = f"[{diffs.mean() - half:+.3f}, {diffs.mean() + half:+.3f}] (paired t p={p:.3f})"
        else:
            ci = "n/a"

        rows.append({"deployment": label, "auc_complexity": a_cx,
                     "auc_category": a_cat, "auc_combined": a_both,
                     "delta_complexity_minus_category": a_cx - a_cat,
                     "delta_ci_or_p": ci,
                     "blind_rate": float(tab["blind"].mean()),
                     "n_contracts": int(len(tab))})
        print(f"{label:<16} complexity {a_cx:.3f} | category {a_cat:.3f} | "
              f"combined {a_both:.3f} | delta {a_cx - a_cat:+.3f}")

    res = pd.DataFrame(rows)
    res.to_csv(TABLES / "s4_triage_baseline.csv", index=False)

    _hdr("S4 VERDICT")
    prim = res[res["deployment"] == "slither"]
    if len(prim):
        r = prim.iloc[0]
        print(f"Primary (Slither-only): complexity {r['auc_complexity']:.3f}, "
              f"category-only {r['auc_category']:.3f}, "
              f"delta {r['delta_complexity_minus_category']:+.3f}")
        print(f"  paired per-fold 95% CI on the difference: {r['delta_ci_or_p']}")
        if r["delta_complexity_minus_category"] > 0.05:
            print("  -> complexity carries information category composition does not.")
        elif r["delta_complexity_minus_category"] > 0:
            print("  -> complexity edges out category, but the margin is small;")
            print("     a material share of the AUC is category composition.")
        else:
            print("  -> ** category composition alone matches or beats complexity: **")
            print("     the triage AUC should not be attributed to complexity.")
    print(f"\n-> {TABLES / 's4_triage_baseline.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
