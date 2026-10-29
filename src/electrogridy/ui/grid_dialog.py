"""Dialog for grid and snap spacing."""

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout


def _spin(value: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(2)
    box.setRange(0.1, 1000.0)
    box.setSingleStep(0.5)
    box.setSuffix(" mm")
    box.setValue(value)
    return box


class GridDialog(QDialog):
    def __init__(self, grid_spacing: float, snap_spacing: float, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Raster und Fang"))
        self.grid_box = _spin(grid_spacing)
        self.snap_box = _spin(snap_spacing)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow(self.tr("Rasterabstand:"), self.grid_box)
        form.addRow(self.tr("Fangabstand:"), self.snap_box)
        form.addRow(buttons)

    def grid_spacing(self) -> float:
        return self.grid_box.value()

    def snap_spacing(self) -> float:
        return self.snap_box.value()
