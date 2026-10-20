"""Top-level drawing document: one model space plus one or more sheet layouts.

Sheets show the model through viewports (circuit diagram SLD, scaled drawings).
Pages are sheets without viewports that are drawn on directly (multi-line circuit
diagram MLD): they carry a plant and location designation and a column grid, and
are numbered per plant and location.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from sldgridy.model.blocks import BlockDefinition
from sldgridy.model.container import EntityContainer
from sldgridy.model.entities import Entity, Viewport, new_id
from sldgridy.model.layers import DEFAULT_LAYER, Layer
from sldgridy.model.paper import DEFAULT_FORMAT, DEFAULT_ORIENTATION, Orientation, sheet_size
from sldgridy.model.sheet import default_viewport
from sldgridy.model.title_block import (
    DOCUMENT_FIELDS,
    SHEET_FIELDS,
    TITLE_BLOCK_NAME,
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
    # Pages only: designation "=plant +location" and columns of the reference grid.
    plant: str = ""
    location: str = ""
    columns: int = 0

    @property
    def size(self) -> tuple[float, float]:
        return sheet_size(self.paper, self.orientation)

    def viewports(self) -> list[Viewport]:
        return [e for e in self.entities if isinstance(e, Viewport)]


PAGE_FORMAT = "A4"
PAGE_COLUMNS = 10
SHEETS, PAGES = "sheets", "pages"


def new_page(
    name: str = "",
    plant: str = "",
    location: str = "",
    paper: str = PAGE_FORMAT,
    orientation: Orientation = Orientation.LANDSCAPE,
) -> SheetLayout:
    """Page of a multi-line circuit diagram: drawn on directly, no viewport."""
    return SheetLayout(
        name=name,
        paper=paper,
        orientation=orientation,
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
    pages: list[SheetLayout] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=lambda: [Layer(DEFAULT_LAYER)])
    blocks: dict[str, BlockDefinition] = field(default_factory=dict)
    # Drawing-wide title block values (PROJEKT, FIRMA, BEARBEITER).
    properties: dict[str, str] = field(default_factory=dict)
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
    def new(cls, first_sheet_name: str, title_labels: dict[str, str] | None = None) -> "Document":
        """Create an empty drawing with one A0 landscape sheet and the standard title block."""
        doc = cls(sheets=[new_sheet(first_sheet_name)])
        doc.blocks[TITLE_BLOCK_NAME] = title_block_definition(title_labels)
        return doc

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
        self.insert_layout(SHEETS, index, sheet)

    def remove_sheet(self, sheet_id: str) -> tuple[int, SheetLayout]:
        return self.remove_layout(SHEETS, sheet_id)

    def move_sheet(self, old: int, new: int) -> None:
        self.move_layout(SHEETS, old, new)

    # -- sheets and pages alike -----------------------------------------------

    def layouts(self, kind: str) -> list[SheetLayout]:
        if kind == SHEETS:
            return self.sheets
        if kind == PAGES:
            return self.pages
        raise ValueError(kind)

    def kind_of(self, layout_id: str) -> str:
        if any(s.id == layout_id for s in self.sheets):
            return SHEETS
        if any(p.id == layout_id for p in self.pages):
            return PAGES
        raise KeyError(layout_id)

    def layout_index(self, layout_id: str) -> int:
        for i, s in enumerate(self.layouts(self.kind_of(layout_id))):
            if s.id == layout_id:
                return i
        raise KeyError(layout_id)

    def layout(self, layout_id: str) -> SheetLayout:
        """A sheet or page by id."""
        return self.layouts(self.kind_of(layout_id))[self.layout_index(layout_id)]

    def insert_layout(self, kind: str, index: int, layout: SheetLayout) -> None:
        self.layouts(kind).insert(index, layout)
        self.sheets_changed()

    def remove_layout(self, kind: str, layout_id: str) -> tuple[int, SheetLayout]:
        items = self.layouts(kind)
        if kind == SHEETS and len(items) <= 1:
            raise ValueError("a drawing keeps at least one sheet")
        i = self.layout_index(layout_id)
        layout = items.pop(i)
        self.sheets_changed()
        return i, layout

    def move_layout(self, kind: str, old: int, new: int) -> None:
        items = self.layouts(kind)
        items.insert(new, items.pop(old))
        self.sheets_changed()

    # -- pages ----------------------------------------------------------------

    def page_index(self, page_id: str) -> int:
        for i, p in enumerate(self.pages):
            if p.id == page_id:
                return i
        raise KeyError(page_id)

    def page(self, page_id: str) -> SheetLayout:
        return self.pages[self.page_index(page_id)]

    def page_group(self, page: SheetLayout) -> list[SheetLayout]:
        """Pages with the same plant and location, in page order."""
        return [p for p in self.pages if (p.plant, p.location) == (page.plant, page.location)]

    def page_number(self, page_id: str) -> tuple[int, int]:
        """Number of a page within its plant and location, and how many there are."""
        page = self.page(page_id)
        group = self.page_group(page)
        return [p.id for p in group].index(page_id) + 1, len(group)

    def page_label(self, page_id: str) -> str:
        """Full page designation, e.g. "=PV1 +UV1 /3"."""
        page = self.page(page_id)
        number = self.page_number(page_id)[0]
        prefix = designation(page.plant, page.location)
        return f"{prefix} /{number}" if prefix else f"/{number}"

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
    ) -> dict[str, str]:
        """Title block values of a sheet or page including computed ones (words for
        BLATT/FORMAT). Pages count within their plant and location."""
        sheet = self.layout(sheet_id)
        values = {tag: self.properties.get(tag, "") for tag in DOCUMENT_FIELDS}
        values.update({tag: sheet.fields.get(tag, "") for tag in SHEET_FIELDS})
        if self.kind_of(sheet_id) == PAGES:
            number, total = self.page_number(sheet_id)
            if not values["TITEL"]:
                values["TITEL"] = sheet.name
            if not values["ZEICHNUNGSNR"]:
                values["ZEICHNUNGSNR"] = designation(sheet.plant, sheet.location)
        else:
            number, total = self.sheet_index(sheet_id) + 1, len(self.sheets)
        values["BLATT"] = f"{number} {of} {total}"
        orientation = landscape if sheet.orientation is Orientation.LANDSCAPE else portrait
        values["FORMAT"] = f"{sheet.paper} {orientation}"
        return values

    def containers(self) -> Iterator[EntityContainer]:
        """Every entity container of the drawing."""
        yield self.model_space
        for sheet in self.sheets:
            yield sheet.entities
        for page in self.pages:
            yield page.entities
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
