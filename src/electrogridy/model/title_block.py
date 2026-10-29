"""Built-in title block after DIN EN ISO 7200 and its field tags."""

from collections.abc import Mapping

from electrogridy.model.blocks import BlockDefinition, symbol_bounds
from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import AttributeDefinition, BlockReference, Line, Rectangle, Text
from electrogridy.model.geometry import Point

TITLE_BLOCK_NAME = "Schriftfeld"
TITLE_BLOCK_WIDTH = 180.0
TITLE_BLOCK_HEIGHT = 36.0

# Field tags filled automatically in title blocks on sheets. ANLAGE and ORT of the
# project are the defaults for pages that have none of their own.
DOCUMENT_FIELDS = (
    "PROJEKT",
    "KUNDE",
    "AUFTRAG",
    "SCHALTPLANNR",
    "ANLAGE",
    "ORT",
    "FIRMA",
    "ADRESSE",
    "BEARBEITER",
    "BAUJAHR",
)
SHEET_FIELDS = (
    "TITEL",
    "ZEICHNUNGSNR",
    "DATUM",
    "GEPRUEFT",
    "AENDERUNG",
    "AENDDATUM",
    "AENDNAME",
    "ERSF",
    "ERSD",
)
# Fields with several lines (name with address below). The circuit diagram title
# block shows the lines one below the other, other title blocks in one line.
MULTILINE_FIELDS = ("FIRMA", "KUNDE")
COMPUTED_FIELDS = ("BLATT", "BLATTNR", "VON", "FORMAT", "SEITENTYP")
ALL_FIELDS = DOCUMENT_FIELDS + SHEET_FIELDS + COMPUTED_FIELDS

FIELD_LABELS = {
    "PROJEKT": "Projekt",
    "KUNDE": "Kunde",
    "AUFTRAG": "Auftragsnummer",
    "SCHALTPLANNR": "Schaltplannummer",
    "ANLAGE": "Anlage",
    "ORT": "Ort",
    "ADRESSE": "Anschrift",
    "BAUJAHR": "Baujahr",
    "AENDDATUM": "Änderungsdatum",
    "AENDNAME": "Geändert von",
    "ERSF": "Ersatz für",
    "ERSD": "Ersetzt durch",
    "BLATTNR": "Blatt",
    "VON": "von",
    "SEITENTYP": "Seitentyp",
    "FIRMA": "Firma",
    "BEARBEITER": "Bearbeiter",
    "TITEL": "Titel",
    "ZEICHNUNGSNR": "Zeichnungsnummer",
    "DATUM": "Datum",
    "GEPRUEFT": "Geprüft",
    "AENDERUNG": "Änderungsindex",
    "BLATT": "Blatt",
    "FORMAT": "Format",
}

# Fixed captions of the circuit diagram title block (no fields), translatable too.
CAPTIONS = {
    "_VERSION": "Version",
    "_DATE": "Datum",
    "_EDITOR": "Bearbeiter",
    "_INDEX": "Index:",
    "_AUTHOR": "Ersteller",
    "_CHECKED": "Geprüft",
    "_REPLACES": "Ers.f",
    "_REPLACED": "Ers.d",
}

LABEL_HEIGHT = 1.8
VALUE_HEIGHT = 3.5
OUTER = 0.7
INNER = 0.35

# Cells (left, top, right, bottom, tag, value height) relative to the bottom
# right corner, which is the base point.
_CELLS = (
    (-180, -36, -120, -18, "FIRMA", 5.0),
    (-180, -18, -120, -9, "BEARBEITER", VALUE_HEIGHT),
    (-180, -9, -120, 0, "GEPRUEFT", VALUE_HEIGHT),
    (-120, -36, -40, -27, "PROJEKT", VALUE_HEIGHT),
    (-120, -27, -40, -9, "TITEL", 5.0),
    (-120, -9, -40, 0, "ZEICHNUNGSNR", VALUE_HEIGHT),
    (-40, -36, 0, -27, "AENDERUNG", VALUE_HEIGHT),
    (-40, -27, 0, -18, "DATUM", VALUE_HEIGHT),
    (-40, -18, 0, -9, "BLATT", VALUE_HEIGHT),
    (-40, -9, 0, 0, "FORMAT", VALUE_HEIGHT),
)


