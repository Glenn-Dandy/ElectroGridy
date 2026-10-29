"""Dock listing the layers of the drawing."""

from dataclasses import replace
from typing import Protocol

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QUndoCommand
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from electrogridy.commands.layers import AddLayerCommand, ChangeLayerCommand, RemoveLayerCommand
from electrogridy.model.document import Document
from electrogridy.model.layers import DEFAULT_LAYER, Layer
from electrogridy.ui.styles import color_icon, linetype_names, lineweight_items

COL_CURRENT, COL_NAME, COL_VISIBLE, COL_LOCKED, COL_PRINT, COL_COLOR, COL_WEIGHT, COL_TYPE = range(
    8
)


class LayerHost(Protocol):
    document: Document
    current_layer: str

    def push(self, command: QUndoCommand) -> None: ...

    def message(self, text: str) -> None: ...

    def set_current_layer(self, name: str) -> None: ...


class LayersDock(QDockWidget):
    current_changed = pyqtSignal(str)

    def __init__(self, host: LayerHost, parent=None) -> None:
        super().__init__(self.tr("Ebenen"), parent)
        self.setObjectName("dock_layers")
        self._host = host
        self._rows: list[Layer] = []
        self._updating = False

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "",
                self.tr("Name"),
                self.tr("Sicht"),
                self.tr("Sperre"),
                self.tr("Druck"),
                self.tr("Farbe"),
                self.tr("Breite"),
                self.tr("Art"),
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellDoubleClicked.connect(self._on_double_click)

        self.btn_new = QPushButton(self.tr("Neu"))
        self.btn_delete = QPushButton(self.tr("Löschen"))
        self.btn_current = QPushButton(self.tr("Aktuell setzen"))
        self.btn_new.clicked.connect(self.add_layer)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.btn_current.clicked.connect(self._set_selected_current)

        buttons = QHBoxLayout()
        for b in (self.btn_new, self.btn_delete, self.btn_current):
            buttons.addWidget(b)
        buttons.addStretch(1)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        self.setWidget(widget)
        self.rebuild()

    # -- building -----------------------------------------------------------

    def _check_item(self, checked: bool) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item

    def _workspace(self) -> str:
        return getattr(self._host, "workspace", "")

    def rebuild(self) -> None:
        self._updating = True
        try:
            # Only the layers of the current workspace (plus layer 0) are listed.
            layers = [
                layer
                for layer in self._host.document.layers
                if layer.in_workspace(self._workspace())
            ]
            self._rows = layers
            self.table.setRowCount(len(layers))
            for row, layer in enumerate(layers):
                self._fill_row(row, layer)
        finally:
            self._updating = False

    def _fill_row(self, row: int, layer: Layer) -> None:
        current = QTableWidgetItem("✓" if layer.name == self._host.current_layer else "")
        current.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        current.setToolTip(self.tr("Doppelklick setzt die aktuelle Ebene"))
        self.table.setItem(row, COL_CURRENT, current)

        name = QTableWidgetItem(layer.name)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if layer.name != DEFAULT_LAYER:
            flags |= Qt.ItemFlag.ItemIsEditable
        name.setFlags(flags)
        self.table.setItem(row, COL_NAME, name)

        self.table.setItem(row, COL_VISIBLE, self._check_item(layer.visible))
        self.table.setItem(row, COL_LOCKED, self._check_item(layer.locked))
        self.table.setItem(row, COL_PRINT, self._check_item(layer.printable))

        color = QToolButton()
        color.setIcon(color_icon(layer.color))
        color.setToolTip(layer.color)
        color.clicked.connect(lambda _=False, n=layer.name: self._pick_color(n))
        self.table.setCellWidget(row, COL_COLOR, color)

        weight = QComboBox()
        for label, value in lineweight_items():
            weight.addItem(label, value)
        weight.setCurrentIndex(max(weight.findData(layer.lineweight), 0))
        weight.currentIndexChanged.connect(
            lambda _i, n=layer.name, w=weight: self._change(n, lineweight=w.currentData())
        )
        self.table.setCellWidget(row, COL_WEIGHT, weight)

        ltype = QComboBox()
        for key, label in linetype_names().items():
            ltype.addItem(label, key)
        ltype.setCurrentIndex(max(ltype.findData(layer.linetype), 0))
        ltype.currentIndexChanged.connect(
            lambda _i, n=layer.name, c=ltype: self._change(n, linetype=c.currentData())
        )
        self.table.setCellWidget(row, COL_TYPE, ltype)

    # -- changes ------------------------------------------------------------

    def _layer(self, name: str) -> Layer:
        return self._host.document.layer(name)

    def _change(self, layer_name: str, **changes) -> None:
        if self._updating:
            return
        old = self._layer(layer_name)
        new = replace(old, **changes)
        if new != old:
            self._host.push(
                ChangeLayerCommand(self._host.document, layer_name, new, self.tr("Ebene ändern"))
            )

    def _pick_color(self, name: str) -> None:
        color = QColorDialog.getColor(QColor(self._layer(name).color), self, self.tr("Farbe"))
        if color.isValid():
            self._change(name, color=color.name())

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating:
            return
        row, col = item.row(), item.column()
        layer = self._rows[row]
        checked = item.checkState() == Qt.CheckState.Checked
        if col == COL_VISIBLE:
            self._change(layer.name, visible=checked)
        elif col == COL_LOCKED:
            self._change(layer.name, locked=checked)
        elif col == COL_PRINT:
            self._change(layer.name, printable=checked)
        elif col == COL_NAME:
            new_name = item.text().strip()
            if not new_name or new_name == layer.name:
                self.rebuild()
                return
            if self._host.document.has_layer(new_name):
                self._host.message(
                    self.tr("Eine Ebene „{name}“ gibt es schon").format(name=new_name)
                )
                self.rebuild()
                return
            was_current = self._host.current_layer == layer.name
            self._change(layer.name, name=new_name)
            if was_current:
                self._host.set_current_layer(new_name)

    def _selected_name(self) -> str | None:
        row = self.table.currentRow()
        return self._rows[row].name if 0 <= row < len(self._rows) else None

    def _on_double_click(self, row: int, col: int) -> None:
        if col != COL_NAME:
            self._host.set_current_layer(self._rows[row].name)

    def _set_selected_current(self) -> None:
        name = self._selected_name()
        if name is not None:
            self._host.set_current_layer(name)

    def add_layer(self) -> None:
        doc = self._host.document
        n = 1
        while doc.has_layer(self.tr("Ebene {n}").format(n=n)):
            n += 1
        layer = Layer(self.tr("Ebene {n}").format(n=n), workspace=self._workspace())
        self._host.push(AddLayerCommand(doc, layer, self.tr("Ebene anlegen")))
        self.table.selectRow(len(self._rows) - 1)

    def delete_selected(self) -> None:
        name = self._selected_name()
        if name is None:
            return
        doc = self._host.document
        if name == DEFAULT_LAYER:
            self._host.message(self.tr("Ebene 0 kann nicht gelöscht werden"))
        elif name == self._host.current_layer:
            self._host.message(self.tr("Die aktuelle Ebene kann nicht gelöscht werden"))
        elif doc.layer_in_use(name):
            self._host.message(self.tr("Die Ebene enthält noch Objekte"))
        else:
            self._host.push(RemoveLayerCommand(doc, name, self.tr("Ebene löschen")))
