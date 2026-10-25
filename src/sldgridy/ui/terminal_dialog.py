"""Dialog for "Klemme setzen": strip (existing or new) and a free terminal number, or
PE, N, PEN instead of a number."""

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
)

from sldgridy.model.devices import _natural
from sldgridy.model.terminals import NAMED, free_numbers, normalized_strip


class TerminalDialog(QDialog):
    def __init__(self, strips: dict[str, list[str]], last: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Klemme setzen"))
        self._strips = strips
        self.strip = QComboBox()
        self.strip.setEditable(True)
        self.strip.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.strip.addItems(sorted(strips, key=_natural))
        self.strip.setCurrentText(last or (next(iter(strips), "") or "-X1"))
        self.strip.setToolTip(self.tr("Vorhandene Leiste wählen oder neue eintippen, z. B. X2"))
        self.number = QComboBox()
        self.number.setToolTip(
            self.tr("Freie Nummern dieser Leiste, oder PE, N, PEN statt einer Nummer")
        )
        self.used = QLabel()
        self.used.setWordWrap(True)
        form = QFormLayout(self)
        form.addRow(self.tr("Klemmleiste:"), self.strip)
        form.addRow(self.tr("Klemme:"), self.number)
        form.addRow(self.used)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.strip.currentTextChanged.connect(self._refresh)
        self._refresh()
        self.resize(max(self.sizeHint().width(), 340), self.sizeHint().height())

    def _refresh(self, _text: str = "") -> None:
        used = self._strips.get(normalized_strip(self.strip.currentText()), [])
        self.number.clear()
        self.number.addItems(free_numbers(used))
        self.number.insertSeparator(self.number.count())
        self.number.addItems(NAMED)
        self.used.setText(
            self.tr("Belegt: {numbers}").format(numbers=", ".join(used))
            if used
            else self.tr("Neue Leiste")
        )

    def values(self) -> tuple[str, str]:
        """Strip ("-X1") and number ("4", or "PE", "N", "PEN")."""
        return normalized_strip(self.strip.currentText()), self.number.currentText()
