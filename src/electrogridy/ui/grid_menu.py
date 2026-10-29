"""Grid and snap spacing typed right at the status bar buttons (RASTER, FANG)."""

from collections.abc import Callable

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QDoubleSpinBox, QFormLayout, QMenu, QWidget, QWidgetAction


def tr(text: str) -> str:
    return QCoreApplication.translate("GridMenu", text)


def _spin(value: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0.01, 100000.0)
    spin.setDecimals(2)
    spin.setSuffix(" mm")
    spin.setKeyboardTracking(False)  # apply on Enter or when leaving the field
    spin.setValue(value)
    return spin


class GridMenu(QMenu):
    """Grid and snap switches plus their spacing, applied as soon as they are typed."""

    def __init__(
        self,
        parent: QWidget,
        actions: list[QAction],
        get_spacing: Callable[[], tuple[float, float]],
        set_grid: Callable[[float], None],
        set_snap: Callable[[float], None],
        get_angle: Callable[[], float] | None = None,
        set_angle: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__(tr("Raster und Fang"), parent)
        self._get = get_spacing
        for action in actions:
            self.addAction(action)
        self.addSeparator()
        grid, snap = get_spacing()
        box = QWidget()
        form = QFormLayout(box)
        form.setContentsMargins(10, 4, 10, 6)
        self.grid_spin = _spin(grid)
        self.snap_spin = _spin(snap)
        form.addRow(tr("Raster:"), self.grid_spin)
        form.addRow(tr("Fang:"), self.snap_spin)
        self._get_angle = get_angle
        self.angle_spin: QDoubleSpinBox | None = None
        if get_angle is not None and set_angle is not None:
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 90.0)
            spin.setDecimals(1)
            spin.setSuffix("°")
            spin.setSpecialValueText(tr("aus"))
            spin.setKeyboardTracking(False)
            spin.setValue(get_angle())
            spin.setToolTip(
                tr(
                    "Bei eingetippter Länge (oder ohne Rasterfang) rasten Richtungen "
                    "in diesen Schritten ein; 0 schaltet aus"
                )
            )
            spin.valueChanged.connect(set_angle)
            form.addRow(tr("Winkelfang:"), spin)
            self.angle_spin = spin
        widget_action = QWidgetAction(self)
        widget_action.setDefaultWidget(box)
        self.addAction(widget_action)
        self.grid_spin.valueChanged.connect(set_grid)
        self.snap_spin.valueChanged.connect(set_snap)
        self.aboutToShow.connect(self.sync)

    def sync(self) -> None:
        grid, snap = self._get()
        pairs = [(self.grid_spin, grid), (self.snap_spin, snap)]
        if self.angle_spin is not None and self._get_angle is not None:
            pairs.append((self.angle_spin, self._get_angle()))
        for spin, value in pairs:
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
