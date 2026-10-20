"""Dialogs around blocks, attributes and connection points."""

from collections.abc import Mapping

from PyQt6.QtCore import QCoreApplication, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from sldgridy.i18n import library_text
from sldgridy.model.blocks import BlockDefinition
from sldgridy.model.entities import AttributeDefinition
from sldgridy.ui.styles import HeightCombo
from sldgridy.view.thumbnails import block_icon


class AttributeValueEdit(QPlainTextEdit):
    """Attribute value input: Enter confirms like a line edit, Shift+Enter starts a
    new line (the value is then drawn on several lines)."""

    submitted = pyqtSignal()
    MAX_LINES = 4

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setTabChangesFocus(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setToolTip(self.tr("Umschalt+Enter: neue Zeile"))
        self.setPlainText(text)
        self.textChanged.connect(self._fit_height)
        self._fit_height()

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:  # noqa: N802 - QLineEdit compatible
        self.setPlainText(text)

    def _fit_height(self) -> None:
        lines = min(max(self.document().blockCount(), 1), self.MAX_LINES)
        metrics = self.fontMetrics()
        margins = self.contentsMargins()
        frame = 2 * self.frameWidth() + margins.top() + margins.bottom()
        doc_margin = 2 * int(self.document().documentMargin())
        self.setFixedHeight(lines * metrics.lineSpacing() + frame + doc_margin)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.insertPlainText("\n")
            else:
                self.submitted.emit()
            return
        super().keyPressEvent(event)


def _buttons(dialog: QDialog) -> QDialogButtonBox:
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class CreateBlockDialog(QDialog):
    def __init__(self, existing: set[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Block erstellen"))
        self._existing = existing
        self.name = QLineEdit()
        self.category = QLineEdit()
        self.description = QLineEdit()
        self.replace_selection = QCheckBox(self.tr("Auswahl durch Blockreferenz ersetzen"))
        self.replace_selection.setChecked(True)
        self.in_editor = QCheckBox(
            self.tr("Danach im Blockeditor Anschlusspunkte, Attribute und Basispunkt festlegen")
        )
        self.in_editor.setChecked(True)
        self.base_hint = QLabel(self.tr("Danach den Basispunkt in der Zeichnung angeben."))
        self.in_editor.toggled.connect(lambda on: self.base_hint.setHidden(on))
        self.base_hint.setHidden(True)
        self.error = QLabel()
        self.error.setStyleSheet("color: #c00000")
        form = QFormLayout(self)
        form.addRow(self.tr("Name:"), self.name)
        form.addRow(self.tr("Kategorie:"), self.category)
        form.addRow(self.tr("Beschreibung:"), self.description)
        form.addRow(self.replace_selection)
        form.addRow(self.in_editor)
        form.addRow(self.base_hint)
        form.addRow(self.error)
        form.addRow(_buttons(self))

    def accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.error.setText(self.tr("Bitte einen Namen angeben."))
            return
        if name in self._existing:
            self.error.setText(self.tr("Ein Block mit diesem Namen existiert bereits."))
            return
        super().accept()


class BlockPropertiesDialog(QDialog):
    """Name, category and description of an existing block."""

    def __init__(
        self,
        definition: BlockDefinition,
        existing: set[str],
        categories: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Blockeigenschaften"))
        self._old = definition.name
        self._existing = existing
        self.name = QLineEdit(definition.name)
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(sorted(set(categories) - {""}, key=str.casefold))
        self.category.setCurrentText(definition.category)
        self.description = QLineEdit(definition.description)
        # Role in the multi-line diagram (cross references between functions of a device).
        self.function = QComboBox()
        self.function.addItem(self.tr("keine"), "")
        self.function.addItem(self.tr("Hauptfunktion (z. B. Spule, Schalter)"), "main")
        self.function.addItem(self.tr("Nebenfunktion (Kontakt)"), "aux")
        self.function.addItem(self.tr("Klemme (BMK wie -X1:3)"), "terminal")
        self.function.setCurrentIndex(max(self.function.findData(definition.function), 0))
        self.function.setToolTip(
            self.tr(
                "Schaltplan (MLD): Unter einer Hauptfunktion erscheinen die Kontakte mit "
                "gleichem BMK, an jedem Kontakt die Stelle der Hauptfunktion."
            )
        )
        self.contact = QComboBox()
        self.contact.addItem(self.tr("Schließer"), "no")
        self.contact.addItem(self.tr("Öffner"), "nc")
        self.contact.addItem(self.tr("Wechsler"), "co")
        self.contact.setCurrentIndex(max(self.contact.findData(definition.contact), 0))
        self.function.currentIndexChanged.connect(self._update_contact)
        self.error = QLabel()
        self.error.setStyleSheet("color: #c00000")
        form = QFormLayout(self)
        form.addRow(self.tr("Name:"), self.name)
        form.addRow(self.tr("Kategorie:"), self.category)
        form.addRow(self.tr("Beschreibung:"), self.description)
        form.addRow(self.tr("Funktion:"), self.function)
        form.addRow(self.tr("Kontaktart:"), self.contact)
        form.addRow(self.error)
        form.addRow(_buttons(self))
        self._update_contact()
        self.resize(max(self.sizeHint().width(), 380), self.sizeHint().height())

    def _update_contact(self) -> None:
        self.contact.setEnabled(self.function.currentData() == "aux")

    def values(self) -> tuple[str, str, str]:
        return (
            self.name.text().strip(),
            self.category.currentText().strip(),
            self.description.text().strip(),
        )

    def role(self) -> tuple[str, str]:
        """Function and (for an aux function) contact type."""
        function = self.function.currentData()
        return function, self.contact.currentData() if function == "aux" else ""

    def accept(self) -> None:
        name = self.values()[0]
        if not name:
            self.error.setText(self.tr("Bitte einen Namen angeben."))
            return
        if name != self._old and name in self._existing:
            self.error.setText(self.tr("Ein Block mit diesem Namen existiert bereits."))
            return
        super().accept()


class BlockChooserDialog(QDialog):
    """Pick one (or several) blocks of the document."""

    def __init__(
        self,
        blocks: Mapping[str, BlockDefinition],
        title: str,
        parent=None,
        multi: bool = False,
        select_all: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Suchen …"))
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(64, 64))
        self.list.setGridSize(QSize(120, 100))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setWordWrap(True)
        if multi:
            self.list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        for name in sorted(blocks, key=str.casefold):
            item = QListWidgetItem(block_icon(name, blocks), library_text(name))
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setToolTip(library_text(blocks[name].description) or library_text(name))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        if select_all:
            self.list.selectAll()
        self.search.textChanged.connect(self._filter)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.list)
        layout.addWidget(_buttons(self))
        self.resize(560, 420)

    def _filter(self, text: str) -> None:
        needle = text.casefold()
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(needle not in item.text().casefold())

    def selected_names(self) -> list[str]:
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]


class AttributeValuesDialog(QDialog):
    def __init__(
        self,
        block_name: str,
        definitions: list[AttributeDefinition],
        values: dict[str, str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Attribute: {name}").format(name=library_text(block_name)))
        self._edits: dict[str, AttributeValueEdit] = {}
        form = QFormLayout(self)
        for d in definitions:
            edit = AttributeValueEdit(values.get(d.tag, d.default))
            edit.submitted.connect(self.accept)
            label = library_text(d.prompt) or d.tag
            form.addRow(f"{label}:", edit)
            self._edits[d.tag] = edit
        form.addRow(_buttons(self))

    def values(self) -> dict[str, str]:
        return {tag: edit.text() for tag, edit in self._edits.items()}


class AttributeDefinitionDialog(QDialog):
    def __init__(self, parent=None, current: AttributeDefinition | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Attribut definieren"))
        self.tag = QLineEdit(current.tag if current else "")
        self.prompt = QLineEdit(current.prompt if current else "")
        self.default = QLineEdit(current.default if current else "")
        self.height = HeightCombo()
        self.height.set_height(current.height if current else 2.5)
        self.halign = QComboBox()
        for key, label in (
            ("left", self.tr("links")),
            ("center", self.tr("zentriert")),
            ("right", self.tr("rechts")),
        ):
            self.halign.addItem(label, key)
        self.halign.setCurrentIndex(
            max(self.halign.findData(current.halign if current else "left"), 0)
        )
        self.visible = QCheckBox(self.tr("sichtbar"))
        self.visible.setChecked(current.visible if current else True)
        self.error = QLabel()
        self.error.setStyleSheet("color: #c00000")
        form = QFormLayout(self)
        form.addRow(self.tr("Kennung:"), self.tag)
        form.addRow(self.tr("Abfragetext:"), self.prompt)
        form.addRow(self.tr("Vorgabewert:"), self.default)
        form.addRow(self.tr("Texthöhe:"), self.height)
        form.addRow(self.tr("Ausrichtung:"), self.halign)
        form.addRow(self.visible)
        form.addRow(self.error)
        form.addRow(_buttons(self))

    def accept(self) -> None:
        tag = self.tag.text().strip()
        if not tag or any(c.isspace() for c in tag):
            self.error.setText(
                self.tr("Die Kennung darf nicht leer sein und keine Leerzeichen enthalten.")
            )
            return
        super().accept()

    def values(self) -> dict:
        return {
            "tag": self.tag.text().strip().upper(),
            "prompt": self.prompt.text().strip(),
            "default": self.default.text(),
            "height": self.height.height() or 2.5,
            "halign": self.halign.currentData(),
            "visible": self.visible.isChecked(),
        }


def direction_names() -> list[tuple[int, str]]:
    def tr(text: str) -> str:
        return QCoreApplication.translate("ConnectionPointDialog", text)

    return [
        (0, tr("rechts (0°)")),
        (90, tr("oben (90°)")),
        (180, tr("links (180°)")),
        (270, tr("unten (270°)")),
    ]


class ConnectionPointDialog(QDialog):
    def __init__(self, parent=None, name: str = "", direction: int = 90) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Anschlusspunkt"))
        self.name = QLineEdit(name)
        self.direction = QComboBox()
        for value, label in direction_names():
            self.direction.addItem(label, value)
        self.direction.setCurrentIndex(max(self.direction.findData(direction), 0))
        self.error = QLabel()
        self.error.setStyleSheet("color: #c00000")
        form = QFormLayout(self)
        form.addRow(self.tr("Name:"), self.name)
        form.addRow(self.tr("Leitung geht nach:"), self.direction)
        form.addRow(self.error)
        form.addRow(_buttons(self))

    def accept(self) -> None:
        if not self.name.text().strip():
            self.error.setText(self.tr("Bitte einen Namen angeben."))
            return
        super().accept()

    def values(self) -> tuple[str, int]:
        return self.name.text().strip(), int(self.direction.currentData())


KEEP, REPLACE, RENAME = "keep", "replace", "rename"


def ask_block_conflict(parent, name: str) -> str | None:
    """Ask how to handle a library block whose name exists with other content."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(parent.tr("Block existiert bereits"))
    box.setText(
        parent.tr(
            "Die Zeichnung enthält bereits einen anderen Block „{name}“. Wie soll verfahren werden?"
        ).format(name=name)
    )
    keep = box.addButton(parent.tr("Dokumentversion behalten"), QMessageBox.ButtonRole.AcceptRole)
    replace = box.addButton(parent.tr("Ersetzen"), QMessageBox.ButtonRole.DestructiveRole)
    rename = box.addButton(parent.tr("Umbenennen"), QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is keep:
        return KEEP
    if clicked is replace:
        return REPLACE
    if clicked is rename:
        return RENAME
    return None
