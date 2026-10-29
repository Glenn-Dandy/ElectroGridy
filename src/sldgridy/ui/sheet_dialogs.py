"""Dialogs for sheet format, title block fields and frame templates."""

from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from sldgridy.i18n import library_text
from sldgridy.model.blocks import BlockDefinition
from sldgridy.model.paper import PAPER_FORMATS, Orientation
from sldgridy.model.title_block import (
    DOCUMENT_FIELDS,
    FIELD_LABELS,
    LOGO_KEYS,
    MULTILINE_FIELDS,
    SHEET_FIELDS,
)
from sldgridy.view.thumbnails import block_icon

# What the logo choosers need: the logos on offer (name: block) and a way to import one.
Logos = Callable[[], Mapping[str, BlockDefinition]]
LogoImporter = Callable[[], str | None]


class LogoDialog(QDialog):
    """The logos of the library with large previews; no logo, or import one."""

    NONE = ""

    def __init__(
        self, current: str, logos: Logos, importer: LogoImporter | None, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Logo aus der Bibliothek"))
        self._logos, self._importer = logos, importer
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(120, 72))
        self.list.setGridSize(QSize(150, 110))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        self.empty = QLabel(
            self.tr("Noch keine Logos. Mit „Logo importieren …“ eines in „Eigene Logos“ ablegen.")
        )
        self.empty.setWordWrap(True)
        none = QPushButton(self.tr("Kein Logo"))
        none.clicked.connect(self._none)
        buttons = _buttons(self)
        buttons.addButton(none, QDialogButtonBox.ButtonRole.ResetRole)
        if importer is not None:
            add = QPushButton(self.tr("Logo importieren …"))
            add.clicked.connect(self._import)
            buttons.addButton(add, QDialogButtonBox.ButtonRole.ActionRole)
        layout = QVBoxLayout(self)
        layout.addWidget(self.empty)
        layout.addWidget(self.list, 1)
        layout.addWidget(buttons)
        self._fill(current)
        self.resize(560, 400)

    def _fill(self, current: str) -> None:
        logos = self._logos()
        self.list.clear()
        for name in sorted(logos, key=str.casefold):
            item = QListWidgetItem(block_icon(name, logos, 128), library_text(name))
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == current:
                self.list.setCurrentItem(item)
        self.empty.setVisible(not logos)

    def _none(self) -> None:
        self.list.clearSelection()
        self.list.setCurrentItem(None)
        self.accept()

    def _import(self) -> None:
        name = self._importer()
        if name:
            self._fill(name)

    def chosen(self) -> str:
        item = self.list.currentItem()
        if item is None or not item.isSelected():
            return self.NONE
        return item.data(Qt.ItemDataRole.UserRole)


class LogoChooser(QToolButton):
    """Logo of company or customer in the title block, chosen from the logos in the
    library ("Eigene Logos") or imported there (PNG, JPG, SVG)."""

    def __init__(self, current: str, logos: Logos, importer: LogoImporter | None, parent=None):
        super().__init__(parent)
        self.name = current
        self._logos, self._importer = logos, importer
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(40, 28))
        self.setFixedWidth(170)  # both fields stay as long
        self.setToolTip(self.tr("Logo im Schriftfeld, aus der Bibliothek gewählt"))
        self.clicked.connect(self._pick)
        self._show()

    def _show(self) -> None:
        logos = self._logos()
        if self.name and self.name in logos:
            self.setIcon(block_icon(self.name, logos, 64))
            self.setText(library_text(self.name))
        else:
            self.setIcon(QIcon())
            self.setText(self.tr("Logo …") if not self.name else self.name)

    def choose(self, name: str) -> None:
        self.name = name
        self._show()

    def _pick(self) -> None:
        dialog = LogoDialog(self.name, self._logos, self._importer, self)
        if dialog.exec() == LogoDialog.DialogCode.Accepted:
            self.choose(dialog.chosen())


