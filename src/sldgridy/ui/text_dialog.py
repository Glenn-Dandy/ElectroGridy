"""Dialog for entering or editing a text entity, or a cable outlet label (with its
cable)."""

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPlainTextEdit,
    QVBoxLayout,
)

from sldgridy.model.entities import DEFAULT_TEXT_HEIGHT
from sldgridy.ui.styles import HeightCombo


class TextDialog(QDialog):
    def __init__(
        self,
        parent=None,
        text: str = "",
        height: float | None = None,
        cables: list[str] | None = None,
        cable: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Kabelabgang") if cables is not None else self.tr("Text"))

        self.edit = QPlainTextEdit(text)
        self.edit.setPlaceholderText(self.tr("Mehrere Zeilen mit Enter trennen"))
        self.height_box = HeightCombo()
        self.height_box.set_height(DEFAULT_TEXT_HEIGHT if height is None else height)

        form = QFormLayout()
        form.addRow(self.tr("Texthöhe:"), self.height_box)
        self.cable_box: QComboBox | None = None
        if cables is not None:
            self.edit.setPlaceholderText(self.tr("Wohin das Kabel geht, z. B. Abgang zur NSA"))
            self.cable_box = QComboBox()
            self.cable_box.setEditable(True)
            self.cable_box.addItems(cables)
            self.cable_box.setCurrentText(cable)
            self.cable_box.setToolTip(self.tr("Kabel, zu dem der Abgang gehört, z. B. -W1"))
            form.addRow(self.tr("Kabel:"), self.cable_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.edit)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(420, 220)
        self.edit.setFocus()

    def text(self) -> str:
        return self.edit.toPlainText()

    def cable(self) -> str:
        return self.cable_box.currentText().strip() if self.cable_box is not None else ""

    def text_height(self) -> float:
        return self.height_box.height() or DEFAULT_TEXT_HEIGHT
