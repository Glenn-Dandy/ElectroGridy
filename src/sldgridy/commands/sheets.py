"""Undo commands for sheets (drawing frames) and title block fields."""

from PyQt6.QtGui import QUndoCommand

from sldgridy.commands.entities import ReplaceEntitiesCommand
from sldgridy.model.container import EntityContainer
from sldgridy.model.document import SHEETS, Document, SheetLayout
from sldgridy.model.entities import Viewport

VIEWPORT_NAVIGATION_ID = 6001


class AddSheetCommand(QUndoCommand):
    """Add a sheet, or with ``kind`` PAGES a page of the multi-line diagram."""

    def __init__(
        self, doc: Document, index: int, sheet: SheetLayout, text: str, kind: str = SHEETS
    ) -> None:
        super().__init__(text)
        self._doc, self._index, self._sheet, self._kind = doc, index, sheet, kind

    def redo(self) -> None:
        self._doc.insert_layout(self._kind, self._index, self._sheet)

    def undo(self) -> None:
        self._doc.remove_layout(self._kind, self._sheet.id)


class RemoveSheetCommand(QUndoCommand):
    def __init__(self, doc: Document, sheet_id: str, text: str) -> None:
        super().__init__(text)
        self._kind = doc.kind_of(sheet_id)
        if self._kind == SHEETS and len(doc.sheets) <= 1:
            raise ValueError("a drawing keeps at least one sheet")
        self._doc, self._id = doc, sheet_id
        self._removed: tuple[int, SheetLayout] | None = None

    def redo(self) -> None:
        self._removed = self._doc.remove_layout(self._kind, self._id)

    def undo(self) -> None:
        assert self._removed is not None
        self._doc.insert_layout(self._kind, *self._removed)


class MoveSheetCommand(QUndoCommand):
    def __init__(self, doc: Document, old: int, new: int, text: str, kind: str = SHEETS) -> None:
        super().__init__(text)
        self._doc, self._old, self._new, self._kind = doc, old, new, kind

    def redo(self) -> None:
        self._doc.move_layout(self._kind, self._old, self._new)

    def undo(self) -> None:
        self._doc.move_layout(self._kind, self._new, self._old)


_SHEET_ATTRIBUTES = (
    "name",
    "paper",
    "orientation",
    "title_block",
    "fields",
    "plant",
    "location",
    "columns",
)


class ChangeSheetCommand(QUndoCommand):
    """Change name, format, orientation, title block, field values or (pages) designation
    and columns of a sheet or page."""

    def __init__(self, doc: Document, sheet_id: str, text: str, **changes) -> None:
        super().__init__(text)
        unknown = set(changes) - set(_SHEET_ATTRIBUTES)
        if unknown:
            raise ValueError(f"unknown sheet attributes {unknown}")
        self._doc, self._id = doc, sheet_id
        sheet = doc.layout(sheet_id)
        self._new = {k: (dict(v) if isinstance(v, dict) else v) for k, v in changes.items()}
        self._old = {
            k: (dict(getattr(sheet, k)) if k == "fields" else getattr(sheet, k)) for k in changes
        }

    def _apply(self, values: dict) -> None:
        sheet = self._doc.layout(self._id)
        for k, v in values.items():
            setattr(sheet, k, dict(v) if isinstance(v, dict) else v)
        self._doc.sheets_changed()

    def redo(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)


class ChangeDocumentPropertiesCommand(QUndoCommand):
    def __init__(self, doc: Document, properties: dict[str, str], text: str) -> None:
        super().__init__(text)
        self._doc = doc
        self._old = dict(doc.properties)
        self._new = dict(properties)

    def redo(self) -> None:
        self._doc.properties = dict(self._new)
        self._doc.sheets_changed()

    def undo(self) -> None:
        self._doc.properties = dict(self._old)
        self._doc.sheets_changed()


class NavigateViewportCommand(ReplaceEntitiesCommand):
    """Pan or zoom inside an active viewport; consecutive steps merge into one undo step."""

    def __init__(self, container: EntityContainer, viewport: Viewport, text: str) -> None:
        super().__init__(container, [viewport], text)
        self._viewport_id = viewport.id

    def id(self) -> int:
        return VIEWPORT_NAVIGATION_ID

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 - Qt API
        if not isinstance(other, NavigateViewportCommand):
            return False
        if other._viewport_id != self._viewport_id or other._container is not self._container:
            return False
        self._new = other._new
        return True
