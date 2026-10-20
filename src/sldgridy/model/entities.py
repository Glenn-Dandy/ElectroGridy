"""Drawing entities. Immutable: edits create new instances with the same id."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Self

from sldgridy.model.geometry import Point, mirror_point, rotate_quarter
from sldgridy.model.layers import DEFAULT_LAYER

TEXT_HEIGHTS = (2.5, 3.5, 5.0, 7.0)
DEFAULT_TEXT_HEIGHT = 3.5


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True, kw_only=True)
class Entity:
    id: str
    layer: str = DEFAULT_LAYER
    # None means "by layer".
    color: str | None = None
    lineweight: float | None = None
    linetype: str | None = None

    def with_new_id(self) -> Self:
        return replace(self, id=new_id())

    def translated(self, dx: float, dy: float) -> Self:
        return self._mapped(lambda p: p.translated(dx, dy), 0)

    def rotated(self, center: Point, quarters: int) -> Self:
        return self._mapped(lambda p: rotate_quarter(p, center, quarters), quarters % 4)

    def mirrored(self, axis: Point, horizontal: bool) -> Self:
        """Mirror at the horizontal (``horizontal``) or vertical line through ``axis``.

        Texts keep their reading direction; only the insertion point moves.
        """
        return self._mapped(lambda p: mirror_point(p, axis, horizontal), 0)

    def _mapped(self, fn: Callable[[Point], Point], quarters: int) -> Self:
        raise NotImplementedError


@dataclass(frozen=True, kw_only=True)
class Line(Entity):
    p1: Point
    p2: Point

    def _mapped(self, fn, quarters):
        return replace(self, p1=fn(self.p1), p2=fn(self.p2))


@dataclass(frozen=True, kw_only=True)
class Polyline(Entity):
    points: tuple[Point, ...]
    closed: bool = False

    def _mapped(self, fn, quarters):
        return replace(self, points=tuple(fn(p) for p in self.points))


@dataclass(frozen=True, kw_only=True)
class Rectangle(Entity):
    """Axis-aligned rectangle given by two opposite corners."""

    p1: Point
    p2: Point

    def _mapped(self, fn, quarters):
        return replace(self, p1=fn(self.p1), p2=fn(self.p2))


@dataclass(frozen=True, kw_only=True)
class Circle(Entity):
    center: Point
    radius: float

    def _mapped(self, fn, quarters):
        return replace(self, center=fn(self.center))


@dataclass(frozen=True, kw_only=True)
class Arc(Entity):
    """Arc from ``start_angle`` counter-clockwise to ``end_angle`` (degrees)."""

    center: Point
    radius: float
    start_angle: float
    end_angle: float

    def _mapped(self, fn, quarters):
        return replace(
            self,
            center=fn(self.center),
            start_angle=(self.start_angle + 90 * quarters) % 360,
            end_angle=(self.end_angle + 90 * quarters) % 360,
        )

    def mirrored(self, axis: Point, horizontal: bool) -> Self:
        # Mirroring reverses the direction, so start and end swap.
        def flip(a: float) -> float:
            return (-a if horizontal else 180.0 - a) % 360

        return replace(
            self,
            center=mirror_point(self.center, axis, horizontal),
            start_angle=flip(self.end_angle),
            end_angle=flip(self.start_angle),
        )

    @property
    def sweep(self) -> float:
        s = (self.end_angle - self.start_angle) % 360
        return s if s else 360.0


HALIGNS = ("left", "center", "right")
VALIGNS = ("baseline", "middle")


@dataclass(frozen=True, kw_only=True)
class Text(Entity):
    """Single or multi-line text.

    ``position`` is the anchor: by default the left end of the first baseline.
    ``halign`` moves it to the centre or right end, ``valign`` "middle" to the
    vertical middle between the top of the first line and the last baseline.
    """

    position: Point
    text: str
    height: float = DEFAULT_TEXT_HEIGHT
    rotation: float = 0
    halign: str = "left"
    valign: str = "baseline"

    def _mapped(self, fn, quarters):
        return replace(
            self, position=fn(self.position), rotation=(self.rotation + 90 * quarters) % 360
        )


@dataclass(frozen=True, kw_only=True)
class AttributeDefinition(Entity):
    """Placeholder for a text value that each block reference fills in."""

    tag: str
    prompt: str = ""
    default: str = ""
    position: Point
    height: float = 2.5
    rotation: float = 0
    visible: bool = True
    halign: str = "left"
    valign: str = "middle"

    def _mapped(self, fn, quarters):
        return replace(
            self, position=fn(self.position), rotation=(self.rotation + 90 * quarters) % 360
        )

    def as_text(self, value: str) -> Text:
        return Text(
            id=self.id,
            layer=self.layer,
            color=self.color,
            lineweight=self.lineweight,
            linetype=self.linetype,
            position=self.position,
            text=value,
            height=self.height,
            rotation=self.rotation,
            halign=self.halign,
            valign=self.valign,
        )


# Direction of a connection point: the side a wire leaves from, in degrees.
DIRECTIONS = (0, 90, 180, 270)


@dataclass(frozen=True, kw_only=True)
class ConnectionPoint(Entity):
    """Where wires attach to a symbol. Only shown as a helper marker."""

    name: str
    position: Point
    direction: float = 0

    def _mapped(self, fn, quarters):
        return replace(
            self, position=fn(self.position), direction=(self.direction + 90 * quarters) % 360
        )

    def mirrored(self, axis: Point, horizontal: bool) -> Self:
        flipped = (-self.direction if horizontal else 180 - self.direction) % 360
        return replace(
            self, position=mirror_point(self.position, axis, horizontal), direction=flipped
        )


@dataclass(frozen=True, kw_only=True)
class BlockReference(Entity):
    """Placed instance of a block definition.

    Local definition coordinates map to the drawing as: subtract the base
    point, mirror X if ``mirrored_x``, rotate by ``rotation`` (counter-clockwise),
    then add ``insert``.
    """

    name: str
    insert: Point
    rotation: int = 0
    mirrored_x: bool = False
    attributes: tuple[tuple[str, str], ...] = ()
    # Extra connection points of this instance only ("docks"), in definition coordinates,
    # so wires attached anywhere on the symbol follow it.
    docks: tuple[Point, ...] = ()
    # Uniform size factor of this instance (1: the definition's real size).
    scale: float = 1.0

    def _mapped(self, fn, quarters):
        return replace(self, insert=fn(self.insert), rotation=(self.rotation + 90 * quarters) % 360)

    def mirrored(self, axis: Point, horizontal: bool) -> Self:
        # M_world . R(r) . Mx^m = R(-r) . Mx^(m+1) for a vertical axis and
        # R(180 - r) . Mx^(m+1) for a horizontal one.
        rotation = (180 - self.rotation if horizontal else -self.rotation) % 360
        return replace(
            self,
            insert=mirror_point(self.insert, axis, horizontal),
            rotation=rotation,
            mirrored_x=not self.mirrored_x,
        )

    def attribute(self, tag: str, default: str = "") -> str:
        for t, v in self.attributes:
            if t == tag:
                return v
        return default

    def with_attribute(self, tag: str, value: str) -> "BlockReference":
        attrs = [(t, v) for t, v in self.attributes if t != tag]
        attrs.append((tag, value))
        return replace(self, attributes=tuple(sorted(attrs)))


DEFAULT_BUSBAR_WEIGHT = 0.7
DEFAULT_WIRE_LABEL_HEIGHT = 2.5


@dataclass(frozen=True, kw_only=True)
class Wire(Entity):
    """Orthogonal wire. ``label`` is shown at the longest segment; ``label_side``
    1 puts it above (horizontal) or left (vertical), -1 below or right.
    ``label_align`` "left", "center" or "right" places it along the segment in
    reading direction (vertical labels read bottom to top)."""

    points: tuple[Point, ...]
    label: str = ""
    label_side: int = 1
    label_height: float = DEFAULT_WIRE_LABEL_HEIGHT
    label_align: str = "center"
    # "auto" (longest segment), "start", "end" or "free" at ``label_at`` mm along the wire.
    label_pos: str = "auto"
    label_at: float = 0.0
    # Cable this conductor belongs to (e.g. "-W1"), for the cable list; the label is
    # taken as the cable type.
    cable: str = ""

    def _mapped(self, fn, quarters):
        return replace(self, points=tuple(fn(p) for p in self.points))


@dataclass(frozen=True, kw_only=True)
class Busbar(Entity):
    """Bus bar; wires may connect anywhere along it."""

    p1: Point
    p2: Point

    def _mapped(self, fn, quarters):
        return replace(self, p1=fn(self.p1), p2=fn(self.p2))


@dataclass(frozen=True, kw_only=True)
class Viewport(Entity):
    """Window on a sheet showing part of the model.

    ``p1``/``p2`` are opposite corners on the sheet, ``center`` is the model
    point shown in the middle and ``scale`` is sheet mm per model mm
    (1 = 1:1, 0.5 = 1:2, 2 = 2:1).
    """

    p1: Point
    p2: Point
    center: Point
    scale: float = 1.0
    locked: bool = False
    print_border: bool = False

    def _mapped(self, fn, quarters):
        return replace(self, p1=fn(self.p1), p2=fn(self.p2))

    @property
    def left(self) -> float:
        return min(self.p1.x, self.p2.x)

    @property
    def top(self) -> float:
        return min(self.p1.y, self.p2.y)

    @property
    def width(self) -> float:
        return abs(self.p2.x - self.p1.x)

    @property
    def height(self) -> float:
        return abs(self.p2.y - self.p1.y)

    @property
    def sheet_center(self) -> Point:
        return Point(self.left + self.width / 2, self.top + self.height / 2)

    def model_to_sheet(self, p: Point) -> Point:
        c = self.sheet_center
        return Point(
            c.x + (p.x - self.center.x) * self.scale, c.y + (p.y - self.center.y) * self.scale
        )

    def sheet_to_model(self, p: Point) -> Point:
        c = self.sheet_center
        return Point(
            self.center.x + (p.x - c.x) / self.scale, self.center.y + (p.y - c.y) / self.scale
        )

    def model_rect(self) -> tuple[Point, Point]:
        """Top left and bottom right of the model area shown."""
        hw, hh = self.width / 2 / self.scale, self.height / 2 / self.scale
        return (
            Point(self.center.x - hw, self.center.y - hh),
            Point(self.center.x + hw, self.center.y + hh),
        )

    def contains(self, p: Point) -> bool:
        return (
            self.left <= p.x <= self.left + self.width and self.top <= p.y <= self.top + self.height
        )


DIMENSION_ORIENTATIONS = ("horizontal", "vertical", "aligned", "angular")


@dataclass(frozen=True, kw_only=True)
class Dimension(Entity):
    """Linear dimension between ``p1`` and ``p2``; the dimension line passes through
    ``position``. ``orientation`` measures the horizontal or vertical distance, or the
    true distance ("aligned"). ``text`` replaces the measured value when not empty.

    "angular" measures the angle at ``vertex`` between the legs through ``p1`` and
    ``p2``; the arc passes through ``position`` and lies in the sector containing it."""

    p1: Point
    p2: Point
    position: Point
    orientation: str = "aligned"
    text: str = ""
    height: float = 2.5
    vertex: Point | None = None

    def _mapped(self, fn, quarters):
        orientation = self.orientation
        if quarters % 2 and orientation in ("horizontal", "vertical"):
            orientation = "vertical" if orientation == "horizontal" else "horizontal"
        return replace(
            self,
            p1=fn(self.p1),
            p2=fn(self.p2),
            position=fn(self.position),
            orientation=orientation,
            vertex=fn(self.vertex) if self.vertex is not None else None,
        )


@dataclass(frozen=True, kw_only=True)
class InterruptionPoint(Entity):
    """Where a conductor leaves a page and continues on another one.

    Points with the same ``name`` (e.g. "L1", "-X1:3") belong together; each shows
    where its partner sits ("/3.4": page 3, column 4). ``direction`` points the way the
    conductor runs on (degrees, 0 right, counter-clockwise).
    """

    position: Point
    name: str
    direction: float = 0
    height: float = 2.5

    def _mapped(self, fn, quarters):
        return replace(
            self, position=fn(self.position), direction=(self.direction + 90 * quarters) % 360
        )

    def mirrored(self, axis: Point, horizontal: bool) -> Self:
        flipped = (-self.direction if horizontal else 180.0 - self.direction) % 360
        return replace(
            self, position=mirror_point(self.position, axis, horizontal), direction=flipped
        )


@dataclass(frozen=True, kw_only=True)
class JunctionMark(Entity):
    """Manual override of the automatic connection dot at ``position``.

    ``connected`` True forces a dot, False suppresses an automatic one.
    """

    position: Point
    connected: bool = True

    def _mapped(self, fn, quarters):
        return replace(self, position=fn(self.position))