class MultiLineEdit(QPlainTextEdit):
    """A few lines of text with the interface of a QLineEdit (text, setText)."""

    def __init__(self, text: str = "", lines: int = 3, parent=None) -> None:
        super().__init__(text, parent)
        self.setTabChangesFocus(True)
        height = self.fontMetrics().lineSpacing() * lines
        self.setFixedHeight(round(height + 2 * self.frameWidth() + 8))
        self.setPlaceholderText(self.tr("Name, darunter z. B. Straße und Ort (Enter: neue Zeile)"))

    def text(self) -> str:
        return "\n".join(line.rstrip() for line in self.toPlainText().strip().splitlines())

    def setText(self, text: str) -> None:  # noqa: N802 - like QLineEdit
        self.setPlainText(text)


def _field_edit(tag: str, value: str) -> QLineEdit | MultiLineEdit:
    return MultiLineEdit(value) if tag in MULTILINE_FIELDS else QLineEdit(value)


def _field_row(edit: QLineEdit, chooser: QToolButton | None):
    if chooser is None:
        return edit
    row = QHBoxLayout()
    row.addWidget(edit, 1)
    row.addWidget(chooser)
    return row


def _logo_choosers(
    properties: Mapping[str, str], logos: Logos | None, importer: LogoImporter | None
) -> dict[str, LogoChooser]:
    if logos is None:
        return {}
    return {
        tag: LogoChooser(properties.get(key, ""), logos, importer) for tag, key in LOGO_KEYS.items()
    }


def _with_logos(
    original: Mapping[str, str], fields: dict[str, str], choosers: dict[str, LogoChooser]
) -> dict[str, str]:
    """Document properties: the edited fields, the logos, the rest as it was."""
    out = {k: v for k, v in original.items() if k not in DOCUMENT_FIELDS}
    for tag, chooser in choosers.items():
        out.pop(LOGO_KEYS[tag], None)
        if chooser.name:
            out[LOGO_KEYS[tag]] = chooser.name
    out.update(fields)
    return out


def _label(tag: str) -> str:
    return QCoreApplication.translate("title_block", FIELD_LABELS[tag])


