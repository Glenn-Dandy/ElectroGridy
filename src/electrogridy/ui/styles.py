"""Shared choices for colours, line widths and line types in the UI."""

from PyQt6.QtCore import QCoreApplication, QRegularExpression, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap, QRegularExpressionValidator
from PyQt6.QtWidgets import QComboBox

from electrogridy.i18n import ui_locale
from electrogridy.model.layers import LINETYPES, LINEWEIGHTS

BY_LAYER = "__bylayer__"
MIXED = "__mixed__"
OTHER_COLOR = "__other__"


def tr(text: str) -> str:
    return QCoreApplication.translate("styles", text)


def standard_colors() -> list[tuple[str, str]]:
    return [
        (tr("Schwarz"), "#000000"),
        (tr("Rot"), "#e00000"),
        (tr("Orange"), "#f08000"),
        (tr("Grün"), "#008000"),
        (tr("Cyan"), "#00a0b0"),
        (tr("Blau"), "#0000e0"),
        (tr("Magenta"), "#c000c0"),
        (tr("Grau"), "#808080"),
    ]


def linetype_names() -> dict[str, str]:
    names = {
        "continuous": tr("durchgezogen"),
        "dashed": tr("gestrichelt"),
        "dashdot": tr("strichpunktiert"),
    }
    assert set(names) == set(LINETYPES)
    return names


def lineweight_label(value: float) -> str:
    return f"{ui_locale().toString(value, 'f', 2)} mm"


def lineweight_items() -> list[tuple[str, float]]:
    return [(lineweight_label(w), w) for w in LINEWEIGHTS]


def color_icon(color: str, size: int = 14) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def mm_label(value: float) -> str:
    """Short length like "2,5 mm" (German) or "2.5 mm" (English)."""
    text = f"{value:g}"
    return f"{text.replace('.', ui_locale().decimalPoint())} mm"


def parse_mm(text: str) -> float | None:
    """A typed length such as "3,5", "125 mm" or "2.5mm"; None if it is no positive number."""
    text = text.strip().lower().removesuffix("mm").strip().replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if 0 < value < 1e6 else None


class HeightCombo(QComboBox):
    """Text height: the usual sizes to pick, or any value typed in (e.g. 125 mm for a
    plan at 1:50). ``value_chosen`` fires when a new valid value is picked or typed."""

    value_chosen = pyqtSignal(float)

    def __init__(self, parent=None, presets=None) -> None:
        super().__init__(parent)
        from electrogridy.model.entities import TEXT_HEIGHTS

        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"\s*[0-9]*[.,]?[0-9]*\s*(mm)?\s*"))
        )
        for h in presets if presets is not None else TEXT_HEIGHTS:
            self.addItem(mm_label(h), h)
        self.setToolTip(tr("Auswählen oder eine beliebige Höhe in mm eintragen"))
        self._last: float | None = None
        self.activated.connect(lambda _i: self._commit())
        self.lineEdit().editingFinished.connect(self._commit)

    def set_height(self, value: object) -> None:
        """Show ``value`` (a number or MIXED) without firing ``value_chosen``."""
        if value == MIXED or value is None:
            self._last = None
            self.setCurrentIndex(-1)
            self.lineEdit().clear()
            self.lineEdit().setPlaceholderText(tr("*verschieden*"))
            return
        self._last = float(value)
        index = self.findData(float(value))
        if index >= 0:
            self.setCurrentIndex(index)
        self.setEditText(mm_label(float(value)))

    def height(self) -> float | None:
        return parse_mm(self.currentText())

    def _commit(self) -> None:
        value = self.height()
        if value is None:
            if self._last is not None:
                self.setEditText(mm_label(self._last))  # invalid input: back to the old value
            return
        self.setEditText(mm_label(value))
        if value != self._last:
            self._last = value
            self.value_chosen.emit(value)
