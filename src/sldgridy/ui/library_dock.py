"""Dock with block previews from the drawing and from library files."""

import json
from pathlib import Path
from typing import Protocol

from PyQt6.QtCore import QMimeData, QPoint, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from sldgridy.fileio.files import LIBRARY_SUFFIX, library_workspace, load_library
from sldgridy.fileio.json_format import FileFormatError
from sldgridy.fileio.paths import system_library_dir, user_library_dir
from sldgridy.i18n import library_text
from sldgridy.model.blocks import BlockDefinition
from sldgridy.model.document import DOC_DRAWING, DOC_PROJECT, DOC_SLD, Document
from sldgridy.view.canvas import BLOCK_MIME
from sldgridy.view.thumbnails import block_icon

DOCUMENT_SOURCE = ""
ALL_LIBRARIES = "*"
ALL_CATEGORIES = "*"
ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_NAME = Qt.ItemDataRole.UserRole + 1
ROLE_CATEGORY = Qt.ItemDataRole.UserRole + 3


class LibraryHost(Protocol):
    document: Document

    def message(self, text: str) -> None: ...


class _BlockList(QListWidget):
    def startDrag(self, supported_actions) -> None:
        """Drag without a picture at the cursor: the drawing shows the block itself, and a
        picture would hide the crosshair and the target point."""
        items = self.selectedItems() or [self.currentItem()]
        if items[0] is None:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items[:1]))
        pixmap = QPixmap(1, 1)
        pixmap.fill(Qt.GlobalColor.transparent)
        drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.CopyAction)

    def mimeTypes(self) -> list[str]:
        return [BLOCK_MIME]

    def mimeData(self, items) -> QMimeData:
        data = QMimeData()
        if items:
            item = items[0]
            payload = {"path": item.data(ROLE_PATH), "name": item.data(ROLE_NAME)}
            data.setData(BLOCK_MIME, json.dumps(payload).encode("utf-8"))
        return data


class Library:
    def __init__(
        self,
        path: Path,
        title: str,
        blocks: dict[str, BlockDefinition],
        shipped: bool,
        workspace: str = "",
    ):
        self.path = path
        self.title = title
        self.blocks = blocks
        self.shipped = shipped
        # Workspace the library is meant for; empty: shown in every workspace.
        self.workspace = workspace


SLD, MLD, DRAWING_LIBRARY = "sld", "mld", "drawing"
# Libraries (by their "workspace") offered for each document kind.
KIND_LIBRARIES = {
    DOC_SLD: (SLD,),
    DOC_PROJECT: (SLD, MLD),
    DOC_DRAWING: (DRAWING_LIBRARY,),
}
_GROUP_ORDER = {SLD: 0, MLD: 1, DRAWING_LIBRARY: 2}


def library_files() -> list[tuple[Path, bool]]:
    """(path, shipped) of all library files, shipped ones first."""
    result: list[tuple[Path, bool]] = []
    for directory, shipped in ((system_library_dir(), True), (user_library_dir(), False)):
        if directory.is_dir():
            result += [(p, shipped) for p in sorted(directory.glob(f"*{LIBRARY_SUFFIX}"))]
    return result


