"""Terminal plan: each strip on its own pages, laid out like the usual terminal diagram
form. Pure Python.

A row is a terminal of the strip, in number order: a note, the cores of the cables on
its outer side, target 1 (outer side), the terminal symbol with bridges, colour, number,
target 2 (inner side), the cores of the cables on its inner side, page and column of the
terminal in the circuit diagram.

The outer side is the side with a cable, otherwise the upper (or left) connection. A
target is the nearest connection point along the conductors, not the whole net: on a
rail every device shares the net. Neighbouring terminals in one net are bridged (bridge
right of the symbols); all PE terminals of a strip are connected through the mounting
rail (drawn left of the symbols).
"""

import heapq
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from sldgridy.model.cables import cable_types
from sldgridy.model.devices import MODEL, SHEET, _natural, devices, place
from sldgridy.model.document import Document, SheetLayout
from sldgridy.model.entities import (
    BlockReference,
    Busbar,
    Circle,
    Entity,
    InterruptionPoint,
    Line,
    Text,
    Wire,
)
from sldgridy.model.geometry import Point
from sldgridy.model.netlist import Netlist, Pin, _key, _on_segment, netlist
from sldgridy.model.sheet import schematic_inner
from sldgridy.model.terminals import TERMINAL_PE
from sldgridy.model.title_block import SCHEMATIC_TITLE_HEIGHT

ROWS = 21  # terminals per page
COLOR, NOTE = "FARBE", "BEMERKUNG"  # attributes of the terminal symbol

# -- rows ---------------------------------------------------------------------------


@dataclass
class TerminalRow:
    number: str
    pe: bool = False
    color: str = ""
    note: str = ""
    target1: str = ""
    target2: str = ""
    cores1: dict[str, str] = field(default_factory=dict)  # cable -> core, outer side
    cores2: dict[str, str] = field(default_factory=dict)
    page: str = ""
    column: str = ""
    bmk: str = ""
    nets: tuple = ()


@dataclass
class StripPlan:
    strip: str
    rows: list[TerminalRow]
    cables1: list[tuple[str, str]]  # (cable, type) on the outer side, nearest first
    cables2: list[tuple[str, str]]
    bridges: list[tuple[int, int]]  # first and last row of each bridged run
    pe_rows: list[int]  # PE terminals joined by the mounting rail (two or more)


class _Graph:
    """Conductors as a graph of positions; edge length in mm. Interruption points of
    one name meet at a common node."""

    def __init__(self, doc: Document, nl: Netlist) -> None:
        self.edges: dict[object, list[tuple[object, float]]] = {}
        self.pins_at: dict[object, list[Pin]] = {}
        stops: dict[str, list[Point]] = {}
        for pin, node in nl.pins:
            self.pins_at.setdefault(node, []).append(pin)
            stops.setdefault(node[0], []).append(Point(node[1], node[2]))
        areas = [(MODEL, doc.model_space)] + [(p.id, p.entities) for p in doc.sheets]
        for area, entities in areas:
            self._add_area(area, list(entities), stops.get(area, []))

    def _link(self, a, b, length: float) -> None:
        self.edges.setdefault(a, []).append((b, length))
        self.edges.setdefault(b, []).append((a, length))

    def _add_area(self, area: str, entities: list[Entity], pins: list[Point]) -> None:
        runs: list[tuple[Point, ...]] = []
        for e in entities:
            if isinstance(e, Wire) and len(e.points) >= 2:
                runs.append(e.points)
            elif isinstance(e, Busbar):
                runs.append((e.p1, e.p2))
            elif isinstance(e, InterruptionPoint) and e.name.strip():
                self._link(_key(area, e.position), ("interruption", e.name.strip()), 0.0)
                pins = [*pins, e.position]
        stops = pins + [p for run in runs for p in (run[0], run[-1])]
        # Conductors run horizontally or vertically: look up the stops on their line.
        by_x: dict[float, list[Point]] = {}
        by_y: dict[float, list[Point]] = {}
        for p in stops:
            by_x.setdefault(round(p.x, 3), []).append(p)
            by_y.setdefault(round(p.y, 3), []).append(p)
        for run in runs:
            for a, b in zip(run, run[1:], strict=False):
                if abs(a.x - b.x) < 1e-6:
                    near = by_x.get(round(a.x, 3), [])
                elif abs(a.y - b.y) < 1e-6:
                    near = by_y.get(round(a.y, 3), [])
                else:
                    near = stops
                on = [p for p in near if _on_segment(p, a, b)] + [a, b]
                on.sort(key=lambda p: math.hypot(p.x - a.x, p.y - a.y))
                for p, q in zip(on, on[1:], strict=False):
                    self._link(_key(area, p), _key(area, q), math.hypot(q.x - p.x, q.y - p.y))

    def nearest(self, start, skip: set[str]) -> list[Pin]:
        """The connection points closest to ``start`` along the conductors, leaving out
        those of the block references in ``skip``."""
        best: float | None = None
        found: list[Pin] = []
        done: set = set()
        queue = [(0.0, 0, start)]
        count = 1
        while queue:
            d, _n, node = heapq.heappop(queue)
            if node in done:
                continue
            if best is not None and d > best + 1e-6:
                break
            done.add(node)
            for pin in self.pins_at.get(node, []):
                if pin.entity_id not in skip:
                    best = d if best is None else best
                    found.append(pin)
            for nxt, length in self.edges.get(node, []):
                if nxt not in done:
                    heapq.heappush(queue, (d + length, count, nxt))
                    count += 1
        return found


