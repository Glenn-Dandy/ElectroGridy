"""Automatic backup of the open drawing to ~/.cache/electrogridy/ and recovery after a crash."""

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer

from electrogridy.fileio.files import save_document
from electrogridy.fileio.paths import cache_dir

INTERVAL_MS = 5 * 60 * 1000
PREFIX = "autosave-"


@dataclass
class Backup:
    path: Path
    meta: Path
    original: Path | None
    saved: str


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _alive_windows(pid: int) -> bool:
    # os.kill(pid, 0) would end the process on Windows; ask for its exit code instead.
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: it exists
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def orphaned_backups(directory: Path | None = None) -> list[Backup]:
    """Backups left behind by instances that are no longer running."""
    directory = directory or cache_dir()
    result = []
    for meta in sorted(directory.glob(f"{PREFIX}*.json")):
        try:
            pid = int(meta.stem[len(PREFIX) :])
        except ValueError:
            continue
        drawing = meta.with_suffix(".grdy")
        if pid == os.getpid() or _alive(pid) or not drawing.exists():
            continue
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
        original = info.get("original")
        result.append(
            Backup(drawing, meta, Path(original) if original else None, str(info.get("saved", "")))
        )
    return result


KEEP_OLD = 10  # discarded or recovered backups kept in the "alt" folder


def remove_backup(backup: Backup) -> None:
    """Take a backup out of the recovery list. The drawing is moved to ``alt/`` next to
    it (the newest KEEP_OLD stay), so a wrong click never loses work for good."""
    old = backup.path.parent / "alt"
    try:
        if backup.path.exists():
            old.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            name = backup.original.stem if backup.original else "Unbenannt"
            backup.path.replace(old / f"{stamp}_{name}.grdy")
            for stale in sorted(old.glob("*.grdy"))[:-KEEP_OLD]:
                stale.unlink(missing_ok=True)
    except OSError:
        pass
    backup.path.unlink(missing_ok=True)
    backup.meta.unlink(missing_ok=True)
    backup.path.with_name(backup.path.name + ".bak").unlink(missing_ok=True)


class AutoSaver(QObject):
    """Writes the drawing every few minutes while it has unsaved changes."""

    def __init__(self, window, interval_ms: int = INTERVAL_MS, directory: Path | None = None):
        super().__init__(window)
        self.w = window
        self.directory = directory or cache_dir()
        name = f"{PREFIX}{os.getpid()}"
        self.path = self.directory / f"{name}.grdy"
        self.meta = self.directory / f"{name}.json"
        self._saved_index: int | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.save_now)
        self.timer.start(interval_ms)

    def save_now(self) -> bool:
        """Back up if there are unsaved changes not yet backed up. True if written."""
        stack = self.w.undo_stack
        if stack.isClean():
            self.discard()
            return False
        if self._saved_index == stack.index() and self.path.exists():
            return False
        self.directory.mkdir(parents=True, exist_ok=True)
        save_document(self.w.document, self.path)
        self.path.with_name(self.path.name + ".bak").unlink(missing_ok=True)
        info = {
            "original": str(self.w.file_path) if self.w.file_path else None,
            "saved": datetime.now().isoformat(timespec="seconds"),
        }
        self.meta.write_text(json.dumps(info), encoding="utf-8")
        self._saved_index = stack.index()
        return True

    def discard(self) -> None:
        self._saved_index = None
        for p in (self.path, self.meta, self.path.with_name(self.path.name + ".bak")):
            p.unlink(missing_ok=True)
