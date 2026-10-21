"""Built-in title block after DIN EN ISO 7200 and its field tags."""

from sldgridy.model.blocks import BlockDefinition
from sldgridy.model.container import EntityContainer
from sldgridy.model.entities import AttributeDefinition, Line, Rectangle, Text
from sldgridy.model.geometry import Point

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

SCHEMATIC_TITLE_HEIGHT = 20.0
SCHEMATIC_TITLE_PREFIX = "Schriftfeld Schaltplan"
_REVISION = 87.0  # revision and approval table on the left
_LOGO = 45.0  # company field (narrow, Florian's template)
_RIGHT = 70.0  # plant, location, sheet number
SMALL = 1.8
VALUE = 2.5
BIG = 3.5


def schematic_title_block_name(width: float) -> str:
    return f"{SCHEMATIC_TITLE_PREFIX} {width:g}"


def schematic_title_block_definition(
    width: float, labels: dict[str, str] | None = None
) -> BlockDefinition:
    """Title block across the full width of the circuit diagram frame, 20 mm high, four
    rows of 5 mm; base point bottom right. From the left: revision table, customer,
    company, circuit diagram number with page type, plant/location/sheet."""
    labels = {**FIELD_LABELS, **CAPTIONS, **(labels or {})}
    rest = max(width - _REVISION - _LOGO - _RIGHT, 40.0)
    customer = round(rest * 0.52, 1)
    left = -width
    x_customer = left + _REVISION
    x_logo = x_customer + customer
    x_number = x_logo + _LOGO
    x_right = -_RIGHT
    rows = [-20.0, -15.0, -10.0, -5.0, 0.0]
    out: list = [
        Rectangle(id="frame", p1=Point(left, -20), p2=Point(0, 0), lineweight=0.5),
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

    for x in (x_customer, x_logo, x_number, x_right):
        line(x, -20, x, 0, 0.5)
    # Revision table: version/index, date and editor of the change; date, author and
    # checker of the drawing.
    cols = [left, left + 15, left + 37, left + 55, left + 69, x_customer]
    for x in cols[1:-1]:
        line(x, -20, x, 0)
    for y in rows[1:-1]:
        line(left, y, x_customer, y)
    text(cols[0] + 0.8, -16.6, labels["_VERSION"])
    text(cols[1] + 0.8, -16.6, labels["_DATE"])
    text(cols[2] + 0.8, -16.6, labels["_EDITOR"])
    text(cols[0] + 0.8, -11.6, labels["_INDEX"])
    for i, (caption, tag) in enumerate(
        (
            (labels["_DATE"], "DATUM"),
            (labels["_AUTHOR"], "BEARBEITER"),
            (labels["_CHECKED"], "GEPRUEFT"),
        )
    ):
        text(cols[3] + 0.8, -16.6 + 5 * i, caption)
        attribute(tag, cols[4] + 0.8, -17.5 + 5 * i, SMALL + 0.2)
    attribute("AENDERUNG", cols[0] + 0.8, -7.5, VALUE)
    attribute("AENDDATUM", cols[1] + 0.8, -7.5, SMALL + 0.2)
    attribute("AENDNAME", cols[2] + 0.8, -7.5, SMALL + 0.2)
    # Customer, and what this plan replaces or is replaced by.
    line(x_customer, -5, x_logo, -5)
    x_mid = x_customer + customer / 2
    line(x_mid, -5, x_mid, 0)
    text(x_customer + 0.8, -17.6, labels["KUNDE"])
    attribute("KUNDE", x_customer + 2, -10.5, BIG)
    text(x_customer + 0.8, -1.4, labels["_REPLACES"])
    attribute("ERSF", x_customer + 9, -2.5, SMALL + 0.2)
    text(x_mid + 0.8, -1.4, labels["_REPLACED"])
    attribute("ERSD", x_mid + 9, -2.5, SMALL + 0.2)
    # Company (small, in place of a logo).
    attribute("FIRMA", x_logo + _LOGO / 2, -10.0, VALUE, "center")
    # Circuit diagram number, page type and page title.
    line(x_number, -10, x_right, -10)
    text(x_number + 0.8, -16.6, labels["SCHALTPLANNR"] + ":")
    attribute("SCHALTPLANNR", x_number + 2, -12.5, VALUE)
    attribute("SEITENTYP", x_number + 2, -6.8, VALUE)
    attribute("TITEL", x_number + 2, -2.5, SMALL + 0.2)
    # Plant, location, sheet x of y.
    for y in (-15.0, -10.0):
        line(x_right, y, 0, y)
    line(-30, -10, -30, 0)
    line(-30, -5, 0, -5)
    text(x_right + 0.8, -16.6, labels["ANLAGE"] + ":")
    attribute("ANLAGE", x_right + 12, -17.5, VALUE)
    text(x_right + 0.8, -11.6, labels["ORT"] + ":")
    attribute("ORT", x_right + 12, -12.5, VALUE)
    attribute("FORMAT", x_right + 1, -5.0, SMALL + 0.2)
    text(-29.2, -6.6, labels["BLATTNR"] + ":")
    attribute("BLATTNR", -18, -7.5, VALUE)
    text(-29.2, -1.6, labels["VON"])
    attribute("VON", -18, -2.5, VALUE)
    return BlockDefinition(
        name=schematic_title_block_name(width),
        base_point=Point(0, 0),
        entities=EntityContainer(out),
        category="Rahmen",
        description=f"Schriftfeld für Schaltpläne, {width:g} mm breit",
    )