def _target_text(pins: Iterable[Pin]) -> str:
    # A terminal's tag already names the point (-X1:3).
    names = {p.bmk if ":" in p.bmk else f"{p.bmk}:{p.name}" for p in pins}
    return ", ".join(sorted(names, key=_natural))


def terminal_plan(doc: Document, nl: Netlist | None = None) -> list[StripPlan]:
    """Every strip with its terminals, cables and bridges, strips in natural order."""
    nl = nl or netlist(doc)
    refs: dict[str, BlockReference] = {}
    for container in [doc.model_space, *(p.entities for p in doc.sheets)]:
        for e in container:
            if isinstance(e, BlockReference):
                refs[e.id] = e
    pins_of: dict[str, list[tuple[Pin, object]]] = {}
    for pin, node in nl.pins:
        pins_of.setdefault(pin.entity_id, []).append((pin, node))
    wires_at: dict[object, list[Wire]] = {}
    cable_type: dict[str, str] = {}
    for wire, _area, first, last in nl.wires:
        for node in (first, last):
            wires_at.setdefault(node, []).append(wire)
        if wire.cable and wire.label and wire.cable not in cable_type:
            cable_type[wire.cable] = wire.label
    for cable, kind in cable_types(doc).items():  # given at the cable marks
        cable_type.setdefault(cable, kind)

    def cores(node) -> dict[str, str]:
        return {w.cable: w.core for w in wires_at.get(node, []) if w.cable}

    # Terminals per strip with both sides (outer first).
    found: dict[str, list[tuple[TerminalRow, str, list[tuple[Pin, object]]]]] = {}
    for bmk, group in devices(doc).items():
        for occ in group:
            if occ.function != "terminal":
                continue
            strip, _, number = bmk.partition(":")
            sides = sorted(pins_of.get(occ.entity_id, []), key=lambda pn: (pn[1][2], pn[1][1]))
            sides = sides[:2]
            if len(sides) == 2 and not cores(sides[0][1]) and cores(sides[1][1]):
                sides.reverse()
            attributes = dict(refs[occ.entity_id].attributes) if occ.entity_id in refs else {}
            pe = occ.block == TERMINAL_PE
            row = TerminalRow(
                number=number,
                pe=pe,
                color="PE" if pe else attributes.get(COLOR, "").strip(),
                note=attributes.get(NOTE, "").strip(),
                bmk=bmk,
                nets=tuple(nl.net(node) for _pin, node in sides),
            )
            if occ.where == SHEET and occ.layout_id is not None:
                page, column = place(doc, occ.layout_id, occ.position.x)
                row.page, row.column = str(page), "" if column is None else str(column)
            if sides:
                row.cores1 = cores(sides[0][1])
            if len(sides) > 1:
                row.cores2 = cores(sides[1][1])
            found.setdefault(strip, []).append((row, occ.entity_id, sides))

    graph = _Graph(doc, nl)
    plans = []
    for strip in sorted(found, key=_natural):
        entries = sorted(found[strip], key=lambda t: _natural(t[0].number))
        rows = [r for r, _id, _sides in entries]
        # Bridged runs: neighbouring (non-PE) terminals sharing a net.
        run_of = list(range(len(rows)))
        bridges = []
        start = 0
        for i in range(1, len(rows) + 1):
            joined = (
                i < len(rows)
                and not rows[i].pe
                and not rows[i - 1].pe
                and set(rows[i].nets) & set(rows[i - 1].nets)
            )
            if joined:
                continue
            if i - 1 > start:
                bridges.append((start, i - 1))
            for k in range(start, i):
                run_of[k] = start
            start = i
        pe_rows = [i for i, r in enumerate(rows) if r.pe]
        for i, (row, entity_id, sides) in enumerate(entries):
            skip = {entity_id} | {entries[k][1] for k in range(len(rows)) if run_of[k] == run_of[i]}
            texts = [_target_text(graph.nearest(node, skip)) for _pin, node in sides]
            texts += ["", ""]
            # A bridged run shares its source: shown once, on the first terminal.
            run = [entries[k][0] for k in range(i) if run_of[k] == run_of[i]]
            if any(texts[0] and r.target1 == texts[0] for r in run):
                texts[0] = ""
            if any(texts[1] and r.target2 == texts[1] for r in run):
                texts[1] = ""
            row.target1, row.target2 = texts[0], texts[1]
        plans.append(
            StripPlan(
                strip=strip,
                rows=rows,
                cables1=_cables(rows, "cores1", cable_type),
                cables2=_cables(rows, "cores2", cable_type),
                bridges=bridges,
                pe_rows=pe_rows if len(pe_rows) > 1 else [],
            )
        )
    return plans


