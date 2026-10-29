"""About dialog: feedback, GitHub star, source, support and update check (like BoatSpeedy)."""

import contextlib
import os
import platform
import threading
from pathlib import Path
from urllib.parse import quote

from PyQt6.QtCore import QT_VERSION_STR, QObject, QSize, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QIcon, QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from electrogridy import __version__, project
from electrogridy.update import UpdateResult, check

ICONS = Path(__file__).resolve().parent.parent / "resources" / "icons"
ICON_PATH = ICONS / "electrogridy.svg"
LOGO_SIZE = 56  # wozise logo under the footer, as in BoatSpeedy
SUPPORT_COLOR = "#c62828"


def app_icon() -> QIcon:
    return QIcon(str(ICON_PATH)) if ICON_PATH.exists() else QIcon()


def open_url(url: str) -> bool:
    return QDesktopServices.openUrl(QUrl(url))


def system_info() -> str:
    try:
        os_name = platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
    except OSError:
        os_name = platform.platform()
    session = os.environ.get("XDG_SESSION_TYPE") or QGuiApplication.platformName()
    return (
        f"**ElectroGridy:** {__version__}\n"
        f"**System:** {os_name}\n"
        f"**Qt:** {QT_VERSION_STR} ({session})\n"
        f"**Python:** {platform.python_version()}\n"
    )


def issue_url(title_prefix: str, label: str) -> str:
    body = "\n\n---\n" + system_info()
    return (
        f"{project.ISSUES_NEW_URL}?labels={quote(label)}"
        f"&title={quote(title_prefix)}&body={quote(body)}"
    )


def installed_as_snap() -> bool:
    return bool(os.environ.get("SNAP")) and "electrogridy" in os.environ.get("SNAP_NAME", "")


class _UpdateWorker(QObject):
    finished = pyqtSignal(object)

    def start(self) -> None:
        threading.Thread(target=lambda: self.finished.emit(check(__version__)), daemon=True).start()


DIALOG_WIDTH = 420


class ActionRow(QPushButton):
    """Full-width flat row with symbol, label and arrow, as in BoatSpeedy."""

    def __init__(self, symbol: str, text: str, color: str | None = None) -> None:
        super().__init__(f"{symbol}    {text}")
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        style = "QPushButton { text-align: left; padding: 8px 10px; border: none; }"
        style += " QPushButton:hover { background: palette(midlight); }"
        if color:
            style += f" QPushButton {{ color: {color}; font-weight: bold; }}"
        self.setStyleSheet(style)
        # Never squeeze a row: symbols from fallback fonts make rows taller than Qt
        # expects, and a too small dialog would otherwise cut the labels in half.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self.sizeHint().height())


