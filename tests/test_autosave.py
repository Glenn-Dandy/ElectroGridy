import json
import os

import pytest
from PyQt6.QtCore import QSettings

from electrogridy.model.entities import Line
from electrogridy.model.geometry import Point
from electrogridy.ui.autosave import AutoSaver, orphaned_backups
from electrogridy.ui.main_window import MainWindow


@pytest.fixture
def window(qapp, tmp_path):
    QSettings().clear()
    w = MainWindow()
    w.autosave.timer.stop()
    w.autosave = AutoSaver(w, directory=tmp_path)
    yield w
    w.undo_stack.setClean()
    w.close()


def draw_line(window):
    from electrogridy.commands.entities import AddEntitiesCommand

    line = Line(id="l", p1=Point(0, 0), p2=Point(10, 0))
    window.push(AddEntitiesCommand(window.document.model_space, [line], "x"))


def test_nothing_written_without_changes(window):
    assert not window.autosave.save_now()
    assert not window.autosave.path.exists()


def test_backup_written_once_per_change(window, tmp_path):
    draw_line(window)
    assert window.autosave.save_now()
    assert window.autosave.path.exists()
    meta = json.loads(window.autosave.meta.read_text(encoding="utf-8"))
    assert meta["original"] is None and meta["saved"]
    assert not window.autosave.save_now()  # unchanged since the last backup
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        f"autosave-{os.getpid()}.grdy",
        f"autosave-{os.getpid()}.json",
    ]


def test_saving_removes_backup(window, tmp_path):
    draw_line(window)
    window.autosave.save_now()
    assert window.save_to(tmp_path / "plan.grdy")
    assert not window.autosave.path.exists()


def test_orphans_from_dead_processes_are_offered(window, tmp_path):
    draw_line(window)
    window.autosave.save_now()
    # Our own backup is not an orphan.
    assert orphaned_backups(tmp_path) == []
    dead = 2**22 + 12345  # far above pid_max defaults, never alive
    for suffix in (".grdy", ".json"):
        src = window.autosave.path.with_suffix(suffix)
        (tmp_path / f"autosave-{dead}{suffix}").write_bytes(src.read_bytes())
    (backup,) = orphaned_backups(tmp_path)
    assert backup.path.name == f"autosave-{dead}.grdy"
    window.undo_stack.setClean()  # otherwise restoring asks to save first
    assert window.restore_backup(backup)
    assert len(window.document.model_space) == 1
    assert window.isWindowModified()
    # Removed only because our own backup of the recovered drawing exists now.
    assert window.autosave.path.exists()
    assert not backup.path.exists()
    assert orphaned_backups(tmp_path) == []
    # Kept aside, not deleted.
    assert len(list((tmp_path / "alt").glob("*.grdy"))) == 1