def _cables(rows: list[TerminalRow], side: str, types: dict[str, str]) -> list[tuple[str, str]]:
    names = {c for r in rows for c in getattr(r, side)}
    return [(c, types.get(c, "")) for c in sorted(names, key=_natural)]


def plan_rows(plans: list[StripPlan]) -> list[list[str]]:
    """Flat rows for the CSV export: strip, terminal, colour, target 1, target 2, cables
    on either side ("-W1 bl"), page, column, note."""

    def cables(cores: dict[str, str]) -> str:
        return ", ".join(f"{c} {k}".strip() for c, k in sorted(cores.items()))

    return [
        [
            plan.strip,
            r.number,
            r.color,
            r.target1,
            r.target2,
            cables(r.cores1),
            cables(r.cores2),
            r.page,
            r.column,
            r.note,
        ]
        for plan in plans
        for r in plan.rows
    ]


def plan_pages(plans: list[StripPlan]) -> list[tuple[StripPlan, int]]:
    """Strip and first row of each page: a strip starts on a new page, ROWS per page."""
    pages = []
    for plan in plans:
        for first in range(0, max(len(plan.rows), 1), ROWS):
            pages.append((plan, first))
    return pages


# -- layout -------------------------------------------------------------------------

# The form in millimetres on an A3 page, from the left top corner of the table (the
# inner frame) to the title block; scaled to the actual table size.
FORM_WIDTH, FORM_HEIGHT = 397.12, 241.26
TITLE_BOTTOM = 54.48  # strip title and cable names above this line
HEAD_BOTTOM = 87.55  # column captions and cable types above this line
NOTE_COLUMN = (0.0, 38.22)
OUTER_CABLES = [38.22 + 10.6 * i for i in range(9)]  # 8 columns, the last ends at 123.02
TARGET1 = (128.86, 191.84)
SYMBOL = (191.84, 210.52)
SYMBOL_X, BRIDGE_X, PE_BRIDGE_X = 201.39, 208.0, 194.77
COLOR_COLUMN = (210.52, 222.07)
NUMBER = (222.07, 239.16)
TARGET2 = (239.16, 301.57)
INNER_CABLES = [307.41 + 10.6 * i for i in range(7)]  # 6 columns, the last ends at 370.98
SHEET_COLUMN = (370.98, 383.71)
PATH_COLUMN = (383.71, 397.12)
FULL_LINES = [0.0, *OUTER_CABLES, 128.86, 301.57, *INNER_CABLES, 383.71, 397.12]
LOWER_LINES = [191.84, 210.52, 222.07, 239.16]  # start below the strip title
RADIUS = 1.85  # terminal circle
GRID, THIN = 0.35, 0.25
BIG, NORMAL, SMALL, TINY = 10.0, 5.0, 3.5, 2.0
CHAR_WIDTH = 0.75  # rough text width per character as a multiple of the height


