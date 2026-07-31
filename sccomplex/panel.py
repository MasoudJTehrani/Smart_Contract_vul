"""Construction of the analysis panel.

The outcome unit is the **(vulnerability instance x tool) pair**, not the
contract. A contract-level "did the tool get everything right" flag -- as used
in the earlier prototype -- collapses "missed one of five bugs" into "found
nothing", destroys outcome variance, and produces degenerate all-zero
regressions. One row per bug per tool keeps the variance and lets contract and
tool be modelled as random effects.

Two matching semantics are computed and reported side by side, because they
answer different questions and disagree substantially:

  detected_category : the tool reported the right vulnerability category
                      somewhere in the contract. This is the protocol of
                      Durieux et al. (ICSE'20) and Salzano et al. (EMSE'26),
                      and is the only option for the 21% of findings that
                      carry no line information.

  detected_line     : the tool reported the right category *and* placed it
                      within `tol` lines of the annotated location. Stricter,
                      and the relevant notion if a tool's output is meant to
                      direct an auditor's attention.

`analysis_failed` marks runs where the tool crashed or timed out. These are
NOT silently counted as misses: a tool that never ran has failed differently
from one that ran and missed, and complexity may drive the two differently.
"""
from __future__ import annotations

import pandas as pd

from sccomplex.config import DETECTOR_CLASS
from sccomplex.data import salzano

DEFAULT_TOLERANCE = 5


def _line_hit(gt_lines: frozenset[int], det_lines: frozenset[int], tol: int) -> bool:
    if not gt_lines or not det_lines:
        return False
    return any(abs(g - d) <= tol for g in gt_lines for d in det_lines)


def build_detection_panel(
    tol: int = DEFAULT_TOLERANCE,
    exclude_arithmetic: bool = False,
) -> pd.DataFrame:
    """One row per (vulnerability instance, tool).

    Columns:
        contract, corpus, category, gt_lines, tool, detector_class,
        analysis_failed, detected_category, detected_line
    """
    gt = salzano.load_ground_truth(exclude_arithmetic=exclude_arithmetic)
    det = salzano.load_detections(exclude_arithmetic=exclude_arithmetic)

    vulns = gt[~gt["is_safe"]].copy()

    # Index detections by contract for a single pass over the cross product.
    by_contract: dict[str, list[dict]] = {}
    for rec in det.to_dict("records"):
        by_contract.setdefault(rec["contract"], []).append(rec)

    rows = []
    for v in vulns.itertuples():
        for run in by_contract.get(v.contract, ()):
            failed = run["status"] == salzano.STATUS_ERROR
            cat_hit = v.category in run["categories"]
            line_hit = cat_hit and _line_hit(
                v.lines, run["lines_by_category"].get(v.category, frozenset()), tol
            )

            rows.append(
                {
                    "contract": v.contract,
                    "corpus": v.corpus,
                    "category": v.category,
                    # Stored as a sorted list: frozensets are not serialisable
                    # to parquet.
                    "gt_lines": sorted(v.lines),
                    "tool": run["tool"],
                    "detector_class": DETECTOR_CLASS.get(run["tool"], "unknown"),
                    "analysis_failed": bool(failed),
                    # A crashed run is not evidence of a miss; left as NA so
                    # that detection models can exclude it explicitly.
                    "detected_category": pd.NA if failed else bool(cat_hit),
                    "detected_line": pd.NA if failed else bool(line_hit),
                }
            )

    return pd.DataFrame(rows)


def build_run_panel(exclude_arithmetic: bool = False) -> pd.DataFrame:
    """One row per (contract, tool) run -- the unit for analysis-failure models.

    Unlike the detection panel this includes contracts annotated as safe,
    because whether a tool crashes does not depend on there being a bug.
    """
    gt = salzano.load_ground_truth(exclude_arithmetic=exclude_arithmetic)
    det = salzano.load_detections(exclude_arithmetic=exclude_arithmetic)

    corpus_of = dict(zip(gt["contract"], gt["corpus"]))
    n_vulns = (
        gt[~gt["is_safe"]].groupby("contract").size().rename("n_vulns")
    )

    panel = det.assign(
        corpus=det["contract"].map(corpus_of),
        detector_class=det["tool"].map(DETECTOR_CLASS).fillna("unknown"),
        analysis_failed=det["status"].eq(salzano.STATUS_ERROR),
        n_reported=det["categories"].apply(len),
    ).merge(n_vulns, left_on="contract", right_index=True, how="left")

    panel["n_vulns"] = panel["n_vulns"].fillna(0).astype(int)
    return panel.drop(columns=["categories", "lines_by_category"])


def attach_metrics(panel: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """Join per-contract complexity metrics onto a panel.

    The metric extractor emits one row per *contract declaration*, while the
    detection data is per *file*. A .sol file routinely declares several
    contracts (a token plus SafeMath plus Ownable), so file-level complexity is
    aggregated: sums for size and count metrics, max for inheritance depth,
    and a size-weighted mean for the Avg. family.
    """
    from sccomplex.config import SOLMET_METRICS

    m = metrics.copy()
    m["contract"] = m["file"].map(lambda p: p.rsplit("/", 1)[-1].removesuffix(".sol"))

    sum_cols = ["SLOC", "LLOC", "CLOC", "NF", "WMC", "NL", "NLE", "NUMPAR", "NOS", "NA", "NOI"]
    max_cols = ["DIT", "NOA", "NOD", "CBO"]
    avg_cols = [c for c in SOLMET_METRICS if c.startswith("Avg")]

    agg = {c: "sum" for c in sum_cols}
    agg.update({c: "max" for c in max_cols})

    grouped = m.groupby("contract").agg(agg)

    # Weight the averages by function count so a one-function helper contract
    # does not carry the same weight as the main contract in the same file.
    weights = m.groupby("contract")["NF"].sum().replace(0, pd.NA)
    for c in avg_cols:
        num = m.assign(_w=m[c] * m["NF"]).groupby("contract")["_w"].sum()
        grouped[c] = (num / weights).fillna(0.0)

    grouped["n_declarations"] = m.groupby("contract").size()

    return panel.merge(grouped, left_on="contract", right_index=True, how="inner")
