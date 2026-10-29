"""Tools for placing block references and picking single points."""

from collections.abc import Callable, Mapping
from dataclasses import replace

from electrogridy.model.blocks import BlockDefinition, BlockError, expand
from electrogridy.model.entities import BlockReference, Entity
from electrogridy.model.geometry import Point
from electrogridy.tools.base import Tool


class PointTool(Tool):
    """Asks for one point and hands it to ``on_point``."""

    def __init__(
        self,
        ctx,
        prompt: str,
        on_point: Callable[[Point], None],
        preview: Callable[[Point], list[Entity]] | None = None,
    ) -> None:
        super().__init__(ctx)
        self._prompt = prompt
        self._on_point = on_point
        self._preview = preview

    def prompt(self) -> str:
        return self._prompt

    def pick(self, p: Point) -> None:
        self.done = True
        self._on_point(p)

    def preview(self) -> list[Entity]:
        if self._preview is None or self.cursor is None:
            return []
        return self._preview(self.cursor)


class InsertBlockTool(Tool):
    """Shows a block at the cursor; a click hands the placed reference to ``on_place``.

    ``blocks`` may contain definitions that are not in the document yet
    (library blocks), so the preview is expanded here.
    """

    def __init__(
        self,
        ctx,
        reference: BlockReference,
        blocks: Mapping[str, BlockDefinition],
        prompt: str,
        on_place: Callable[[BlockReference], None],
    ) -> None:
        super().__init__(ctx)
        self._reference = reference
        self._blocks = blocks
        self._prompt = prompt
        self._on_place = on_place

    def prompt(self) -> str:
        return self._prompt

    def _at(self, p: Point) -> BlockReference:
        return replace(self._reference, insert=p, layer=self.ctx.current_layer)

    def pick(self, p: Point) -> None:
        self.done = True
        self._on_place(self._at(p))

    def preview(self) -> list[Entity]:
        if self.cursor is None:
            return []
        try:
            return expand(self._at(self.cursor), self._blocks)
        except BlockError:
            return []
