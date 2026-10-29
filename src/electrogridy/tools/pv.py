"""Module field: fills a roof area with PV modules (blocks of the real module size)."""

import math
from dataclasses import dataclass

from electrogridy.commands.blocks import AddBlockCommand
from electrogridy.commands.entities import AddEntitiesCommand
from electrogridy.model.blocks import BlockDefinition, point_to_world
from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import BlockReference, Circle, Entity, Polyline, Rectangle, new_id
from electrogridy.model.geometry import Point
from electrogridy.model.pv_layout import (
    LayoutParams,
    contains,
    layout_modules,
    polygon_area,
    take_modules,
)
from electrogridy.tools.base import Tool, tr

PORTRAIT, LANDSCAPE = "portrait", "landscape"
FRAME = 0.02  # inner frame line of the module symbol, as a share of the width


@dataclass(frozen=True)
class ModuleSpec:
    width: float = 1134.0  # short side, mm
    height: float = 1762.0  # long side, mm
    power: float = 445.0  # Wp
    orientation: str = PORTRAIT
    gap: float = 20.0
    edge: float = 300.0
    obstacle_gap: float = 200.0
    count: int = 0  # modules to place; 0: as many as fit

    @property
    def block_name(self) -> str:
        return f"PV-Modul {self.width:g}×{self.height:g}"

    def placed_size(self) -> tuple[float, float]:
        if self.orientation == LANDSCAPE:
            return self.height, self.width
        return self.width, self.height


def module_block(spec: ModuleSpec) -> BlockDefinition:
    """Top view of a module in its real size, base point at the top left corner."""
    w, h = spec.width, spec.height
    f = w * FRAME
    return BlockDefinition(
        name=spec.block_name,
        base_point=Point(0.0, 0.0),
        entities=EntityContainer(
            [
                Rectangle(id="frame", p1=Point(0, 0), p2=Point(w, h)),
                Rectangle(id="cells", p1=Point(f, f), p2=Point(w - f, h - f)),
            ]
        ),
        category="Photovoltaik",
        description=f"PV-Modul Draufsicht {w:g} × {h:g} mm",
    )


def closed_outline(e: Entity) -> list[Point] | None:
    """Corner points of a closed shape that can be a roof face or an obstacle."""
    if isinstance(e, Rectangle):
        x0, x1 = sorted((e.p1.x, e.p2.x))
        y0, y1 = sorted((e.p1.y, e.p2.y))
        return [Point(x0, y0), Point(x1, y0), Point(x1, y1), Point(x0, y1)]
    if isinstance(e, Polyline) and e.closed and len(e.points) >= 3:
        return list(e.points)
    if isinstance(e, Circle):
        n = 24
        return [
            Point(
                e.center.x + e.radius * math.cos(2 * math.pi * k / n),
                e.center.y + e.radius * math.sin(2 * math.pi * k / n),
            )
            for k in range(n)
        ]
    return None


def roof_and_obstacles(
    entities: list[Entity], p: Point
) -> tuple[list[Point], list[list[Point]]] | None:
    """The smallest closed shape around ``p`` and the closed shapes inside it."""
    shapes = [(e, o) for e in entities if (o := closed_outline(e)) is not None]
    around = [(e, o) for e, o in shapes if contains(o, p)]
    if not around:
        return None
    roof_entity, roof = min(around, key=lambda eo: polygon_area(eo[1]))
    area = polygon_area(roof)
    obstacles = [
        o
        for e, o in shapes
        if e is not roof_entity and polygon_area(o) < area and any(contains(roof, q) for q in o)
    ]
    return roof, obstacles


class ModuleFieldTool(Tool):
    """Click into a roof face; it is filled with modules as far as they fit."""

    def __init__(self, ctx, spec: ModuleSpec) -> None:
        super().__init__(ctx)
        self._spec = spec

    def prompt(self) -> str:
        return tr("Modulfeld: In die Dachfläche klicken (Rechteck oder geschlossene Polylinie)")

    def dynamic_mode(self) -> tuple[str, Point | None]:
        return ("xy", None)

    def pick(self, p: Point) -> None:
        container = self.ctx.container
        found = roof_and_obstacles(list(container), p)
        if found is None:
            self.ctx.message(tr("Keine geschlossene Fläche an dieser Stelle"))
            return
        roof, obstacles = found
        spec = self._spec
        w, h = spec.placed_size()
        corners = layout_modules(
            roof, obstacles, LayoutParams(w, h, spec.gap, spec.edge, spec.obstacle_gap)
        )
        if not corners:
            self.ctx.message(tr("Auf dieser Fläche hat kein Modul Platz"))
            return
        fitting = len(corners)
        corners = take_modules(corners, int(spec.count))
        definition = module_block(spec)
        rotation = 90 if spec.orientation == LANDSCAPE else 0
        # Where the turned block lands relative to its insert point.
        probe = BlockReference(id="", name=definition.name, insert=Point(0, 0), rotation=rotation)
        local = [
            point_to_world(probe, definition.base_point, q)
            for q in (Point(0, 0), Point(spec.width, spec.height))
        ]
        dx, dy = min(q.x for q in local), min(q.y for q in local)
        refs = [
            BlockReference(
                id=new_id(),
                layer=self.ctx.current_layer,
                name=definition.name,
                insert=Point(c.x - dx, c.y - dy),
                rotation=rotation,
            )
            for c in corners
        ]
        blocks = self.ctx.block_definitions
        self.ctx.begin_macro(tr("Modulfeld"))
        if definition.name not in blocks:
            self.ctx.push(AddBlockCommand(self.ctx.document, definition, tr("Modul anlegen")))
        self.ctx.push(AddEntitiesCommand(container, refs, tr("Modulfeld")))
        self.ctx.end_macro()
        kwp = f"{len(refs) * spec.power / 1000:.2f}".replace(".", ",")
        if spec.count > fitting:
            self.ctx.message(
                tr("Nur {n} von {wanted} Modulen haben Platz, {kwp} kWp").format(
                    n=len(refs), wanted=int(spec.count), kwp=kwp
                )
            )
        else:
            self.ctx.message(tr("{n} Module, {kwp} kWp").format(n=len(refs), kwp=kwp))
        self.done = True
