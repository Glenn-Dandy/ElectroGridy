"""Dock showing and editing properties of the selected entities."""

from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QColor, QUndoCommand
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sldgridy.commands.entities import ReplaceEntitiesCommand
from sldgridy.model.container import EntityContainer
from sldgridy.model.document import Document
from sldgridy.model.entities import (
    Arc,
    Circle,
    Dimension,
    Entity,
    Line,
    Polyline,
    RasterImage,
    Rectangle,
    Text,
)
from sldgridy.ui.styles import (
    BY_LAYER,
    MIXED,
    OTHER_COLOR,
    HeightCombo,
    color_icon,
    linetype_names,
    lineweight_items,
    standard_colors,
)


def tr(text: str) -> str:
    return QCoreApplication.translate("PropertiesDock", text)


def type_names() -> dict[type, str]:
    return {
        Line: tr("Linie"),
        Polyline: tr("Polylinie"),
        Rectangle: tr("Rechteck"),
        RasterImage: tr("Bild"),
        Circle: tr("Kreis"),
        Arc: tr("Bogen"),
        Text: tr("Text"),
        Dimension: tr("Bemaßung"),
    }


class PropertyHost(Protocol):
    document: Document

    @property
    def container(self) -> EntityContainer: ...

    def selected_ids(self) -> list[str]: ...

    def push(self, command: QUndoCommand) -> None: ...


def _common(values: list) -> object:
    first = values[0]
    return first if all(v == first for v in values) else MIXED


