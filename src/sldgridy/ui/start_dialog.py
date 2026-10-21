"""Start window: a new overview diagram, project or drawing, or a file opened last."""

from pathlib import Path

from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from sldgridy import __version__
from sldgridy.model.document import DOC_DRAWING, DOC_KINDS, DOC_PROJECT, DOC_SLD

SHOW_KEY = "start/show_dialog"
PATH_ROLE = Qt.ItemDataRole.UserRole


def show_on_start() -> bool:
    return QSettings().value(SHOW_KEY, True, type=bool)


class StartDialog(QDialog):
    """``choice`` after acceptance: ("new", kind), ("open", path) or ("browse", "")."""

    def __init__(self, recent: list[tuple[Path, str]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("SLDGridy {version}").format(version=__version__))
        self.choice: tuple[str, str] = ("", "")
        hints = {
            DOC_SLD: self.tr(
                "Einpoliger Übersichtsschaltplan, z. B. einer PV-Anlage: Modell mit "
                "Zeichnungsrahmen A0 bis A4"
            ),
            DOC_PROJECT: self.tr(
                "Allpoliger Schaltplan mit nummerierten Seiten A3: Deckblatt, Stromlaufplan, "
                "Klemmenplan, Stückliste, Querverweise"
            ),
            DOC_DRAWING: self.tr("Maßstäbliche Zeichnung, z. B. Dachbelegung mit PV-Modulen"),
        }
        new_box = QGroupBox(self.tr("Neu"))
        new_layout = QVBoxLayout(new_box)
        for kind in (DOC_SLD, DOC_PROJECT, DOC_DRAWING):
            button = QPushButton(self.tr(DOC_KINDS[kind]))
            button.setMinimumHeight(36)
            button.setStyleSheet("text-align: left; padding-left: 10px; font-weight: bold;")
            button.clicked.connect(lambda _c, k=kind: self._choose("new", k))
            hint = QLabel(hints[kind])
            hint.setWordWrap(True)
            hint.setContentsMargins(10, 0, 0, 6)
            new_layout.addWidget(button)
            new_layout.addWidget(hint)
        new_layout.addStretch(1)

        recent_box = QGroupBox(self.tr("Zuletzt geöffnet"))
        recent_layout = QVBoxLayout(recent_box)
        self.recent = QListWidget()
        self.recent.setIconSize(QSize(0, 0))
        self.recent.setSpacing(3)
        for path, kind in recent:
            item = QListWidgetItem(f"{path.name}\n{self.tr(DOC_KINDS[kind])}  ·  {path.parent}")
            item.setData(PATH_ROLE, str(path))
            item.setToolTip(str(path))
            self.recent.addItem(item)
        if not recent:
            empty = QListWidgetItem(self.tr("Noch keine Dateien"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(empty)
        else:
            self.recent.setCurrentRow(0)
        self.recent.itemActivated.connect(self._open_item)
        open_button = QPushButton(self.tr("Ö&ffnen"))
        open_button.clicked.connect(self._open_current)
        open_button.setEnabled(bool(recent))
        browse = QPushButton(self.tr("&Andere Datei …"))
        browse.clicked.connect(lambda: self._choose("browse", ""))
        buttons = QHBoxLayout()
        buttons.addWidget(open_button)
        buttons.addWidget(browse)
        buttons.addStretch(1)
        recent_layout.addWidget(self.recent)
        recent_layout.addLayout(buttons)

        self.show_next = QCheckBox(self.tr("Beim Start anzeigen"))
        self.show_next.setChecked(show_on_start())
        self.show_next.toggled.connect(lambda on: QSettings().setValue(SHOW_KEY, on))
        close = QPushButton(self.tr("Schließen"))
        close.clicked.connect(self.reject)

        columns = QHBoxLayout()
        columns.addWidget(new_box, 1)
        columns.addWidget(recent_box, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(self.show_next)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addLayout(columns)
        layout.addLayout(bottom)
        self.resize(760, 420)

    def _choose(self, action: str, value: str) -> None:
        self.choice = (action, value)
        self.accept()

    def _open_item(self, item: QListWidgetItem) -> None:
        path = item.data(PATH_ROLE)
        if path:
            self._choose("open", path)

    def _open_current(self) -> None:
        item = self.recent.currentItem()
        if item is not None:
            self._open_item(item)
