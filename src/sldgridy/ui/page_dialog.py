"""Dialog for a page of the project: type, description, plant, location, format."""

from dataclasses import dataclass

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
)

from sldgridy.model.document import (
    CIRCUIT,
    DRAWING,
    ENCLOSURE,
    GENERATED_KINDS,
    OVERVIEW,
    PAGE_FORMAT,
    PAGE_KINDS,
)
from sldgridy.model.paper import PAPER_FORMATS, Orientation

# Page types that usually show the model through a viewport.
VIEWPORT_KINDS = (OVERVIEW, DRAWING)


@dataclass(frozen=True)
class PageSpec:
    kind: str
    name: str
    plant: str
    location: str
    paper: str
    orientation: Orientation
    viewport: bool
    scale: float = 1.0  # paper mm per real mm (0.2 = 1:5)


def kind_name(kind: str) -> str:
    return QCoreApplication.translate("pages", PAGE_KINDS.get(kind, kind))


def _editable_combo(current: str, choices: list[str]) -> QComboBox:
    box = QComboBox()
    box.setEditable(True)
    box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    box.addItems(choices)
    box.setCurrentText(current)
    return box


class PageDialog(QDialog):
    def __init__(
        self,
        title: str,
        spec: PageSpec,
        plants: list[str],
        locations: list[str],
        new: bool = True,
        parent=None,
        kinds: list[str] | None = None,
        viewport: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.kind = QComboBox()
        for kind in kinds or PAGE_KINDS:
            self.kind.addItem(kind_name(kind), kind)
        self.kind.setCurrentIndex(max(self.kind.findData(spec.kind or DRAWING), 0))
        self.name = QLineEdit(spec.name)
        self.name.setPlaceholderText(self.tr("z. B. Einspeisung, Steuerung Wechselrichter"))
        self.plant = _editable_combo(spec.plant, plants)
        self.plant.setToolTip(self.tr("Anlage, z. B. PV1 (wird als =PV1 geschrieben)"))
        self.location = _editable_combo(spec.location, locations)
        self.location.setToolTip(self.tr("Einbauort, z. B. UV1 (wird als +UV1 geschrieben)"))
        self.paper = QComboBox()
        for paper in PAPER_FORMATS:
            self.paper.addItem(paper, paper)
        self.paper.setCurrentIndex(max(self.paper.findData(spec.paper), 0))
        self.orientation = QComboBox()
        self.orientation.addItem(self.tr("quer"), Orientation.LANDSCAPE)
        self.orientation.addItem(self.tr("hoch"), Orientation.PORTRAIT)
        self.orientation.setCurrentIndex(0 if spec.orientation is Orientation.LANDSCAPE else 1)
        from sldgridy.ui.sheet_controller import format_scale

        self.scale = QComboBox()
        self.scale.setEditable(True)
        self.scale.addItems(["1:1", "1:2", "1:5", "1:10", "1:20", "1:50"])
        self.scale.setCurrentText(format_scale(spec.scale))
        self.scale.setToolTip(
            self.tr(
                "Zeichnungsmaßstab der Seite, z. B. 1:5 für den Gehäuseaufbau: Symbole werden "
                "verkleinert eingefügt, getippte Längen und Bemaßungen sind echte Millimeter."
            )
        )
        self.viewport = QCheckBox(self.tr("Modell zeigen (Ansichtsfenster)"))
        self.viewport.setChecked(spec.viewport)
        self._viewport_offered = viewport
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        form = QFormLayout(self)
        form.addRow(self.tr("Seitentyp:"), self.kind)
        form.addRow(self.tr("Beschreibung:"), self.name)
        form.addRow(self.tr("Anlage (=):"), self.plant)
        form.addRow(self.tr("Ort (+):"), self.location)
        form.addRow(self.tr("Maßstab:"), self.scale)
        if new:
            form.addRow(self.tr("Format:"), self.paper)
            form.addRow(self.tr("Ausrichtung:"), self.orientation)
            if viewport:
                form.addRow(self.viewport)
        form.addRow(self.hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._new = new
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed(adjust=False)
        self.resize(max(self.sizeHint().width(), 420), self.sizeHint().height())

    def _kind_changed(self, _index: int = 0, adjust: bool = True) -> None:
        kind = self.kind.currentData()
        if kind in GENERATED_KINDS:
            self.hint.setText(
                self.tr("Der Inhalt dieser Seite entsteht aus dem Projekt und bleibt aktuell.")
            )
        elif kind in (CIRCUIT, ENCLOSURE) or not self._viewport_offered:
            self.hint.setText(self.tr("Auf dieser Seite wird direkt gezeichnet."))
        else:
            self.hint.setText(
                self.tr("Direkt zeichnen oder das Modell über ein Ansichtsfenster zeigen.")
            )
        if adjust and self._new:
            self.viewport.setChecked(kind in VIEWPORT_KINDS and self._viewport_offered)
            if kind != DRAWING and self.paper.currentData() == "A0":
                self.paper.setCurrentIndex(self.paper.findData(PAGE_FORMAT))
        self.viewport.setEnabled(kind not in GENERATED_KINDS)

    @staticmethod
    def _clean(text: str, prefix: str) -> str:
        """ "=PV1", " PV1 " and "PV1" all mean PV1."""
        return text.strip().removeprefix(prefix).strip()

    def spec(self) -> PageSpec:
        kind = self.kind.currentData()
        return PageSpec(
            kind=kind,
            name=self.name.text().strip(),
            plant=self._clean(self.plant.currentText(), "="),
            location=self._clean(self.location.currentText(), "+"),
            paper=self.paper.currentData(),
            orientation=self.orientation.currentData(),
            viewport=self._viewport_offered
            and self.viewport.isChecked()
            and kind not in GENERATED_KINDS,
            scale=self.scale_value(),
        )

    def scale_value(self) -> float:
        from sldgridy.ui.sheet_controller import parse_scale

        return parse_scale(self.scale.currentText()) or 1.0
