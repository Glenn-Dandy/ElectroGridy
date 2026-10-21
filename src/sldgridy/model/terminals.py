"""Terminals on wires: strips, free numbers and placing a terminal into a wire. Pure
Python.

A terminal is a block with the role "terminal" whose tag names strip and number
("-X1:3"). It is set on a wire and opens it, like any symbol placed into a wire.

Terminals in vertical conductors side by side on one horizontal line are labelled as a
row, readable from the left: the strip left of the first terminal, each terminal's
number right of it ("-X1 (1) 1 (2) 2 (3) 3"). A terminal on another line, of another
strip or further away starts a new row with the strip again.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import replace

from sldgridy.model.blocks import BlockDefinition, world_connections
from sldgridy.model.devices import _natural, devices
from sldgridy.model.document import Document
from sldgridy.model.entities import BlockReference, Entity, Wire, new_id
from sldgridy.model.geometry import Point
from sldgridy.model.routing import open_wires
from sldgridy.model.wires import EPS, on_segment, segments

TERMINAL, TERMINAL_PE = "Klemme", "Klemme PE"
SPARE = 10  # free numbers offered beyond the highest one used
ROW_GAP = 10.0  # mm: terminals further apart on one line start a new row (two poles)


def normalized_strip(text: str) -> str:
    """ "X2", "-X2 " and "-X2:" all mean the strip -X2."""
    text = text.strip().rstrip(":").strip()
    return text if not text or text.startswith("-") else f"-{text}"


def strips(doc: Document) -> dict[str, list[str]]:
    """Strip -> terminal numbers used on it (naturally sorted)."""
    found: dict[str, set[str]] = {}
    for bmk, group in devices(doc).items():
        if any(occ.function == "terminal" for occ in group) and ":" in bmk:
            strip, _, number = bmk.partition(":")
            found.setdefault(strip, set()).add(number)
    return {s: sorted(found[s], key=_natural) for s in sorted(found, key=_natural)}


def free_numbers(used: list[str], spare: int = SPARE) -> list[str]:
    """Numbers not yet used: the gaps, then the next ``spare`` ones."""
    taken = {int(n) for n in used if re.fullmatch(r"\d+", n)}
    top = max(taken, default=0)
    return [str(n) for n in range(1, top + spare + 1) if n not in taken]


def place_terminal(
    wires: list[Wire],
    p: Point,
    definition: BlockDefinition,
    bmk: str,
    layer: str,
) -> tuple[BlockReference, list[str], list[Wire]] | None:
    """A terminal centred on ``p`` along the wire through it, and the wire change
    (ids removed, wires added); None if ``p`` is not on a straight piece of a wire."""
    pins = definition.connection_points()
    if len(pins) < 2:
        return None
    blocks: Mapping[str, BlockDefinition] = {definition.name: definition}
    for wire in wires:
        for a, b in segments(wire.points):
            if not on_segment(p, a, b):
                continue
            vertical = abs(a.x - b.x) <= EPS
            for rotation in (0, 180) if vertical else (90, 270):
                probe = BlockReference(
                    id="", name=definition.name, insert=Point(0, 0), rotation=rotation
                )
                world = world_connections(probe, blocks)
                cx = sum(c.position.x for c in world[:2]) / 2
                cy = sum(c.position.y for c in world[:2]) / 2
                ref = replace(
                    probe,
                    id=new_id(),
                    insert=Point(round(p.x - cx, 6), round(p.y - cy, 6)),
                    layer=layer,
                    attributes=(("BMK", bmk),),
                )
                placed = world_connections(ref, blocks)
                if all(on_segment(c.position, a, b) for c in placed[:2]):
                    removed, added = open_wires([wire], placed)
                    return ref, removed, added
    return None


def terminal_center(
    ref: BlockReference, blocks: Mapping[str, BlockDefinition]
) -> tuple[Point, bool] | None:
    """Middle between the two connection points of a terminal and whether it sits in a
    vertical conductor; None for other symbols."""
    definition = blocks.get(ref.name)
    if definition is None or definition.function != "terminal":
        return None
    pins = world_connections(ref, blocks)
    if len(pins) < 2:
        return None
    a, b = pins[0].position, pins[1].position
    return Point((a.x + b.x) / 2, (a.y + b.y) / 2), abs(a.x - b.x) <= EPS


def row_labels(
    entities: Iterable[Entity], blocks: Mapping[str, BlockDefinition]
) -> dict[str, tuple[str, str]]:
    """Terminal id -> (strip shown left of it, "" inside a row; number shown right of
    it) for the terminals in vertical conductors of one drawing area."""
    found: dict[tuple[str, float], list[tuple[float, str, str]]] = {}
    for e in entities:
        if not isinstance(e, BlockReference):
            continue
        place = terminal_center(e, blocks)
        if place is None or not place[1]:
            continue
        definition = blocks[e.name]
        default = next(
            (a.default for a in definition.attribute_definitions() if a.tag == "BMK"), ""
        )
        strip, colon, number = e.attribute("BMK", default).partition(":")
        if not colon:
            continue
        center = place[0]
        found.setdefault((strip.strip(), round(center.y, 2)), []).append(
            (center.x, e.id, number.strip())
        )
    labels: dict[str, tuple[str, str]] = {}
    for (strip, _y), row in found.items():
        row.sort()
        previous = None
        for x, ref_id, number in row:
            first = previous is None or x - previous > ROW_GAP + EPS
            labels[ref_id] = (strip if first else "", number)
            previous = x
    return labels