@dataclass(frozen=True)
class _Form:
    left: float
    top: float
    sx: float
    sy: float

    def x(self, v: float) -> float:
        return self.left + v * self.sx

    def y(self, v: float) -> float:
        return self.top + v * self.sy

    @property
    def k(self) -> float:
        return min(self.sx, self.sy)

    def row_top(self, i: int) -> float:
        return self.y(HEAD_BOTTOM + i * (FORM_HEIGHT - HEAD_BOTTOM) / ROWS)

    def row_height(self) -> float:
        return (FORM_HEIGHT - HEAD_BOTTOM) / ROWS * self.sy


def _form(page: SheetLayout) -> _Form:
    a, b = schematic_inner(*page.size)
    bottom = b.y - SCHEMATIC_TITLE_HEIGHT
    return _Form(a.x, a.y, (b.x - a.x) / FORM_WIDTH, (bottom - a.y) / FORM_HEIGHT)


def _line(x1: float, y1: float, x2: float, y2: float, weight: float = GRID) -> Line:
    return Line(
        id=f"gen:{x1:.2f}:{y1:.2f}:{x2:.2f}:{y2:.2f}",
        p1=Point(x1, y1),
        p2=Point(x2, y2),
        lineweight=weight,
    )


def _text(x: float, y: float, value: str, height: float, **kw) -> Text:
    return Text(
        id=f"gen:{x:.2f}:{y:.2f}:{value[:12]}",
        position=Point(x, y),
        text=value,
        height=height,
        **kw,
    )


def _fitted(value: str, height: float, width: float) -> float:
    """Text height so that ``value`` fits ``width`` (never above ``height``)."""
    need = len(value) * CHAR_WIDTH * height
    return height if need <= width else max(width / (len(value) * CHAR_WIDTH), height / 3)


def _cell(
    f: _Form, columns: tuple[float, float], row: int, value: str, height: float, align: str
) -> Text:
    x1, x2 = f.x(columns[0]), f.x(columns[1])
    h = _fitted(value, height * f.k, x2 - x1 - 2 * f.k)
    x = {"left": x1 + 1.0 * f.k, "center": (x1 + x2) / 2}[align]
    bottom = f.row_top(row) + f.row_height()
    return _text(x, bottom - (f.row_height() - h) / 2, value, h, halign=align)


def _vertical(f: _Form, columns: tuple[float, float], bottom: float, value: str, h: float) -> Text:
    """Text reading upwards, centred in a column, ending ``bottom`` (form mm)."""
    x1, x2 = f.x(columns[0]), f.x(columns[1])
    h = _fitted(value, h * f.k, 1e9)
    return _text((x1 + x2) / 2 + h / 2, f.y(bottom), value, h, rotation=90)


def _cable_columns(cables: list[tuple[str, str]], edges: list[float], nearest_right: bool):
    """Column (x1, x2) per cable: nearest the terminal first."""
    slots = list(zip(edges, edges[1:], strict=False))
    if nearest_right:
        slots.reverse()
    return {c: slot for (c, _t), slot in zip(cables, slots, strict=False)}


