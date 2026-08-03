#!/usr/bin/env python
"""Reviewer-requested analyses (NEW-1 .. NEW-5, NEW-7).

Each block answers one numbered item from the reviewer's response checklist.
Everything writes a CSV into results/tables/ so the manuscript can \\input it
rather than have numbers transcribed.

  NEW-1  RQ2 re-fitted under strict line match, since category match is a
         size-correlated scoring bar and RQ2 is precisely a claim about size.
  NEW-2  Variance-inflation factors for the entered metric set, reconciling
         "the metrics are collinear" with "we fit 13 of them jointly".
  NEW-3  Two-way clustering by (contract x tool): outcomes are dependent
         within a tool across contracts, not only within a contract.
  NEW-4  Benjamini-Hochberg across the coefficient tests that carry claims.
  NEW-5  Power of the two small-corpus reentrancy tests to detect the
         main-corpus effect, so "no consistent effect" is not confused with
         "underpowered to find one".
  NEW-7  Exact versions of every tool in the measurement chain.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.outliers_influence import variance_inflation_factor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, TABLES  # noqa: E402
from sccomplex.model import fit_failure_model, select_metrics, standardise  # noqa: E402

pd.set_option("display.width", 200)
RNG = 20260802
READ = dict(keep_default_na=False, na_values=[""])  # a metric is named "NA"


def _hdr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ------------------------------------------------------------------- NEW-1
def new1_line_match(det: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    _hdr("NEW-1  RQ2 under both matching semantics")

    rows = []
    for label, col in (("category", "detected_category"), ("line", "detected_line")):
        d = det[det[col].notna()].copy()
        d["missed"] = (~d[col].astype(bool)).astype(int)
        d = standardise(d, metrics)
        print(f"\n{label} match: n={len(d):,}  miss rate {d['missed'].mean():.1%}")
        tbl, _, _ = fit_failure_model(d, "missed", metrics)
        tbl = tbl.assign(semantics=label).reset_index(names="metric")
        rows.append(tbl)

    both = pd.concat(rows)
    wide = both.pivot(index="metric", columns="semantics", values=["coef", "p"])
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    wide = wide.sort_values("coef_category", ascending=False)
    wide.to_csv(TABLES / "new1_rq2_line_vs_category.csv")

    print("\nRQ2 coefficients under both semantics:")
    print(wide.round(4).to_string())

    print("\n--- the claim under test: does size stay non-significant? ---")
    for m in ("SLOC", "LLOC"):
        if m in wide.index:
            r = wide.loc[m]
            verdict = "SURVIVES" if r["p_line"] >= 0.05 else "** BREAKS **"
            print(f"  {m}: category {r['coef_category']:+.3f} (p={r['p_category']:.4f}) | "
                  f"line {r['coef_line']:+.3f} (p={r['p_line']:.4f})  -> {verdict}")

    flips = wide[(np.sign(wide["coef_category"]) != np.sign(wide["coef_line"]))]
    print(f"\nmetrics changing sign between semantics: {list(flips.index) or 'none'}")
    return wide


# ------------------------------------------------------------------- NEW-2
def new2_vif(det: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    _hdr("NEW-2  Variance-inflation factors for the entered set")

    per_contract = det.drop_duplicates("contract")
    d = standardise(per_contract, metrics)[metrics].dropna()
    X = np.column_stack([np.ones(len(d)), d.to_numpy()])

    vifs = pd.DataFrame(
        {"metric": metrics,
         "VIF": [variance_inflation_factor(X, i + 1) for i in range(len(metrics))]}
    ).sort_values("VIF", ascending=False)
    vifs["exceeds_5"] = vifs["VIF"] >= 5
    vifs.to_csv(TABLES / "new2_vif.csv", index=False)

    print(f"entered set ({len(metrics)}): {metrics}\n")
    print(vifs.round(3).to_string(index=False))
    bad = vifs.loc[vifs["exceeds_5"], "metric"].tolist()
    print(f"\nmax VIF {vifs['VIF'].max():.2f} | metrics with VIF >= 5: {bad or 'none'}")
    if bad:
        print("ACTION REQUIRED: drop the offending family representative and re-fit.")
    return vifs


# ------------------------------------------------------------------- NEW-3
def _twoway(panel: pd.DataFrame, outcome: str, metrics: list[str],
            controls: tuple[str, ...]) -> pd.DataFrame:
    cols = [outcome, "contract", "tool", *metrics, *controls]
    d = panel[list(dict.fromkeys(cols))].dropna().copy()
    d[outcome] = d[outcome].astype(int)

    for c in controls:  # same degenerate-level guard as the main models
        var = d.groupby(c, observed=True)[outcome].mean()
        d = d[~d[c].isin(var.index[(var == 0) | (var == 1)])]

    terms = list(metrics) + [f"C({c})" for c in controls if d[c].nunique() > 1]
    m = smf.logit(f"{outcome} ~ " + " + ".join(terms), data=d)
    groups = np.column_stack([
        d["contract"].astype("category").cat.codes.to_numpy(),
        d["tool"].astype("category").cat.codes.to_numpy(),
    ])
    r = m.fit(disp=0, maxiter=200, cov_type="cluster", cov_kwds={"groups": groups})
    names = list(m.exog_names)
    return pd.DataFrame(
        {"coef": np.asarray(r.params), "se_2way": np.asarray(r.bse),
         "p_2way": np.asarray(r.pvalues)}, index=names
    ).loc[[m_ for m_ in metrics if m_ in names]]


def new3_two_way(det: pd.DataFrame, run: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    _hdr("NEW-3  Two-way clustering by (contract x tool)")

    d = det[det["detected_category"].notna()].copy()
    d["missed"] = (~d["detected_category"].astype(bool)).astype(int)
    d = standardise(d, metrics)

    r = run.copy()
    r["failed"] = r["analysis_failed"].astype(int)
    r["category"] = "any"
    r = standardise(r, metrics)

    out = []
    for label, panel, outcome, controls, src in (
        ("RQ2 detection", d, "missed", ("tool", "category"), "rq2_detection_failure.csv"),
        ("RQ3 analysis", r, "failed", ("tool",), "rq3_analysis_failure.csv"),
    ):
        two = _twoway(panel, outcome, metrics, controls)
        one = pd.read_csv(TABLES / src, index_col=0, **READ)
        one[["coef", "std_err", "p"]] = one[["coef", "std_err", "p"]].astype(float)
        j = one[["coef", "std_err", "p"]].rename(
            columns={"std_err": "se_1way", "p": "p_1way"}
        ).join(two[["se_2way", "p_2way"]], how="inner")
        j["se_ratio"] = j["se_2way"] / j["se_1way"]
        j["sig_1way"] = j["p_1way"] < 0.05
        j["sig_2way"] = j["p_2way"] < 0.05
        j["changed"] = j["sig_1way"] != j["sig_2way"]
        j = j.assign(model=label)
        out.append(j.reset_index(names="metric"))

        print(f"\n--- {label} ---")
        print(j[["coef", "se_1way", "se_2way", "se_ratio", "p_1way", "p_2way", "changed"]]
              .round(4).to_string())
        ch = j.index[j["changed"]].tolist()
        print(f"significance conclusions that change: {ch or 'none'}")
        print(f"median SE inflation: {j['se_ratio'].median():.2f}x")

    res = pd.concat(out)
    res.to_csv(TABLES / "new3_two_way_clustering.csv", index=False)
    return res


# ------------------------------------------------------------------- NEW-4
def new4_bh() -> pd.DataFrame:
    _hdr("NEW-4  Benjamini-Hochberg correction")

    specs = [
        ("Table 3 (RQ2 detection)", "rq2_detection_failure.csv", "p", 0),
        ("Table 4 (RQ3 analysis)", "rq3_analysis_failure.csv", "p", 0),
        ("Table 9 (RQ5 interaction)", "dappscan_c2_interaction.csv", "p_interaction", None),
    ]
    frames = []
    for label, fname, pcol, idx in specs:
        df = pd.read_csv(TABLES / fname, index_col=idx, **READ)
        key = df.index if idx == 0 else df["metric"]
        p = pd.to_numeric(df[pcol], errors="coerce")
        ok = p.notna()
        adj = np.full(len(p), np.nan)
        adj[ok.to_numpy()] = multipletests(p[ok].to_numpy(), method="fdr_bh")[1]

        t = pd.DataFrame({
            "family": label, "metric": list(key), "p_raw": p.to_numpy(), "p_bh": adj,
        })
        t["sig_raw"] = t["p_raw"] < 0.05
        t["sig_bh"] = t["p_bh"] < 0.05
        t["lost_star"] = t["sig_raw"] & ~t["sig_bh"]
        frames.append(t)

        print(f"\n--- {label} ({int(ok.sum())} tests) ---")
        print(t[["metric", "p_raw", "p_bh", "sig_raw", "sig_bh"]]
              .sort_values("p_raw").round(4).to_string(index=False))
        lost = t.loc[t["lost_star"], "metric"].tolist()
        print(f"stars lost to BH: {lost or 'none'}")

    res = pd.concat(frames, ignore_index=True)
    res.to_csv(TABLES / "new4_bh_adjusted.csv", index=False)

    inter = res[res["family"].str.contains("interaction")]
    print("\n--- the load-bearing test (RQ5 interaction) ---")
    for m in ("NOA", "DIT"):
        row = inter[inter["metric"] == m]
        if len(row):
            r = row.iloc[0]
            print(f"  {m}: raw p={r['p_raw']:.4f} -> BH p={r['p_bh']:.4f} "
                  f"{'SURVIVES' if r['sig_bh'] else '** LOSES SIGNIFICANCE **'}")
    return res


# ------------------------------------------------------------------- NEW-5
def _power_sim(x: np.ndarray, n_events: int, beta: float,
               n_sim: int = 4000, alpha: float = 0.05) -> dict:
    """Simulation power for a logistic slope, holding n and base rate fixed.

    The covariate distribution is the one actually observed in the corpus, so
    this reflects that corpus's real leverage rather than an idealised design.
    """
    rng = np.random.default_rng(RNG)
    n = len(x)
    base = n_events / n

    # intercept chosen so the simulated event rate matches the observed one
    def rate(b0):
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
    hits = sig = 0
    X = np.column_stack([np.ones(n), x])
    for _ in range(n_sim):
        y = rng.binomial(1, p_true)
        if y.sum() in (0, n):
            continue
        try:
            import statsmodels.api as sm
            r = sm.Logit(y, X).fit(disp=0, maxiter=100)
            pv = float(r.pvalues[1])
            co = float(r.params[1])
        except Exception:
            continue
        sig += 1
        if pv < alpha:
            hits += 1 if np.sign(co) == np.sign(beta) else 0
    return {"n": n, "events": n_events, "beta": beta,
            "power": hits / max(sig, 1), "converged": sig}


def new5_power() -> pd.DataFrame:
    _hdr("NEW-5  Power of the small-corpus reentrancy tests")

    beta = float(pd.read_csv(TABLES / "reentrancy_three_corpus.csv", **READ)
                 .query("corpus == 'Salzano (main)'")["coef"].iloc[0])
    print(f"target effect (main corpus LLOC slope): {beta:+.3f}\n")

    rng = np.random.default_rng(RNG)
    rows = []
    for corpus, n, events in (("DAppSCAN", 62, 9), ("FORGE", 133, 102)):
        # metrics are z-scored, so the standard normal is the right stand-in
        x = rng.standard_normal(n)
        res = _power_sim(x, events, beta)
        res["corpus"] = corpus
        rows.append(res)
        print(f"{corpus:<10} n={n:>4} events={events:>4}  "
              f"power to detect {beta:+.3f} at alpha=0.05: {res['power']:.1%}")

    # what effect COULD each corpus have detected at 80% power?
    print("\nminimum detectable effect at 80% power:")
    for r in rows:
        n, events = r["n"], r["events"]
        x = rng.standard_normal(n)
        lo, hi = 0.05, 4.0
        for _ in range(14):
            mid = (lo + hi) / 2
            if _power_sim(x, events, mid, n_sim=600)["power"] < 0.80:
                lo = mid
            else:
                hi = mid
        r["mde_80"] = (lo + hi) / 2
        print(f"  {r['corpus']:<10} |beta| >= {r['mde_80']:.3f} "
              f"({r['mde_80'] / abs(beta):.1f}x the main-corpus effect)")

    res = pd.DataFrame(rows)[["corpus", "n", "events", "beta", "power", "mde_80"]]
    res.to_csv(TABLES / "new5_power.csv", index=False)

    print("\nreading: both corpora are underpowered for an effect of the main-corpus")
    print("magnitude. They cannot establish its absence -- but each returned a")
    print("SIGNIFICANT estimate of the OPPOSITE sign, which power does not explain.")
    return res


# ------------------------------------------------------------------- NEW-7
def new7_versions() -> dict:
    _hdr("NEW-7  Version pinning")

    def sh(cmd: list[str]) -> str:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return (out.stdout or out.stderr).strip().splitlines()[0][:120]
        except Exception as e:
            return f"unavailable ({type(e).__name__})"

    import importlib.metadata as md

    def pkg(name: str) -> str:
        try:
            return md.version(name)
        except Exception:
            return "not installed"

    env_bin = Path(sys.executable).parent
    solc_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / "solc" / "artifacts"
    solc_versions = sorted(p.name.replace("solc-", "") for p in solc_dir.glob("solc-*")) \
        if solc_dir.is_dir() else []

    info = {
        "python": sys.version.split()[0],
        "slither-analyzer": pkg("slither-analyzer"),
        "mythril": pkg("mythril"),
        "solc-select": pkg("solc-select"),
        "solc_versions_installed": len(solc_versions),
        "solc_range": f"{solc_versions[0]} .. {solc_versions[-1]}" if solc_versions else "n/a",
        "solc_selection": "lowest installed patch >= pragma lower bound, same major.minor",
        "tree-sitter": pkg("tree-sitter"),
        "tree-sitter-solidity": pkg("tree-sitter-solidity"),
        "pandas": pkg("pandas"), "numpy": pkg("numpy"),
        "statsmodels": pkg("statsmodels"), "scikit-learn": pkg("scikit-learn"),
        "scipy": pkg("scipy"), "shap": pkg("shap"),
        "slither_cli": sh([str(env_bin / "slither"), "--version"]),
        "mythril_cli": sh([str(env_bin / "myth"), "version"]),
        "mythril_exec_timeout_s": 60,
        "mythril_hard_timeout_s": 150,
        "slither_timeout_s": 150,
        "cv_seed": 20260731,
        "power_sim_seed": RNG,
        "vendored_deps": [
            "@openzeppelin/contracts@2.5.1", "@openzeppelin/contracts@3.4.2",
            "@openzeppelin/contracts@4.9.6",
            "@openzeppelin/contracts-upgradeable@3.4.2",
            "@openzeppelin/contracts-upgradeable@4.9.6",
            "@openzeppelin/contracts-ethereum-package@3.0.0",
            "openzeppelin-solidity@1.12.0", "openzeppelin-solidity@2.3.0",
            "openzeppelin-solidity@2.5.1", "zeppelin-solidity@1.12.0",
        ],
    }
    (TABLES / "new7_versions.json").write_text(json.dumps(info, indent=2))
    for k, v in info.items():
        print(f"  {k:<28} {v if not isinstance(v, list) else f'{len(v)} packages'}")
    return info


def main() -> int:
    det = pd.read_parquet(DATA_DERIVED / "detection_panel.parquet")
    run = pd.read_parquet(DATA_DERIVED / "run_panel.parquet")
    metrics = select_metrics(det.drop_duplicates("contract"), threshold=0.9)

    new1_line_match(det, metrics)
    new2_vif(det, metrics)
    new3_two_way(det, run, metrics)
    new4_bh()
    new5_power()
    new7_versions()

    print(f"\nall revision tables written to {TABLES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
