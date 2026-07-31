#!/usr/bin/env python
"""The practitioner deliverable: complexity-guided audit triage.

An auditor cannot hand-review everything. Automated tools miss a large share of
bugs. If complexity predicts *where* the tools go blind, an auditor can spend a
limited manual budget on the contracts where the scanner is least trustworthy.

This script asks: order contracts by predicted detector-blindness, review them
by hand in that order, and how many tool-missed bugs do you catch per line of
code read?

Two things the earlier prototype got wrong and that are fixed here:

  * predictions are strictly out-of-sample (grouped k-fold by contract).
    In-sample failure probabilities inflate the curve, sometimes dramatically.
  * the curve is compared against honest baselines. A triage model is only
    useful if it beats "review the biggest contracts first", which is free.

Outcome modelled: does the deployed tool set miss at least one annotated bug in
this contract.

The tool set is a parameter, and that choice matters more than it looks. The
union of all 19 tools misses only 3.5% of annotated bugs -- triaging against it
is pointless. But no audit team runs 19 tools; they run one or two, and pay for
the false positives. So the default is Slither alone, the most widely deployed
tool in practice, with a realistic small combo reported alongside.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, FIGURES, TABLES  # noqa: E402
from sccomplex.model import select_metrics  # noqa: E402

RNG = 20260731
BUDGETS = (0.05, 0.10, 0.25, 0.50)


def build_contract_table(
    det: pd.DataFrame, metrics: list[str], tools: list[str] | None = None
) -> pd.DataFrame:
    """One row per contract: complexity, bug count, bugs missed by `tools`.

    A tool that crashed on a contract cannot have found anything there, so
    crashed runs count as misses for triage purposes -- an auditor gets no
    information either way. That differs from the RQ2 model, which deliberately
    excludes crashes to isolate detection ability from robustness.
    """
    d = det if tools is None else det[det["tool"].isin(tools)]
    d = d.copy()
    d["found"] = d["detected_category"].fillna(False).astype(bool)

    per_bug = d.groupby(["contract", "category"])["found"].any().rename("found_by_set")
    per_contract = (
        per_bug.reset_index()
        .groupby("contract")
        .agg(n_bugs=("found_by_set", "size"), n_found=("found_by_set", "sum"))
    )
    per_contract["n_missed"] = per_contract["n_bugs"] - per_contract["n_found"]
    per_contract["blind"] = (per_contract["n_missed"] > 0).astype(int)

    cols = list(dict.fromkeys(["contract", "SLOC", *metrics]))
    complexity = det[cols].drop_duplicates("contract").set_index("contract")

    return per_contract.join(complexity, how="inner").reset_index()


def out_of_sample_scores(tab: pd.DataFrame, metrics: list[str], n_splits: int = 5):
    """Grouped cross-validated P(blind). One row per contract, never fit on itself."""
    X = tab[metrics].to_numpy()
    y = tab["blind"].to_numpy()
    scores = np.full(len(tab), np.nan)

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=RNG)
    for train, test in skf.split(X, y):
        clf = GradientBoostingClassifier(random_state=RNG)
        clf.fit(X[train], y[train])
        scores[test] = clf.predict_proba(X[test])[:, 1]

    return scores


def triage_curve(tab: pd.DataFrame, order: np.ndarray) -> pd.DataFrame:
    """Cumulative missed bugs captured, against two different cost models.

    `loc_share`      lines of code read.
    `contract_share` contracts reviewed.

    Both are reported because they rank strategies differently, and the
    difference is not a detail. Under a pure LOC budget, "review the smallest
    contracts first" looks excellent -- it reviews a huge number of contracts
    for almost no lines, harvesting one bug each. That is an artefact of
    charging nothing for the fixed cost of picking up a contract, reading its
    context and writing it up. Under a per-contract budget the same strategy has
    no advantage at all. Real audit effort sits between the two.
    """
    t = tab.iloc[order]
    n = len(t)
    return pd.DataFrame(
        {
            "loc_share": (t["SLOC"].cumsum() / t["SLOC"].sum()).to_numpy(),
            "contract_share": np.arange(1, n + 1) / n,
            "missed_share": (t["n_missed"].cumsum() / max(t["n_missed"].sum(), 1)).to_numpy(),
        }
    )


def at_budget(curve: pd.DataFrame, budget: float, cost: str = "loc_share") -> float:
    """Share of missed bugs captured once `budget` of the cost has been spent."""
    hit = curve[curve[cost] <= budget]
    return float(hit["missed_share"].iloc[-1]) if len(hit) else 0.0


TOOL_SETS = {
    "slither": ["slither"],
    "slither+mythril": ["slither", "mythril"],
    "combo3": ["slither", "conkas", "smartcheck"],
    "all19": None,
}


def evaluate(det: pd.DataFrame, metrics: list[str], label: str, tools):
    tab = build_contract_table(det, metrics, tools)
    n_bugs, n_missed = int(tab["n_bugs"].sum()), int(tab["n_missed"].sum())

    print("\n" + "=" * 74)
    print(f"TOOL SET: {label}   ({'all 19' if tools is None else ', '.join(tools)})")
    print("=" * 74)
    print(f"contracts {len(tab):,} | bugs {n_bugs:,} | missed {n_missed:,} "
          f"({n_missed / n_bugs:.1%}) | blind contracts {tab['blind'].mean():.1%}")

    if tab["blind"].sum() < 30 or tab["blind"].nunique() < 2:
        print("too few blind contracts to model a triage ordering -- skipped")
        return None, None

    tab["p_blind"] = out_of_sample_scores(tab, metrics)
    auc = roc_auc_score(tab["blind"], tab["p_blind"])
    print(f"out-of-sample AUC (complexity -> blind spot): {auc:.3f}")

    rng = np.random.default_rng(RNG)
    strategies = {
        "complexity model": np.argsort(-tab["p_blind"].to_numpy(), kind="stable"),
        "largest first": np.argsort(-tab["SLOC"].to_numpy(), kind="stable"),
        "smallest first": np.argsort(tab["SLOC"].to_numpy(), kind="stable"),
        "random": rng.permutation(len(tab)),
    }
    curves = {n: triage_curve(tab, o) for n, o in strategies.items()}

    frames = []
    for cost, cost_label in (("loc_share", "LOC"), ("contract_share", "contracts")):
        s = pd.DataFrame(
            [{"strategy": n,
              **{f"@{int(b * 100)}%": at_budget(c, b, cost) for b in BUDGETS}}
             for n, c in curves.items()]
        ).set_index("strategy")
        print(f"\nmissed bugs captured, budget measured in {cost_label} (%):")
        print((s * 100).round(1).to_string())

        best = s.loc["complexity model"]
        for rival in ("largest first", "smallest first", "random"):
            lift = ", ".join(
                f"{c}: {(best[c] - s.loc[rival][c]) * 100:+.1f}pp" for c in s.columns
            )
            print(f"  vs {rival:<15} -> {lift}")

        frames.append(s.assign(cost_model=cost_label, auc=auc))

    return pd.concat(frames), curves


def main() -> int:
    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    metrics = select_metrics(det.drop_duplicates("contract"), threshold=0.9)
    print(f"contracts {det['contract'].nunique():,} | metrics {len(metrics)}")

    all_summaries, main_curves = [], None
    for label, tools in TOOL_SETS.items():
        summary, curves = evaluate(det, metrics, label, tools)
        if summary is None:
            continue
        all_summaries.append(summary.assign(tool_set=label))
        if label == "slither":
            main_curves = curves

    combined = pd.concat(all_summaries)
    combined.to_csv(TABLES / "triage_summary.csv")

    if main_curves is None:
        print("\nno curve to plot", file=sys.stderr)
        return 0

    curves = main_curves
    for name, curve in curves.items():
        curve.to_csv(TABLES / f"triage_curve_{name.replace(' ', '_')}.csv", index=False)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 5))
        for name, curve in curves.items():
            style = "-" if name == "complexity model" else "--"
            lw = 2.4 if name == "complexity model" else 1.3
            ax.plot(curve["loc_share"], curve["missed_share"], style, lw=lw, label=name)
        ax.plot([0, 1], [0, 1], ":", color="0.6", lw=1, label="no information")
        ax.set_xlabel("share of total LOC manually reviewed")
        ax.set_ylabel("share of Slither-missed bugs found")
        ax.set_title("Complexity-guided audit triage (deployed tool: Slither)")
        ax.legend(frameon=False)
        ax.grid(alpha=0.25)
        fig.tight_layout()
        out = FIGURES / "triage_curve.png"
        fig.savefig(out, dpi=150)
        print(f"\nfigure -> {out}")
    except Exception as e:  # plotting must never break the analysis
        print(f"(figure skipped: {type(e).__name__}: {e})", file=sys.stderr)

    print(f"tables -> {TABLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
