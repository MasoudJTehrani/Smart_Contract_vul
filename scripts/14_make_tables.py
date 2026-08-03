#!/usr/bin/env python
"""Generate the paper's LaTeX tables from the result CSVs.

Numbers in the manuscript are never transcribed by hand. Every table in
paper/emse/tables/ is written by this script from results/tables/, so a change
in the analysis propagates to the paper on the next run and cannot silently
disagree with it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import ROOT, TABLES  # noqa: E402

OUT = ROOT / "paper" / "emse" / "tables"
OUT.mkdir(parents=True, exist_ok=True)

# One metric is literally named "NA"; pandas otherwise reads it back as missing.
READ = dict(keep_default_na=False, na_values=[""])


def fmt_p(p) -> str:
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "--"
    if p != p:
        return "--"
    if p < 0.0001:
        return "$<$0.0001"
    return f"{p:.4f}".rstrip("0").rstrip(".")


def sig(p) -> str:
    try:
        p = float(p)
    except (TypeError, ValueError):
        return ""
    return "$^{*}$" if p < 0.05 else ""


def write(name: str, body: str) -> None:
    (OUT / f"{name}.tex").write_text(body)
    print(f"  wrote tables/{name}.tex")


def tabular(header: list[str], rows: list[list[str]], align: str) -> str:
    out = [f"\\begin{{tabular}}{{{align}}}", "\\toprule",
           " & ".join(header) + " \\\\", "\\midrule"]
    out += [" & ".join(r) + " \\\\" for r in rows]
    out += ["\\bottomrule", "\\end{tabular}"]
    return "\n".join(out)


def t_redundancy() -> None:
    df = pd.read_csv(TABLES / "metric_correlation.csv", index_col=0, **READ)
    metrics = list(df.columns)
    pairs = [
        (metrics[i], metrics[j], df.iloc[i, j])
        for i in range(len(metrics)) for j in range(i + 1, len(metrics))
        if abs(float(df.iloc[i, j])) >= 0.9
    ]
    pairs.sort(key=lambda t: -abs(t[2]))
    half = (len(pairs) + 1) // 2
    rows = []
    for a, b in zip(pairs[:half], pairs[half:] + [None] * half):
        left = f"{a[0]} -- {a[1]} & {a[2]:.3f}"
        right = f"{b[0]} -- {b[1]} & {b[2]:.3f}" if b else " & "
        rows.append([left, right])
    body = "\n".join(
        ["\\begin{tabular}{llll}", "\\toprule",
         "Pair & $\\rho$ & Pair & $\\rho$ \\\\", "\\midrule"]
        + [" & ".join(r) + " \\\\" for r in rows]
        + ["\\bottomrule", "\\end{tabular}"]
    )
    write("redundancy", body)


def t_coeffs(src: str, name: str) -> None:
    df = pd.read_csv(TABLES / src, index_col=0, **READ)
    df = df.astype({"coef": float, "p": float, "odds_ratio": float})
    df = df.sort_values("coef", ascending=False)
    rows = [
        [i, f"{r.coef:+.3f}", f"{r.odds_ratio:.2f}", fmt_p(r.p) + sig(r.p)]
        for i, r in df.iterrows()
    ]
    write(name, tabular(["Metric", "Coef.", "OR", "$p$"], rows, "lrrr"))


def t_class_slopes() -> None:
    det = pd.read_csv(TABLES / "slopes_by_class_missed.csv", **READ)
    run = pd.read_csv(TABLES / "slopes_by_class_failed.csv", **READ)
    m = det.merge(run, on="detector_class", suffixes=("_det", "_run"))
    order = ["symbolic", "static", "linter", "fuzzing"]
    m["o"] = m["detector_class"].map({k: i for i, k in enumerate(order)})
    m = m.sort_values("o")
    rows = []
    for r in m.itertuples():
        rows.append([
            r.detector_class,
            f"{float(r.coef_det):+.3f}{sig(r.p_det)}", fmt_p(r.p_det),
            f"{float(r.coef_run):+.3f}{sig(r.p_run)}", fmt_p(r.p_run),
        ])
    write("class_slopes", tabular(
        ["Detector class", "Detection", "$p$", "Analysis", "$p$"], rows, "lrrrr"))


def t_robustness() -> None:
    df = pd.read_csv(TABLES / "robust_verdict.csv", **READ)
    cols = ["baseline", "B: single-bug", "D: no arithmetic"]
    rows = []
    for r in df.sort_values("sign_stable", ascending=False).itertuples():
        d = r._asdict()
        vals = []
        for c in cols:
            v = d.get(c.replace(" ", "_").replace(":", "").replace("-", "_"))
            if v is None:
                v = getattr(r, "_" + str(df.columns.get_loc(c) + 1), None)
            try:
                fv = float(v)
                vals.append("--" if fv != fv else f"{fv:+.3f}")
            except (TypeError, ValueError):
                vals.append("--")
        rows.append([r.tool] + vals +
                    ["\\checkmark" if r.sign_stable else "\\textbf{flips}"])
    write("robustness", tabular(
        ["Tool", "Baseline", "Single-bug", "No arith.", "Stable"], rows, "lrrrc"))


def t_by_category() -> None:
    df = pd.read_csv(TABLES / "robust_c_by_category.csv", **READ)
    df = df[df["coef"].astype(str) != ""].copy()
    df[["coef", "p", "n"]] = df[["coef", "p", "n"]].astype(float)
    rows = [
        [r.category.replace("_", "\\_"), f"{int(r.n)}",
         f"{r.coef:+.3f}{sig(r.p)}", fmt_p(r.p)]
        for r in df.sort_values("coef", ascending=False).itertuples()
    ]
    write("by_category", tabular(["Category", "$n$", "LLOC slope", "$p$"], rows, "lrrr"))


def t_triage() -> None:
    df = pd.read_csv(TABLES / "triage_summary.csv", **READ)
    df = df[(df["cost_model"] == "contracts") & (df["tool_set"] == "slither")]
    cols = ["@5%", "@10%", "@25%", "@50%"]
    order = ["complexity model", "largest first", "smallest first", "random"]
    df["o"] = df["strategy"].map({k: i for i, k in enumerate(order)})
    rows = []
    for r in df.sort_values("o").itertuples():
        vals = [f"{float(getattr(r, '_' + str(df.columns.get_loc(c) + 1))) * 100:.1f}"
                for c in cols]
        label = r.strategy
        if label == "complexity model":
            label = "\\textbf{complexity model}"
            vals = [f"\\textbf{{{v}}}" for v in vals]
        rows.append([label] + vals)
    write("triage", tabular(
        ["Strategy", "5\\%", "10\\%", "25\\%", "50\\%"], rows, "lrrrr"))


def t_interaction() -> None:
    df = pd.read_csv(TABLES / "dappscan_c2_interaction.csv", **READ)
    df[["slither_slope", "mythril_minus_slither", "p_interaction"]] = df[
        ["slither_slope", "mythril_minus_slither", "p_interaction"]].astype(float)
    rows = []
    for r in df.sort_values("p_interaction").itertuples():
        name = r.metric
        bold = r.p_interaction < 0.05
        cells = [name, f"{r.slither_slope:+.3f}",
                 f"{r.mythril_minus_slither:+.3f}", fmt_p(r.p_interaction)]
        if bold:
            cells = [f"\\textbf{{{c}}}" for c in cells]
        rows.append(cells)
    write("interaction", tabular(
        ["Metric", "Slither", "Mythril $-$ Slither", "$p$"], rows, "lrrr"))


def t_three_corpus() -> None:
    df = pd.read_csv(TABLES / "reentrancy_three_corpus.csv", **READ)
    df[["n", "coef", "p"]] = df[["n", "coef", "p"]].astype(float)
    prov = {"Salzano (main)": "researcher annotation",
            "DAppSCAN": "human report extraction",
            "FORGE": "LLM report extraction"}
    rows = [
        [r.corpus, prov.get(r.corpus, ""), f"{int(r.n)}",
         f"{r.coef:+.3f}{sig(r.p)}", fmt_p(r.p)]
        for r in df.itertuples()
    ]
    write("three_corpus", tabular(
        ["Corpus", "Ground truth", "$n$", "LLOC slope", "$p$"], rows, "llrrr"))


def t_forge_slopes() -> None:
    df = pd.read_csv(TABLES / "forge_reentrancy_slopes.csv", **READ)
    df[["coef", "p"]] = df[["coef", "p"]].astype(float)
    rows = [
        [r.metric, f"{r.coef:+.3f}{sig(r.p)}", fmt_p(r.p)]
        for r in df.sort_values("coef").itertuples()
    ]
    write("forge_slopes", tabular(["Metric", "Slope", "$p$"], rows, "lrr"))


def main() -> int:
    print(f"generating LaTeX tables into {OUT}")
    t_redundancy()
    t_coeffs("rq2_detection_failure.csv", "rq2_detection")
    t_coeffs("rq3_analysis_failure.csv", "rq3_analysis")
    t_class_slopes()
    t_robustness()
    t_by_category()
    t_triage()
    t_interaction()
    t_three_corpus()
    t_forge_slopes()
    revisions()
    print("done")
    return 0



# ---------------------------------------------------------------- revisions
def t_new1_linematch() -> None:
    df = pd.read_csv(TABLES / "new1_rq2_line_vs_category.csv", index_col=0, **READ)
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    rows = [[i, f"{r.coef_category:+.3f}{sig(r.p_category)}", fmt_p(r.p_category),
             f"{r.coef_line:+.3f}{sig(r.p_line)}", fmt_p(r.p_line)]
            for i, r in df.iterrows()]
    write("new1_linematch", tabular(
        ["Metric", "Category coef.", "$p$", "Line coef.", "$p$"], rows, "lrrrr"))


def t_new2_vif() -> None:
    a = pd.read_csv(TABLES / "new2_vif.csv", **READ)
    b = pd.read_csv(TABLES / "new2_vif_pruned.csv", **READ)
    a["VIF"] = pd.to_numeric(a["VIF"]); b["VIF"] = pd.to_numeric(b["VIF"])
    keep = set(b["metric"])
    rows = []
    for r in a.sort_values("VIF", ascending=False).itertuples():
        after = b.loc[b["metric"] == r.metric, "VIF"]
        rows.append([r.metric, f"{r.VIF:.1f}",
                     f"{after.iloc[0]:.2f}" if len(after) else "\\emph{dropped}",
                     "\\checkmark" if r.metric in keep else ""])
    write("new2_vif", tabular(
        ["Metric", "VIF ($\\rho$-screened)", "VIF (pruned)", "Entered"], rows, "lrrc"))


def t_new3_twoway() -> None:
    df = pd.read_csv(TABLES / "new3_two_way_clustering.csv", **READ)
    for c in ("coef", "p_1way", "p_2way", "se_ratio"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    rows = []
    for fam in df["model"].unique():
        s = df[df["model"] == fam].sort_values("p_2way")
        rows.append([f"\\multicolumn{{5}}{{l}}{{\\emph{{{fam}}}}}", "", "", "", ""])
        for r in s.itertuples():
            mark = "\\textbf{loses}" if r.changed else ""
            rows.append([f"\\quad {r.metric}", f"{r.coef:+.3f}",
                         fmt_p(r.p_1way), fmt_p(r.p_2way), mark])
    write("new3_twoway", tabular(
        ["Metric", "Coef.", "$p$ (1-way)", "$p$ (2-way)", ""], rows, "lrrrl"))


def t_gauntlet() -> None:
    df = pd.read_csv(TABLES / "new_gauntlet.csv", **READ)
    for c in ("coef", "p_2way", "p_2way_bh"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    rows = []
    for fam in df["family"].unique():
        s = df[df["family"] == fam].sort_values("p_2way_bh")
        rows.append([f"\\multicolumn{{4}}{{l}}{{\\emph{{{fam}}}}}", "", "", ""])
        for r in s.itertuples():
            cells = [f"\\quad {r.metric}", f"{r.coef:+.3f}", fmt_p(r.p_2way_bh),
                     "\\checkmark" if r.survives else ""]
            if r.survives:
                cells = [f"\\quad \\textbf{{{r.metric}}}", f"\\textbf{{{r.coef:+.3f}}}",
                         f"\\textbf{{{fmt_p(r.p_2way_bh)}}}", "\\checkmark"]
            rows.append(cells)
    write("gauntlet", tabular(
        ["Metric", "Coef.", "$p$ (2-way, BH)", "Survives"], rows, "lrrc"))


def t_new5_power() -> None:
    df = pd.read_csv(TABLES / "new5_power.csv", **READ)
    for c in ("n", "events", "beta", "power", "mde_80"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    rows = [[r.corpus, f"{int(r.n)}", f"{int(r.events)}", f"{r.power:.1%}".replace("%", "\\%"),
             f"{r.mde_80:.2f}"] for r in df.itertuples()]
    write("new5_power", tabular(
        ["Corpus", "$n$", "Misses", "Power at $\\beta{=}0.278$", "MDE (80\\%)"],
        rows, "lrrrr"))


def t_new6_mix() -> None:
    df = pd.read_csv(TABLES / "new6_category_mix.csv", **READ)
    for c in ("instances", "arithmetic_share", "LLOC_slope", "p"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    rows = [[r.benchmark.replace("_", "\\_"), f"{int(r.instances)}",
             f"{r.arithmetic_share:.1%}".replace("%", "\\%"),
             f"{r.LLOC_slope:+.3f}{sig(r.p)}", fmt_p(r.p)]
            for r in df.sort_values("arithmetic_share").itertuples()]
    write("new6_mix", tabular(
        ["Sub-benchmark", "Instances", "Arithmetic", "LLOC slope", "$p$"], rows, "lrrrr"))


def t_rq_vif(src: str, name: str) -> None:
    df = pd.read_csv(TABLES / src, index_col=0, **READ)
    for c in ("coef", "p", "odds_ratio"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    rows = [[i, f"{r.coef:+.3f}", f"{r.odds_ratio:.2f}", fmt_p(r.p) + sig(r.p)]
            for i, r in df.sort_values("coef", ascending=False).iterrows()]
    write(name, tabular(["Metric", "Coef.", "OR", "$p$"], rows, "lrrr"))


def t_newA_types() -> None:
    df = pd.read_csv(TABLES / "newA_type_s.csv", **READ)
    for c in ("n","events","power","type_s","type_m","mde_80"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    rows = [[r.corpus, f"{int(r.n)}", f"{int(r.events)}",
             f"{r.power:.1%}".replace("%","\\%"),
             f"{r.mde_80:.2f}",
             f"{r.type_s:.1%}".replace("%","\\%"),
             f"{r.type_m:.2f}$\\times$"] for r in df.itertuples()]
    write("newA_types", tabular(
        ["Corpus","$n$","Misses","Power","MDE (80\\%)","Type-S","Type-M"],
        rows, "lrrrrrr"))


def t_newB_mechanism() -> None:
    df = pd.read_csv(TABLES / "newB_instance_mechanism.csv", **READ)
    for c in ("coef","se","p"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    pretty = {"LLOC": "LLOC", "arith_share_c": "Arithmetic share (centred)",
              "LLOC:arith_share_c": "LLOC $\\times$ arithmetic share"}
    rows = []
    for r in df.itertuples():
        name = pretty.get(r.term, r.term)
        cells = [name, f"{r.coef:+.3f}", f"{r.se:.3f}", fmt_p(r.p) + sig(r.p)]
        if r.term == "LLOC:arith_share_c":
            cells = [f"\\textbf{{{c}}}" for c in cells]
        rows.append(cells)
    write("newB_mechanism", tabular(
        ["Term", "Coef.", "SE", "$p$"], rows, "lrrr"))


def revisions() -> None:
    t_new1_linematch(); t_new2_vif(); t_new3_twoway(); t_gauntlet()
    t_new5_power(); t_new6_mix()
    t_rq_vif("rq2_detection_failure_vif.csv", "rq2_detection_vif")
    t_rq_vif("rq3_analysis_failure_vif.csv", "rq3_analysis_vif")
    t_newA_types(); t_newB_mechanism()

if __name__ == "__main__":
    raise SystemExit(main())
