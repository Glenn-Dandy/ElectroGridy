"""Tools that create new entities."""

from dataclasses import replace

from sldgridy.commands.entities import AddEntitiesCommand, ReplaceEntitiesCommand
from sldgridy.model.dimensions import PAPER_TEXT_HEIGHT, auto_orientation, default_height
from sldgridy.model.entities import (
    DEFAULT_BUSBAR_WEIGHT,
    Arc,
    Busbar,
    Circle,
    Dimension,
    Entity,
    InterruptionPoint,
    Line,
    Polyline,
    Rectangle,
    Text,
    Wire,
    new_id,
)
from sldgridy.model.geometry import Point, angle_deg, distance, ortho
from sldgridy.model.routing import Pin, connect, pin_at, pins_of, rails
from sldgridy.model.snap import edges_of
from sldgridy.model.wires import elbow, simplify
from sldgridy.tools.base import PREVIEW_ID, Tool, tr

DIMENSION_LINEWEIGHT = 0.18  # thin lines for dimensions (ISO 128)


class _DrawTool(Tool):
    def _add(self, entity: Entity, text: str) -> None:
        self.ctx.push(AddEntitiesCommand(self.ctx.container, [entity], text))


class LineTool(_DrawTool):
    """Chained line segments, each one a separate entity."""

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._start: Point | None = None

    def prompt(self) -> str:
        if self._start is None:
            return tr("Linie: Ersten Punkt angeben")
        return tr("Linie: Nächsten Punkt angeben (Enter beendet)")

    def pick(self, p: Point) -> None:
        if self._start is not None and p != self._start:
            line = Line(id=new_id(), layer=self.ctx.current_layer, p1=self._start, p2=p)
            self._add(line, tr("Linie zeichnen"))
        self._start = p

    def base_point(self) -> Point | None:
        return self._start

    def preview(self) -> list[Entity]:
        if self._start is None or self.cursor is None:
            return []
        return [Line(id=PREVIEW_ID, layer=self.ctx.current_layer, p1=self._start, p2=self.cursor)]


class PolylineTool(_DrawTool):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._points: list[Point] = []

    def prompt(self) -> str:
        if not self._points:
            return tr("Polylinie: Startpunkt angeben")
        return tr("Polylinie: Nächsten Punkt angeben (Enter beendet, Startpunkt schließt)")

    def pick(self, p: Point) -> None:
        if self._points and p == self._points[-1]:
            return
        if len(self._points) >= 3 and p == self._points[0]:
            self._commit(closed=True)
            return
        self._points.append(p)

    def finish(self) -> None:
        if len(self._points) >= 2:
            self._commit(closed=False)
        self.done = True

    def _commit(self, closed: bool) -> None:
        poly = Polyline(
            id=new_id(), layer=self.ctx.current_layer, points=tuple(self._points), closed=closed
        )
        self._add(poly, tr("Polylinie zeichnen"))
        self.done = True

    def base_point(self) -> Point | None:
        return self._points[-1] if self._points else None

    def snap_entities(self) -> list[Entity]:
        if len(self._points) < 2:
            return []
        return [
            Polyline(
                id="drawing-polyline", layer=self.ctx.current_layer, points=tuple(self._points)
            )
        ]

    def preview(self) -> list[Entity]:
        if not self._points or self.cursor is None:
            return []
        pts = (*self._points, self.cursor)
        return [Polyline(id=PREVIEW_ID, layer=self.ctx.current_layer, points=pts)]


class RectangleTool(_DrawTool):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._corner: Point | None = None

    def prompt(self) -> str:
        if self._corner is None:
            return tr("Rechteck: Erste Ecke angeben")
        return tr("Rechteck: Gegenüberliegende Ecke angeben")

    def dynamic_mode(self) -> tuple[str, Point | None]:
        # Width and height instead of length and angle.
        return ("size", self._corner) if self._corner is not None else ("xy", None)

    def pick(self, p: Point) -> None:
        if self._corner is None:
            self._corner = p
            return
        if p.x == self._corner.x or p.y == self._corner.y:
            return
        rect = Rectangle(id=new_id(), layer=self.ctx.current_layer, p1=self._corner, p2=p)
        self._add(rect, tr("Rechteck zeichnen"))
        self.done = True

    def preview(self) -> list[Entity]:
        if self._corner is None or self.cursor is None:
            return []
        return [
            Rectangle(id=PREVIEW_ID, layer=self.ctx.current_layer, p1=self._corner, p2=self.cursor)
        ]


