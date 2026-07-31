#!/usr/bin/env python
"""Vendor the npm packages DAppSCAN contracts import but does not ship.

Without these, ~57% of DAppSCAN contracts fail to compile and are lost to the
analysis. That loss is not random -- it correlates with project structure -- so
recovering them materially changes what the replication can conclude.

There is no npm client in this environment, so tarballs are fetched straight
from the registry and unpacked. Only the OpenZeppelin family is vendored: it
accounts for roughly 991 of the external imports, an order of magnitude more
than everything else combined.

Version selection is by Solidity era, because the projects almost never ship a
package.json. OpenZeppelin's major versions track compiler generations closely
enough for this to work:

    ^0.4.x -> openzeppelin-solidity 1.12 / 2.0    (pre-namespace naming)
    ^0.5.x -> @openzeppelin/contracts 2.5
    ^0.6.x -> @openzeppelin/contracts 3.4
    ^0.7.x -> @openzeppelin/contracts 3.4 (solc-0.7 build)
    ^0.8.x -> @openzeppelin/contracts 4.9

A wrong pick shows up as a compile error and is recorded, not silently treated
as a detector miss.
"""
from __future__ import annotations

import io
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sccomplex.config import DATA_RAW  # noqa: E402

VENDOR = DATA_RAW / "vendor"
REGISTRY = "https://registry.npmjs.org"

# (npm package, version) -> local directory name
PACKAGES = [
    ("@openzeppelin/contracts", "2.5.1"),
    ("@openzeppelin/contracts", "3.4.2"),
    ("@openzeppelin/contracts", "4.9.6"),
    ("@openzeppelin/contracts-upgradeable", "3.4.2"),
    ("@openzeppelin/contracts-upgradeable", "4.9.6"),
    ("@openzeppelin/contracts-ethereum-package", "3.0.0"),
    ("openzeppelin-solidity", "1.12.0"),
    ("openzeppelin-solidity", "2.3.0"),
    ("openzeppelin-solidity", "2.5.1"),
    ("zeppelin-solidity", "1.12.0"),
]


def tarball_url(pkg: str, version: str) -> str:
    name = pkg.rsplit("/", 1)[-1]
    return f"{REGISTRY}/{pkg}/-/{name}-{version}.tgz"


def local_dir(pkg: str, version: str) -> Path:
    return VENDOR / f"{pkg.replace('/', '__')}@{version}"


def fetch(pkg: str, version: str) -> bool:
    dest = local_dir(pkg, version)
    if (dest / "contracts").exists() or (dest / "package.json").exists():
        print(f"  cached  {pkg}@{version}")
        return True

    url = tarball_url(pkg, version)
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            blob = r.read()
    except Exception as e:
        print(f"  FAILED  {pkg}@{version}: {type(e).__name__}: {e}", file=sys.stderr)
        return False

    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for member in tf.getmembers():
            # npm tarballs nest everything under "package/"; strip that, and
            # refuse absolute or traversing paths.
            parts = Path(member.name).parts
            if not parts or parts[0] != "package":
                continue
            rel = Path(*parts[1:])
            if rel.is_absolute() or ".." in rel.parts:
                continue
            target = dest / rel
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(member)
                if src is not None:
                    target.write_bytes(src.read())

    n = len(list(dest.rglob("*.sol")))
    print(f"  ok      {pkg}@{version}  ({n} .sol files)")
    return True


def main() -> int:
    VENDOR.mkdir(parents=True, exist_ok=True)
    print(f"vendoring into {VENDOR}\n")

    ok = sum(fetch(pkg, ver) for pkg, ver in PACKAGES)
    print(f"\n{ok}/{len(PACKAGES)} packages available")

    total = len(list(VENDOR.rglob("*.sol")))
    print(f"total vendored .sol files: {total}")
    if ok == 0:
        return 1
    print("\nnext: ./run.sh scripts/08_dappscan_detect.py --remap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