def title_block_definition(labels: dict[str, str] | None = None) -> BlockDefinition:
    """The ISO 7200 title block; ``labels`` replaces the German cell captions."""
    labels = {**FIELD_LABELS, **(labels or {})}
    entities = [
        Rectangle(id="frame", p1=Point(-180, -36), p2=Point(0, 0), lineweight=OUTER),
        Line(id="v1", p1=Point(-120, -36), p2=Point(-120, 0), lineweight=INNER),
        Line(id="v2", p1=Point(-40, -36), p2=Point(-40, 0), lineweight=INNER),
    ]
    for n, (left, top, right, bottom, tag, height) in enumerate(_CELLS):
        if bottom < 0:
            entities.append(
                Line(id=f"h{n}", p1=Point(left, bottom), p2=Point(right, bottom), lineweight=INNER)
            )
        entities.append(
            Text(
                id=f"label_{tag.lower()}",
                position=Point(left + 1.0, top + 1.0 + LABEL_HEIGHT),
                text=labels[tag],
                height=LABEL_HEIGHT,
            )
        )
        entities.append(
            AttributeDefinition(
                id=f"att_{tag.lower()}",
                tag=tag,
                prompt=labels[tag],
                position=Point(left + 1.5, (top + bottom) / 2 + 1.5),
                height=height,
                valign="middle",
            )
        )
    return BlockDefinition(
        name=TITLE_BLOCK_NAME,
        base_point=Point(0, 0),
        entities=EntityContainer(entities),
        category="Rahmen",
        description="Schriftfeld nach DIN EN ISO 7200, 180 mm breit",
    )


# -- title block of the circuit diagram frame ---------------------------------------

# Four rows of 4 mm (5 mm until 1.3.2.dev12, Florian 2026-10-29).
ROW = 4.0
SCHEMATIC_TITLE_HEIGHT = 4 * ROW
SCHEMATIC_TITLE_PREFIX = "Schriftfeld Schaltplan"
# Revision and approval table on the left: version, then date, editor, caption and value
# all as wide as each other (Florian 2026-10-28).
_REVISION_COLUMNS = (15.0, 18.0, 18.0, 18.0, 18.0)
_REVISION = sum(_REVISION_COLUMNS)
# Page type cell at the right: as wide as the longest type ("Übersichtsschaltbild" is
# 34.6 mm at 2.5 mm), then sheet / of; plant and location above both. The circuit
# diagram number with the project title below (short: "TST", "PV-Anlage") has a fixed
# width; company and customer share the rest (Florian 2026-10-28).
_TYPE = 37.0
_SHEET = 18.0
_RIGHT = _TYPE + _SHEET
_NUMBER = 35.0
_COMPANY_MIN = 30.0
# A logo fills the height of the company or customer field, not distorted, at its left;
# the name follows right of it, made smaller until it fits (``schematic_text_boxes``).
LOGO_TOP, LOGO_BOTTOM = -SCHEMATIC_TITLE_HEIGHT + 0.6, -ROW - 0.6
LOGO_SHARE = 0.5  # with a name the logo takes at most half the field
NAME_Y = (-SCHEMATIC_TITLE_HEIGHT - ROW) / 2
NAME_GAP = 1.5  # between logo and name
SMALL = 1.8
VALUE = 2.5
NAME = 2.0  # largest company and customer name (2.5 mm until 1.3.2.dev12)
BIG = 3.5


# Raised with every change of the layout: files with an older one get the new title
# block when opened, also at the same width (1.3.2.dev9 kept the old one).
SCHEMATIC_TITLE_LAYOUT = 4


def schematic_title_block_name(width: float) -> str:
    return f"{SCHEMATIC_TITLE_PREFIX} {width:g}"


def schematic_title_description(width: float) -> str:
    return f"Schriftfeld für Schaltpläne, {width:g} mm breit (Aufbau {SCHEMATIC_TITLE_LAYOUT})"