class CircleTool(_DrawTool):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._center: Point | None = None

    def prompt(self) -> str:
        if self._center is None:
            return tr("Kreis: Mittelpunkt angeben")
        return tr("Kreis: Punkt auf dem Umfang angeben")

    def pick(self, p: Point) -> None:
        if self._center is None:
            self._center = p
            return
        r = distance(self._center, p)
        if r <= 0:
            return
        circle = Circle(id=new_id(), layer=self.ctx.current_layer, center=self._center, radius=r)
        self._add(circle, tr("Kreis zeichnen"))
        self.done = True

    def base_point(self) -> Point | None:
        return self._center

    def preview(self) -> list[Entity]:
        if self._center is None or self.cursor is None:
            return []
        r = distance(self._center, self.cursor)
        if r <= 0:
            return []
        return [Circle(id=PREVIEW_ID, layer=self.ctx.current_layer, center=self._center, radius=r)]


class ArcTool(_DrawTool):
    """Arc by center, start point and end point, counter-clockwise."""

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._center: Point | None = None
        self._start: Point | None = None

    def prompt(self) -> str:
        if self._center is None:
            return tr("Bogen: Mittelpunkt angeben")
        if self._start is None:
            return tr("Bogen: Startpunkt angeben")
        return tr("Bogen: Endpunkt angeben (gegen den Uhrzeigersinn)")

    def _arc(self, end: Point, entity_id: str) -> Arc | None:
        assert self._center is not None and self._start is not None
        r = distance(self._center, self._start)
        a0 = angle_deg(self._center, self._start)
        a1 = angle_deg(self._center, end)
        if r <= 0 or end == self._center or abs(a1 - a0) < 1e-9:
            return None
        return Arc(
            id=entity_id,
            layer=self.ctx.current_layer,
            center=self._center,
            radius=r,
            start_angle=a0,
            end_angle=a1,
        )

    def pick(self, p: Point) -> None:
        if self._center is None:
            self._center = p
        elif self._start is None:
            if p != self._center:
                self._start = p
        else:
            arc = self._arc(p, new_id())
            if arc is not None:
                self._add(arc, tr("Bogen zeichnen"))
                self.done = True

    def base_point(self) -> Point | None:
        return self._center

    def preview(self) -> list[Entity]:
        if self._center is None or self.cursor is None:
            return []
        if self._start is None:
            return [
                Line(id=PREVIEW_ID, layer=self.ctx.current_layer, p1=self._center, p2=self.cursor)
            ]
        arc = self._arc(self.cursor, PREVIEW_ID)
        return [arc] if arc else []


class TextTool(_DrawTool):
    def prompt(self) -> str:
        return tr("Text: Einfügepunkt angeben")

    def pick(self, p: Point) -> None:
        result = self.ctx.ask_text()
        if result is not None:
            content, height = result
            if content.strip():
                text = Text(
                    id=new_id(),
                    layer=self.ctx.current_layer,
                    position=p,
                    text=content,
                    height=height,
                )
                self._add(text, tr("Text einfügen"))
        self.done = True