class LibraryDock(QDockWidget):
    # (source path, block name); an empty path means the drawing itself.
    insert_requested = pyqtSignal(str, str)
    edit_requested = pyqtSignal(str, str)
    editor_requested = pyqtSignal(str, str)
    delete_requested = pyqtSignal(str, str)
    # Name of a block of the drawing.
    save_requested = pyqtSignal(str)

    def __init__(self, host: LibraryHost, parent=None) -> None:
        super().__init__(self.tr("Bibliothek"), parent)
        self.setObjectName("dock_library")
        self._host = host
        self.libraries: dict[str, Library] = {}
        self.kind = DOC_SLD
        self._preferred = ""
        self._icons: dict[tuple[str, str], object] = {}

        self.source = QComboBox()
        self.category = QComboBox()
        self.category.setToolTip(self.tr("Kategorie"))
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Suchen …"))
        self.search.setClearButtonEnabled(True)
        self.btn_reload = QToolButton()
        self.btn_reload.setText("↻")
        self.btn_reload.setToolTip(self.tr("Bibliotheken neu laden"))
        self.list = _BlockList()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(56, 56))
        self.list.setGridSize(QSize(96, 92))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setWordWrap(True)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QListWidget.DragDropMode.DragOnly)

        self.source.currentIndexChanged.connect(lambda _i: self._fill())
        self.category.currentIndexChanged.connect(lambda _i: self._apply_filter(self.search.text()))
        self.search.textChanged.connect(self._apply_filter)
        self.btn_reload.clicked.connect(self.reload)
        self.list.itemDoubleClicked.connect(self._on_double_click)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)

        top = QHBoxLayout()
        top.addWidget(self.source, 1)
        top.addWidget(self.btn_reload)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top)
        layout.addWidget(self.category)
        layout.addWidget(self.search)
        layout.addWidget(self.list)
        self.setWidget(widget)
        self.reload()

    # -- data ---------------------------------------------------------------

    def library(self, path: str) -> dict[str, BlockDefinition]:
        if path == DOCUMENT_SOURCE:
            return self._host.document.blocks
        lib = self.libraries.get(path)
        return lib.blocks if lib else {}

    def reload(self) -> None:
        self.libraries.clear()
        self._icons.clear()
        for path, shipped in library_files():
            try:
                title, blocks = load_library(path)
            except (OSError, FileFormatError) as exc:
                self._host.message(
                    self.tr("Bibliothek {name} ist fehlerhaft: {error}").format(
                        name=path.name, error=exc
                    )
                )
                continue
            self.libraries[str(path)] = Library(
                path,
                title or path.stem,
                {b.name: b for b in blocks},
                shipped,
                library_workspace(path),
            )
        self._fill_sources()

    def visible_libraries(self) -> dict[str, Library]:
        """Libraries for the kind of the open file (and those for every kind), the
        overview diagram ones (SLD) before the circuit diagram ones (MLD)."""
        shown = [
            (key, lib)
            for key, lib in self.libraries.items()
            if not lib.workspace or lib.workspace in KIND_LIBRARIES.get(self.kind, ())
        ]
        shown.sort(key=lambda kv: _GROUP_ORDER.get(kv[1].workspace, len(_GROUP_ORDER)))
        return dict(shown)

    def set_kind(self, kind: str) -> None:
        """Document kind: "sld", "project" or "drawing"."""
        if kind == self.kind:
            return
        self.kind = kind
        # A project starts with the circuit diagram symbols.
        self._preferred = MLD if kind == DOC_PROJECT else ""
        self._fill_sources()

    def _group(self, path: str) -> str:
        """ "SLD" or "MLD" when both kinds of symbols are listed, else empty."""
        lib = self.libraries.get(path)
        if lib is None or self.kind != DOC_PROJECT:
            return ""
        return {SLD: "SLD", MLD: "MLD"}.get(lib.workspace, "")

    def _fill_sources(self) -> None:
        current = self.source.currentData()
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem(self.tr("Alle Bibliotheken"), ALL_LIBRARIES)
        self.source.addItem(self.tr("Blöcke der Zeichnung"), DOCUMENT_SOURCE)
        for key, lib in self.visible_libraries().items():
            self.source.addItem(library_text(lib.title), key)
        index = self.source.findData(current) if current is not None else 0
        if self._preferred:
            preferred = [
                k for k, lib in self.visible_libraries().items() if lib.workspace == self._preferred
            ]
            index = self.source.findData(preferred[0]) if preferred else index
            self._preferred = ""
        self.source.setCurrentIndex(max(index, 0))
        self.source.blockSignals(False)
        self._fill()

    def refresh_icons(self) -> None:
        """Preview images again, e.g. after switching to dark mode (they use its colours)."""
        self._icons.clear()
        self._fill()

    def refresh_document(self) -> None:
        for key in [k for k in self._icons if k[0] == DOCUMENT_SOURCE]:
            del self._icons[key]
        if self.source.currentData() == DOCUMENT_SOURCE:
            self._fill()

    # -- list ---------------------------------------------------------------

    def _entries(self) -> list[tuple[str, BlockDefinition]]:
        source = self.source.currentData()
        if source == DOCUMENT_SOURCE:
            return [(DOCUMENT_SOURCE, b) for b in self._host.document.blocks.values()]
        visible = self.visible_libraries()
        if source == ALL_LIBRARIES:
            libs = list(visible.values())
        else:
            libs = [visible[source]] if source in visible else []
        return [(str(lib.path), b) for lib in libs for b in lib.blocks.values()]

    def _fill_categories(self, entries: list[tuple[str, BlockDefinition]]) -> None:
        current = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem(self.tr("Alle Kategorien"), ALL_CATEGORIES)
        keys = {(self._group(p), d.category) for p, d in entries if d.category}
        for group, name in sorted(keys, key=lambda k: (k[0] != "SLD", k[0], k[1].casefold())):
            text = library_text(name)
            self.category.addItem(f"{group}: {text}" if group else text, f"{group}|{name}")
        if any(not d.category for _, d in entries):
            self.category.addItem(self.tr("Ohne Kategorie"), "|")
        index = self.category.findData(current) if current is not None else 0
        self.category.setCurrentIndex(max(index, 0))
        self.category.blockSignals(False)

    def _fill(self) -> None:
        self.list.clear()
        entries = sorted(
            self._entries(),
            key=lambda e: (self._group(e[0]) != "SLD", e[1].category, e[1].name.casefold()),
        )
        self._fill_categories(entries)
        for path, definition in entries:
            key = (path, definition.name)
            if key not in self._icons:
                self._icons[key] = block_icon(definition.name, self.library(path))
            item = QListWidgetItem(self._icons[key], library_text(definition.name))
            item.setData(ROLE_PATH, path)
            item.setData(ROLE_NAME, definition.name)
            tip = library_text(definition.name)
            if definition.category:
                tip += f"\n{library_text(definition.category)}"
            if definition.description:
                tip += f"\n{library_text(definition.description)}"
            item.setToolTip(tip)
            item.setData(Qt.ItemDataRole.UserRole + 2, tip.casefold())
            item.setData(ROLE_CATEGORY, f"{self._group(path)}|{definition.category}")
            self.list.addItem(item)
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold().strip()
        category = self.category.currentData()
        for i in range(self.list.count()):
            item = self.list.item(i)
            haystack = item.data(Qt.ItemDataRole.UserRole + 2) or ""
            hidden = bool(needle) and needle not in haystack
            if category not in (None, ALL_CATEGORIES):
                own = item.data(ROLE_CATEGORY) or "|"
                if category == "|":  # without a category, in any group
                    hidden = hidden or bool(own.partition("|")[2])
                else:
                    hidden = hidden or own != category
            item.setHidden(hidden)

    def _on_double_click(self, item: QListWidgetItem) -> None:
        self.insert_requested.emit(item.data(ROLE_PATH), item.data(ROLE_NAME))

    def editable(self, path: str) -> bool:
        """Blocks of the drawing and of user libraries can be changed, shipped ones not."""
        if path == DOCUMENT_SOURCE:
            return True
        lib = self.libraries.get(path)
        return lib is not None and not lib.shipped

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        path, name = item.data(ROLE_PATH), item.data(ROLE_NAME)
        menu = QMenu(self)
        menu.addAction(self.tr("Einfügen"), lambda: self.insert_requested.emit(path, name))
        if self.editable(path):
            menu.addSeparator()
            menu.addAction(
                self.tr("Im Blockeditor bearbeiten"), lambda: self.editor_requested.emit(path, name)
            )
            menu.addAction(
                self.tr("Eigenschaften bearbeiten …"), lambda: self.edit_requested.emit(path, name)
            )
            if path == DOCUMENT_SOURCE:
                menu.addAction(
                    self.tr("In Benutzerbibliothek speichern"),
                    lambda: self.save_requested.emit(name),
                )
                text = self.tr("Aus Zeichnung löschen")
            else:
                text = self.tr("Aus Bibliothek löschen")
            menu.addAction(text, lambda: self.delete_requested.emit(path, name))
        else:
            menu.addSeparator()
            hint = menu.addAction(self.tr("Mitgelieferte Bibliothek: nicht änderbar"))
            hint.setEnabled(False)
        menu.exec(self.list.viewport().mapToGlobal(pos))