def _schematic_columns(width: float) -> tuple[float, float, float, float, float]:
    """Left edge and the borders of company, customer, number and the right part."""
    left = -width
    x_company = left + _REVISION
    x_right = -_RIGHT
    company = max(_COMPANY_MIN, (x_right - _NUMBER - x_company) / 2)
    x_customer = round(x_company + company, 3)
    x_number = round(x_customer + company, 3)
    return left, x_company, x_customer, x_number, x_right


def schematic_text_boxes(width: float) -> dict[str, tuple[float, float, float]]:
    """Texts whose size follows their field: left and right end of the room (block
    coordinates) and the largest height. The name of company and customer starts
    after a logo, the project title stands in the middle (a few letters: large)."""
    _left, x_company, x_customer, x_number, x_right = _schematic_columns(width)
    return {
        "FIRMA": (x_company + 2.0, x_customer - 1.0, NAME),
        "KUNDE": (x_customer + 2.0, x_number - 1.0, NAME),
        "PROJEKT": (x_number + 1.0, x_right - 1.0, 5.0),
    }


def schematic_logo_boxes(width: float) -> dict[str, tuple[Point, Point]]:
    """Where the logos of company and customer go (block coordinates, top left and
    bottom right): the field above the "replaced" row."""
    _left, x_company, x_customer, x_number, _right = _schematic_columns(width)
    return {
        tag: (Point(start + 0.6, LOGO_TOP), Point(right - 0.6, LOGO_BOTTOM))
        for start, right, tag in ((x_company, x_customer, "FIRMA"), (x_customer, x_number, "KUNDE"))
    }


# Document properties naming the logo block of company and customer.
LOGO_KEYS = {"FIRMA": "FIRMA_LOGO", "KUNDE": "KUNDE_LOGO"}
LOGO_CATEGORY = "Logos"


def logo_references(
    properties: Mapping[str, str],
    blocks: Mapping[str, BlockDefinition],
    width: float,
    insert: Point,
) -> list[BlockReference]:
    """The logos chosen for company and customer, scaled into their boxes of a title
    block ``width`` wide whose base point is at ``insert``."""
    out = []
    for tag, (a, b) in schematic_logo_boxes(width).items():
        name = properties.get(LOGO_KEYS[tag], "")
        definition = blocks.get(name) if name else None
        box = symbol_bounds(definition) if definition is not None else None
        if box is None or box[2] - box[0] <= 0 or box[3] - box[1] <= 0:
            continue
        x0, y0, x1, y1 = box
        room = (b.x - a.x) * (LOGO_SHARE if properties.get(tag, "").strip() else 1.0)
        k = min(room / (x1 - x0), (b.y - a.y) / (y1 - y0))
        # At the left of the field, in the middle of its height.
        cx = a.x + insert.x + (x1 - x0) * k / 2
        cy = (a.y + b.y) / 2 + insert.y
        base = definition.base_point
        ref = BlockReference(
            id=f"logo_{tag.lower()}",
            name=name,
            insert=Point(cx - ((x0 + x1) / 2 - base.x) * k, cy - ((y0 + y1) / 2 - base.y) * k),
            scale=k,
        )
        out.append(ref)
    return out


