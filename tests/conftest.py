import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    # Keep tests away from the user's real settings.
    settings_dir = tmp_path_factory.mktemp("settings")
    os.environ["XDG_DATA_HOME"] = str(tmp_path_factory.mktemp("data"))
    os.environ["XDG_CACHE_HOME"] = str(tmp_path_factory.mktemp("cache"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(settings_dir))

    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("electrogridy-test")
    app.setApplicationName("electrogridy-test")
    from electrogridy.view.render import ensure_text_font

    ensure_text_font()
    yield app
