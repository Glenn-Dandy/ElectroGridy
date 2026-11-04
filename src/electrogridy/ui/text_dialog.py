"""Dialog for entering or editing a text entity, or a cable outlet label (with its
cable)."""

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPlainTextEdit,
    QVBoxLayout,
)

from electrogridy.model.entities import DEFAULT_TEXT_HEIGHT
from electrogridy.ui.styles import HeightCombo

LEFT_BASELINE = ("left", "baseline")
Anchor = tuple[str, str]  # (halign, valign) of a text


def text_anchors() -> list[tuple[str, Anchor]]:
    """Reference points a text can have, with their names."""

    def tr(text: str) -> str:
        return QCoreApplication.translate("TextAnchor", text)

    return [
        (tr("Links (Grundlinie)"), ("left", "baseline")),
        (tr("Mittig (Grundlinie)"), ("center", "baseline")),
        (tr("Rechts (Grundlinie)"), ("right", "baseline")),
        (tr("Links, Mitte"), ("left", "middle")),
        (tr("Mitte"), ("center", "middle")),
        (tr("Rechts, Mitte"), ("right", "middle")),
    ]


class TextDialog(QDialog):
    def __init__(
        self,
        parent=None,
        text: str = "",
        height: float | None = None,
        cables: list[str] | None = None,
        cable: str = "",
        anchor: Anchor | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Kabelabgang") if cables is not None else self.tr("Text"))

        self.edit = QPlainTextEdit(text)
        self.edit.setPlaceholderText(self.tr("Mehrere Zeilen mit Enter trennen"))
        self.height_box = HeightCombo()
        self.height_box.set_height(DEFAULT_TEXT_HEIGHT if height is None else height)

        form = QFormLayout()
        form.addRow(self.tr("Texthöhe:"), self.height_box)
        self.anchor_box: QComboBox | None = None
        if anchor is not None:
            self.anchor_box = QComboBox()
            for label, key in text_anchors():
                self.anchor_box.addItem(label, key)
            self.anchor_box.setCurrentIndex(max(self.anchor_box.findData(anchor), 0))
            self.anchor_box.setToolTip(
                self.tr("Wo der Punkt des Textes sitzt, an dem er gefangen und verschoben wird")
            )
            form.addRow(self.tr("Bezugspunkt:"), self.anchor_box)
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

    def anchor(self) -> Anchor:
        return tuple(self.anchor_box.currentData()) if self.anchor_box else LEFT_BASELINE

    def text_height(self) -> float:
        return self.height_box.height() or DEFAULT_TEXT_HEIGHT
