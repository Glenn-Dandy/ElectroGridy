"""Cable marks: a line across the conductors of one cable with its name ("-W1") at the
start and the core of each conductor next to the crossing. Pure Python.

The mark holds name and type; the cores belong to the wires (``Wire.cable``,
``Wire.core``), so terminal plan and cable list read them where they always did.
"""

import re
from collections.abc import Iterable
from dataclasses import replace

from sldgridy.model.document import Document
from sldgridy.model.entities import CableMark, Entity, InterruptionPoint, Line, Text, Wire
from sldgridy.model.geometry import Point
from sldgridy.model.wires import EPS, segments

CORE_HEIGHT = 1.5  # mm, fits between conductors 5 mm apart ("GNYE")
NAME_GAP = 1.5  # mm between the line and the cable name
CORE_GAP = 0.6  # mm between conductor or line and a core text
OVERHANG = 2.5  # mm the line reaches beyond the outer conductors

# Core colours to IEC 60757 for the usual low voltage cables, by number of cores.
COLOR_CORES = {
    1: ["BN"],
    2: ["BN", "BU"],
    3: ["BN", "BU", "GNYE"],
    4: ["BN", "BK", "GY", "GNYE"],
    5: ["BN", "BK", "GY", "BU", "GNYE"],
}


def default_cores(count: int) -> list[str]:
    """Cores proposed for ``count`` conductors in drawing order: colours up to five,
    beyond that numbers and the protective conductor last."""
    if count in COLOR_CORES:
        return list(COLOR_CORES[count])
    return [str(i) for i in range(1, count)] + ["GNYE"] if count > 0 else []


def is_horizontal(mark: CableMark) -> bool:
    return abs(mark.p2.x - mark.p1.x) >= abs(mark.p2.y - mark.p1.y)


def _span(mark: CableMark) -> tuple[Point, Point]:
    """Both ends, the left (upper) one first."""
    a, b = mark.p1, mark.p2
    key = (lambda p: p.x) if is_horizontal(mark) else (lambda p: p.y)
    return (a, b) if key(a) <= key(b) else (b, a)


def crossings(mark: CableMark, entities: Iterable[Entity]) -> list[tuple[Point, Wire]]:
    """Wires crossing the mark, one point each, in order along the mark."""
    a, b = _span(mark)
    horizontal = is_horizontal(mark)
    found = []
    for e in entities:
        if not isinstance(e, Wire):
            continue
        for s, t in segments(e.points):
            if horizontal:
                y = a.y
                if abs(s.x - t.x) > EPS or not a.x - EPS <= s.x <= b.x + EPS:
                    continue
                if min(s.y, t.y) - EPS <= y <= max(s.y, t.y) + EPS:
                    found.append((Point(s.x, y), e))
                    break
            else:
                x = a.x
                if abs(s.y - t.y) > EPS or not a.y - EPS <= s.y <= b.y + EPS:
                    continue
                if min(s.x, t.x) - EPS <= x <= max(s.x, t.x) + EPS:
                    found.append((Point(x, s.y), e))
                    break
    found.sort(key=lambda pw: pw[0].x if horizontal else pw[0].y)
    return found


def fitted(mark: CableMark, entities: Iterable[Entity]) -> CableMark:
    """The mark reaching ``OVERHANG`` beyond the outer conductors it crosses (clicked
    right on them, it would end on the conductor)."""
    found = crossings(mark, entities)
    if not found:
        return mark
    a, b = _span(mark)
    if is_horizontal(mark):
        xs = [p.x for p, _w in found]
        lo, hi = min(a.x, min(xs) - OVERHANG), max(b.x, max(xs) + OVERHANG)
        return replace(mark, p1=Point(lo, a.y), p2=Point(hi, a.y))
    ys = [p.y for p, _w in found]
    lo, hi = min(a.y, min(ys) - OVERHANG), max(b.y, max(ys) + OVERHANG)
    return replace(mark, p1=Point(a.x, lo), p2=Point(a.x, hi))


PROTECTIVE = {"PE", "PEN", "GNYE"}
OUTER_CORES = ["BN", "BK", "GY"]


def _role(names: set[str]) -> str:
    """ "PE", "N" or "L" from the terminal and interruption names of a conductor's net;
    "" when nothing tells."""
    upper = {n.upper() for n in names}
    if upper & PROTECTIVE:
        return "PE"
    if "N" in upper:
        return "N"
    if upper & {"L", "L1", "L2", "L3", "L+", "L-"} or any(n.isdigit() for n in upper):
        return "L"
    return ""


