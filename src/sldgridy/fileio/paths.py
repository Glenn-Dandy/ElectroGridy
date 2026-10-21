"""Locations of shipped and user data."""

import os
from pathlib import Path

_MODULE_DIR = Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "sldgridy"


def user_library_dir() -> Path:
    return user_data_dir() / "library"


def user_template_dir() -> Path:
    return user_data_dir() / "templates"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
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


def symbols_dir() -> Path:
    """Symbols the program places itself (terminals); always inside the module."""
    return _MODULE_DIR / "resources" / "symbols"
