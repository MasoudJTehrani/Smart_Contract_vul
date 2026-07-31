#!/usr/bin/env python
"""Extract the 21 Solmet metrics for every contract in the Salzano corpus.

Writes data/derived/metrics.parquet (one row per contract declaration).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, DATA_RAW  # noqa: E402
from sccomplex.data import salzano  # noqa: E402
from sccomplex.metrics.solmet import extract_corpus  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DATA_DERIVED / "metrics.parquet"))
    ap.add_argument(
        "--sources",
        default=str(DATA_RAW / "sources"),
        help="where to materialise .sol files from the replication package",
    )
    args = ap.parse_args()

    src_dir = Path(args.sources)
    existing = sorted(src_dir.glob("*.sol")) if src_dir.exists() else []
    if existing:
        print(f"reusing {len(existing)} materialised contracts in {src_dir}")
        paths = existing
    else:
        print(f"materialising contract sources into {src_dir} ...")
        paths = salzano.materialise_sources(src_dir)
        print(f"wrote {len(paths)} .sol files")

    df = extract_corpus(paths)
    if df.empty:
        print("ERROR: no contracts parsed", file=sys.stderr)
        return 1

    out = Path(args.out)
    df.to_parquet(out, index=False)

    print(f"\nparsed {len(df)} contract declarations "
          f"across {df['file'].nunique()} files -> {out}")
    print(f"declarations per file: mean {len(df) / df['file'].nunique():.2f}")
    print("\nmetric summary:")
    from sccomplex.config import SOLMET_METRICS
    print(df[SOLMET_METRICS].describe().T[["mean", "std", "min", "50%", "max"]]
          .round(2).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
