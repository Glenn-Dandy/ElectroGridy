"""Runs one tool at a time and remembers the last one for repetition."""

from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal

from electrogridy.model.entities import Entity
from electrogridy.model.geometry import Point
from electrogridy.tools.base import Tool, ToolContext

ToolFactory = Callable[[ToolContext], Tool]


class ToolController(QObject):
    # Emitted whenever prompt, preview or the active tool may have changed.
    changed = pyqtSignal()

    def __init__(self, ctx: ToolContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._tool: Tool | None = None
        self._last_factory: ToolFactory | None = None
        self._cursor: Point | None = None
        # Last point given to any tool, reference for relative input without base point.
        self.last_point: Point | None = None

    @property
    def active(self) -> Tool | None:
        return self._tool

    def start(self, factory: ToolFactory) -> None:
        self.cancel()
        self._last_factory = factory
        self._tool = factory(self._ctx)
        self._tool.start()
        if self._cursor is not None:
            self._tool.hover(self._cursor)
        self._after_event()

    def repeat(self) -> None:
        if self._last_factory is not None:
            self.start(self._last_factory)

    def pick(self, p: Point) -> None:
        if self._tool and not self._tool.selecting:
            self.last_point = p
            self._tool.pick(p)
            self._after_event()

    def typed_value(self, name: str, value: float) -> bool:
        if self._tool is None or self._tool.selecting or not self._tool.typed_value(name, value):
            return False
        self._after_event()
        return True

    def typed_changed(self, name: str, value: float | None) -> None:
        if self._tool is not None:
            self._tool.typed_changed(name, value)
            self.changed.emit()

    def hover(self, p: Point) -> None:
        self._cursor = p
        if self._tool:
            self._tool.hover(p)
            self.changed.emit()

    def finish(self) -> None:
        if self._tool:
            self._tool.finish()
            self._after_event()

    def cancel(self) -> None:
        if self._tool:
            self._tool.cancel()
            self._tool = None
            self.changed.emit()

    def _after_event(self) -> None:
        if self._tool and self._tool.done:
            self._tool = None
        self.changed.emit()

    def prompt(self) -> str:
        return self._tool.prompt() if self._tool else ""

    def base_point(self) -> Point | None:
        return self._tool.base_point() if self._tool else None

    def selecting(self) -> bool:
        return self._tool is not None and self._tool.selecting

    def dynamic_mode(self) -> tuple[str, Point | None] | None:
        if self._tool is None or self._tool.selecting:
            return None
        return self._tool.dynamic_mode()

    def preview(self) -> list[Entity]:
        return self._tool.preview() if self._tool else []
