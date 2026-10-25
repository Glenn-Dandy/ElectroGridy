"""Top-level drawing document: one model space plus the pages of the project.

Every page (``SheetLayout``) has a type: cover, table of contents, overview diagram,
circuit diagram, enclosure layout, terminal plan, cable list, parts list or drawing.
Pages are numbered through the whole project ("Blatt 3 von 12"); plant and location
are fields of a page, shown in its title block and in the table of contents. Any page
can be drawn on directly and can show the model through viewports.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from sldgridy.model.blocks import BlockDefinition
from sldgridy.model.container import EntityContainer
from sldgridy.model.entities import Entity, Viewport, new_id
from sldgridy.model.layers import DEFAULT_LAYER, Layer
from sldgridy.model.paper import DEFAULT_FORMAT, DEFAULT_ORIENTATION, Orientation, sheet_size
from sldgridy.model.sheet import default_viewport, schematic_title_width
from sldgridy.model.title_block import (
    DOCUMENT_FIELDS,
    SCHEMATIC_TITLE_PREFIX,
    SHEET_FIELDS,
    TITLE_BLOCK_NAME,
    schematic_title_block_definition,
    schematic_title_block_name,
    title_block_definition,
)


class ModelSpace(EntityContainer):
    """Unbounded drawing area holding the schematic itself."""


@dataclass
class SheetLayout:
    """A drawing frame: a paper sheet with border, title block and viewports.

    Sheet objects and viewports live in ``entities``. Border and title block
    position follow from the format.
    """

    name: str
    paper: str = DEFAULT_FORMAT
    orientation: Orientation = DEFAULT_ORIENTATION
    entities: EntityContainer = field(default_factory=EntityContainer)
    id: str = field(default_factory=new_id)
    title_block: str = TITLE_BLOCK_NAME
    # Per-sheet title block values (TITEL, ZEICHNUNGSNR, DATUM, GEPRUEFT, AENDERUNG).
    fields: dict[str, str] = field(default_factory=dict)
    # Type of the page (see PAGE_KINDS; "" for sheets from before page types) and its
    # frame: "" = drawing frame after DIN EN ISO 5457, "schematic" = circuit diagram
    # frame with columns and rows.
    kind: str = ""
    frame: str = ""
    plant: str = ""  # Anlage
    location: str = ""  # Ort
    columns: int = 0  # columns of the reference grid (schematic frame)
    # Drawing scale of the page (paper mm per real mm, 0.2 = 1:5): symbols placed on it
    # shrink, typed lengths and dimensions are real millimetres (enclosure layouts).
    scale: float = 1.0

    @property
    def size(self) -> tuple[float, float]:
        return sheet_size(self.paper, self.orientation)

    def viewports(self) -> list[Viewport]:
        return [e for e in self.entities if isinstance(e, Viewport)]


PAGE_FORMAT = "A3"  # printed fitted onto A4 (see sheet.schematic_margins)
PAGE_COLUMNS = 10
SCHEMATIC_FRAME = "schematic"

# Page types and their names (German source text, translated in the user interface).
COVER, TOC, OVERVIEW, CIRCUIT = "cover", "toc", "overview", "circuit"
ENCLOSURE, TERMINALS, CABLES, PARTS, DRAWING = (
    "enclosure",
    "terminals",
    "cables",
    "parts",
    "drawing",
)
PAGE_KINDS = {
    COVER: "Deckblatt",
    TOC: "Inhaltsverzeichnis",
    OVERVIEW: "Übersichtsschaltbild",
    CIRCUIT: "Stromlaufplan",
    ENCLOSURE: "Gehäuseaufbau",
    TERMINALS: "Klemmenplan",
    CABLES: "Kabelliste",
    PARTS: "Stückliste",
    DRAWING: "Zeichnung",
}
# Pages whose content is generated from the project (and kept up to date).
GENERATED_KINDS = (COVER, TOC, TERMINALS, CABLES, PARTS)

# What a file is, chosen when it is created: a single-line overview diagram (model and
# drawing sheets), a circuit diagram project (numbered pages in the circuit diagram
# frame, lists, cross references) or a scaled drawing (roof layout).
DOC_SLD, DOC_PROJECT, DOC_DRAWING = "sld", "project", "drawing"
DOC_KINDS = {
    DOC_SLD: "Übersichtsschaltplan",
    DOC_PROJECT: "Schaltplanprojekt",
    DOC_DRAWING: "Zeichnung",
}
# Page types offered in a project (drawings belong into a drawing file).
PROJECT_PAGE_KINDS = tuple(k for k in PAGE_KINDS if k != DRAWING)


def new_page(
    kind: str = CIRCUIT,
    name: str = "",
    plant: str = "",
    location: str = "",
    paper: str = PAGE_FORMAT,
    orientation: Orientation = Orientation.LANDSCAPE,
) -> SheetLayout:
    """A page of the project in the circuit diagram frame, drawn on directly."""
    return SheetLayout(
        name=name,
        paper=paper,
        orientation=orientation,
        kind=kind,
        frame=SCHEMATIC_FRAME,
        plant=plant,
        location=location,
        columns=PAGE_COLUMNS,
    )


def designation(plant: str, location: str) -> str:
    """ "=PV1 +UV1" style designation (empty parts left out)."""
    parts = []
    if plant:
        parts.append(f"={plant}")
    if location:
        parts.append(f"+{location}")
    return " ".join(parts)


def new_sheet(
    name: str,
    paper: str = DEFAULT_FORMAT,
    orientation: Orientation = DEFAULT_ORIENTATION,
) -> SheetLayout:
    """Sheet with one viewport filling the drawing area."""
    sheet = SheetLayout(name=name, paper=paper, orientation=orientation)
    sheet.entities.add(default_viewport(*sheet.size))
    return sheet


@dataclass
class Document:
    model_space: ModelSpace = field(default_factory=ModelSpace)
    sheets: list[SheetLayout] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=lambda: [Layer(DEFAULT_LAYER)])
    blocks: dict[str, BlockDefinition] = field(default_factory=dict)
    # Drawing-wide title block values (PROJEKT, FIRMA, BEARBEITER).
    properties: dict[str, str] = field(default_factory=dict)
    kind: str = DOC_SLD
    _sheet_listeners: list[Callable[[], None]] = field(
        default_factory=list, repr=False, compare=False
    )
    _layer_listeners: list[Callable[[], None]] = field(
        default_factory=list, repr=False, compare=False
    )
    _block_listeners: list[Callable[[str], None]] = field(
        default_factory=list, repr=False, compare=False
    )

    @classmethod
    def new(
        cls,
        first_sheet_name: str,
        title_labels: dict[str, str] | None = None,
        kind: str = DOC_SLD,
    ) -> "Document":
        """Create an empty drawing with one A0 landscape sheet and the standard title block."""
        doc = cls(sheets=[new_sheet(first_sheet_name)], kind=kind)
        doc.blocks[TITLE_BLOCK_NAME] = title_block_definition(title_labels)
        return doc

    @classmethod
    def new_project(
        cls, title_definition: Callable[[float], BlockDefinition] | None = None
    ) -> "Document":
        """Empty circuit diagram project: a cover and a first circuit diagram page, A3,
        each with the circuit diagram title block (``title_definition`` makes it for a
        width, translated by the caller)."""
        make = title_definition or schematic_title_block_definition
        doc = cls(sheets=[new_page(COVER), new_page(CIRCUIT)], kind=DOC_PROJECT)
        for page in doc.sheets:
            width = schematic_title_width(*page.size)
            page.title_block = schematic_title_block_name(width)
            if page.title_block not in doc.blocks:
                doc.blocks[page.title_block] = make(width)
        return doc

    @property
    def is_project(self) -> bool:
        return self.kind == DOC_PROJECT

    def fit_schematic_title_blocks(
        self, title_definition: Callable[[float], BlockDefinition] | None = None
    ) -> bool:
        """Give every page in the circuit diagram frame the title block for its width
        (files of older versions had other frame margins); title blocks no page uses
        any more are dropped. True if anything changed."""
        make = title_definition or schematic_title_block_definition
        changed = False
        for page in self.sheets:
            if page.frame != SCHEMATIC_FRAME or not page.title_block.startswith(
                SCHEMATIC_TITLE_PREFIX
            ):
                continue
            width = schematic_title_width(*page.size)
            name = schematic_title_block_name(width)
            if page.title_block != name:
                if name not in self.blocks:
                    self.blocks[name] = make(width)
                page.title_block = name
                changed = True
        if changed:
            used = {page.title_block for page in self.sheets}
            for name in [n for n in self.blocks if n.startswith(SCHEMATIC_TITLE_PREFIX)]:
                if name not in used:
                    del self.blocks[name]
        return changed

    # -- sheets -------------------------------------------------------------

    def subscribe_sheets(self, listener: Callable[[], None]) -> None:
        self._sheet_listeners.append(listener)

    def unsubscribe_sheets(self, listener: Callable[[], None]) -> None:
        self._sheet_listeners.remove(listener)

    def sheets_changed(self) -> None:
        """Notify listeners; called after any change to the sheet list or sheet settings."""
        for listener in list(self._sheet_listeners):
            listener()

    def sheet_index(self, sheet_id: str) -> int:
        for i, s in enumerate(self.sheets):
            if s.id == sheet_id:
                return i
        raise KeyError(sheet_id)

    def sheet(self, sheet_id: str) -> SheetLayout:
        return self.sheets[self.sheet_index(sheet_id)]

    def insert_sheet(self, index: int, sheet: SheetLayout) -> None:
        self.sheets.insert(index, sheet)
        self.sheets_changed()

    def remove_sheet(self, sheet_id: str) -> tuple[int, SheetLayout]:
        if len(self.sheets) <= 1:
            raise ValueError("a drawing keeps at least one sheet")
        i = self.sheet_index(sheet_id)
        sheet = self.sheets.pop(i)
        self.sheets_changed()
        return i, sheet

    def move_sheet(self, old: int, new: int) -> None:
        sheet = self.sheets.pop(old)
        self.sheets.insert(new, sheet)
        self.sheets_changed()

    # -- page numbers -----------------------------------------------------------

    def page_number(self, sheet_id: str) -> int:
        """Pages are numbered through the whole project."""
        return self.sheet_index(sheet_id) + 1

    def page_label(self, sheet_id: str) -> str:
        """ "/3" for page 3."""
        return f"/{self.page_number(sheet_id)}"

    def unique_sheet_name(self, base: str) -> str:
        names = {s.name for s in self.sheets}
        if base not in names:
            return base
        n = 2
        while f"{base} ({n})" in names:
            n += 1
        return f"{base} ({n})"

    def field_values(
        self,
        sheet_id: str,
        of: str = "von",
        landscape: str = "quer",
        portrait: str = "hoch",
        kinds: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Title block values of a page including computed ones (words for BLATT,
        FORMAT and the page type come from the caller in its language)."""
        sheet = self.sheet(sheet_id)
        values = {tag: self.properties.get(tag, "") for tag in DOCUMENT_FIELDS}
        values.update({tag: sheet.fields.get(tag, "") for tag in SHEET_FIELDS})
        number, total = self.page_number(sheet_id), len(self.sheets)
        values["BLATT"] = f"{number} {of} {total}"
        values["BLATTNR"] = str(number)
        values["VON"] = str(total)
        orientation = landscape if sheet.orientation is Orientation.LANDSCAPE else portrait
        values["FORMAT"] = f"{sheet.paper} {orientation}"
        # Plant and location of the page, else those of the project.
        values["ANLAGE"] = sheet.plant or values.get("ANLAGE", "")
        values["ORT"] = sheet.location or values.get("ORT", "")
        kind_name = (kinds or PAGE_KINDS).get(sheet.kind, "")
        values["SEITENTYP"] = kind_name
        if not values["TITEL"]:
            # The circuit diagram title block shows the type in a field of its own.
            schematic = sheet.frame == SCHEMATIC_FRAME
            values["TITEL"] = sheet.name or ("" if schematic else kind_name)
        return values

    def containers(self) -> Iterator[EntityContainer]:
        """Every entity container of the drawing."""
        yield self.model_space
        for sheet in self.sheets:
            yield sheet.entities
        for definition in self.blocks.values():
            yield definition.entities

    # -- blocks -------------------------------------------------------------

    def subscribe_blocks(self, listener: Callable[[str], None]) -> None:
        self._block_listeners.append(listener)

    def unsubscribe_blocks(self, listener: Callable[[str], None]) -> None:
        self._block_listeners.remove(listener)

    def _block_changed(self, name: str) -> None:
        for listener in list(self._block_listeners):
            listener(name)

    def set_block(self, definition: BlockDefinition) -> None:
        """Add or replace a block definition."""
        self.blocks[definition.name] = definition
        self._block_changed(definition.name)

    def remove_block(self, name: str) -> BlockDefinition:
        definition = self.blocks.pop(name)
        self._block_changed(name)
        return definition

    def block_in_use(self, name: str) -> bool:
        from sldgridy.model.entities import BlockReference

        return any(
            isinstance(e, BlockReference) and e.name == name for c in self.containers() for e in c
        )

    # -- layers -------------------------------------------------------------

    def subscribe_layers(self, listener: Callable[[], None]) -> None:
        self._layer_listeners.append(listener)

    def unsubscribe_layers(self, listener: Callable[[], None]) -> None:
        self._layer_listeners.remove(listener)

    def _layers_changed(self) -> None:
        for listener in list(self._layer_listeners):
            listener()

    def has_layer(self, name: str) -> bool:
        return any(layer.name == name for layer in self.layers)

    def layer_index(self, name: str) -> int:
        for i, layer in enumerate(self.layers):
            if layer.name == name:
                return i
        raise KeyError(name)

    def insert_layer(self, index: int, layer: Layer) -> None:
        if self.has_layer(layer.name):
            raise ValueError(f"layer {layer.name!r} exists")
        self.layers.insert(index, layer)
        self._layers_changed()

    def remove_layer(self, name: str) -> tuple[int, Layer]:
        if name == DEFAULT_LAYER:
            raise ValueError("layer 0 cannot be removed")
        i = self.layer_index(name)
        layer = self.layers.pop(i)
        self._layers_changed()
        return i, layer

    def set_layer(self, index: int, layer: Layer) -> None:
        """Replace the layer at ``index`` (also used for renaming)."""
        old = self.layers[index]
        if old.name == DEFAULT_LAYER and layer.name != DEFAULT_LAYER:
            raise ValueError("layer 0 cannot be renamed")
        if layer.name != old.name and self.has_layer(layer.name):
            raise ValueError(f"layer {layer.name!r} exists")
        self.layers[index] = layer
        self._layers_changed()

    def layer_in_use(self, name: str) -> bool:
        return any(e.layer == name for c in self.containers() for e in c)

    def layer(self, name: str) -> Layer:
        """Layer by name; unknown names fall back to layer 0."""
        for layer in self.layers:
            if layer.name == name:
                return layer
        return self.layers[0]

    def effective_color(self, entity: Entity) -> str:
        return entity.color or self.layer(entity.layer).color

    def effective_lineweight(self, entity: Entity) -> float:
        if entity.lineweight is not None:
            return entity.lineweight
        return self.layer(entity.layer).lineweight

    def effective_linetype(self, entity: Entity) -> str:
        return entity.linetype or self.layer(entity.layer).linetype
