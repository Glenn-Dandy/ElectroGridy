"""Dialog for the main circuit conductors (rails) drawn across a page."""

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel

from electrogridy.model.routing import POLE_SPACING, RAIL_PRESETS, rail_names

KEY = "rails/"


class RailsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Potentialschienen"))
        settings = QSettings()
        self.names = QComboBox()
        self.names.setEditable(True)
        self.names.addItems(RAIL_PRESETS)
        self.names.setCurrentText(str(settings.value(KEY + "names", RAIL_PRESETS[0])))
        self.ends = QCheckBox(self.tr("Unterbrechungspunkte an beiden Enden (Seitenübergang)"))
        self.ends.setChecked(settings.value(KEY + "ends", True, type=bool))
        hint = QLabel(
            self.tr(
                "Leiter im festen Abstand von {mm} mm, über die ganze Seitenbreite. "
                "Geräte darunter setzen und mit der Leitung von Anschluss zu Anschluss "
                "verbinden."
            ).format(mm=f"{POLE_SPACING:g}")
        )
        hint.setWordWrap(True)
        form = QFormLayout(self)
        form.addRow(self.tr("Leiter:"), self.names)
        form.addRow(self.ends)
        form.addRow(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(max(self.sizeHint().width(), 420), self.sizeHint().height())

    def values(self) -> tuple[list[str], bool]:
        settings = QSettings()
        settings.setValue(KEY + "names", self.names.currentText())
        settings.setValue(KEY + "ends", self.ends.isChecked())
        return rail_names(self.names.currentText()), self.ends.isChecked()
