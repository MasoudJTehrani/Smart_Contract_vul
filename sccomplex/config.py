"""Paths and shared constants."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_DERIVED = ROOT / "data" / "derived"
RESULTS = ROOT / "results"
FIGURES = RESULTS / "figures"
TABLES = RESULTS / "tables"

for _d in (DATA_RAW, DATA_DERIVED, RESULTS, FIGURES, TABLES):
    _d.mkdir(parents=True, exist_ok=True)

# Replication package of Salzano et al. (EMSE 2026). Supplies the detection
# outcomes (19 tools) and the DASP-10 tool-check mapping.
SALZANO_REPO = "https://github.com/fsalzano/Empirical-Analysis-of-Vulnerability-Detection-Tools-for-Solidity-Smart-Contracts.git"
SALZANO_DIR = DATA_RAW / "salzano"

# DAppSCAN (TSE 2024). External-validity corpus: real DApp projects.
DAPPSCAN_REPO = "https://github.com/InPlusLab/DAppSCAN.git"
DAPPSCAN_DIR = DATA_RAW / "dappscan"

# FORGE (ICSE 2026). Third corpus: 6,571 projects, labels extracted from real
# audit reports by an LLM pipeline. Used to break the reentrancy tie between
# the first two corpora.
FORGE_REPO = "https://github.com/shenyimings/FORGE-Artifacts.git"
FORGE_DIR = DATA_RAW / "forge"

# The 21 metrics of Solmet (Hegedus 2019), as used in Paper 1.
# NOTE: the metric named "NA" (number of attributes) is read back from CSV as a
# missing value unless readers pass keep_default_na=False. Any script that
# reloads a results table must do so.
SOLMET_METRICS = [
    "SLOC", "LLOC", "CLOC", "NF", "WMC", "NL", "NLE", "NUMPAR", "NOS",
    "DIT", "NOA", "NOD", "CBO", "NA", "NOI",
    "AvgMcCC", "AvgNL", "AvgNLE", "AvgNUMPAR", "AvgNOS", "AvgNOI",
]

# DASP-10 categories, the label space used by Salzano's mapping.
DASP_CATEGORIES = [
    "access_control", "arithmetic", "denial_service", "reentrancy",
    "unchecked_low_calls", "bad_randomness", "front_running",
    "time_manipulation", "short_addresses", "other",
]

# Detector class assignment. Salzano covers static + LLM; the learned class is
# ours to add.
DETECTOR_CLASS = {
    "slither": "static", "mythril": "symbolic", "securify": "static",
    "conkas": "symbolic", "smartcheck": "static", "maian": "symbolic",
    "sfuzz": "fuzzing", "confuzzius": "fuzzing", "teether": "symbolic",
    "madmax": "static", "ethainter": "static", "vandal": "static",
    "ethor-2023": "symbolic", "pakala": "symbolic", "manticore": "symbolic",
    "oyente": "symbolic", "solhint": "linter", "semgrep": "linter",
    "osiris": "symbolic",
    "gpt-4o": "llm", "neural": "learned",
}
