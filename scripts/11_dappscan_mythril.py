#!/usr/bin/env python
"""Run Mythril across the labelled DAppSCAN contracts, in parallel.

Purpose: test C2 -- complexity predicts *analysis* failure -- which the
Slither-only replication could not, because C2 was a symbolic-execution effect
and Slither is a static analyser.

Parallelism is process-level with a per-contract compiler pinned onto each
subprocess's PATH. `solc-select use` is deliberately never called here: it
writes a single global version file, so concurrent workers would silently
compile each other's contracts with the wrong compiler.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, DATA_RAW  # noqa: E402
from sccomplex.data import dappscan  # noqa: E402
from sccomplex.detect.mythril_runner import (  # noqa: E402
    run_one,
    solc_artifacts_dir,
)
from sccomplex.detect.slither_runner import (  # noqa: E402
    build_remaps,
    installed_solc,
    load_dasp_mapping,
)


def _task(args):
    (cid, sol, mapping, versions, myth, solc_select, exec_to, hard_to,
     remaps, artifacts) = args
    r = run_one(Path(sol), cid, mapping, versions, myth, solc_select,
                exec_to, hard_to, remaps, artifacts)
    return {
        "contract": r.contract,
        "status": r.status,
        "solc": r.solc,
        "error": r.error[:200],
        "seconds": round(r.seconds, 2),
        "categories": sorted(r.categories),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--exec-timeout", type=int, default=60,
                    help="Mythril's own symbolic-execution budget, held constant")
    ap.add_argument("--hard-timeout", type=int, default=150)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--remap", action="store_true")
    ap.add_argument("--out", default=str(DATA_DERIVED / "dappscan_mythril.parquet"))
    args = ap.parse_args()

    env_bin = Path(sys.executable).parent
    myth = shutil.which("myth", path=str(env_bin)) or shutil.which("myth")
    solc_select = shutil.which("solc-select", path=str(env_bin)) or shutil.which("solc-select")
    if not myth:
        print("ERROR: myth not found. pip install mythril", file=sys.stderr)
        return 1

    versions = installed_solc(solc_select)
    artifacts = solc_artifacts_dir(solc_select)
    mapping = load_dasp_mapping("mythril")
    vendor = DATA_RAW / "vendor"

    print(f"myth          : {myth}")
    print(f"solc versions : {len(versions)}")
    print(f"solc artifacts: {artifacts}")
    print(f"checks mapped : {len(mapping)}")

    paths = sorted(dappscan.contract_paths().items())
    if args.limit:
        paths = paths[: args.limit]
    print(f"contracts     : {len(paths)} | workers {args.workers} "
          f"| exec-timeout {args.exec_timeout}s\n")

    tasks = [
        (cid, str(sol), mapping, versions, myth, solc_select,
         args.exec_timeout, args.hard_timeout,
         build_remaps(sol, vendor) if args.remap else None, artifacts)
        for cid, sol in paths
    ]

    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_task, t) for t in tasks]
        for f in tqdm(as_completed(futures), total=len(futures), desc="mythril"):
            try:
                rows.append(f.result())
            except Exception as e:  # a worker dying must not lose the run
                rows.append({"contract": "?", "status": "error", "solc": "",
                             "error": f"worker:{type(e).__name__}", "seconds": 0.0,
                             "categories": []})

    df = pd.DataFrame(rows)
    df.to_parquet(args.out, index=False)

    print("\nrun status:")
    print(df["status"].value_counts().to_string())
    print(f"\nmedian runtime: {df['seconds'].median():.1f}s "
          f"| total {df['seconds'].sum() / 3600:.2f}h of analysis")
    print("\nfailure reasons (top):")
    print(df[df["status"] != "ok"]["error"].str.slice(0, 55)
          .value_counts().head(8).to_string())
    print("\ncategories reported:")
    print(df.explode("categories")["categories"].value_counts().to_string())
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