def plan_page_entities(
    page: SheetLayout, plan: StripPlan | None, first: int, tr: Callable[[str], str] = str
) -> list[Entity]:
    """One page of the terminal plan: the form, the strip and rows ``first`` on."""
    f = _form(page)
    right, bottom = f.x(FORM_WIDTH), f.y(FORM_HEIGHT)
    out: list[Entity] = []
    for v in FULL_LINES:
        out.append(_line(f.x(v), f.y(0), f.x(v), bottom))
    for v in LOWER_LINES:
        out.append(_line(f.x(v), f.y(TITLE_BOTTOM), f.x(v), bottom))
    for v in (TITLE_BOTTOM, HEAD_BOTTOM, FORM_HEIGHT):
        out.append(_line(f.x(0), f.y(v), right, f.y(v)))
    for i in range(1, ROWS):
        out.append(_line(f.x(0), f.row_top(i), right, f.row_top(i)))
    # Title and captions.
    out.append(_text(f.x(TARGET1[0] + 8.4), f.y(22.2), tr("Klemmleiste:"), BIG * f.k))
    middle = (f.x(TARGET1[0]) + f.x(TARGET2[1])) / 2
    head_middle = f.y((TITLE_BOTTOM + HEAD_BOTTOM) / 2)
    for columns, caption in ((TARGET1, tr("Ziel 1")), (TARGET2, tr("Ziel 2"))):
        x = (f.x(columns[0]) + f.x(columns[1])) / 2
        out.append(_text(x, head_middle, caption, NORMAL * f.k, halign="center", valign="middle"))
    for columns, caption in (
        (COLOR_COLUMN, tr("Farbe")),
        (SHEET_COLUMN, tr("Blatt")),
        (PATH_COLUMN, tr("Pfad")),
    ):
        x = (f.x(columns[0]) + f.x(columns[1])) / 2
        out.append(
            _text(
                x, head_middle, caption, NORMAL * f.k, rotation=90, halign="center", valign="middle"
            )
        )
    if plan is None:
        return out
    out.append(_text(middle, f.y(42.3), plan.strip, BIG * f.k, halign="center"))
    rows = plan.rows[first : first + ROWS]
    # Cables: name above, type below, core per row.
    outer = _cable_columns(plan.cables1, OUTER_CABLES, nearest_right=True)
    inner = _cable_columns(plan.cables2, INNER_CABLES, nearest_right=False)
    for cables, slots in ((plan.cables1, outer), (plan.cables2, inner)):
        for cable, type_ in cables:
            if cable not in slots:
                continue
            out.append(_vertical(f, slots[cable], TITLE_BOTTOM - 4.0, cable, NORMAL))
            if type_:
                out.append(_vertical(f, slots[cable], HEAD_BOTTOM - 3.0, type_, TINY))
    for i, row in enumerate(rows):
        if row.note:
            out.append(_cell(f, NOTE_COLUMN, i, row.note, SMALL, "left"))
        out.append(_cell(f, TARGET1, i, row.target1, SMALL, "left"))
        out.append(_cell(f, COLOR_COLUMN, i, row.color, NORMAL, "left"))
        out.append(_cell(f, NUMBER, i, row.number, NORMAL, "center"))
        out.append(_cell(f, TARGET2, i, row.target2, NORMAL, "left"))
        out.append(_cell(f, SHEET_COLUMN, i, row.page, NORMAL, "center"))
        out.append(_cell(f, PATH_COLUMN, i, row.column, NORMAL, "center"))
        for cores, slots in ((row.cores1, outer), (row.cores2, inner)):
            for cable, core in cores.items():
                if cable in slots and core:
                    out.append(_cell(f, slots[cable], i, core, NORMAL, "center"))
    out += _symbols(f, plan, first, len(rows))
    return [e for e in out if not isinstance(e, Text) or e.text]


def _symbols(f: _Form, plan: StripPlan, first: int, count: int) -> list[Entity]:
    """Terminal circles, bridges right of them, the PE rail left of them."""
    out: list[Entity] = []
    r = RADIUS * f.k
    x = f.x(SYMBOL_X)

    def centre(i: int) -> float:
        return f.row_top(i - first) + f.row_height() / 2

    bridged = set(plan.pe_rows)
    for a, b in plan.bridges:
        bridged |= set(range(a, b + 1))
    for i in range(first, first + count):
        y = centre(i)
        out.append(Circle(id=f"gen:t{i}", center=Point(x, y), radius=r, lineweight=THIN))
        if i in bridged:
            out.append(
                Circle(id=f"gen:d{i}", center=Point(x, y), radius=0.5 * f.k, lineweight=THIN)
            )
    groups = [(list(range(a, b + 1)), f.x(BRIDGE_X), 1) for a, b in plan.bridges]
    if plan.pe_rows:
        groups.append((plan.pe_rows, f.x(PE_BRIDGE_X), -1))
    last = first + count - 1
    for members, bx, side in groups:
        shown = [i for i in members if first <= i <= last]
        if not shown:
            continue
        # A bridge continuing from or onto the neighbouring page runs to the edge.
        top = centre(shown[0]) if members[0] >= first else f.row_top(0)
        end = centre(shown[-1]) if members[-1] <= last else f.row_top(count)
        out.append(_line(bx, top, bx, end, THIN))
        for i in shown:
            y = centre(i)
            out.append(_line(x + side * r, y, bx, y, THIN))
            if i not in (members[0], members[-1]):
                out.append(
                    Circle(
                        id=f"gen:j{i}{side}", center=Point(bx, y), radius=0.2 * f.k, lineweight=0.5
                    )
                )
    return out
