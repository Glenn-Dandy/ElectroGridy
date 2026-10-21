"""Application entry point."""

import faulthandler
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import QApplication

from sldgridy import __version__, i18n, memwatch, platform_choice
from sldgridy.fileio.paths import cache_dir
from sldgridy.ui.main_window import APP_NAME, MainWindow
from sldgridy.ui.start_dialog import show_on_start
from sldgridy.view.render import ensure_text_font


def create_application(argv: list[str]) -> QApplication:
    app = QApplication(argv)
    app.setOrganizationName("sldgridy")
    app.setApplicationName("sldgridy")
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("sldgridy")
    ensure_text_font()
    i18n.install(app, i18n.configured_language())
    return app


def enable_crash_log() -> None:
    """Write Python tracebacks of hard crashes (e.g. in Qt) to ~/.cache/sldgridy/crash.log."""
    try:
        directory = cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "crash.log"
        mode = "w" if path.exists() and path.stat().st_size > 256 * 1024 else "a"
        log = open(path, mode, encoding="utf-8")  # noqa: SIM115 - kept open
    except OSError:
        return
    log.write(f"--- SLDGridy {__version__} started\n")
    log.flush()
    faulthandler.enable(log, all_threads=True)
    _crash_log.append(log)  # keep the file object alive
    memwatch.start(log)


_crash_log: list = []


def select_platform() -> None:
    """Set QT_QPA_PLATFORM from the user's choice before Qt starts."""
    setting = str(
        QSettings("sldgridy", "sldgridy").value(platform_choice.SETTINGS_KEY, platform_choice.AUTO)
    )
    chosen = platform_choice.choose_platform(os.environ, setting)
    if chosen:
        os.environ["QT_QPA_PLATFORM"] = chosen


def main(argv: list[str] | None = None) -> int:
    enable_crash_log()
    select_platform()
    app = create_application(sys.argv if argv is None else argv)
    window = MainWindow()
    window.show()
    beat = QTimer(app)  # lets the memory watch notice a hanging user interface
    beat.timeout.connect(memwatch.heartbeat)
    beat.start(1000)
    memwatch.heartbeat()
    files = [a for a in app.arguments()[1:] if not a.startswith("-")]
    if files:
        window.open_path(Path(files[0]))
    if not window.offer_recovery() and not files and show_on_start():
        QTimer.singleShot(0, window.show_start_dialog)
    return app.exec()
