"""Takes over settings and own symbols of SLDGridy, the program's name until 1.3.2."""

import contextlib
import shutil
from pathlib import Path

from PyQt6.QtCore import QSettings

from electrogridy.fileio.paths import user_data_dir

NAME = "electrogridy"
OLD_NAME = "sldgridy"
# Old file names in the copied data directory, so that "eigene.sldglib" becomes the
# "eigene.grdylib" new symbols are saved to.
RENAMED = {".sldglib": ".grdylib", ".sldgframe": ".grdyframe"}


def migrate_settings(new: QSettings, old: QSettings) -> bool:
    """Copy all old settings unless there are new ones already."""
    if new.allKeys() or not old.allKeys():
        return False
    for key in old.allKeys():
        new.setValue(key, old.value(key))
    new.sync()
    return True


def migrate_data(new_dir: Path, old_dir: Path) -> bool:
    """Copy the old data directory (own libraries, templates) unless the new one exists.
    The old one stays for the old version."""
    if new_dir.exists() or not old_dir.is_dir():
        return False
    shutil.copytree(old_dir, new_dir)
    for path in [p for p in new_dir.rglob("*") if p.suffix in RENAMED and p.is_file()]:
        target = path.with_suffix(RENAMED[path.suffix])
        if not target.exists():
            path.rename(target)
    return True


def take_over() -> None:
    """Before the first start under the new name; does nothing afterwards."""
    data = user_data_dir()
    with contextlib.suppress(OSError):
        migrate_data(data, data.with_name(OLD_NAME))
    migrate_settings(QSettings(NAME, NAME), QSettings(OLD_NAME, OLD_NAME))
