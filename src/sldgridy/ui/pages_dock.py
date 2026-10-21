"""Dock with all pages of the project: number, type, description, plant and location."""

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDockWidget, QMenu, QTreeWidget, QTreeWidgetItem

from sldgridy.commands.sheets import MoveSheetCommand
from sldgridy.ui.page_dialog import kind_name

if TYPE_CHECKING:
    from sldgridy.ui.main_window import MainWindow

PAGE_ROLE = Qt.ItemDataRole.UserRole


class PagesDock(QDockWidget):
    def __init__(self, window: "MainWindow", parent=None) -> None:
        super().__init__(self.tr("Seiten"), parent)
        self.setObjectName("pages_dock")
        self.w = window
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(
            [self.tr("Nr."), self.tr("Seitentyp"), self.tr("Beschreibung"), self.tr("Anlage/Ort")]
        )
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemClicked.connect(self._open)
        self.tree.itemActivated.connect(self._open)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.setWidget(self.tree)

    @property
    def doc(self):
        return self.w.document

    def rebuild(self) -> None:
        current = self.w.sheets.current_sheet()
        self.tree.clear()
        for sheet in self.doc.sheets:
            where = " ".join(
                t
                for t in (
                    f"={sheet.plant}" if sheet.plant else "",
                    f"+{sheet.location}" if sheet.location else "",
                )
                if t
            )
            item = QTreeWidgetItem(
                self.tree,
                [
                    str(self.doc.page_number(sheet.id)),
                    kind_name(sheet.kind) if sheet.kind else "",
                    sheet.name,
                    where,
                ],
            )
            item.setData(0, PAGE_ROLE, sheet.id)
            if current is not None and current.id == sheet.id:
                self.tree.setCurrentItem(item)
        for column in range(3):
            self.tree.resizeColumnToContents(column)

    def select_page(self, page_id: str | None) -> None:
        """Mark the page that is shown (or nothing)."""
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if page_id is not None and item.data(0, PAGE_ROLE) == page_id:
                self.tree.setCurrentItem(item)
                return
        self.tree.setCurrentItem(None)

    def _open(self, item: QTreeWidgetItem) -> None:
        page_id = item.data(0, PAGE_ROLE)
        if page_id is not None:
            self.w.sheets.show_sheet(page_id)

    def _move(self, page_id: str, step: int) -> None:
        old = self.doc.sheet_index(page_id)
        new = old + step
        if 0 <= new < len(self.doc.sheets):
            self.w.push(MoveSheetCommand(self.doc, old, new, self.tr("Seite verschieben")))

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        page_id = item.data(0, PAGE_ROLE) if item is not None else None
        sheets = self.w.sheets
        menu = QMenu(self)
        if page_id is not None:
            sheets.show_sheet(page_id)
        menu.addAction(sheets.act_new)
        if page_id is not None:
            menu.addAction(sheets.act_rename)
            menu.addAction(sheets.act_duplicate)
            menu.addSeparator()
            menu.addAction(self.tr("Nach &oben"), lambda: self._move(page_id, -1))
            menu.addAction(self.tr("Nach &unten"), lambda: self._move(page_id, 1))
            menu.addSeparator()
            menu.addAction(sheets.act_delete)
        menu.exec(self.tree.viewport().mapToGlobal(pos))
