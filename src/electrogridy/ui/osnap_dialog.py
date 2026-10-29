"""Dialog for choosing the active object snap modes."""

from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QVBoxLayout

from electrogridy.model.snap import SnapMode
from electrogridy.ui.osnap_menu import mode_labels


class OsnapDialog(QDialog):
    def __init__(self, modes: frozenset[SnapMode], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Objektfang"))
        labels = mode_labels()
        layout = QVBoxLayout(self)
        self._boxes: dict[SnapMode, QCheckBox] = {}
        for mode, label in labels.items():
            box = QCheckBox(label)
            box.setChecked(mode in modes)
            layout.addWidget(box)
            self._boxes[mode] = box
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def modes(self) -> frozenset[SnapMode]:
        return frozenset(m for m, box in self._boxes.items() if box.isChecked())
