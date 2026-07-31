#!/usr/bin/env python
"""External validation of the metric extractor.

The extractor is a tree-sitter reimplementation of Solmet, so its output needs
checking against an independent implementation. Salzano et al. computed summed
cyclomatic complexity per file with Slither (a compiler-based tool, entirely
different machinery). Agreement between that and our file-level WMC is
evidence the extractor measures what it claims.

Perfect agreement is not expected: their figure comes from Slither's CFG
(edges - nodes + 2 per function, summed over contracts that compiled) whereas
ours is an AST decision-point count over every contract in the file. Strong
rank correlation is the meaningful bar.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from scipy.stats import pearsonr, spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_DERIVED, SALZANO_DIR, TABLES  # noqa: E402


def main() -> int:
    ours = pd.read_parquet(DATA_DERIVED / "metrics.parquet")
    ours["contract"] = ours["file"].map(lambda p: Path(p).stem)
    per_file = ours.groupby("contract")["WMC"].sum().rename("wmc_ours")

    frames = []
    for name in ("sbc_complexity.csv", "sbr_complexity.csv"):
        p = SALZANO_DIR / "contracts" / name
        if p.exists():
            frames.append(pd.read_csv(p))
    if not frames:
        print("ERROR: Salzano complexity CSVs not found", file=sys.stderr)
        return 1

    theirs = pd.concat(frames, ignore_index=True)
    theirs["contract"] = theirs["file"].map(lambda f: Path(str(f)).stem)
    theirs = (
        theirs.groupby("contract")["cyclomatic_complexity"].sum().rename("cc_slither")
    )

    joined = pd.concat([per_file, theirs], axis=1, join="inner").dropna()
    if joined.empty:
        print("ERROR: no overlapping contracts to validate on", file=sys.stderr)
        return 1

    rho, p_rho = spearmanr(joined["wmc_ours"], joined["cc_slither"])
    r, p_r = pearsonr(joined["wmc_ours"], joined["cc_slither"])

    print(f"contracts compared : {len(joined)}")
    print(f"Spearman rho       : {rho:.3f}  (p={p_rho:.2e})")
    print(f"Pearson r          : {r:.3f}  (p={p_r:.2e})")
    print("\nour WMC (file sum) vs Slither cyclomatic complexity:")
    print(joined.describe().T[["mean", "std", "min", "50%", "max"]].round(2).to_string())

    out = TABLES / "metric_validation.csv"
    joined.to_csv(out)
    print(f"\nwrote {out}")

    if rho < 0.7:
        print(
            f"\nWARNING: rank correlation {rho:.3f} is weaker than expected; "
            "inspect the extractor before relying on these metrics.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
