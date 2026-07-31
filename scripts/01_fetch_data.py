#!/usr/bin/env python
"""Fetch the external corpora this study builds on.

Nothing under data/ is committed: the corpora are large and belong to their
original authors. This script reconstructs them so the pipeline is reproducible
from a clean checkout.

  Salzano et al. (EMSE 2026)  -- detection outcomes for 19 tools + line-level
                                 manual ground truth. Required.
  DAppSCAN (TSE 2024)         -- real DApp projects, for external validity.
                                 Optional; large.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import (  # noqa: E402
    DAPPSCAN_DIR,
    DAPPSCAN_REPO,
    SALZANO_DIR,
    SALZANO_REPO,
)


def clone(repo: str, dest: Path, sparse: list[str] | None = None) -> bool:
    if dest.exists():
        print(f"  already present: {dest}")
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1"]
    if sparse:
        cmd += ["--filter=blob:none", "--sparse"]
    cmd += [repo, str(dest)]

    print(f"  cloning {repo} -> {dest}")
    if subprocess.run(cmd).returncode != 0:
        print(f"  FAILED to clone {repo}", file=sys.stderr)
        return False

    if sparse:
        # A blobless clone still downloads every blob on a full checkout, which
        # defeats the point; restrict the working tree to the paths needed.
        subprocess.run(["git", "-C", str(dest), "sparse-checkout", "set", *sparse], check=True)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-dappscan", action="store_true",
                    help="also fetch DAppSCAN (large; only needed for the external-validity step)")
    args = ap.parse_args()

    print("Salzano et al. replication package (required):")
    if not clone(SALZANO_REPO, SALZANO_DIR):
        return 1

    required = [
        SALZANO_DIR / "vulnerabilities_log.csv",
        SALZANO_DIR / "csvs" / "sample_of_interest.csv",
        SALZANO_DIR / "csvs" / "sample_of_interest_with_code.csv",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        print("  ERROR: expected files missing after clone:", file=sys.stderr)
        for p in missing:
            print(f"    {p}", file=sys.stderr)
        return 1
    print("  all required files present")

    if args.with_dappscan:
        print("\nDAppSCAN (optional):")
        clone(
            DAPPSCAN_REPO,
            DAPPSCAN_DIR,
            sparse=["DAppSCAN-source/SWCsource", "DAppSCAN-source/contracts"],
        )

    print("\nnext: ./run.sh scripts/02_extract_metrics.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
