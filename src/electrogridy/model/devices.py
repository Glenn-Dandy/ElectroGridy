"""Devices: everything carrying the same BMK is one device. Pure Python.

A device can appear in the model (overview diagram, drawings) and on any number of
pages. On the pages its functions refer to each other: under the attributes of a main
function (coil, breaker) a contact mirror shows one line per pole of its auxiliary
functions (contacts): terminal, a small contact symbol, terminal, place ("13 -/- 14
/3.4": page 3, column 4); each contact shows where the main function sits ("/2.5").
The roles come from the block definitions (``function``, ``contact``).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from electrogridy.model.blocks import (
    BlockDefinition,
    point_to_world,
    symbol_bounds,
    world_connections,
)
from electrogridy.model.document import Document
from electrogridy.model.entities import BlockReference, Entity, Line, Text
from electrogridy.model.geometry import Point
from electrogridy.model.sheet import column_at

BMK = "BMK"
MODEL, SHEET = "model", "sheet"
XREF_HEIGHT = 1.5  # contact mirror and references (2.0 until 1.4.2.dev6: too dominant)
XREF_GAP = 1.5
MIRROR_GAP = 1.0  # mm between the attributes and the first mirror line
CHAR_WIDTH = 0.75  # rough width of a character as a share of the text height
MIRROR_WEIGHT = 0.18
GLYPH_LENGTH = 2.5  # contact symbol in the mirror, in text heights


@dataclass(frozen=True)
class Occurrence:
    bmk: str
    entity_id: str
    block: str
    where: str  # MODEL or SHEET (a page)
    layout_id: str | None  # page id
    position: Point
    function: str  # "main", "aux" or ""
    contact: str
    terminals: tuple[str, ...]  # connection point names of the symbol, e.g. ("13", "14")
    manufacturer: str = ""
    type: str = ""
    poles: tuple[tuple[str, str], ...] = ()  # terminal pairs per pole, e.g. (("1", "2"), …)


@dataclass(frozen=True)
class MirrorLine:
    """One pole in the contact mirror of a main function."""

    first: str
    contact: str  # "no", "nc", "co" or ""
    second: str
    reference: str  # "/3.4"


def poles(definition: BlockDefinition, ref: BlockReference) -> tuple[tuple[str, str], ...]:
    """Terminal pairs of a symbol, left to right: the upper and the lower end of each
    pole (as named on this reference). A changeover contact is one pole: the common
    terminal and its two others ("11", "12/14")."""
    columns: dict[float, list] = {}
    for c in definition.connection_points():
        columns.setdefault(round(c.position.x, 1), []).append(c)
    pairs = []
    for x in sorted(columns):
        ends = sorted(columns[x], key=lambda c: c.position.y)
        names = [ref.terminal_label(c.name) for c in ends]
        pairs.append((names[0], names[-1] if len(names) > 1 else ""))
    if definition.contact == "co":
        lower = max(definition.connection_points(), key=lambda c: c.position.y)
        common = ref.terminal_label(lower.name)
        others = sorted(
            (ref.terminal_label(c.name) for c in definition.connection_points() if c is not lower),
            key=_natural,
        )
        return ((common, "/".join(others)),)
    return tuple(pairs)


def bmk_of(ref: BlockReference) -> str:
    return dict(ref.attributes).get(BMK, "").strip()


def _natural(text: str) -> list:
    """-K2 before -K10."""
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text)]


def occurrences(doc: Document) -> list[Occurrence]:
    """Every block reference with a BMK, in the model and on the pages."""
    places = [(MODEL, None, doc.model_space)]
    places += [(SHEET, s.id, s.entities) for s in doc.sheets]
    found = []
    for where, layout_id, container in places:
        for e in container:
            if not isinstance(e, BlockReference):
                continue
            bmk = bmk_of(e)
            if not bmk:
                continue
            definition = doc.blocks.get(e.name)
            attributes = dict(e.attributes)
            found.append(
                Occurrence(
                    bmk=bmk,
                    entity_id=e.id,
                    block=e.name,
                    where=where,
                    layout_id=layout_id,
                    position=e.insert,
                    function=definition.function if definition else "",
                    contact=definition.contact if definition else "",
                    terminals=tuple(
                        e.terminal_label(c.name) for c in definition.connection_points()
                    )
                    if definition
                    else (),
                    manufacturer=attributes.get("HERSTELLER", ""),
                    type=attributes.get("TYP", ""),
                    poles=poles(definition, e) if definition else (),
                )
            )
    return found


def devices(doc: Document) -> dict[str, list[Occurrence]]:
    """Occurrences grouped by BMK, sorted naturally (-K2 before -K10)."""
    groups: dict[str, list[Occurrence]] = {}
    for occ in occurrences(doc):
        groups.setdefault(occ.bmk, []).append(occ)
    return {k: groups[k] for k in sorted(groups, key=_natural)}


def place(doc: Document, sheet_id: str, x: float) -> tuple[int, int | None]:
    """Page number and column of a point on a page."""
    sheet = doc.sheet(sheet_id)
    w, h = sheet.size
    return doc.page_number(sheet_id), column_at(w, h, sheet.columns, x)


def page_reference(doc: Document, occ: Occurrence) -> str:
    """ "/3.4": page 3, column 4 (just "/3" on pages without columns)."""
    number, column = place(doc, occ.layout_id, occ.position.x)
    return f"/{number}.{column}" if column is not None else f"/{number}"


def crossrefs(doc: Document) -> dict[str, list]:
    """Reference id -> what is shown with it (functions on pages only): a main function
    gets its contact mirror (``MirrorLine`` per pole), a contact the places of its main
    function ("/2.5")."""
    lines: dict[str, list] = {}
    for group in devices(doc).values():
        on_pages = [o for o in group if o.where == SHEET]
        mains = [o for o in on_pages if o.function == "main"]
        auxes = [o for o in on_pages if o.function == "aux"]
        for main in mains:
            mirror = [
                MirrorLine(first, aux.contact, second, page_reference(doc, aux))
                for aux in auxes
                for first, second in aux.poles or (("", ""),)
            ]
            if mirror:
                lines[main.entity_id] = mirror
        for aux in auxes:
            refs = [page_reference(doc, m) for m in mains]
            if refs:
                lines[aux.entity_id] = refs
    return lines


def crossref_texts(
    ref: BlockReference,
    blocks: Mapping[str, BlockDefinition],
    lines: list,
    parts: list[Entity] | None = None,
) -> list[Entity]:
    """Places of the main function under the attributes of a contact, the contact
    mirror under the attributes of a main function (beside the symbol, out of the way
    of its wires); under the symbol when there are no attributes beside it."""
    definition = blocks.get(ref.name)
    if definition is None or not lines:
        return []
    box = symbol_bounds(definition)
    if box is None:
        return []
    x0, y0, x1, y1 = box
    corners = [
        point_to_world(ref, definition.base_point, Point(x, y)) for x in (x0, x1) for y in (y0, y1)
    ]
    left = min(c.x for c in corners)
    top = min(c.y for c in corners)
    bottom = max(c.y for c in corners)
    style = {"layer": ref.layer, "color": ref.color}
    h = XREF_HEIGHT
    x, first = left, bottom + XREF_GAP + h / 2
    beside = _attribute_column(definition, parts or [])
    if beside is not None and beside[1] > top + h:  # attributes beside, not above
        x, first = beside[0], beside[1] + MIRROR_GAP + h / 2
    mirror = [m for m in lines if isinstance(m, MirrorLine)]
    if not mirror:
        return [
            Text(
                id=f"{ref.id}:xref{i}",
                position=Point(x, first + i * 1.4 * h),
                text=line,
                height=h,
                valign="middle",
                **style,
            )
            for i, line in enumerate(lines)
        ]
    widest = max(len(m.second) for m in mirror)
    out: list[Entity] = []
    for i, m in enumerate(mirror):
        y = first + i * 1.4 * h
        glyph_x = x + 1.8 * h
        second_x = glyph_x + GLYPH_LENGTH * h + 0.3 * h
        reference_x = second_x + widest * CHAR_WIDTH * h + 0.75 * h
        for j, (text, tx, align) in enumerate(
            (
                (m.first, x + 1.5 * h, "right"),
                (m.second, second_x, "left"),
                (m.reference, reference_x, "left"),
            )
        ):
            if text:
                out.append(
                    Text(
                        id=f"{ref.id}:xref{i}:{j}",
                        position=Point(tx, y),
                        text=text,
                        height=h,
                        halign=align,
                        valign="middle",
                        **style,
                    )
                )
        out += [
            Line(id=f"{ref.id}:xref{i}:g{k}", p1=a, p2=b, lineweight=MIRROR_WEIGHT, **style)
            for k, (a, b) in enumerate(contact_glyph(m.contact, glyph_x, y, h))
        ]
    return out


POLE_TEXT_HEIGHT = 1.8
POLE_TEXT_GAP = 0.6  # mm from the conductor and from the end of the pole


def pole_texts(ref: BlockReference, blocks: Mapping[str, BlockDefinition]) -> list[Text]:
    """The terminal names at the ends of the poles, horizontal: left of an upright pole
    (just inside its end), above a lying one."""
    definition = blocks.get(ref.name)
    if definition is None:
        return []
    out = []
    g = POLE_TEXT_GAP
    for c in world_connections(ref, blocks):
        if c.id.startswith("dock") or not c.name.strip():
            continue
        p = c.position
        direction = round(c.direction) % 360
        if direction == 90:  # upper end, y down
            at, halign, valign = Point(p.x - g, p.y + g), "right", "top"
        elif direction == 270:
            at, halign, valign = Point(p.x - g, p.y - g), "right", "bottom"
        elif direction == 180:  # left end of a lying pole
            at, halign, valign = Point(p.x + g, p.y - g), "left", "bottom"
        else:
            at, halign, valign = Point(p.x - g, p.y - g), "right", "bottom"
        out.append(
            Text(
                id=f"{ref.id}:pole:{c.id}",
                layer=ref.layer,
                color=ref.color,
                position=at,
                text=c.name,
                height=POLE_TEXT_HEIGHT,
                halign=halign,
                valign=valign,
            )
        )
    return out


def contact_glyph(
    contact: str, x: float, y: float, h: float = XREF_HEIGHT
) -> list[tuple[Point, Point]]:
    """A small lying contact symbol ``GLYPH_LENGTH`` text heights long starting at ``x``
    on the middle line ``y``: make contact (also for an unknown kind), break contact
    with its stop, changeover."""
    k = h / 2.0  # drawn for 2 mm text
    a, b, c, d = x, x + 1.8 * k, x + 3.2 * k, x + 5.0 * k

    def seg(x1, y1, x2, y2):
        return Point(round(x1, 4), round(y1, 4)), Point(round(x2, 4), round(y2, 4))

    if contact == "nc":
        return [
            seg(a, y, b, y),
            seg(c, y, d, y),
            seg(c, y, c, y + 0.9 * k),
            seg(b, y, c + 0.3 * k, y + 0.9 * k),
        ]
    if contact == "co":
        return [
            seg(a, y, b, y),
            seg(c, y - 0.9 * k, d, y - 0.9 * k),
            seg(c, y + 0.9 * k, d, y + 0.9 * k),
            seg(b, y, c + 0.2 * k, y + 0.9 * k),
        ]
    return [seg(a, y, b, y), seg(c, y, d, y), seg(b, y, c + 0.2 * k, y - 1.0 * k)]


def _attribute_column(
    definition: BlockDefinition, parts: list[Entity]
) -> tuple[float, float] | None:
    """Left edge and lower edge of the attribute texts drawn with a reference."""
    ids = {a.id for a in definition.attribute_definitions()}
    texts = [
        p for p in parts if isinstance(p, Text) and p.text.strip() and p.id.split("~")[0] in ids
    ]
    if not texts:
        return None
    below = {"top": 1.0, "middle": 0.5}

    def lower(t: Text) -> float:
        return t.position.y + below.get(t.valign, 0.0) * t.height + 0.25 * t.height

    return min(t.position.x for t in texts), max(lower(t) for t in texts)


def problems(doc: Document) -> dict[str, list[str]]:
    """BMK -> problem codes: "main_twice" (several main functions on the pages),
    "sld_twice" (more than once in the model), "aux_alone" (contacts on the pages
    without a main function)."""
    found: dict[str, list[str]] = {}
    for bmk, group in devices(doc).items():
        codes = []
        on_pages = [o for o in group if o.where == SHEET]
        mains = [o for o in on_pages if o.function == "main"]
        if len(mains) > 1:
            codes.append("main_twice")
        if len([o for o in group if o.where == MODEL]) > 1:
            codes.append("sld_twice")
        if not mains and any(o.function == "aux" for o in on_pages):
            codes.append("aux_alone")
        if codes:
            found[bmk] = codes
    return found


_NUMBERED = re.compile(r"^(.*?)(\d+)$")


def suggest_bmk(doc: Document, default: str, function: str = "") -> str:
    """BMK proposed when a symbol is placed: the next free number after the ones used
    (-Q2 after -Q1, terminal -X1:4 after -X1:3). A contact (aux) belongs to a coil that
    is already there, so it gets the last number used. Defaults without a trailing
    number (-X1:PE) stay as they are."""
    match = _NUMBERED.match(default.strip())
    if match is None:
        return default
    prefix = match.group(1)
    used = []
    for occ in occurrences(doc):
        found = _NUMBERED.match(occ.bmk)
        if found is not None and found.group(1) == prefix:
            used.append(int(found.group(2)))
    if not used:
        return default
    return f"{prefix}{max(used) if function == 'aux' else max(used) + 1}"


def renamed(ref: BlockReference, bmk: str) -> BlockReference:
    attributes = dict(ref.attributes)
    attributes[BMK] = bmk
    return replace(ref, attributes=tuple(sorted(attributes.items())))