class WireTool(_DrawTool):
    """Orthogonal wire; points that are not aligned get an automatic corner.

    From one connection point straight to another, the wire is laid automatically; on
    multi-pole devices all following poles are wired at once (L1 to L1, L2 to L2 …).
    The tool then waits for the next connection.
    """

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._points: list[Point] = []
        self._pins: list[Pin] = []
        self._start_pin: Pin | None = None

    def prompt(self) -> str:
        if not self._points:
            return tr("Leitung: Startpunkt angeben (Anschlusspunkt: automatisch verlegen)")
        if self._start_pin is not None and len(self._points) == 1:
            return tr("Leitung: Ziel-Anschlusspunkt oder nächsten Punkt angeben")
        return tr("Leitung: Nächsten Punkt angeben (Enter beendet)")

    def _routed(self, p: Point) -> list[tuple[Point, ...]]:
        """Automatic paths when the wire runs from a connection point to another one."""
        if self._start_pin is None or len(self._points) != 1:
            return []
        end = pin_at(self._pins, p)
        if end is None or end == self._start_pin:
            return []
        return [path for path in connect(self._pins, self._start_pin, end) if len(path) >= 2]

    def pick(self, p: Point) -> None:
        if not self._points:
            self._points.append(p)
            self._pins = pins_of(self.ctx.container, self.ctx.block_definitions)
            self._start_pin = pin_at(self._pins, p)
            return
        if p == self._points[-1]:
            return
        paths = self._routed(p)
        if paths:
            wires = [Wire(id=new_id(), layer=self.ctx.current_layer, points=path) for path in paths]
            text = tr("Leitung zeichnen") if len(wires) == 1 else tr("Leitungen verlegen")
            self.ctx.push(AddEntitiesCommand(self.ctx.container, wires, text))
            if len(wires) > 1:
                self.ctx.message(tr("{n} Leitungen verlegt").format(n=len(wires)))
            self._points, self._start_pin = [], None
            return
        self._points += elbow(self._points[-1], p)

    def finish(self) -> None:
        points = simplify(self._points)
        if len(points) >= 2:
            wire = Wire(id=new_id(), layer=self.ctx.current_layer, points=points)
            self._add(wire, tr("Leitung zeichnen"))
        self.done = True

    def base_point(self) -> Point | None:
        return self._points[-1] if self._points else None

    def preview(self) -> list[Entity]:
        if not self._points or self.cursor is None:
            return []
        paths = self._routed(self.cursor)
        if paths:
            return [
                Wire(id=f"{PREVIEW_ID}{i}", layer=self.ctx.current_layer, points=path)
                for i, path in enumerate(paths)
            ]
        pts = simplify([*self._points, *elbow(self._points[-1], self.cursor)])
        if len(pts) < 2:
            return []
        return [Wire(id=PREVIEW_ID, layer=self.ctx.current_layer, points=pts)]


class BusbarTool(_DrawTool):
    """Straight horizontal or vertical bus bar."""

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._start: Point | None = None

    def prompt(self) -> str:
        if self._start is None:
            return tr("Sammelschiene: Startpunkt angeben")
        return tr("Sammelschiene: Endpunkt angeben")

    def _bar(self, p: Point, entity_id: str) -> Busbar | None:
        assert self._start is not None
        end = ortho(self._start, p)
        if end == self._start:
            return None
        return Busbar(
            id=entity_id,
            layer=self.ctx.current_layer,
            lineweight=DEFAULT_BUSBAR_WEIGHT,
            p1=self._start,
            p2=end,
        )

    def pick(self, p: Point) -> None:
        if self._start is None:
            self._start = p
            return
        bar = self._bar(p, new_id())
        if bar is not None:
            self._add(bar, tr("Sammelschiene zeichnen"))
            self.done = True

    def base_point(self) -> Point | None:
        return self._start

    def preview(self) -> list[Entity]:
        if self._start is None or self.cursor is None:
            return []
        bar = self._bar(self.cursor, PREVIEW_ID)
        return [bar] if bar else []


class ExtendTool(_DrawTool):
    """Continue a wire or polyline from one of its ends (``end`` 0 = start, -1 = end)."""

    def __init__(self, ctx, entity_id: str, end: int) -> None:
        super().__init__(ctx)
        self._entity = ctx.container.get(entity_id)
        pts = list(self._entity.points)
        self._reversed = end == 0
        self._points = list(reversed(pts)) if self._reversed else pts
        self._added = 0

    def prompt(self) -> str:
        return tr("Verlängern: Nächsten Punkt angeben (Enter beendet)")

    def _extend(self, pts: list[Point], p: Point) -> list[Point]:
        if isinstance(self._entity, Wire):
            return [*pts, *elbow(pts[-1], p)]
        return [*pts, p]

    def pick(self, p: Point) -> None:
        if p == self._points[-1]:
            return
        self._points = self._extend(self._points, p)
        self._added += 1

    def _result(self, pts: list[Point]) -> Entity:
        ordered = list(reversed(pts)) if self._reversed else pts
        if isinstance(self._entity, Wire):
            return replace(self._entity, points=simplify(ordered))
        return replace(self._entity, points=tuple(ordered))

    def finish(self) -> None:
        if self._added:
            self.ctx.push(
                ReplaceEntitiesCommand(
                    self.ctx.container, [self._result(self._points)], tr("Verlängern")
                )
            )
        self.done = True

    def base_point(self) -> Point | None:
        return self._points[-1]

    def preview(self) -> list[Entity]:
        if self.cursor is None or self.cursor == self._points[-1]:
            return []
        return [self._result(self._extend(self._points, self.cursor))]


