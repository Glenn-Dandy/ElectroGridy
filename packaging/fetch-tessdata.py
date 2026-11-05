#!/usr/bin/env python3
"""Fetch the exact text recognition models (tessdata_best, Apache-2.0) into
src/electrogridy/resources/tessdata, checked against known hashes.

The picture import reads texts with them when "exact" is chosen; without them it
uses the models of the installed tesseract. Run before building a package (the
release workflow does); the files are not kept in git (about 24 MB).
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

TAG = "4.1.0"
BASE = f"https://github.com/tesseract-ocr/tessdata_best/raw/{TAG}"
FILES = {
    "deu.traineddata": "8407331d6aa0229dc927685c01a7938fc5a641d1a9524f74838cdac599f0d06e",
    "eng.traineddata": "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba",
}
LICENSE = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/{TAG}/LICENSE"
TARGET = Path(__file__).resolve().parent.parent / "src" / "electrogridy" / "resources" / "tessdata"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, path: Path) -> None:
    part = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as response, part.open("wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    part.replace(path)


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        path = TARGET / name
        if path.exists() and sha256(path) == expected:
            print(f"{name}: present")
            continue
        print(f"{name}: fetching {BASE}/{name}")
        fetch(f"{BASE}/{name}", path)
        got = sha256(path)
        if got != expected:
            path.unlink()
            print(f"{name}: wrong checksum {got}", file=sys.stderr)
            return 1
    license_path = TARGET / "LICENSE-tessdata_best.txt"
    if not license_path.exists():
        fetch(LICENSE, license_path)
    print(f"models in {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
