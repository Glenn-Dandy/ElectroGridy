from PyQt6.QtCore import QSettings

from electrogridy.takeover import migrate_data, migrate_settings
from electrogridy.ui.library_dock import library_files


def _settings(path):
    return QSettings(str(path), QSettings.Format.IniFormat)


def test_old_settings_are_copied_once(tmp_path):
    old, new = _settings(tmp_path / "old.ini"), _settings(tmp_path / "new.ini")
    old.setValue("files/last_dir", "/home/x/plaene")
    old.setValue("view/polar_increment", 15)
    assert migrate_settings(new, old)
    assert new.value("files/last_dir") == "/home/x/plaene"
    old.setValue("files/last_dir", "/anders")
    assert not migrate_settings(new, old)
    assert new.value("files/last_dir") == "/home/x/plaene"


def test_old_symbols_and_templates_are_copied_with_new_suffix(tmp_path):
    old, new = tmp_path / "sldgridy", tmp_path / "electrogridy"
    (old / "library").mkdir(parents=True)
    (old / "templates").mkdir()
    (old / "library" / "eigene.sldglib").write_text("{}")
    (old / "templates" / "Kunde.sldgframe").write_text("{}")
    assert migrate_data(new, old)
    assert (new / "library" / "eigene.grdylib").exists()
    assert (new / "templates" / "Kunde.grdyframe").exists()
    assert (old / "library" / "eigene.sldglib").exists()  # the old version keeps its own
    assert not migrate_data(new, old)


def test_old_library_files_are_listed(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    directory = tmp_path / "electrogridy" / "library"
    directory.mkdir(parents=True)
    (directory / "alt.sldglib").write_text("{}")
    (directory / "neu.grdylib").write_text("{}")
    mine = [p.name for p, shipped in library_files() if not shipped]
    assert mine == ["alt.sldglib", "neu.grdylib"]
