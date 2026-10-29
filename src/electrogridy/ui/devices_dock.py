"""Dock listing the devices (BMK) with every place they appear: circuit diagram, sheets,
pages of the multi-line diagram. Jump to a place, rename a BMK everywhere."""

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDockWidget,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from electrogridy.commands.entities import ReplaceEntitiesCommand
from electrogridy.model.devices import (
    MODEL,
    Occurrence,
    devices,
    page_reference,
    problems,
    renamed,
)

if TYPE_CHECKING:
    from electrogridy.ui.main_window import MainWindow

OCCURRENCE_ROLE = Qt.ItemDataRole.UserRole
BMK_ROLE = Qt.ItemDataRole.UserRole + 1
WARNING_COLOR = QColor("#c62828")


class DevicesDock(QDockWidget):
    def __init__(self, window: "MainWindow", parent=None) -> None:
        super().__init__(self.tr("Geräte"), parent)
        self.setObjectName("devices_dock")
        self.w = window
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("BMK suchen …"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.rebuild())
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([self.tr("BMK / Stelle"), self.tr("Block"), self.tr("Hinweis")])
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemActivated.connect(self._activate)
        self.tree.itemDoubleClicked.connect(self._activate)
        self.tree.customContextMenuRequested.connect(self._menu)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(self.search)
        layout.addWidget(self.tree)
        self.setWidget(body)
        self._pending = False
        self.visibilityChanged.connect(lambda visible: visible and self.rebuild())

    @property
    def doc(self):
        return self.w.document

    def problem_text(self, code: str) -> str:
        return {
            "main_twice": self.tr("Hauptfunktion mehrfach im Schaltplan (MLD)"),
            "sld_twice": self.tr("mehrfach im Schaltplan (SLD)"),
            "aux_alone": self.tr("Kontakte ohne Hauptfunktion"),
        }.get(code, code)

    def place_text(self, occ: Occurrence) -> str:
        if occ.where == MODEL:
            return self.tr("Modell")
        return page_reference(self.doc, occ)

    def function_text(self, occ: Occurrence) -> str:
        return {"main": self.tr("Hauptfunktion"), "aux": self.tr("Kontakt")}.get(occ.function, "")

    def schedule_rebuild(self) -> None:
        """Many changes in a row rebuild the list once, and only while it is shown."""
        if not self._pending and self.isVisible():
            self._pending = True
            QTimer.singleShot(0, self.rebuild)

    def rebuild(self) -> None:
        self._pending = False
        if not self.isVisible():
            return
        needle = self.search.text().strip().casefold()
        found = problems(self.doc)
        self.tree.clear()
        for bmk, group in devices(self.doc).items():
            if needle and needle not in bmk.casefold():
                continue
            blocks = sorted({o.block for o in group})
            notes = "; ".join(self.problem_text(c) for c in found.get(bmk, []))
            top = QTreeWidgetItem(self.tree, [bmk, ", ".join(blocks), notes])
            top.setData(0, BMK_ROLE, bmk)
            if notes:
                top.setForeground(2, WARNING_COLOR)
            for occ in group:
                child = QTreeWidgetItem(
                    top, [self.place_text(occ), occ.block, self.function_text(occ)]
                )
                child.setData(0, OCCURRENCE_ROLE, occ)
                child.setData(0, BMK_ROLE, bmk)
        self.tree.resizeColumnToContents(0)

    def _activate(self, item: QTreeWidgetItem) -> None:
        occ = item.data(0, OCCURRENCE_ROLE)
        if occ is None and item.childCount():
            occ = item.child(0).data(0, OCCURRENCE_ROLE)
        if occ is not None:
            self.w.go_to_occurrence(occ)

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        bmk = item.data(0, BMK_ROLE)
        menu = QMenu(self)
        menu.addAction(self.tr("Gehe zu"), lambda: self._activate(item))
        menu.addAction(self.tr("BMK umbenennen …"), lambda: self.rename(bmk))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def rename(self, bmk: str, new: str | None = None) -> bool:
        """Give every occurrence of ``bmk`` the new BMK, in one undo step."""
        if new is None:
            new, ok = QInputDialog.getText(
                self,
                self.tr("BMK umbenennen"),
                self.tr("Neues BMK für {bmk}:").format(bmk=bmk),
                text=bmk,
            )
            if not ok:
                return False
        new = new.strip()
        if not new or new == bmk:
            return False
        group = devices(self.doc).get(bmk, [])
        if new in devices(self.doc):
            answer = QMessageBox.question(
                self,
                self.tr("BMK umbenennen"),
                self.tr("{new} gibt es schon. Trotzdem umbenennen (dann ein Gerät)?").format(
                    new=new
                ),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        by_container: dict[int, tuple] = {}
        for occ in group:
            container = self._container(occ)
            entry = by_container.setdefault(id(container), (container, []))
            entry[1].append(renamed(container.get(occ.entity_id), new))
        self.w.begin_macro(self.tr("BMK {old} in {new} umbenennen").format(old=bmk, new=new))
        for container, changed in by_container.values():
            self.w.push(ReplaceEntitiesCommand(container, changed, ""))
        self.w.end_macro()
        self.rebuild()
        return True

    def _container(self, occ: Occurrence):
        if occ.where == MODEL:
            return self.doc.model_space
        return self.doc.sheet(occ.layout_id).entities
