"""Which connection points are connected: nets of wires, bus bars and interruption
points. Pure Python.

Within one drawing area (the model or a page) a wire connects all its vertices; a
wire end lying on another wire or a bus bar joins it; a connection point of a block
joins the wire ends and bus bars at its position. Interruption points with the same
name join nets across pages. Positions are compared rounded to 1/1000 mm.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from electrogridy.model.blocks import BlockDefinition, world_connections
from electrogridy.model.devices import bmk_of
from electrogridy.model.document import Document
from electrogridy.model.entities import BlockReference, Busbar, Entity, InterruptionPoint, Wire
from electrogridy.model.geometry import Point

EPS = 1e-6


def _key(area: str, p: Point) -> tuple[str, float, float]:
    return area, round(p.x, 3), round(p.y, 3)


def _on_segment(p: Point, a: Point, b: Point) -> bool:
    if not (min(a.x, b.x) - EPS <= p.x <= max(a.x, b.x) + EPS):
        return False
    if not (min(a.y, b.y) - EPS <= p.y <= max(a.y, b.y) + EPS):
        return False
    cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
    length = max(abs(b.x - a.x), abs(b.y - a.y), EPS)
    return abs(cross) / length <= 1e-3


class _Union:
    def __init__(self) -> None:
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


@dataclass(frozen=True)
class Pin:
    """A connection point of a device: "-K1" pin "A1" (block reference ``entity_id``)."""

    bmk: str
    name: str
    entity_id: str
    area: str  # "model" or a page id


@dataclass(frozen=True)
class WireEnds:
    """A wire's two ends as net ids (for the cable list)."""

    wire: Wire
    area: str
    start: object
    end: object


class Netlist:
    def __init__(self) -> None:
        self._u = _Union()
        self.pins: list[tuple[Pin, object]] = []  # pin and its node
        self.wires: list[tuple[Wire, str, object, object]] = []

    def net(self, node) -> object:
        return self._u.find(node)

    def pins_of_net(self, net) -> list[Pin]:
        return [pin for pin, node in self.pins if self._u.find(node) == net]

    def net_of_pin(self, entity_id: str, name: str):
        for pin, node in self.pins:
            if pin.entity_id == entity_id and pin.name == name:
                return self._u.find(node)
        return None

    def wire_ends(self) -> list[WireEnds]:
        """Each wire with the positions (nodes) of its two ends, not their nets: a
        conductor joins both ends, the cable list needs what sits at either end."""
        return [WireEnds(w, area, a, b) for w, area, a, b in self.wires]

    def pins_at(self, node) -> list[Pin]:
        """Connection points exactly at a position node."""
        return [pin for pin, n in self.pins if n == node]


def _add_area(
    nl: Netlist, area: str, entities: Iterable[Entity], blocks: dict[str, BlockDefinition]
) -> None:
    u = nl._u
    conductors: list[tuple[list[Point], object]] = []
    for e in entities:
        if isinstance(e, Wire) and len(e.points) >= 2:
            first = _key(area, e.points[0])
            for p in e.points[1:]:
                u.union(first, _key(area, p))
            conductors.append((list(e.points), first))
            nl.wires.append((e, area, first, _key(area, e.points[-1])))
        elif isinstance(e, Busbar):
            a = _key(area, e.p1)
            u.union(a, _key(area, e.p2))
            conductors.append(([e.p1, e.p2], a))
        elif isinstance(e, InterruptionPoint) and e.name.strip():
            u.union(_key(area, e.position), ("interruption", e.name.strip()))
            conductors.append(([e.position], _key(area, e.position)))
    # Ends (and connection points) lying on a conductor join it.
    ends: list[Point] = []
    for points, _node in conductors:
        ends += [points[0], points[-1]]
    for e in entities:
        if isinstance(e, BlockReference):
            bmk = bmk_of(e)
            for c in world_connections(e, blocks):
                node = _key(area, c.position)
                u.find(node)
                ends.append(c.position)
                if bmk:
                    nl.pins.append((Pin(bmk, c.name, e.id, area), node))
    for p in ends:
        for points, node in conductors:
            if len(points) == 1:
                if abs(points[0].x - p.x) <= EPS and abs(points[0].y - p.y) <= EPS:
                    u.union(_key(area, p), node)
                continue
            if any(_on_segment(p, a, b) for a, b in zip(points, points[1:], strict=False)):
                u.union(_key(area, p), node)


def netlist(doc: Document) -> Netlist:
    """Nets of the model and of all pages."""
    nl = Netlist()
    _add_area(nl, "model", doc.model_space, doc.blocks)
    for page in doc.sheets:
        _add_area(nl, page.id, page.entities, doc.blocks)
    return nl
