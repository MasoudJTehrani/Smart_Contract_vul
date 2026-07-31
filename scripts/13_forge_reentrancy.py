#!/usr/bin/env python
"""Break the reentrancy tie with a third corpus.

The main corpus finds reentrancy detection *degrading* with complexity
(+0.278, p=0.0001); DAppSCAN finds it *improving* (-0.834, p=0.041) on only 9
misses. FORGE supplies 350 audited projects with a reentrancy finding.

Scoring is per project and deliberately generous to the tool: a project counts
as detected if Slither reports reentrancy in **any** of its files. FORGE
findings carry free-text locations rather than line numbers, so a stricter
criterion is not available -- and a generous criterion biases against finding
the "complexity hurts detection" effect, which is the conservative direction
for the claim being tested.

Complexity is aggregated to the project: sums for size and count metrics, max
for inheritance and coupling, size-weighted means for the Avg. family.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, DATA_RAW, SOLMET_METRICS, TABLES  # noqa: E402
from sccomplex.data import forge  # noqa: E402
from sccomplex.detect.slither_runner import (  # noqa: E402
    STATUS_OK,
    STATUS_UNRESOLVED,
    build_remaps,
    installed_solc,
    load_dasp_mapping,
    run_one,
)
from sccomplex.metrics.solmet import extract_corpus  # noqa: E402
from sccomplex.model import per_group_slopes, select_metrics, standardise  # noqa: E402

pd.set_option("display.width", 200)
MAX_FILES = 20  # cap per project; a few projects ship hundreds of vendored files


def _scan(args):
    proj, files, mapping, versions, slither, solc_select, timeout, vendor = args
    found, statuses = False, []
    for f in files:
        r = run_one(Path(f), proj, mapping, versions, slither, solc_select,
                    timeout, remaps=build_remaps(Path(f), Path(vendor)))
        statuses.append(r.status)
        if r.status == STATUS_OK and "reentrancy" in r.categories:
            found = True
            break
    ok = sum(s == STATUS_OK for s in statuses)
    return {
        "project_path": proj,
        "files_scanned": len(statuses),
        "files_ok": ok,
        "any_ok": ok > 0,
        "unresolved": sum(s == STATUS_UNRESOLVED for s in statuses),
        "detected": found,
    }


def project_metrics(paths: list[str]) -> pd.DataFrame:
    cache = DATA_DERIVED / "forge_metrics.parquet"
    if cache.exists():
        return pd.read_parquet(cache)

    rows = []
    for p in tqdm(paths, desc="metrics"):
        files = forge.project_files(p, limit=MAX_FILES)
        if not files:
            continue
        df = extract_corpus(files, progress=False)
        if df.empty:
            continue
        sums = ["SLOC", "LLOC", "CLOC", "NF", "WMC", "NL", "NLE", "NUMPAR", "NOS", "NA", "NOI"]
        maxs = ["DIT", "NOA", "NOD", "CBO"]
        avgs = [m for m in SOLMET_METRICS if m.startswith("Avg")]
        rec = {"project_path": p, "n_files": len(files), "n_declarations": len(df)}
        rec |= {c: float(df[c].sum()) for c in sums}
        rec |= {c: float(df[c].max()) for c in maxs}
        w = df["NF"].sum()
        rec |= {c: float((df[c] * df["NF"]).sum() / w) if w else 0.0 for c in avgs}
        rows.append(rec)

    out = pd.DataFrame(rows)
    out.to_parquet(cache, index=False)
    return out


def main() -> int:
    global MAX_FILES
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-files", type=int, default=20)
    args = ap.parse_args()

    env_bin = Path(sys.executable).parent
    slither = shutil.which("slither", path=str(env_bin)) or shutil.which("slither")
    solc_select = shutil.which("solc-select", path=str(env_bin)) or shutil.which("solc-select")
    versions = installed_solc(solc_select)
    mapping = load_dasp_mapping("slither")
    vendor = str(DATA_RAW / "vendor")

    MAX_FILES = args.max_files

    gt = forge.available_projects(["reentrancy"])
    projects = sorted(gt["project_path"].unique())
    if args.limit:
        projects = projects[: args.limit]
    print(f"FORGE reentrancy projects: {len(projects)}")

    det_path = DATA_DERIVED / "forge_slither.parquet"
    if det_path.exists():
        det = pd.read_parquet(det_path)
        print(f"reusing detections for {len(det)} projects")
    else:
        tasks = [
            (p, [str(f) for f in forge.project_files(p, limit=MAX_FILES)],
             mapping, versions, slither, solc_select, args.timeout, vendor)
            for p in projects
        ]
        tasks = [t for t in tasks if t[1]]
        rows = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(_scan, t) for t in tasks]
            for f in tqdm(as_completed(futs), total=len(futs), desc="slither"):
                try:
                    rows.append(f.result())
                except Exception as e:
                    rows.append({"project_path": "?", "files_scanned": 0, "files_ok": 0,
                                 "any_ok": False, "unresolved": 0, "detected": False})
        det = pd.DataFrame(rows)
        det.to_parquet(det_path, index=False)

    print("\nprojects with at least one analysable file: "
          f"{int(det['any_ok'].sum())} / {len(det)}")

    metrics = project_metrics(projects)
    panel = det[det["any_ok"]].merge(metrics, on="project_path", how="inner")
    panel["missed"] = (~panel["detected"]).astype(int)

    print("\n" + "=" * 78)
    print("FORGE: reentrancy detection vs complexity")
    print("=" * 78)
    print(f"projects analysed : {len(panel)}")
    print(f"miss rate         : {panel['missed'].mean():.1%} "
          f"({int(panel['missed'].sum())} misses)")
    print(f"median SLOC       : {panel['SLOC'].median():.0f}")

    if panel["missed"].nunique() < 2 or len(panel) < 30:
        print("insufficient variation to model", file=sys.stderr)
        return 1

    sel = select_metrics(panel, threshold=0.9)
    for must in ("LLOC", "SLOC"):
        if must not in sel:
            sel.append(must)
    p = standardise(panel, sel).assign(_all="all", contract=panel["project_path"],
                                       category="reentrancy")

    rows = []
    for m in sel:
        s = per_group_slopes(p, "missed", m, "_all", min_n=30, min_events=10)
        rows.append({"metric": m, "n": s["n"].iloc[0], "events": s["events"].iloc[0],
                     "coef": s["coef"].iloc[0], "p": s["p"].iloc[0]})
    tbl = pd.DataFrame(rows).sort_values("coef", ascending=False)
    tbl.to_csv(TABLES / "forge_reentrancy_slopes.csv", index=False)
    print("\ncomplexity slopes on reentrancy detection failure:")
    print(tbl.round(4).to_string(index=False))

    print("\n" + "=" * 78)
    print("THREE-CORPUS VERDICT  reentrancy detection failure vs size")
    print("=" * 78)
    salz = pd.read_csv(TABLES / "robust_c_by_category.csv").set_index("category")
    dapp = pd.read_csv(TABLES / "dappscan_c1_comparison.csv").set_index("category")
    forge_lloc = tbl.set_index("metric").loc["LLOC"] if "LLOC" in tbl["metric"].values else None

    verdict = pd.DataFrame([
        {"corpus": "Salzano (main)", "n": salz.loc["reentrancy", "n"],
         "coef": salz.loc["reentrancy", "coef"], "p": salz.loc["reentrancy", "p"]},
        {"corpus": "DAppSCAN", "n": dapp.loc["reentrancy", "n_dapp"],
         "coef": dapp.loc["reentrancy", "coef_dapp"], "p": dapp.loc["reentrancy", "p_dapp"]},
        {"corpus": "FORGE", "n": forge_lloc["n"] if forge_lloc is not None else np.nan,
         "coef": forge_lloc["coef"] if forge_lloc is not None else np.nan,
         "p": forge_lloc["p"] if forge_lloc is not None else np.nan},
    ])
    print(verdict.round(4).to_string(index=False))
    verdict.to_csv(TABLES / "reentrancy_three_corpus.csv", index=False)

    signs = [np.sign(v) for v in verdict["coef"] if v == v]
    print(f"\nsign agreement: {len(set(signs))} distinct sign(s) across "
          f"{len(signs)} corpora")
    if len(set(signs)) == 1:
        print("-> the effect is consistent across corpora")
    else:
        print("-> the effect is NOT consistent; FORGE sides with "
              f"{'Salzano' if signs[-1] == signs[0] else 'DAppSCAN'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
