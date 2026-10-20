"""Dock with the pages of the multi-line circuit diagram as a tree: plant, location, page."""

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDockWidget,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
)

from sldgridy.commands.sheets import MoveSheetCommand
from sldgridy.model.document import PAGES

if TYPE_CHECKING:
    from sldgridy.ui.main_window import MainWindow

PAGE_ROLE = Qt.ItemDataRole.UserRole


class PagesDock(QDockWidget):
    def __init__(self, window: "MainWindow", parent=None) -> None:
        super().__init__(self.tr("Seiten"), parent)
        self.setObjectName("pages_dock")
        self.w = window
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
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
        groups: dict[str, QTreeWidgetItem] = {}
        selected = None
        for page in self.doc.pages:
            parent = self.tree.invisibleRootItem()
            if page.plant:
                key = f"={page.plant}"
                if key not in groups:
                    groups[key] = QTreeWidgetItem(parent, [key])
                parent = groups[key]
            if page.location:
                key = f"={page.plant}+{page.location}"
                if key not in groups:
                    groups[key] = QTreeWidgetItem(parent, [f"+{page.location}"])
                parent = groups[key]
            number = self.doc.page_number(page.id)[0]
            item = QTreeWidgetItem(parent, [f"/{number}  {page.name}".rstrip()])
            item.setData(0, PAGE_ROLE, page.id)
            item.setToolTip(0, self.doc.page_label(page.id))
            if current is not None and current.id == page.id:
                selected = item
        self.tree.expandAll()
        if selected is not None:
            self.tree.setCurrentItem(selected)

    def select_page(self, page_id: str | None) -> None:
        """Mark the page that is shown (or nothing)."""
        it = QTreeWidgetItemIterator(self.tree)
        while it.value() is not None:
            item = it.value()
            if item.data(0, PAGE_ROLE) == page_id and page_id is not None:
                self.tree.setCurrentItem(item)
                return
            it += 1
        self.tree.setCurrentItem(None)

    def _open(self, item: QTreeWidgetItem) -> None:
        page_id = item.data(0, PAGE_ROLE)
        if page_id is not None:
            self.w.sheets.show_sheet(page_id)

    def _move(self, page_id: str, step: int) -> None:
        """Up or down within the page's plant and location."""
        page = self.doc.page(page_id)
        group = [p.id for p in self.doc.page_group(page)]
        pos = group.index(page_id) + step
        if not 0 <= pos < len(group):
            return
        old = self.doc.page_index(page_id)
        new = self.doc.page_index(group[pos])
        self.w.push(MoveSheetCommand(self.doc, old, new, self.tr("Seite verschieben"), kind=PAGES))

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