def schematic_title_block_definition(
    width: float, labels: dict[str, str] | None = None
) -> BlockDefinition:
    """Title block across the full width of the circuit diagram frame, four rows of
    ``ROW`` mm; base point bottom right. From the left: revision table, company with
    "replaced by", customer with "replaces" (both as wide, room for a logo), circuit
    diagram number with page type, plant/location/sheet."""
    labels = {**FIELD_LABELS, **CAPTIONS, **(labels or {})}
    left, x_company, x_customer, x_number, x_right = _schematic_columns(width)
    top = -SCHEMATIC_TITLE_HEIGHT
    rows = [top + i * ROW for i in range(5)]
    # Middle of each row: values stand there, captions (SMALL) on a baseline below it.
    mid = [y + ROW / 2 for y in rows[:-1]]
    cap = [y + SMALL / 2 for y in mid]
    out: list = [
        Rectangle(id="frame", p1=Point(left, top), p2=Point(0, 0), lineweight=0.5),
    ]
    n = 0

    def line(x1, y1, x2, y2, weight=INNER) -> None:
        nonlocal n
        n += 1
        out.append(Line(id=f"l{n}", p1=Point(x1, y1), p2=Point(x2, y2), lineweight=weight))

    def text(x, y, value, height=SMALL) -> None:
        nonlocal n
        n += 1
        out.append(Text(id=f"t{n}", position=Point(x, y), text=value, height=height))

    def attribute(tag, x, y, height=VALUE, halign="left") -> None:
        out.append(
            AttributeDefinition(
                id=f"att_{tag.lower()}",
                tag=tag,
                prompt=labels.get(tag, tag),
                position=Point(x, y),
                height=height,
                halign=halign,
                valign="middle",
            )
        )

    for x in (x_company, x_customer, x_number, x_right):
        line(x, top, x, 0, 0.5)
    # Revision table: version/index, date and editor of the change; date, author and
    # checker of the drawing.
    cols = [left]
    for w in _REVISION_COLUMNS:
        cols.append(cols[-1] + w)
    for x in cols[1:-1]:
        line(x, top, x, 0)
    for y in rows[1:-1]:
        line(left, y, x_company, y)
    text(cols[0] + 0.8, cap[0], labels["_VERSION"])
    text(cols[1] + 0.8, cap[0], labels["_DATE"])
    text(cols[2] + 0.8, cap[0], labels["_EDITOR"])
    text(cols[0] + 0.8, cap[1], labels["_INDEX"])
    for i, (caption, tag) in enumerate(
        (
            (labels["_DATE"], "DATUM"),
            (labels["_AUTHOR"], "BEARBEITER"),
            (labels["_CHECKED"], "GEPRUEFT"),
        )
    ):
        text(cols[3] + 0.8, cap[i], caption)
        attribute(tag, cols[4] + 0.8, mid[i], SMALL + 0.2)
    attribute("AENDERUNG", cols[0] + 0.8, mid[2], VALUE)
    attribute("AENDDATUM", cols[1] + 0.8, mid[2], SMALL + 0.2)
    attribute("AENDNAME", cols[2] + 0.8, mid[2], SMALL + 0.2)
    # Company with "replaced by" below, customer with "replaces" below.
    line(x_company, rows[3], x_number, rows[3])
    for x, tag, replaced, replaced_tag in (
        (x_company, "FIRMA", labels["_REPLACED"], "ERSD"),
        (x_customer, "KUNDE", labels["_REPLACES"], "ERSF"),
    ):
        attribute(tag, x + 2, NAME_Y, NAME)
        text(x + 0.8, cap[3], replaced)
        attribute(replaced_tag, x + 9, mid[3], SMALL + 0.2)
    # Circuit diagram number, below it the project title (one text, in the middle).
    line(x_number, rows[2], x_right, rows[2])
    text(x_number + 0.8, cap[0], labels["SCHALTPLANNR"] + ":")
    attribute("SCHALTPLANNR", x_number + 1.5, mid[1], VALUE)
    attribute("PROJEKT", (x_number + x_right) / 2, rows[3], BIG, "center")
    # Plant, location; page type (in the middle) and sheet x of y.
    for y in rows[1:3]:
        line(x_right, y, 0, y)
    line(-_SHEET, rows[2], -_SHEET, 0)
    line(-_SHEET, rows[3], 0, rows[3])
    attribute("SEITENTYP", x_right + _TYPE / 2, rows[3], VALUE, "center")
    text(x_right + 0.8, cap[0], labels["ANLAGE"] + ":")
    attribute("ANLAGE", x_right + 11, mid[0], VALUE)
    text(x_right + 0.8, cap[1], labels["ORT"] + ":")
    attribute("ORT", x_right + 11, mid[1], VALUE)
    text(-_SHEET + 0.8, cap[2], labels["BLATTNR"] + ":")
    attribute("BLATTNR", -_SHEET + 9, mid[2], VALUE)
    text(-_SHEET + 0.8, cap[3], labels["VON"])
    attribute("VON", -_SHEET + 9, mid[3], VALUE)
    return BlockDefinition(
        name=schematic_title_block_name(width),
        base_point=Point(0, 0),
        entities=EntityContainer(out),
        category="Rahmen",
        description=schematic_title_description(width),
    )
