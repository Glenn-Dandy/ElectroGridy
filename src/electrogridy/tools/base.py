"""Tool base class and the context tools operate in."""

from collections.abc import Mapping
from typing import Protocol

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QUndoCommand

from electrogridy.model.blocks import BlockDefinition
from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import Entity
from electrogridy.model.geometry import Point

PREVIEW_ID = "preview"


def tr(text: str) -> str:
    return QCoreApplication.translate("tools", text)


class ToolContext(Protocol):
    @property
    def container(self) -> EntityContainer: ...

    @property
    def current_layer(self) -> str: ...

    @property
    def block_definitions(self) -> Mapping[str, BlockDefinition]: ...

    def push(self, command: QUndoCommand) -> None: ...

    def selected_ids(self) -> list[str]: ...

    def ask_text(self, text: str = "", height: float | None = None) -> tuple[str, float] | None: ...

    def message(self, text: str) -> None: ...

    def ask_choice(self, key: str, options: list[str]) -> int | None:
        """Index of the chosen option (None: cancelled); ``key`` remembers the last one."""
        ...


class Tool:
    """State machine fed with already snapped points."""

    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx
        self.done = False
        self.cursor: Point | None = None
        # While True the canvas selects objects instead of picking points.
        self.selecting = False

    def start(self) -> None:
        pass

    def prompt(self) -> str:
        return ""

    def pick(self, p: Point) -> None:
        raise NotImplementedError

    def hover(self, p: Point) -> None:
        self.cursor = p

    def finish(self) -> None:
        """Enter or right click."""
        self.done = True

    def cancel(self) -> None:
        """Escape."""
        self.done = True

    def snap_ignored_ids(self) -> set[str]:
        """Objects the object snap leaves out while this tool runs."""
        return set()

    def typed_value(self, name: str, value: float) -> bool:
        """A value typed at the cursor that is not a point (e.g. a scale factor), confirmed
        with Enter. True if the tool used it."""
        return False

    def typed_changed(self, name: str, value: float | None) -> None:
        """The value at the cursor changed while typing (for a live preview)."""

    def snap_entities(self) -> list[Entity]:
        """Objects not yet in the drawing the object snap should offer (e.g. the
        segments of a polyline being drawn, so it can be closed on its start)."""
        return []

    def base_point(self) -> Point | None:
        """Reference point for ortho mode and the rubber band line."""
        return None

    def dynamic_mode(self) -> tuple[str, Point | None]:
        """Fields for typed values at the cursor: X/Y before a base point, else length
        and angle from it (tools.dynamic_input)."""
        base = self.base_point()
        return ("polar", base) if base is not None else ("xy", None)

    def preview(self) -> list[Entity]:
        return []