def _section(title: str, rows: list[QWidget]) -> QGroupBox:
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(4, 8, 4, 4)
    layout.setSpacing(0)
    for i, row in enumerate(rows):
        if i:
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            layout.addWidget(line)
        layout.addWidget(row)
    return box


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Über ElectroGridy"))
        self.opened: list[str] = []  # URLs opened, for tests

        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(QSize(72, 72)))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = QLabel("<b style='font-size:16pt'>ElectroGridy</b>")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version = QLabel(self.tr("Version {v}").format(v=__version__))
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color: gray")
        tagline = QLabel(
            self.tr(
                "Einpolige Übersichtsschaltpläne für Photovoltaik, "
                "Transformatorstationen und Niederspannungsverteilungen."
            )
        )
        tagline.setWordWrap(True)
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_bug = ActionRow("⚠", self.tr("Fehler melden"))
        self.btn_feature = ActionRow("✎", self.tr("Funktion vorschlagen"))
        self.btn_star = ActionRow("★", self.tr("Stern auf GitHub geben"))
        self.btn_source = ActionRow("</>", self.tr("Quellcode ansehen"))
        self.btn_support = ActionRow("♥", self.tr("Projekt unterstützen"), SUPPORT_COLOR)
        self.btn_bug.clicked.connect(lambda: self._open(issue_url("[Bug] ", "bug")))
        self.btn_feature.clicked.connect(lambda: self._open(issue_url("[Feature] ", "enhancement")))
        self.btn_star.clicked.connect(lambda: self._open(project.URL))
        self.btn_source.clicked.connect(lambda: self._open(project.URL))
        self.btn_support.clicked.connect(lambda: self._open(project.SUPPORT_URL))

        self.btn_update = ActionRow("⟳", self.tr("Auf Updates prüfen"))
        self.btn_update.clicked.connect(self.check_updates)
        self.lbl_update = QLabel()
        self.lbl_update.setWordWrap(True)
        self.lbl_update.hide()
        self.btn_download = QPushButton(self.tr("Herunterladen"))
        self.btn_release = QPushButton(self.tr("Release öffnen"))
        self.btn_download.hide()
        self.btn_release.hide()
        if installed_as_snap():
            # The Snap Store updates the snap; a .deb download would be wrong here.
            self.btn_update.hide()
            self.lbl_update.setText(self.tr("Updates kommen automatisch über den Snap Store."))
            self.lbl_update.show()
        update_row = QWidget()
        ul = QVBoxLayout(update_row)
        ul.setContentsMargins(10, 0, 10, 6)
        ul.addWidget(self.lbl_update)
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_download)
        buttons.addWidget(self.btn_release)
        buttons.addStretch(1)
        ul.addLayout(buttons)

        footer = QLabel(
            f"<span style='color: gray'>{project.LICENSE} · © {project.OWNER} · </span>"
            f"<a href='{project.WEBSITE_URL}'>{project.WEBSITE_LABEL}</a>"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.linkActivated.connect(lambda _link: self._open(project.WEBSITE_URL))
        self.btn_website = QToolButton()
        self.btn_website.setIcon(QIcon(str(ICONS / self._logo_file())))
        self.btn_website.setIconSize(QSize(LOGO_SIZE, LOGO_SIZE))
        self.btn_website.setAutoRaise(True)
        self.btn_website.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_website.setToolTip(project.WEBSITE_LABEL)
        self.btn_website.clicked.connect(lambda: self._open(project.WEBSITE_URL))
        close = QPushButton(self.tr("Schließen"))
        close.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(icon)
        layout.addWidget(name)
        layout.addWidget(version)
        layout.addWidget(tagline)
        layout.addSpacing(8)
        layout.addWidget(_section(self.tr("Feedback"), [self.btn_bug, self.btn_feature]))
        layout.addWidget(
            _section(self.tr("Projekt"), [self.btn_star, self.btn_source, self.btn_support])
        )
        layout.addWidget(_section(self.tr("Update"), [self.btn_update, update_row]))
        layout.addSpacing(6)
        layout.addWidget(footer)
        layout.addWidget(self.btn_website, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        self._fit()

        self._worker = _UpdateWorker(self)
        self._worker.finished.connect(self.show_update_result)

    def _fit(self) -> None:
        """Size for the real width: the wrapped texts need more lines in a narrow dialog,
        and Qt's own minimum height does not account for that (it squeezed the rows)."""
        layout = self.layout()
        layout.activate()
        width = max(DIALOG_WIDTH, self.width() if self.isVisible() else 0)
        width = max(width, layout.minimumSize().width())
        self.setMinimumSize(width, layout.totalHeightForWidth(width))
        if self.height() < self.minimumHeight() or not self.isVisible():
            self.resize(width, self.minimumHeight())

    def _logo_file(self) -> str:
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        return "wozise_dark.svg" if dark else "wozise.svg"

    def _open(self, url: str) -> None:
        self.opened.append(url)
        open_url(url)

    def check_updates(self) -> None:
        self.btn_update.setEnabled(False)
        self.lbl_update.setText(self.tr("Suche nach Updates …"))
        self.lbl_update.show()
        self.btn_download.hide()
        self.btn_release.hide()
        self._fit()
        self._worker.start()

    def show_update_result(self, result: UpdateResult) -> None:
        self._show_update_result(result)
        self._fit()  # the result adds lines and buttons

    def _show_update_result(self, result: UpdateResult) -> None:
        self.btn_update.setEnabled(True)
        self.lbl_update.show()
        for b in (self.btn_download, self.btn_release):
            with contextlib.suppress(TypeError):  # nothing connected yet
                b.clicked.disconnect()
        if not result.ok:
            self.lbl_update.setText(
                self.tr("Die Update-Prüfung ist fehlgeschlagen (keine Verbindung zu GitHub?).")
            )
            self.lbl_update.setStyleSheet(f"color: {SUPPORT_COLOR}")
            return
        self.lbl_update.setStyleSheet("")
        if not result.available:
            self.lbl_update.setText(self.tr("ElectroGridy ist aktuell."))
            return
        self.lbl_update.setText(
            self.tr("<b>Version {v} ist verfügbar.</b>").format(v=result.version)
        )
        self.btn_download.clicked.connect(
            lambda: self._open(result.download_url or result.release_url)
        )
        self.btn_release.clicked.connect(lambda: self._open(result.release_url))
        self.btn_download.show()
        self.btn_release.show()
