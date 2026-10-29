"""Dialog for "Klemme setzen": strip (existing or new) and a free terminal number, or
PE, N, PEN instead of a number (ticking one greys out the numbers)."""

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
)

from electrogridy.model.devices import _natural
from electrogridy.model.terminals import NAMED, free_numbers, normalized_strip


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
        self.number.setToolTip(self.tr("Nur freie Klemmen dieser Leiste"))
        # Instead of a number: at most one ticked, the numbers are greyed out then.
        self.named = {name: QCheckBox(name) for name in NAMED}
        named_row = QHBoxLayout()
        for name, box in self.named.items():
            box.setToolTip(self.tr("Klemme {name} statt einer Nummer").format(name=name))
            box.toggled.connect(lambda on, name=name: self._named_toggled(name, on))
            named_row.addWidget(box)
        named_row.addStretch(1)
        self.used = QLabel()
        self.used.setWordWrap(True)
        form = QFormLayout(self)
        form.addRow(self.tr("Klemmleiste:"), self.strip)
        form.addRow(self.tr("Klemme:"), self.number)
        form.addRow(self.tr("Statt Nummer:"), named_row)
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
        self.used.setText(
            self.tr("Belegt: {numbers}").format(numbers=", ".join(used))
            if used
            else self.tr("Neue Leiste")
        )

    def _named_toggled(self, name: str, on: bool) -> None:
        if on:
            for other, box in self.named.items():
                if other != name:
                    box.setChecked(False)
        self.number.setEnabled(not self.named_choice())

    def named_choice(self) -> str:
        return next((name for name, box in self.named.items() if box.isChecked()), "")

    def values(self) -> tuple[str, str]:
        """Strip ("-X1") and number ("4", or "PE", "N", "PEN")."""
        number = self.named_choice() or self.number.currentText()
        return normalized_strip(self.strip.currentText()), number