class PropertiesDock(QDockWidget):
    def __init__(self, host: PropertyHost, parent=None) -> None:
        super().__init__(self.tr("Eigenschaften"), parent)
        self.setObjectName("dock_properties")
        self._host = host
        self._updating = False
        self._entities: list[Entity] = []
        # Extra describers for entity types added later (blocks, wires).
        self.extra_type_names: dict[type, str] = {}

        self.lbl_selection = QLabel()
        self.lbl_selection.setWordWrap(True)
        self.cmb_layer = QComboBox()
        self.cmb_color = QComboBox()
        self.cmb_weight = QComboBox()
        self.cmb_type = QComboBox()
        self.txt_text = QPlainTextEdit()
        self.txt_text.setMaximumHeight(90)
        self.btn_apply_text = QPushButton(self.tr("Text übernehmen"))
        self.cmb_height = HeightCombo()

        self.cmb_layer.activated.connect(lambda _i: self._apply_combo(self.cmb_layer, "layer"))
        self.cmb_color.activated.connect(self._on_color)
        self.cmb_weight.activated.connect(
            lambda _i: self._apply_combo(self.cmb_weight, "lineweight")
        )
        self.cmb_type.activated.connect(lambda _i: self._apply_combo(self.cmb_type, "linetype"))
        self.cmb_height.value_chosen.connect(self._apply_height)
        self.btn_apply_text.clicked.connect(self._apply_text)

        self.form = QFormLayout()
        self.form.addRow(self.tr("Ebene:"), self.cmb_layer)
        self.form.addRow(self.tr("Farbe:"), self.cmb_color)
        self.form.addRow(self.tr("Linienbreite:"), self.cmb_weight)
        self.form.addRow(self.tr("Linienart:"), self.cmb_type)
        self.form.addRow(self.tr("Text:"), self.txt_text)
        self.form.addRow("", self.btn_apply_text)
        self.form.addRow(self.tr("Texthöhe:"), self.cmb_height)

        # Area for type specific editors (block attributes).
        self.extra_area = QVBoxLayout()

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.lbl_selection)
        layout.addLayout(self.form)
        layout.addLayout(self.extra_area)
        layout.addStretch(1)
        self.setWidget(widget)
        # Type specific editors, each called with the selection and a layout to fill.
        self.extra_editors: list[Callable[[list[Entity], QVBoxLayout], None]] = []
        self.refresh()

    # -- refresh ------------------------------------------------------------

    def refresh(self) -> None:
        container = self._host.container
        self._entities = [container.get(i) for i in self._host.selected_ids() if i in container]
        self._updating = True
        try:
            self._refresh()
        finally:
            self._updating = False

    def _set_row_visible(self, widget: QWidget, visible: bool) -> None:
        self.form.setRowVisible(widget, visible)

    def _refresh(self) -> None:
        entities = self._entities
        names = {**type_names(), **self.extra_type_names}
        if not entities:
            self.lbl_selection.setText(self.tr("Keine Auswahl"))
        else:
            counts = Counter(names.get(type(e), type(e).__name__) for e in entities)
            parts = ", ".join(f"{name} ({n})" for name, n in sorted(counts.items()))
            self.lbl_selection.setText(
                self.tr("{n} Objekte: {parts}").format(n=len(entities), parts=parts)
            )
        has = bool(entities)
        for w in (self.cmb_layer, self.cmb_color, self.cmb_weight, self.cmb_type):
            self._set_row_visible(w, has)
        texts = [e for e in entities if isinstance(e, Text)]
        all_text = has and len(texts) == len(entities)
        self._set_row_visible(self.txt_text, all_text and len(texts) == 1)
        self._set_row_visible(self.btn_apply_text, all_text and len(texts) == 1)
        self._set_row_visible(self.cmb_height, all_text)
        if has:
            self._fill_layer(_common([e.layer for e in entities]))
            self._fill_color(_common([e.color or BY_LAYER for e in entities]))
            self._fill_weight(_common([e.lineweight or BY_LAYER for e in entities]))
            self._fill_type(_common([e.linetype or BY_LAYER for e in entities]))
        if all_text:
            if len(texts) == 1:
                self.txt_text.setPlainText(texts[0].text)
            self.cmb_height.set_height(_common([t.height for t in texts]))
        while self.extra_area.count():
            item = self.extra_area.takeAt(0)
            if item.widget():
                item.widget().hide()  # gone at once, not only after the deferred delete
                item.widget().deleteLater()
        if has:
            for editor in self.extra_editors:
                editor(entities, self.extra_area)

    def _add_mixed(self, combo: QComboBox, value: object) -> None:
        if value == MIXED:
            combo.insertItem(0, self.tr("*verschieden*"), MIXED)
            combo.setCurrentIndex(0)

    def _select(self, combo: QComboBox, value: object) -> None:
        self._add_mixed(combo, value)
        if value != MIXED:
            combo.setCurrentIndex(max(combo.findData(value), 0))

    def _fill_simple(self, combo: QComboBox, value: object) -> None:
        index = combo.findData(MIXED)
        if index >= 0:
            combo.removeItem(index)
        self._select(combo, value)

    def _fill_layer(self, value: object) -> None:
        self.cmb_layer.clear()
        workspace = getattr(self._host, "workspace", "")
        for layer in self._host.document.layers:
            if layer.in_workspace(workspace) or layer.name == value:
                self.cmb_layer.addItem(color_icon(layer.color), layer.name, layer.name)
        self._select(self.cmb_layer, value)

    def _fill_color(self, value: object) -> None:
        c = self.cmb_color
        c.clear()
        c.addItem(self.tr("VonEbene"), BY_LAYER)
        for name, hex_color in standard_colors():
            c.addItem(color_icon(hex_color), name, hex_color)
        if value not in (MIXED, BY_LAYER) and c.findData(value) < 0:
            c.addItem(color_icon(str(value)), str(value), value)
        c.addItem(self.tr("Andere …"), OTHER_COLOR)
        self._select(c, value)

    def _fill_weight(self, value: object) -> None:
        c = self.cmb_weight
        c.clear()
        c.addItem(self.tr("VonEbene"), BY_LAYER)
        for label, w in lineweight_items():
            c.addItem(label, w)
        self._select(c, value)

    def _fill_type(self, value: object) -> None:
        c = self.cmb_type
        c.clear()
        c.addItem(self.tr("VonEbene"), BY_LAYER)
        for key, label in linetype_names().items():
            c.addItem(label, key)
        self._select(c, value)

    # -- apply --------------------------------------------------------------

    def _push(self, changed: list[Entity], text: str) -> None:
        changed = [n for n, o in zip(changed, self._entities, strict=True) if n != o]
        if changed:
            self._host.push(ReplaceEntitiesCommand(self._host.container, changed, text))

    def _apply_combo(self, combo: QComboBox, field: str) -> None:
        if self._updating:
            return
        value = combo.currentData()
        if value == MIXED:
            return
        if value == BY_LAYER:
            value = None
        if field == "height":
            new = [replace(e, height=value) if isinstance(e, Text) else e for e in self._entities]
        else:
            new = [replace(e, **{field: value}) for e in self._entities]
        self._push(new, self.tr("Eigenschaften ändern"))

    def _apply_height(self, value: float) -> None:
        if self._updating:
            return
        new = [replace(e, height=value) if isinstance(e, Text) else e for e in self._entities]
        self._push(new, self.tr("Eigenschaften ändern"))

    def _on_color(self, _index: int) -> None:
        if self._updating:
            return
        if self.cmb_color.currentData() == OTHER_COLOR:
            color = QColorDialog.getColor(QColor("#000000"), self, self.tr("Farbe"))
            if not color.isValid():
                self.refresh()
                return
            new = [replace(e, color=color.name()) for e in self._entities]
            self._push(new, self.tr("Eigenschaften ändern"))
            return
        self._apply_combo(self.cmb_color, "color")

    def _apply_text(self) -> None:
        if len(self._entities) != 1 or not isinstance(self._entities[0], Text):
            return
        content = self.txt_text.toPlainText()
        if content.strip():
            self._push([replace(self._entities[0], text=content)], self.tr("Text ändern"))
