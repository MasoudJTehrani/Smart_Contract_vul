"""Run Mythril over a corpus and normalise its output to DASP-10.

Mythril is a *symbolic executor*, which is the point. The main corpus's
strongest result -- complexity predicting analysis failure, NOI odds ratio
2.49 -- was driven almost entirely by symbolic tools (manticore +1.03,
ethor-2023 +1.36), while Slither's own slope was negative. The DAppSCAN
replication with Slither alone therefore could not test that claim at all.
This module exists to test it.

The outcome that matters here is not what Mythril finds but whether it
*finishes*. Symbolic execution degrades by state explosion: on heavily coupled
code the solver runs out of budget rather than returning a wrong answer. So a
timeout is a first-class result, recorded as an analysis failure, and the
`--execution-timeout` given to Mythril is held constant across contracts so
that the comparison between them is fair.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from sccomplex.detect.slither_runner import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_UNRESOLVED,
    classify_error,
    pick_solc,
)

STATUS_TIMEOUT = "timeout"


def solc_artifacts_dir(solc_select_bin: str) -> Path | None:
    """Locate solc-select's artifacts directory.

    Needed because `solc-select use` writes a *global* version file. Parallel
    workers sharing it would race and silently compile contracts with each
    other's compiler, so each subprocess instead gets its own `solc` on PATH
    pointing straight at the versioned binary.
    """
    import os

    candidates = []
    if (env := os.environ.get("SOLC_SELECT_INSTALL_DIR")):
        candidates.append(Path(env) / "artifacts")
    candidates.append(Path.home() / ".solc-select" / "artifacts")
    for parent in Path(solc_select_bin).resolve().parents:
        candidates.append(parent / ".solc-select" / "artifacts")

    for c in candidates:
        if c.is_dir() and any(c.glob("solc-*")):
            return c
    return None


def pinned_solc_path(artifacts: Path | None, version: str) -> Path | None:
    if not artifacts or not version:
        return None
    p = artifacts / f"solc-{version}" / f"solc-{version}"
    return p if p.exists() else None


@dataclass
class MythrilResult:
    contract: str
    status: str
    categories: set[str] = field(default_factory=set)
    lines_by_category: dict[str, set[int]] = field(default_factory=dict)
    solc: str = ""
    error: str = ""
    seconds: float = 0.0


def run_one(
    sol: Path,
    contract_id: str,
    mapping: dict[str, str],
    solc_versions: list[str],
    myth_bin: str,
    solc_select_bin: str,
    exec_timeout: int = 60,
    hard_timeout: int = 120,
    remaps: list[str] | None = None,
    artifacts: Path | None = None,
) -> MythrilResult:
    import os
    import shutil
    import tempfile
    import time

    res = MythrilResult(contract=contract_id, status=STATUS_ERROR)

    version = pick_solc(sol, solc_versions) or ""
    res.solc = version

    # `--solv` makes Mythril try to *download* a compiler, which needs network
    # and fails; `--no-onchain-data` stops it reaching for a node. The right
    # solc is supplied by putting it first on this subprocess's PATH.
    cmd = [
        myth_bin, "analyze", str(sol),
        "-o", "json",
        "--execution-timeout", str(exec_timeout),
        "--no-onchain-data",
    ]

    env = dict(os.environ)
    tmpdir = None
    settings_file = None
    if remaps:
        # Remappings must go through solc's standard-json `settings`, not
        # --solc-args: Mythril mangles the latter and solc then returns
        # non-JSON, which surfaces as an opaque JSONDecodeError rather than a
        # compile error.
        fd, settings_file = tempfile.mkstemp(suffix=".json", prefix="solcset_")
        with os.fdopen(fd, "w") as fh:
            json.dump({"remappings": list(remaps)}, fh)
        cmd += ["--solc-json", settings_file]
    pinned = pinned_solc_path(artifacts, version)
    if pinned is not None:
        tmpdir = tempfile.mkdtemp(prefix="solcpin_")
        link = Path(tmpdir) / "solc"
        try:
            link.symlink_to(pinned)
            env["PATH"] = f"{tmpdir}:{env.get('PATH', '')}"
        except OSError:
            pass

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=hard_timeout,
            cwd=sol.parent, env=env,
        )
    except subprocess.TimeoutExpired:
        res.status, res.error = STATUS_TIMEOUT, f"hard timeout {hard_timeout}s"
        res.seconds = float(hard_timeout)
        return res
    except OSError as e:
        res.status, res.error = STATUS_ERROR, f"exec:{e}"
        return res
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
        if settings_file:
            Path(settings_file).unlink(missing_ok=True)
    res.seconds = time.monotonic() - start

    payload = None
    for chunk in (proc.stdout, proc.stderr):
        if not chunk:
            continue
        start_idx = chunk.find("{")
        if start_idx == -1:
            continue
        try:
            payload = json.loads(chunk[start_idx:])
            break
        except json.JSONDecodeError:
            continue

    if payload is None:
        diag = (proc.stderr or "") + (proc.stdout or "")
        status, err = classify_error(diag)
        res.status, res.error = status, err
        return res

    if not payload.get("success", True):
        err_text = str(payload.get("error") or "")
        if "not found" in err_text.lower() or "Source" in err_text:
            res.status, res.error = STATUS_UNRESOLVED, err_text[:200]
        else:
            res.status, res.error = STATUS_ERROR, err_text[:200] or "analysis failed"
        return res

    res.status = STATUS_OK
    for issue in payload.get("issues", []) or []:
        title = (issue.get("title") or "").strip()
        cat = mapping.get(title)
        if not cat:
            continue
        res.categories.add(cat)
        ln = issue.get("lineno")
        if isinstance(ln, int):
            res.lines_by_category.setdefault(cat, set()).add(ln)

    return res