class DimensionTool(_DrawTool):
    """Linear dimension: two measured points, then where the dimension line goes.

    ``aligned`` False picks horizontal or vertical from the side the line is dragged
    to; True measures the true distance along the line between the points.
    """

    def __init__(self, ctx, aligned: bool = False) -> None:
        super().__init__(ctx)
        self._aligned = aligned
        self._points: list[Point] = []

    def prompt(self) -> str:
        if not self._points:
            return tr("Bemaßen: Ersten Punkt angeben")
        if len(self._points) == 1:
            return tr("Bemaßen: Zweiten Punkt angeben")
        return tr("Bemaßen: Lage der Maßlinie angeben")

    def _make(self, position: Point, entity_id: str) -> Dimension | None:
        p1, p2 = self._points
        if p1 == p2:
            return None
        orientation = "aligned" if self._aligned else auto_orientation(p1, p2, position)
        return Dimension(
            id=entity_id,
            layer=self.ctx.current_layer,
            lineweight=DIMENSION_LINEWEIGHT,
            p1=p1,
            p2=p2,
            position=position,
            orientation=orientation,
            height=self._height(p1),
        )

    def _height(self, p: Point) -> float:
        """2.5 mm on paper: in the model, scaled by the viewport that shows the point."""
        document = getattr(self.ctx, "document", None)
        if document is None or self.ctx.container is not document.model_space:
            return PAPER_TEXT_HEIGHT
        return default_height(document.sheets, p)

    def pick(self, p: Point) -> None:
        if len(self._points) < 2:
            if not self._points or p != self._points[0]:
                self._points.append(p)
            return
        dimension = self._make(p, new_id())
        if dimension is not None:
            self._add(dimension, tr("Bemaßen"))
        self._points = []

    def base_point(self) -> Point | None:
        # Typed length for the second point; the dimension line is placed freely.
        return self._points[0] if len(self._points) == 1 else None

    def preview(self) -> list[Entity]:
        if self.cursor is None:
            return []
        if len(self._points) == 1:
            return [
                Line(
                    id=PREVIEW_ID, layer=self.ctx.current_layer, p1=self._points[0], p2=self.cursor
                )
            ]
        if len(self._points) == 2:
            d = self._make(self.cursor, PREVIEW_ID)
            return [d] if d is not None else []
        return []


LEG_TOLERANCE = 6.0  # degrees: a leg point this close in direction snaps onto the leg


class AngularDimensionTool(DimensionTool):
    """Angle: vertex, a point on each leg, then where the arc goes.

    A leg point snaps onto a drawn edge running through the vertex when it points
    roughly the same way, so clicking near a sloped line is enough."""

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._vertex: Point | None = None

    def prompt(self) -> str:
        if self._vertex is None:
            return tr("Winkel bemaßen: Scheitelpunkt angeben")
        if not self._points:
            return tr("Winkel bemaßen: Punkt auf dem ersten Schenkel angeben")
        if len(self._points) == 1:
            return tr("Winkel bemaßen: Punkt auf dem zweiten Schenkel angeben")
        return tr("Winkel bemaßen: Lage des Maßbogens angeben")

    def _make(self, position: Point, entity_id: str) -> Dimension | None:
        p1, p2 = self._points
        v = self._vertex
        if v is None or position == v:
            return None
        return Dimension(
            id=entity_id,
            layer=self.ctx.current_layer,
            lineweight=DIMENSION_LINEWEIGHT,
            p1=p1,
            p2=p2,
            position=position,
            orientation="angular",
            vertex=v,
            height=self._height(v),
        )

    def _legs(self) -> list[Point]:
        """Far ends of the drawn edges that start at or pass through the vertex."""
        v = self._vertex
        assert v is not None
        ends: list[Point] = []
        for e in self.ctx.container:
            if isinstance(e, Dimension):
                continue
            for a, b in edges_of(e):
                length = distance(a, b)
                if length <= 1e-9:
                    continue
                da, db = distance(v, a), distance(v, b)
                if da <= 1e-6:
                    ends.append(b)
                elif db <= 1e-6:
                    ends.append(a)
                elif abs(da + db - length) <= 1e-6:
                    ends.extend((a, b))  # vertex inside the edge: both directions
        return ends

    def _on_leg(self, p: Point) -> Point:
        v = self._vertex
        if v is None or len(self._points) >= 2 or distance(v, p) <= 1e-9:
            return p
        aim = angle_deg(v, p)
        best, best_diff = p, LEG_TOLERANCE
        for end in self._legs():
            diff = abs((angle_deg(v, end) - aim + 180) % 360 - 180)
            if diff < best_diff:
                best, best_diff = end, diff
        return best

    def hover(self, p: Point) -> None:
        self.cursor = self._on_leg(p)

    def pick(self, p: Point) -> None:
        if self._vertex is None:
            self._vertex = p
            return
        if len(self._points) < 2:
            p = self._on_leg(p)
            if p != self._vertex:
                self._points.append(p)
            return
        dimension = self._make(p, new_id())
        if dimension is not None:
            self._add(dimension, tr("Winkel bemaßen"))
        self._vertex = None
        self._points = []

    def base_point(self) -> Point | None:
        return self._vertex if self._vertex is not None and len(self._points) < 2 else None

    def preview(self) -> list[Entity]:
        if self.cursor is None or self._vertex is None:
            return []
        if len(self._points) < 2:
            return [
                Line(id=f"{PREVIEW_ID}{i}", layer=self.ctx.current_layer, p1=self._vertex, p2=q)
                for i, q in enumerate([*self._points, self.cursor])
            ]
        d = self._make(self.cursor, PREVIEW_ID)
        return [d] if d is not None else []


