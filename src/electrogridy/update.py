"""Checks GitHub for a newer release. Pure Python apart from the network call."""

import json
import re
import sys
import urllib.request
from dataclasses import dataclass

from electrogridy.project import API_LATEST, LATEST_RELEASE_URL

TIMEOUT = 10  # seconds
# The release asset offered for download: the installer on Windows, else the .deb.
PACKAGE_SUFFIX = "-setup.exe" if sys.platform == "win32" else "_all.deb"


@dataclass(frozen=True)
class UpdateResult:
    ok: bool
    available: bool = False
    version: str = ""
    release_url: str = LATEST_RELEASE_URL
    download_url: str | None = None


def parse_version(text: str) -> tuple[int, ...]:
    """Comparable version: (major, minor, patch, 1) for releases, (..., 0, n) for dev n.

    A development build "1.2.3.dev4" (or "v1.2.3-dev4") sorts before release 1.2.3.
    """
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?(?:[.\-~]?dev(\d+))?", text)
    if not m:
        return ()
    major, minor, patch, dev = m.groups()
    base = (int(major), int(minor), int(patch or 0))
    return (*base, 0, int(dev)) if dev is not None else (*base, 1)


def evaluate(current: str, release: dict, suffix: str = PACKAGE_SUFFIX) -> UpdateResult:
    """Compare the running version with a GitHub release JSON object."""
    tag = str(release.get("tag_name", ""))
    latest = parse_version(tag)
    if not latest:
        return UpdateResult(ok=False)
    download = None
    for asset in release.get("assets", []):
        name = str(asset.get("name", ""))
        if name.endswith(suffix):
            download = asset.get("browser_download_url")
            break
    return UpdateResult(
        ok=True,
        available=latest > parse_version(current),
        version=tag.lstrip("v"),
        release_url=str(release.get("html_url") or LATEST_RELEASE_URL),
        download_url=download,
    )


def check(current: str) -> UpdateResult:
    request = urllib.request.Request(
        API_LATEST,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"ElectroGridy/{current}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            release = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return UpdateResult(ok=False)
    if not isinstance(release, dict):
        return UpdateResult(ok=False)
    return evaluate(current, release)
