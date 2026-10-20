"""Devices: everything carrying the same BMK is one device. Pure Python.

A device can appear in the circuit diagram (SLD, model space), on sheets and on any
number of multi-line pages. On pages its functions refer to each other: under a main
function (coil, breaker) a contact mirror lists the auxiliary functions (contacts) with
their terminals and place ("S 13-14  /3.4"), each contact shows where the main function
sits ("/2.5"). The roles come from the block definitions (``function``, ``contact``).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from sldgridy.model.blocks import BlockDefinition, point_to_world, symbol_bounds
from sldgridy.model.document import Document, designation
from sldgridy.model.entities import BlockReference, Entity, Text
from sldgridy.model.geometry import Point
from sldgridy.model.sheet import column_at

BMK = "BMK"
MODEL, PAGE, SHEET = "model", "page", "sheet"
# Letters of the contact types in the contact mirror; the UI passes translated ones.
CONTACT_LETTERS = {"no": "S", "nc": "Ö", "co": "W", "": ""}
XREF_HEIGHT = 2.0
XREF_GAP = 1.5


@dataclass(frozen=True)
class Occurrence:
    bmk: str
    entity_id: str
    block: str
    where: str  # MODEL, PAGE or SHEET
    layout_id: str | None  # page or sheet id
    position: Point
    function: str  # "main", "aux" or ""
    contact: str
    terminals: tuple[str, ...]  # connection point names of the symbol, e.g. ("13", "14")
    manufacturer: str = ""
    type: str = ""


def bmk_of(ref: BlockReference) -> str:
    return dict(ref.attributes).get(BMK, "").strip()


def _natural(text: str) -> list:
    """-K2 before -K10."""
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text)]


def occurrences(doc: Document) -> list[Occurrence]:
    """Every block reference with a BMK, in the model, on sheets and on pages."""
    places = [(MODEL, None, doc.model_space)]
    places += [(PAGE, p.id, p.entities) for p in doc.pages]
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
                    terminals=tuple(c.name for c in definition.connection_points())
                    if definition
                    else (),
                    manufacturer=attributes.get("HERSTELLER", ""),
                    type=attributes.get("TYP", ""),
                )
            )
    return found


def devices(doc: Document) -> dict[str, list[Occurrence]]:
    """Occurrences grouped by BMK, sorted naturally (-K2 before -K10)."""
    groups: dict[str, list[Occurrence]] = {}
    for occ in occurrences(doc):
        groups.setdefault(occ.bmk, []).append(occ)
    return {k: groups[k] for k in sorted(groups, key=_natural)}


def page_reference(doc: Document, from_page: str | None, occ: Occurrence) -> str:
    """ "/3.4" (page and column), with plant and location in front when the target lies
    in another group (or when there is no page to compare with)."""
    page = doc.page(occ.layout_id)
    w, h = page.size
    column = column_at(w, h, page.columns, occ.position.x)
    number = doc.page_number(page.id)[0]
    ref = f"/{number}.{column}" if column else f"/{number}"
    src = doc.page(from_page) if from_page else None
    if src is None or (src.plant, src.location) != (page.plant, page.location):
        prefix = designation(page.plant, page.location)
        if prefix:
            ref = f"{prefix} {ref}"
    return ref


def crossrefs(doc: Document, letters: Mapping[str, str] = CONTACT_LETTERS) -> dict[str, list[str]]:
    """Reference id -> text lines shown under it (pages only)."""
    lines: dict[str, list[str]] = {}
    for group in devices(doc).values():
        on_pages = [o for o in group if o.where == PAGE]
        mains = [o for o in on_pages if o.function == "main"]
        auxes = [o for o in on_pages if o.function == "aux"]
        for main in mains:
            mirror = []
            for aux in auxes:
                terminals = "-".join(aux.terminals)
                letter = letters.get(aux.contact, "")
                head = " ".join(t for t in (letter, terminals) if t)
                mirror.append(f"{head}  {page_reference(doc, main.layout_id, aux)}".strip())
            if mirror:
                lines[main.entity_id] = mirror
        for aux in auxes:
            refs = [page_reference(doc, aux.layout_id, m) for m in mains]
            if refs:
                lines[aux.entity_id] = refs
    return lines


def crossref_texts(
    ref: BlockReference, blocks: Mapping[str, BlockDefinition], lines: list[str]
) -> list[Entity]:
    """The lines as texts under the symbol (left aligned to it)."""
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
    bottom = max(c.y for c in corners)
    return [
        Text(
            id=f"{ref.id}:xref{i}",
            layer=ref.layer,
            position=Point(left, bottom + XREF_GAP + XREF_HEIGHT + i * 1.4 * XREF_HEIGHT),
            text=line,
            height=XREF_HEIGHT,
        )
        for i, line in enumerate(lines)
    ]


def problems(doc: Document) -> dict[str, list[str]]:
    """BMK -> problem codes: "main_twice" (several main functions on the pages),
    "sld_twice" (more than once in the circuit diagram), "aux_alone" (contacts on the
    pages without a main function)."""
    found: dict[str, list[str]] = {}
    for bmk, group in devices(doc).items():
        codes = []
        on_pages = [o for o in group if o.where == PAGE]
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


def renamed(ref: BlockReference, bmk: str) -> BlockReference:
    attributes = dict(ref.attributes)
    attributes[BMK] = bmk
    return replace(ref, attributes=tuple(sorted(attributes.items())))
