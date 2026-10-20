"""Block definitions and the expansion of block references into plain entities."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace

from sldgridy.model.container import EntityContainer
from sldgridy.model.entities import (
    Arc,
    AttributeDefinition,
    BlockReference,
    Circle,
    ConnectionPoint,
    Entity,
    Line,
    Polyline,
    Rectangle,
    Text,
)
from sldgridy.model.geometry import Point, mirror_point, rotate_quarter
from sldgridy.model.layers import DEFAULT_LAYER
from sldgridy.model.scale import scale_entity

MAX_NESTING = 32


@dataclass
class BlockDefinition:
    name: str
    base_point: Point = field(default_factory=lambda: Point(0.0, 0.0))
    entities: EntityContainer = field(default_factory=EntityContainer)
    category: str = ""
    description: str = ""

    def attribute_definitions(self) -> list[AttributeDefinition]:
        return [e for e in self.entities if isinstance(e, AttributeDefinition)]

    def connection_points(self) -> list[ConnectionPoint]:
        return [e for e in self.entities if isinstance(e, ConnectionPoint)]

    def copy(self, name: str | None = None) -> "BlockDefinition":
        return BlockDefinition(
            name=self.name if name is None else name,
            base_point=self.base_point,
            entities=EntityContainer(list(self.entities)),
            category=self.category,
            description=self.description,
        )


class BlockError(ValueError):
    pass


def referenced_names(entities: Iterable[Entity]) -> set[str]:
    return {e.name for e in entities if isinstance(e, BlockReference)}


def dependencies(name: str, blocks: Mapping[str, BlockDefinition]) -> list[str]:
    """All block names ``name`` needs (itself first, then nested), without duplicates."""
    order: list[str] = []
    stack = [name]
    while stack:
        n = stack.pop()
        if n in order:
            continue
        order.append(n)
        definition = blocks.get(n)
        if definition is not None:
            stack.extend(sorted(referenced_names(definition.entities)))
    return order


def would_create_cycle(
    name: str, entities: Iterable[Entity], blocks: Mapping[str, BlockDefinition]
) -> bool:
    """True if a definition ``name`` holding ``entities`` would reference itself."""
    seen: set[str] = set()
    stack = list(referenced_names(entities))
    while stack:
        n = stack.pop()
        if n == name:
            return True
        if n in seen:
            continue
        seen.add(n)
        definition = blocks.get(n)
        if definition is not None:
            stack.extend(referenced_names(definition.entities))
    return False


def to_world(ref: BlockReference, base: Point, e: Entity) -> Entity:
    """Map a definition entity into drawing coordinates of ``ref``."""
    e = e.translated(-base.x, -base.y)
    if ref.scale != 1.0:
        e = scale_entity(e, Point(0.0, 0.0), ref.scale)
    if ref.mirrored_x:
        e = e.mirrored(Point(0.0, 0.0), horizontal=False)
    e = e.rotated(Point(0.0, 0.0), ref.rotation // 90)
    return e.translated(ref.insert.x, ref.insert.y)


def point_to_world(ref: BlockReference, base: Point, p: Point) -> Point:
    probe = ConnectionPoint(id="", name="", position=p)
    return to_world(ref, base, probe).position


def point_to_local(ref: BlockReference, base: Point, p: Point) -> Point:
    """Inverse of ``point_to_world``: drawing point in definition coordinates."""
    origin = Point(0.0, 0.0)
    q = Point(p.x - ref.insert.x, p.y - ref.insert.y)
    q = rotate_quarter(q, origin, -(ref.rotation // 90))
    if ref.mirrored_x:
        q = mirror_point(q, origin, horizontal=False)
    if ref.scale != 1.0:
        q = Point(q.x / ref.scale, q.y / ref.scale)
    return Point(round(q.x + base.x, 6), round(q.y + base.y, 6))


_FLIP_HALIGN = {"left": "right", "right": "left", "center": "center"}


def readable(text: Text) -> Text:
    """Turn upside-down (180) or downward (270) text into 0 or 90 around the same anchor."""
    if text.rotation % 360 not in (180, 270):
        return text
    return replace(
        text, rotation=(text.rotation - 180) % 360, halign=_FLIP_HALIGN.get(text.halign, "left")
    )


def _inherit(ref: BlockReference, e: Entity) -> Entity:
    """Entities on layer 0 take layer and style of the reference."""
    if e.layer != DEFAULT_LAYER:
        return e
    return replace(
        e,
        layer=ref.layer,
        color=e.color if e.color is not None else ref.color,
        lineweight=e.lineweight if e.lineweight is not None else ref.lineweight,
        linetype=e.linetype if e.linetype is not None else ref.linetype,
    )


ATTRIBUTE_GAP_ABOVE = 1.5  # mm between a lying symbol and its attributes above it
ATTRIBUTE_LINE_FACTOR = 1.4  # line pitch as a multiple of the text height


def bounds(entities: Iterable[Entity]) -> tuple[float, float, float, float] | None:
    """Rough bounding box (min x, min y, max x, max y) of drawn geometry."""
    xs: list[float] = []
    ys: list[float] = []
    for e in entities:
        if isinstance(e, Line):
            pts = [e.p1, e.p2]
        elif isinstance(e, Polyline):
            pts = list(e.points)
        elif isinstance(e, Rectangle):
            pts = [e.p1, e.p2]
        elif isinstance(e, Circle | Arc):
            r = e.radius
            pts = [Point(e.center.x - r, e.center.y - r), Point(e.center.x + r, e.center.y + r)]
        elif isinstance(e, Text):
            pts = [e.position]
        else:
            continue
        xs += [p.x for p in pts]
        ys += [p.y for p in pts]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


COLUMN_TOLERANCE = 0.5  # mm: attributes this close in x form one column


def value_lines(value: str) -> list[str]:
    """Lines of an attribute value; line breaks are entered by the user."""
    return value.replace("\r\n", "\n").split("\n")


def line_pitch(a: AttributeDefinition) -> float:
    return a.height * ATTRIBUTE_LINE_FACTOR


def _attribute_texts(
    ref: BlockReference, definition: BlockDefinition, geometry: list[Entity]
) -> list[Text]:
    """Attribute values of a reference, always horizontal and readable.

    Unrotated references keep the positions of the definition. Rotated or
    mirrored ones place the non-empty values as a left-aligned block: above
    the symbol when it lies (90/270 degrees), right of it otherwise.

    A value may contain line breaks: every line becomes its own text one line
    pitch lower, and the attributes below it in the same column move down.
    """
    attdefs = [a for a in definition.attribute_definitions() if a.visible]
    if not attdefs:
        return []
    if ref.rotation % 360 == 0 and not ref.mirrored_x:
        texts: list[Text] = []
        for a in attdefs:
            shift = sum(
                (len(value_lines(ref.attribute(o.tag, o.default))) - 1) * line_pitch(o)
                for o in attdefs
                if o is not a
                and abs(o.position.x - a.position.x) <= COLUMN_TOLERANCE
                and o.position.y < a.position.y
            )
            for n, line in enumerate(value_lines(ref.attribute(a.tag, a.default))):
                moved = replace(
                    a,
                    id=a.id if n == 0 else f"{a.id}~{n}",
                    position=Point(a.position.x, a.position.y + shift + n * line_pitch(a)),
                )
                texts.append(readable(to_world(ref, definition.base_point, moved).as_text(line)))
        return texts
    world_bounds = bounds(geometry)
    local_bounds = bounds(
        e for e in definition.entities if not isinstance(e, AttributeDefinition | ConnectionPoint)
    )
    if world_bounds is None:
        return []
    min_x, min_y, max_x, max_y = world_bounds
    ordered = sorted(attdefs, key=lambda a: (a.position.y, a.position.x))
    lines = [
        (a if n == 0 else replace(a, id=f"{a.id}~{n}"), line)
        for a in ordered
        for n, line in enumerate(value_lines(ref.attribute(a.tag, a.default)))
    ]
    lines = [(a, v) for a, v in lines if v.strip()]
    if not lines:
        return []
    pitch = max(a.height for a, _ in lines) * ATTRIBUTE_LINE_FACTOR
    gap_right = 2.5
    if local_bounds is not None:
        gap_right = max(1.0, min(a.position.x for a in attdefs) - local_bounds[2])
    if ref.rotation % 180 == 90:
        x = min_x
        last_center = min_y - ATTRIBUTE_GAP_ABOVE - lines[-1][0].height / 2
        first_center = last_center - pitch * (len(lines) - 1)
    else:
        x = max_x + gap_right
        first_center = (min_y + max_y) / 2 - pitch * (len(lines) - 1) / 2
    return [
        Text(
            id=a.id,
            layer=a.layer,
            color=a.color,
            lineweight=a.lineweight,
            linetype=a.linetype,
            position=Point(x, first_center + i * pitch),
            text=value,
            height=a.height,
            rotation=0,
            halign="left",
            valign="middle",
        )
        for i, (a, value) in enumerate(lines)
    ]


def explode(
    ref: BlockReference, blocks: Mapping[str, BlockDefinition], keep_ids: bool = False
) -> list[Entity]:
    """One level of a reference as drawing entities.

    Attribute definitions become horizontal texts with the reference's values
    (invisible ones are dropped), connection points are dropped, nested
    references stay.
    """
    definition = blocks.get(ref.name)
    if definition is None:
        return []
    geometry: list[Entity] = []
    for e in definition.entities:
        if isinstance(e, ConnectionPoint | AttributeDefinition):
            continue
        geometry.append(to_world(ref, definition.base_point, e))
    texts = _attribute_texts(ref, definition, geometry)
    out = geometry + texts
    if not keep_ids:
        out = [e.with_new_id() for e in out]
    return [_inherit(ref, e) for e in out]


def expand(
    ref: BlockReference, blocks: Mapping[str, BlockDefinition], depth: int = 0
) -> list[Entity]:
    """All drawing entities of a reference, nested references resolved."""
    if depth > MAX_NESTING:
        raise BlockError(f"block nesting too deep at {ref.name!r}")
    out: list[Entity] = []
    for e in explode(ref, blocks, keep_ids=True):
        if isinstance(e, BlockReference):
            out.extend(expand(e, blocks, depth + 1))
        else:
            out.append(e)
    return out


def world_connections(
    ref: BlockReference, blocks: Mapping[str, BlockDefinition]
) -> list[ConnectionPoint]:
    """Connection points of the reference (its definition's and its own docks) in drawing
    coordinates."""
    definition = blocks.get(ref.name)
    if definition is None:
        return []
    points = list(definition.connection_points())
    if ref.docks:
        box = symbol_bounds(definition)
        points += [
            ConnectionPoint(
                id=f"dock{i}", name=f"A{i + 1}", position=p, direction=_edge_direction(box, p)
            )
            for i, p in enumerate(ref.docks)
        ]
    return [to_world(ref, definition.base_point, c) for c in points]


def symbol_bounds(definition: BlockDefinition) -> tuple[float, float, float, float] | None:
    """Bounds of the drawn symbol in definition coordinates (without texts and helpers)."""
    return bounds(
        e
        for e in definition.entities
        if not isinstance(e, AttributeDefinition | ConnectionPoint | Text)
    )


def _edge_direction(box: tuple[float, float, float, float] | None, p: Point) -> float:
    """Direction pointing out of the nearest edge of ``box`` (Y down: top is 90)."""
    if box is None:
        return 0.0
    min_x, min_y, max_x, max_y = box
    edges = [(p.x - min_x, 180.0), (max_x - p.x, 0.0), (p.y - min_y, 90.0), (max_y - p.y, 270.0)]
    return min(edges, key=lambda e: abs(e[0]))[1]


def dock_target(
    ref: BlockReference, blocks: Mapping[str, BlockDefinition], p: Point, tolerance: float
) -> Point | None:
    """Definition coordinates for a new dock at drawing point ``p``, or None if ``p`` is
    not on the symbol or already a connection point of it."""
    definition = blocks.get(ref.name)
    if definition is None:
        return None
    if any(
        abs(c.position.x - p.x) <= 1e-6 and abs(c.position.y - p.y) <= 1e-6
        for c in world_connections(ref, blocks)
    ):
        return None
    box = symbol_bounds(definition)
    if box is None:
        return None
    local = point_to_local(ref, definition.base_point, p)
    min_x, min_y, max_x, max_y = box
    inside = (
        min_x - tolerance <= local.x <= max_x + tolerance
        and min_y - tolerance <= local.y <= max_y + tolerance
    )
    return local if inside else None
