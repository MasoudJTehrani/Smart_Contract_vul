#!/usr/bin/env python
"""Run Slither across the labelled DAppSCAN contracts.

Writes data/derived/dappscan_slither.parquet: one row per contract with the
run status and the DASP categories reported.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, DATA_RAW  # noqa: E402
from sccomplex.data import dappscan  # noqa: E402
from sccomplex.detect.slither_runner import (  # noqa: E402
    build_remaps,
    installed_solc,
    load_dasp_mapping,
    run_one,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--out", default=str(DATA_DERIVED / "dappscan_slither.parquet"))
    ap.add_argument("--remap", action="store_true",
                    help="use vendored npm deps (run scripts/10_vendor_deps.py first)")
    args = ap.parse_args()

    env_bin = Path(sys.executable).parent
    slither = shutil.which("slither", path=str(env_bin)) or shutil.which("slither")
    solc_select = shutil.which("solc-select", path=str(env_bin)) or shutil.which("solc-select")
    if not slither or not solc_select:
        print("ERROR: slither / solc-select not found. Install with:\n"
              "  PYTHONNOUSERSITE=1 <env>/bin/python -m pip install slither-analyzer solc-select",
              file=sys.stderr)
        return 1

    versions = installed_solc(solc_select)
    mapping = load_dasp_mapping("slither")
    print(f"slither      : {slither}")
    print(f"solc versions: {versions}")
    print(f"checks mapped: {len(mapping)}")

    paths = dappscan.contract_paths()
    items = sorted(paths.items())
    if args.limit:
        items = items[: args.limit]
    print(f"contracts    : {len(items)}\n")

    vendor = DATA_RAW / "vendor"
    if args.remap:
        if not vendor.exists():
            print("ERROR: --remap needs data/raw/vendor; run scripts/10_vendor_deps.py",
                  file=sys.stderr)
            return 1
        print(f"remapping against vendored deps in {vendor}")

    rows = []
    for cid, sol in tqdm(items, desc="slither"):
        remaps = build_remaps(sol, vendor) if args.remap else None
        r = run_one(sol, cid, mapping, versions, slither, solc_select,
                    args.timeout, remaps=remaps)
        rows.append(
            {
                "contract": r.contract,
                "status": r.status,
                "solc": r.solc,
                "error": r.error[:200],
                "categories": sorted(r.categories),
                "lines_by_category": {k: sorted(v) for k, v in r.lines_by_category.items()},
            }
        )

    df = pd.DataFrame(rows)
    df["lines_by_category"] = df["lines_by_category"].map(str)
    df.to_parquet(args.out, index=False)

    print("\nrun status:")
    print(df["status"].value_counts().to_string())
    print(f"\n  ok                : analysed successfully")
    print(f"  error             : genuine crash / timeout / compiler error")
    print(f"  unresolved_import : dependency never vendored -- harness artefact,")
    print(f"                      excluded from analysis-failure models")
    ok = df["status"].eq("ok")
    print("\nfailure reasons (top):")
    print(df.loc[~ok, "error"].str.slice(0, 55).value_counts().head(8).to_string())
    print("\ncategories reported (contracts):")
    print(df[ok].explode("categories")["categories"].value_counts().to_string())
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
