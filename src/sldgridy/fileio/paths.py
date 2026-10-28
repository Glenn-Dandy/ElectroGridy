"""Locations of shipped and user data."""

import os
import re
import sys
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent.parent
_WINDOWS = sys.platform == "win32"


def user_data_dir() -> Path:
    base = (
        os.environ.get("XDG_DATA_HOME")
        or (os.environ.get("APPDATA") if _WINDOWS else None)
        or str(Path.home() / ".local" / "share")
    )
    return Path(base) / "sldgridy"


def user_library_dir() -> Path:
    return user_data_dir() / "library"


def user_template_dir() -> Path:
    return user_data_dir() / "templates"


def cache_dir() -> Path:
    base = (
        os.environ.get("XDG_CACHE_HOME")
        or (os.environ.get("LOCALAPPDATA") if _WINDOWS else None)
        or str(Path.home() / ".cache")
    )
    return Path(base) / "sldgridy"


def _shipped(name: str) -> Path:
    # Installed package: /usr/share/sldgridy/<name> next to the module directory.
    # Source tree: src/sldgridy/resources/<name>.
    installed = _MODULE_DIR.parent / name
    if installed.is_dir() and (_MODULE_DIR.parent / "sldgridy").samefile(_MODULE_DIR):
        return installed
    return _MODULE_DIR / "resources" / name


def system_library_dir() -> Path:
    return _shipped("library")


def system_template_dir() -> Path:
    return _shipped("templates")


def fonts_dir() -> Path:
    """Fonts shipped where the system may lack them (Windows: DejaVu Sans)."""
    return _MODULE_DIR / "resources" / "fonts"


def symbols_dir() -> Path:
    """Symbols the program places itself (terminals); always inside the module."""
    return _MODULE_DIR / "resources" / "symbols"


def safe_file_name(name: str) -> str:
    """``name`` as part of a file name: letters, digits, - and _ only."""
    return re.sub(r"[^\w\-]+", "_", name.strip()).strip("_")
