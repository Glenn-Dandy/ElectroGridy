"""Terminals on wires: strips, free numbers and placing a terminal into a wire. Pure
Python.

A terminal is a block with the role "terminal" whose tag names strip and number
("-X1:3"). It is set on a wire and opens it, like any symbol placed into a wire.
"""

import re
from collections.abc import Mapping
from dataclasses import replace

from sldgridy.model.blocks import BlockDefinition, world_connections
from sldgridy.model.devices import _natural, devices
from sldgridy.model.document import Document
from sldgridy.model.entities import BlockReference, Wire, new_id
from sldgridy.model.geometry import Point
from sldgridy.model.routing import open_wires
from sldgridy.model.wires import EPS, on_segment, segments

TERMINAL, TERMINAL_PE = "Klemme", "Klemme PE"
SPARE = 10  # free numbers offered beyond the highest one used


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