class InterruptionTool(_DrawTool):
    """Interruption point: position, then the way the conductor runs on (right, left, up
    or down), then its name. Stays active for the next one."""

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self._position: Point | None = None

    def prompt(self) -> str:
        if self._position is None:
            return tr("Unterbrechungspunkt: Stelle angeben")
        return tr("Unterbrechungspunkt: Richtung zeigen, in die die Leitung weiterläuft")

    def base_point(self) -> Point | None:
        return self._position

    def _direction(self, p: Point) -> float:
        assert self._position is not None
        dx, dy = p.x - self._position.x, p.y - self._position.y
        if abs(dx) >= abs(dy):
            return 0.0 if dx >= 0 else 180.0
        return 270.0 if dy > 0 else 90.0

    def pick(self, p: Point) -> None:
        if self._position is None:
            self._position = p
            return
        if p == self._position:
            return
        direction = self._direction(p)
        ask = getattr(self.ctx, "ask_interruption_name", None)
        name = ask() if ask is not None else "L1"
        if name:
            self._add(
                InterruptionPoint(
                    id=new_id(),
                    layer=self.ctx.current_layer,
                    position=self._position,
                    name=name,
                    direction=direction,
                ),
                tr("Unterbrechungspunkt"),
            )
        self._position = None

    def preview(self) -> list[Entity]:
        if self._position is None or self.cursor is None or self.cursor == self._position:
            return []
        return [
            InterruptionPoint(
                id=PREVIEW_ID,
                layer=self.ctx.current_layer,
                position=self._position,
                name="?",
                direction=self._direction(self.cursor),
            )
        ]


class RailsTool(_DrawTool):
    """Main circuit conductors (L1, L2, L3, N, PE) across the page, one pole spacing
    apart. On a page with the circuit diagram frame one click sets the height of the
    first conductor; elsewhere a start and an end point."""

    def __init__(self, ctx, names: list[str], ends: bool, span: tuple[float, float] | None) -> None:
        super().__init__(ctx)
        self._names, self._ends, self._span = names, ends, span
        self._start: Point | None = None

    def prompt(self) -> str:
        if self._span is not None:
            return tr("Potentialschienen: Höhe des ersten Leiters angeben")
        if self._start is None:
            return tr("Potentialschienen: Startpunkt des ersten Leiters angeben")
        return tr("Potentialschienen: Endpunkt angeben")

    def base_point(self) -> Point | None:
        return self._start

    def _entities(self, p: Point) -> list[Entity]:
        if self._span is not None:
            x1, x2, y = self._span[0], self._span[1], p.y
        elif self._start is not None:
            x1, x2, y = self._start.x, p.x, self._start.y
        else:
            return []
        if abs(x2 - x1) < 1e-6:
            return []
        return rails(self._names, x1, x2, y, self.ctx.current_layer, self._ends)

    def pick(self, p: Point) -> None:
        if self._span is None and self._start is None:
            self._start = p
            return
        entities = self._entities(p)
        if entities:
            self.ctx.push(AddEntitiesCommand(self.ctx.container, entities, tr("Potentialschienen")))
            self.done = True

    def preview(self) -> list[Entity]:
        if self.cursor is None:
            return []
        return [
            replace(e, id=f"{PREVIEW_ID}{i}") for i, e in enumerate(self._entities(self.cursor))
        ]
