"""Dialogs for sheet format, title block fields and frame templates."""

from datetime import date
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from sldgridy.i18n import library_text
from sldgridy.model.paper import PAPER_FORMATS, Orientation
from sldgridy.model.title_block import DOCUMENT_FIELDS, FIELD_LABELS, SHEET_FIELDS


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
        self, properties: dict[str, str], fields: dict[str, str], sheet_name: str, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Schriftfeld: {name}").format(name=sheet_name))
        self._doc_edits: dict[str, QLineEdit] = {}
        self._sheet_edits: dict[str, QLineEdit] = {}
        doc_box = QGroupBox(self.tr("Für die ganze Zeichnung"))
        doc_form = QFormLayout(doc_box)
        for tag in DOCUMENT_FIELDS:
            edit = QLineEdit(properties.get(tag, ""))
            doc_form.addRow(f"{_label(tag)}:", edit)
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
        return {t: e.text() for t, e in self._doc_edits.items() if e.text()}

    def fields(self) -> dict[str, str]:
        return {t: e.text() for t, e in self._sheet_edits.items() if e.text()}


class ProjectDialog(QDialog):
    """Data of the whole project: title block fields and the cover page."""

    def __init__(self, properties: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Projektdaten"))
        self._edits: dict[str, QLineEdit] = {}
        form = QFormLayout(self)
        for tag in DOCUMENT_FIELDS:
            edit = QLineEdit(properties.get(tag, ""))
            if tag == "ADRESSE":
                edit.setPlaceholderText(self.tr("Straße, PLZ Ort (Komma trennt die Zeilen)"))
            form.addRow(f"{_label(tag)}:", edit)
            self._edits[tag] = edit
        form.addRow(_buttons(self))
        self.resize(480, self.sizeHint().height())

    def properties(self) -> dict[str, str]:
        return {t: e.text() for t, e in self._edits.items() if e.text()}


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
