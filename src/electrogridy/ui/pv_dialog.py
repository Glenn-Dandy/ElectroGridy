"""Dialog for the module field: module size and power, orientation, distances."""

from dataclasses import fields

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
)

from electrogridy.tools.pv import LANDSCAPE, PORTRAIT, ModuleSpec

SETTINGS_GROUP = "pv_module_field"


def saved_spec() -> ModuleSpec:
    settings = QSettings()
    values = {}
    for f in fields(ModuleSpec):
        default = getattr(ModuleSpec(), f.name)
        kind = type(default)
        values[f.name] = settings.value(f"{SETTINGS_GROUP}/{f.name}", default, type=kind)
    return ModuleSpec(**values)


def save_spec(spec: ModuleSpec) -> None:
    settings = QSettings()
    for f in fields(ModuleSpec):
        settings.setValue(f"{SETTINGS_GROUP}/{f.name}", getattr(spec, f.name))


def _mm(value: float, maximum: float = 100000.0, suffix: str = " mm") -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(0.0, maximum)
    spin.setDecimals(0)
    spin.setSuffix(suffix)
    spin.setValue(value)
    return spin


class ModuleFieldDialog(QDialog):
    def __init__(self, spec: ModuleSpec, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Modulfeld"))
        self.width_spin = _mm(spec.width)
        self.height_spin = _mm(spec.height)
        self.power_spin = _mm(spec.power, 2000.0, " Wp")
        self.orientation = QComboBox()
        self.orientation.addItem(self.tr("Hochformat"), PORTRAIT)
        self.orientation.addItem(self.tr("Querformat"), LANDSCAPE)
        self.orientation.setCurrentIndex(max(self.orientation.findData(spec.orientation), 0))
        self.gap_spin = _mm(spec.gap)
        self.edge_spin = _mm(spec.edge)
        self.obstacle_spin = _mm(spec.obstacle_gap)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(0, 100000)
        self.count_spin.setSpecialValueText(self.tr("so viele wie passen"))
        self.count_spin.setValue(int(spec.count))
        self.count_spin.setToolTip(
            self.tr("Reihen von oben füllen; die letzte, angefangene Reihe sitzt mittig")
        )
        form = QFormLayout(self)
        form.addRow(QLabel(self.tr("<b>Modul</b> (laut Datenblatt)")))
        form.addRow(self.tr("Breite (kurze Seite):"), self.width_spin)
        form.addRow(self.tr("Höhe (lange Seite):"), self.height_spin)
        form.addRow(self.tr("Leistung:"), self.power_spin)
        form.addRow(self.tr("Ausrichtung:"), self.orientation)
        form.addRow(self.tr("Anzahl:"), self.count_spin)
        form.addRow(QLabel(self.tr("<b>Abstände</b>")))
        form.addRow(self.tr("Zwischen den Modulen:"), self.gap_spin)
        form.addRow(self.tr("Zur Dachkante:"), self.edge_spin)
        form.addRow(self.tr("Zu Hindernissen:"), self.obstacle_spin)
        form.addRow(
            QLabel(
                self.tr(
                    "Danach in die Dachfläche klicken (Rechteck oder geschlossene Polylinie). "
                    "Rechtecke, Kreise und geschlossene Polylinien darin gelten als Hindernisse."
                )
            )
        )
        form.itemAt(form.rowCount() - 1, QFormLayout.ItemRole.SpanningRole).widget().setWordWrap(
            True
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def spec(self) -> ModuleSpec:
        width, height = sorted((self.width_spin.value(), self.height_spin.value()))
        return ModuleSpec(
            width=width,
            height=height,
            power=self.power_spin.value(),
            orientation=self.orientation.currentData(),
            gap=self.gap_spin.value(),
            edge=self.edge_spin.value(),
            obstacle_gap=self.obstacle_spin.value(),
            count=self.count_spin.value(),
        )