def _buttons(dialog: QDialog) -> QDialogButtonBox:
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class FormatDialog(QDialog):
    def __init__(
        self,
        paper: str,
        orientation: Orientation,
        title_block: str,
        block_names: list[str],
        parent=None,
        pages: int = 1,
        all_pages: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Blattformat"))
        self.paper = QComboBox()
        for name in sorted(PAPER_FORMATS, key=lambda n: -PAPER_FORMATS[n][0]):
            w, h = PAPER_FORMATS[name]
            self.paper.addItem(f"{name} ({w:g} × {h:g} mm)", name)
        self.paper.setCurrentIndex(max(self.paper.findData(paper), 0))
        self.orientation = QComboBox()
        self.orientation.addItem(self.tr("quer"), Orientation.LANDSCAPE)
        self.orientation.addItem(self.tr("hoch"), Orientation.PORTRAIT)
        self.orientation.setCurrentIndex(0 if orientation is Orientation.LANDSCAPE else 1)
        self.title_block = QComboBox()
        self.title_block.addItem(self.tr("(kein Schriftfeld)"), "")
        for name in sorted(block_names, key=str.casefold):
            self.title_block.addItem(name, name)
        self.title_block.setCurrentIndex(max(self.title_block.findData(title_block), 0))
        form = QFormLayout(self)
        form.addRow(self.tr("Format:"), self.paper)
        form.addRow(self.tr("Ausrichtung:"), self.orientation)
        form.addRow(self.tr("Schriftfeld (Block):"), self.title_block)
        # Several pages: the format of the whole project in one go.
        self.all_pages = QCheckBox(self.tr("Für alle Seiten ({n})").format(n=pages))
        self.all_pages.setChecked(all_pages and pages > 1)
        if pages > 1:
            form.addRow(self.all_pages)
        form.addRow(_buttons(self))

    def values(self) -> tuple[str, Orientation, str]:
        return (
            self.paper.currentData(),
            self.orientation.currentData(),
            self.title_block.currentData(),
        )

    def for_all_pages(self) -> bool:
        return self.all_pages.isChecked()


class FieldsDialog(QDialog):
    """Title block values: drawing-wide ones and those of one sheet."""

    def __init__(
        self,
        properties: dict[str, str],
        fields: dict[str, str],
        sheet_name: str,
        parent=None,
        logos: Logos | None = None,
        importer: LogoImporter | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Schriftfeld: {name}").format(name=sheet_name))
        self._original = dict(properties)
        self._doc_edits: dict[str, QLineEdit] = {}
        self._sheet_edits: dict[str, QLineEdit] = {}
        self.logos = _logo_choosers(properties, logos, importer)
        doc_box = QGroupBox(self.tr("Für die ganze Zeichnung"))
        doc_form = QFormLayout(doc_box)
        for tag in DOCUMENT_FIELDS:
            edit = _field_edit(tag, properties.get(tag, ""))
            doc_form.addRow(f"{_label(tag)}:", _field_row(edit, self.logos.get(tag)))
            self._doc_edits[tag] = edit
        sheet_box = QGroupBox(self.tr("Für dieses Blatt"))
        sheet_form = QFormLayout(sheet_box)
        for tag in SHEET_FIELDS:
            value = fields.get(tag, "")
            if tag == "DATUM" and not value:
                value = date.today().strftime("%d.%m.%Y")
            edit = QLineEdit(value)
            sheet_form.addRow(f"{_label(tag)}:", edit)
            self._sheet_edits[tag] = edit
        layout = QVBoxLayout(self)
        layout.addWidget(doc_box)
        layout.addWidget(sheet_box)
        layout.addWidget(_buttons(self))
        self.resize(460, self.sizeHint().height())

    def properties(self) -> dict[str, str]:
        typed = {t: e.text() for t, e in self._doc_edits.items() if e.text()}
        return _with_logos(self._original, typed, self.logos)

    def fields(self) -> dict[str, str]:
        return {t: e.text() for t, e in self._sheet_edits.items() if e.text()}


class ProjectDialog(QDialog):
    """Data of the whole project: title block fields and the cover page."""

    def __init__(
        self,
        properties: dict[str, str],
        parent=None,
        logos: Logos | None = None,
        importer: LogoImporter | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Projektdaten"))
        self._original = dict(properties)
        self._edits: dict[str, QLineEdit] = {}
        self.logos = _logo_choosers(properties, logos, importer)
        form = QFormLayout(self)
        for tag in DOCUMENT_FIELDS:
            edit = _field_edit(tag, properties.get(tag, ""))
            if tag == "ADRESSE":
                edit.setPlaceholderText(self.tr("Straße, PLZ Ort (Komma trennt die Zeilen)"))
            form.addRow(f"{_label(tag)}:", _field_row(edit, self.logos.get(tag)))
            self._edits[tag] = edit
        form.addRow(_buttons(self))
        self.resize(480, self.sizeHint().height())

    def properties(self) -> dict[str, str]:
        typed = {t: e.text() for t, e in self._edits.items() if e.text()}
        return _with_logos(self._original, typed, self.logos)


class TemplateChooserDialog(QDialog):
    def __init__(self, templates: list[tuple[str, Path, bool]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Neues Blatt aus Vorlage"))
        self.list = QListWidget()
        for title, path, _shipped in templates:
            item = QListWidgetItem(library_text(title))
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addWidget(_buttons(self))
        self.resize(380, 360)

    def selected_path(self) -> Path | None:
        item = self.list.currentItem()
        return Path(item.data(Qt.ItemDataRole.UserRole)) if item else None