def suggested_cores(doc: Document, area: str, wires: list[Wire]) -> list[str]:
    """Cores for the crossed ``wires`` from what they connect to: a PE or PEN terminal
    or rail gives GNYE, N gives BU, the outer conductors BN, BK, GY in order. Without
    any hint the colours by number of cores (``default_cores``)."""
    from sldgridy.model.netlist import netlist

    nl = netlist(doc)
    net_of = {(w.id, a): nl.net(first) for w, a, first, _last in nl.wires}
    names_of: dict[object, set[str]] = {}
    for pin, node in nl.pins:
        _strip, colon, number = pin.bmk.partition(":")
        if colon and number.strip():
            names_of.setdefault(nl.net(node), set()).add(number.strip())
    for container in (doc.model_space, *(s.entities for s in doc.sheets)):
        for e in container:
            if isinstance(e, InterruptionPoint) and e.name.strip():
                net = nl.net(("interruption", e.name.strip()))
                names_of.setdefault(net, set()).add(e.name.strip().rpartition(":")[2])
    roles = [_role(names_of.get(net_of.get((w.id, area)), set())) for w in wires]
    if not any(roles):
        return default_cores(len(wires))
    out, outer = [], 0
    for role in roles:
        if role == "PE":
            out.append("GNYE")
        elif role == "N":
            out.append("BU")
        else:
            out.append(OUTER_CORES[outer] if outer < len(OUTER_CORES) else str(outer + 1))
            outer += 1
    return out


def cable_mark_geometry(mark: CableMark, cores: list[tuple[Point, str]]) -> list[Entity]:
    """Line, name and core texts of a mark (``cores``: crossing and core)."""
    a, b = _span(mark)
    style = {"layer": mark.layer, "color": mark.color}
    parts: list[Entity] = [
        Line(id=f"{mark.id}:line", p1=a, p2=b, lineweight=mark.lineweight, **style)
    ]
    h = mark.height
    if is_horizontal(mark):
        if mark.name:
            parts.append(
                Text(
                    id=f"{mark.id}:name",
                    position=Point(a.x - NAME_GAP, a.y),
                    text=mark.name,
                    height=h,
                    halign="right",
                    valign="middle",
                    **style,
                )
            )
        for i, (p, core) in enumerate(cores):
            if core:
                parts.append(
                    Text(
                        id=f"{mark.id}:core{i}",
                        position=Point(p.x + CORE_GAP, p.y + CORE_GAP + CORE_HEIGHT),
                        text=core,
                        height=CORE_HEIGHT,
                        **style,
                    )
                )
        return parts
    # Across horizontal conductors: texts read upwards, the name above the line.
    if mark.name:
        parts.append(
            Text(
                id=f"{mark.id}:name",
                position=Point(a.x, a.y - NAME_GAP),
                text=mark.name,
                height=h,
                rotation=90,
                valign="middle",
                **style,
            )
        )
    for i, (p, core) in enumerate(cores):
        if core:
            parts.append(
                Text(
                    id=f"{mark.id}:core{i}",
                    position=Point(p.x + CORE_GAP + CORE_HEIGHT, p.y - CORE_GAP),
                    text=core,
                    height=CORE_HEIGHT,
                    rotation=90,
                    **style,
                )
            )
    return parts


def mark_cores(doc: Document) -> dict[str, list[tuple[Point, str]]]:
    """Mark id -> crossings with the core of each crossed wire, for every drawing area."""
    out: dict[str, list[tuple[Point, str]]] = {}
    for container in (doc.model_space, *(s.entities for s in doc.sheets)):
        marks = [e for e in container if isinstance(e, CableMark)]
        if not marks:
            continue
        wires = [e for e in container if isinstance(e, Wire)]
        for m in marks:
            out[m.id] = [(p, w.core) for p, w in crossings(m, wires)]
    return out


def cable_types(doc: Document) -> dict[str, str]:
    """Cable name -> type given at its marks."""
    out: dict[str, str] = {}
    for container in (doc.model_space, *(s.entities for s in doc.sheets)):
        for e in container:
            if isinstance(e, CableMark) and e.name.strip() and e.cable_type.strip():
                out.setdefault(e.name.strip(), e.cable_type.strip())
    return out


_NUMBERED = re.compile(r"^-W(\d+)$")


def used_cables(doc: Document) -> set[str]:
    names = set()
    for container in (doc.model_space, *(s.entities for s in doc.sheets)):
        for e in container:
            if isinstance(e, CableMark) and e.name.strip():
                names.add(e.name.strip())
            elif isinstance(e, Wire) and e.cable.strip():
                names.add(e.cable.strip())
    return names


def next_cable_name(names: Iterable[str]) -> str:
    """-W1, then the number after the highest one used."""
    numbers = [int(m.group(1)) for n in names if (m := _NUMBERED.match(n))]
    return f"-W{max(numbers, default=0) + 1}"


def assigned(wires: list[Wire], name: str, cores: list[str]) -> list[Wire]:
    """The crossed wires with cable and core set."""
    return [replace(w, cable=name, core=core) for w, core in zip(wires, cores, strict=False)]
