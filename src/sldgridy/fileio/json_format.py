"""Conversion between the document model and the versioned JSON structure."""

import base64
import binascii
import copy
from collections.abc import Callable
from typing import Any

from sldgridy import __version__
from sldgridy.model.blocks import BlockDefinition
from sldgridy.model.container import EntityContainer
from sldgridy.model.document import (
    DOC_KINDS,
    DOC_PROJECT,
    DOC_SLD,
    DRAWING,
    PAGE_KINDS,
    SCHEMATIC_FRAME,
    Document,
    ModelSpace,
    SheetLayout,
)
from sldgridy.model.entities import (
    DIMENSION_ORIENTATIONS,
    Arc,
    AttributeDefinition,
    BlockReference,
    Busbar,
    Circle,
    ConnectionPoint,
    Dimension,
    Entity,
    InterruptionPoint,
    JunctionMark,
    Line,
    Polyline,
    RasterImage,
    Rectangle,
    Text,
    Viewport,
    Wire,
    new_id,
)
from sldgridy.model.geometry import Point
from sldgridy.model.layers import DEFAULT_LAYER, Layer
from sldgridy.model.paper import Orientation, sheet_size
from sldgridy.model.sheet import default_viewport, schematic_title_width
from sldgridy.model.title_block import (
    TITLE_BLOCK_NAME,
    schematic_title_block_definition,
    schematic_title_block_name,
    title_block_definition,
)

# Newest version this program reads. Files are written with the lowest version that
# holds their content, so older releases keep opening what they can show: libraries,
# frame templates and drawings without page types or interruption points stay version
# 2; the others (version 3) need SLDGridy 1.3 or newer.
FORMAT_VERSION = 3
BASE_VERSION = 2


def _migrate_1_to_2(data: dict) -> dict:
    """Version 2 adds sheet ids, title blocks, title block fields and viewports."""
    if data.get("type") in ("library", "frame"):
        return data  # nothing changed for these file types
    data.setdefault("properties", {})
    blocks = data.setdefault("blocks", [])
    if not any(b.get("name") == TITLE_BLOCK_NAME for b in blocks if isinstance(b, dict)):
        blocks.append(block_to_dict(title_block_definition()))
    for sheet in data.get("sheets", []):
        sheet.setdefault("id", new_id())
        sheet.setdefault("title_block", TITLE_BLOCK_NAME)
        sheet.setdefault("fields", {})
        entities = sheet.setdefault("entities", [])
        if not any(e.get("type") == "viewport" for e in entities):
            w, h = sheet_size(str(sheet.get("paper", "A0")), Orientation(sheet["orientation"]))
            entities.insert(0, entity_to_dict(default_viewport(w, h)))
    return data


def _migrate_2_to_3(data: dict) -> dict:
    """Version 3 adds page types, the circuit diagram frame and interruption points;
    older files have none of them."""
    return data


# Migration from version N to N + 1, keyed by N.
MIGRATIONS: dict[int, Callable[[dict], dict]] = {1: _migrate_1_to_2, 2: _migrate_2_to_3}


class FileFormatError(Exception):
    pass


# -- points ---------------------------------------------------------------


def _pt(p: Point) -> list[float]:
    return [p.x, p.y]


def _to_pt(v: Any) -> Point:
    x, y = v
    return Point(float(x), float(y))


# -- entities -------------------------------------------------------------

_TYPE_NAMES: dict[type, str] = {
    Line: "line",
    Polyline: "polyline",
    Rectangle: "rectangle",
    RasterImage: "image",
    Circle: "circle",
    Arc: "arc",
    Text: "text",
    AttributeDefinition: "attdef",
    ConnectionPoint: "connection",
    BlockReference: "block_ref",
    Wire: "wire",
    Busbar: "busbar",
    Viewport: "viewport",
    JunctionMark: "junction",
    InterruptionPoint: "interruption",
    Dimension: "dimension",
}


def entity_to_dict(e: Entity) -> dict[str, Any]:
    d: dict[str, Any] = {"type": _TYPE_NAMES[type(e)], "id": e.id, "layer": e.layer}
    for key in ("color", "lineweight", "linetype"):
        value = getattr(e, key)
        if value is not None:
            d[key] = value
    match e:
        case Line() | Rectangle() | Busbar():
            d["p1"], d["p2"] = _pt(e.p1), _pt(e.p2)
        case RasterImage():
            d["p1"], d["p2"] = _pt(e.p1), _pt(e.p2)
            d["data"] = base64.b64encode(e.data).decode("ascii")
            if e.rotation:
                d["rotation"] = e.rotation
            if e.flipped:
                d["flipped"] = True
        case Dimension():
            d["p1"], d["p2"], d["position"] = _pt(e.p1), _pt(e.p2), _pt(e.position)
            d["orientation"], d["height"] = e.orientation, e.height
            if e.vertex is not None:
                d["vertex"] = _pt(e.vertex)
            if e.text:
                d["text"] = e.text
        case Wire():
            d["points"] = [_pt(p) for p in e.points]
            if e.label:
                d["label"], d["label_side"], d["label_height"] = (
                    e.label,
                    e.label_side,
                    e.label_height,
                )
                if e.label_align != "center":
                    d["label_align"] = e.label_align
                if e.label_pos != "auto":
                    d["label_pos"] = e.label_pos
                if e.label_pos == "free":
                    d["label_at"] = e.label_at
            if e.cable:
                d["cable"] = e.cable
            if e.core:
                d["core"] = e.core
        case Polyline():
            d["points"] = [_pt(p) for p in e.points]
            d["closed"] = e.closed
        case Circle():
            d["center"], d["radius"] = _pt(e.center), e.radius
        case Arc():
            d["center"], d["radius"] = _pt(e.center), e.radius
            d["start_angle"], d["end_angle"] = e.start_angle, e.end_angle
        case Text():
            d["position"], d["text"] = _pt(e.position), e.text
            d["height"], d["rotation"] = e.height, e.rotation
            if e.halign != "left":
                d["halign"] = e.halign
            if e.valign != "baseline":
                d["valign"] = e.valign
        case AttributeDefinition():
            d["tag"], d["prompt"], d["default"] = e.tag, e.prompt, e.default
            d["position"], d["height"], d["rotation"] = _pt(e.position), e.height, e.rotation
            d["visible"], d["halign"], d["valign"] = e.visible, e.halign, e.valign
        case ConnectionPoint():
            d["name"], d["position"], d["direction"] = e.name, _pt(e.position), e.direction
        case JunctionMark():
            d["position"], d["connected"] = _pt(e.position), e.connected
        case InterruptionPoint():
            d["name"], d["position"] = e.name, _pt(e.position)
            d["direction"], d["height"] = _angle(e.direction), e.height
        case Viewport():
            d["p1"], d["p2"], d["center"] = _pt(e.p1), _pt(e.p2), _pt(e.center)
            d["scale"], d["locked"], d["print_border"] = e.scale, e.locked, e.print_border
        case BlockReference():
            d["name"], d["insert"] = e.name, _pt(e.insert)
            d["rotation"], d["mirrored"] = e.rotation, e.mirrored_x
            d["attributes"] = dict(e.attributes)
            if e.docks:
                d["docks"] = [_pt(p) for p in e.docks]
            if e.scale != 1.0:
                d["scale"] = e.scale
    return d


def _choice(value: Any, allowed: tuple[str, ...]) -> str:
    """Unknown values (from a newer version) fall back to the first choice."""
    value = str(value)
    return value if value in allowed else allowed[0]


def _positive(value: Any) -> float:
    f = float(value)
    if not f > 0:
        raise FileFormatError("block scale must be positive")
    return f


def _angle(value: Any) -> int | float:
    """Degrees; whole numbers stay int (as written before free rotation existed)."""
    f = float(value)
    return int(f) if f.is_integer() else f


def entity_from_dict(d: dict[str, Any]) -> Entity:
    common = {
        "id": str(d["id"]),
        "layer": str(d.get("layer", DEFAULT_LAYER)),
        "color": d.get("color"),
        "lineweight": d.get("lineweight"),
        "linetype": d.get("linetype"),
    }
    kind = d.get("type")
    match kind:
        case "line":
            return Line(p1=_to_pt(d["p1"]), p2=_to_pt(d["p2"]), **common)
        case "rectangle":
            return Rectangle(p1=_to_pt(d["p1"]), p2=_to_pt(d["p2"]), **common)
        case "image":
            try:
                data = base64.b64decode(str(d["data"]), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise FileFormatError(f"image {d.get('id')!r}: invalid data") from exc
            return RasterImage(
                p1=_to_pt(d["p1"]),
                p2=_to_pt(d["p2"]),
                data=data,
                rotation=int(d.get("rotation", 0)) % 4,
                flipped=bool(d.get("flipped", False)),
                **common,
            )
        case "interruption":
            return InterruptionPoint(
                name=str(d["name"]),
                position=_to_pt(d["position"]),
                direction=_angle(d.get("direction", 0)),
                height=float(d.get("height", 2.5)),
                **common,
            )
        case "junction":
            return JunctionMark(
                position=_to_pt(d["position"]), connected=bool(d.get("connected", True)), **common
            )
        case "viewport":
            scale = float(d.get("scale", 1.0))
            if not scale > 0:
                raise FileFormatError("viewport scale must be positive")
            return Viewport(
                p1=_to_pt(d["p1"]),
                p2=_to_pt(d["p2"]),
                center=_to_pt(d["center"]),
                scale=scale,
                locked=bool(d.get("locked", False)),
                print_border=bool(d.get("print_border", False)),
                **common,
            )
        case "dimension":
            orientation = str(d.get("orientation", "aligned"))
            vertex = _to_pt(d["vertex"]) if "vertex" in d else None
            if orientation == "angular" and vertex is None:
                orientation = "aligned"
            return Dimension(
                vertex=vertex,
                p1=_to_pt(d["p1"]),
                p2=_to_pt(d["p2"]),
                position=_to_pt(d["position"]),
                orientation=orientation if orientation in DIMENSION_ORIENTATIONS else "aligned",
                text=str(d.get("text", "")),
                height=float(d.get("height", 2.5)),
                **common,
            )
        case "busbar":
            return Busbar(p1=_to_pt(d["p1"]), p2=_to_pt(d["p2"]), **common)
        case "wire":
            return Wire(
                points=tuple(_to_pt(p) for p in d["points"]),
                label=str(d.get("label", "")),
                label_side=1 if int(d.get("label_side", 1)) >= 0 else -1,
                label_height=float(d.get("label_height", 2.5)),
                label_align=str(d.get("label_align", "center"))
                if d.get("label_align") in ("left", "right")
                else "center",
                label_pos=str(d["label_pos"])
                if d.get("label_pos") in ("start", "end", "free")
                else "auto",
                label_at=float(d.get("label_at", 0.0)),
                cable=str(d.get("cable", "")),
                core=str(d.get("core", "")),
                **common,
            )
        case "polyline":
            return Polyline(
                points=tuple(_to_pt(p) for p in d["points"]),
                closed=bool(d.get("closed", False)),
                **common,
            )
        case "circle":
            return Circle(center=_to_pt(d["center"]), radius=float(d["radius"]), **common)
        case "arc":
            return Arc(
                center=_to_pt(d["center"]),
                radius=float(d["radius"]),
                start_angle=float(d["start_angle"]),
                end_angle=float(d["end_angle"]),
                **common,
            )
        case "text":
            return Text(
                position=_to_pt(d["position"]),
                text=str(d["text"]),
                height=float(d["height"]),
                rotation=_angle(d.get("rotation", 0)),
                halign=str(d.get("halign", "left")),
                valign=str(d.get("valign", "baseline")),
                **common,
            )
        case "attdef":
            return AttributeDefinition(
                tag=str(d["tag"]),
                prompt=str(d.get("prompt", "")),
                default=str(d.get("default", "")),
                position=_to_pt(d["position"]),
                height=float(d.get("height", 2.5)),
                rotation=_angle(d.get("rotation", 0)),
                visible=bool(d.get("visible", True)),
                halign=str(d.get("halign", "left")),
                valign=str(d.get("valign", "middle")),
                **common,
            )
        case "connection":
            return ConnectionPoint(
                name=str(d["name"]),
                position=_to_pt(d["position"]),
                direction=_angle(d.get("direction", 0)) % 360,
                **common,
            )
        case "block_ref":
            attributes = d.get("attributes", {})
            if not isinstance(attributes, dict):
                raise FileFormatError("block attributes must be an object")
            return BlockReference(
                name=str(d["name"]),
                insert=_to_pt(d["insert"]),
                rotation=int(d.get("rotation", 0)) % 360,
                mirrored_x=bool(d.get("mirrored", False)),
                attributes=tuple(sorted((str(k), str(v)) for k, v in attributes.items())),
                docks=tuple(_to_pt(p) for p in d.get("docks", [])),
                scale=_positive(d.get("scale", 1.0)),
                **common,
            )
    raise FileFormatError(f"unknown entity type {kind!r}")


# -- blocks ---------------------------------------------------------------


def block_to_dict(b: BlockDefinition) -> dict[str, Any]:
    d: dict[str, Any] = {"name": b.name, "base_point": _pt(b.base_point)}
    if b.category:
        d["category"] = b.category
    if b.description:
        d["description"] = b.description
    if b.function:
        d["function"] = b.function
    if b.contact:
        d["contact"] = b.contact
    d["entities"] = [entity_to_dict(e) for e in b.entities]
    return d


def block_from_dict(d: dict[str, Any]) -> BlockDefinition:
    try:
        return BlockDefinition(
            name=str(d["name"]),
            base_point=_to_pt(d.get("base_point", [0, 0])),
            entities=EntityContainer(entity_from_dict(e) for e in d.get("entities", [])),
            category=str(d.get("category", "")),
            description=str(d.get("description", "")),
            function=_choice(d.get("function", ""), ("", "main", "aux", "terminal")),
            contact=_choice(d.get("contact", ""), ("", "no", "nc", "co")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, FileFormatError):
            raise
        raise FileFormatError(f"invalid block definition: {exc}") from exc


def block_signature(b: BlockDefinition) -> dict[str, Any]:
    """Content of a definition without entity ids, for comparing definitions."""
    d = block_to_dict(b)
    d["entities"] = [{k: v for k, v in e.items() if k != "id"} for e in d["entities"]]
    return d


def library_to_dict(blocks: list[BlockDefinition], name: str = "") -> dict[str, Any]:
    return {
        "format_version": BASE_VERSION,
        "type": "library",
        "name": name,
        "blocks": [block_to_dict(b) for b in blocks],
    }


def library_from_dict(data: dict[str, Any]) -> tuple[str, list[BlockDefinition]]:
    data = migrate(data)
    if data.get("type") != "library":
        raise FileFormatError("not a library file")
    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        raise FileFormatError("library without blocks")
    return str(data.get("name", "")), [block_from_dict(b) for b in blocks]


# -- document -------------------------------------------------------------


def _layer_to_dict(layer: Layer) -> dict[str, Any]:
    return {
        "name": layer.name,
        "color": layer.color,
        "lineweight": layer.lineweight,
        "linetype": layer.linetype,
        "visible": layer.visible,
        "locked": layer.locked,
        "printable": layer.printable,
        "workspace": layer.workspace,
    }


def _layer_from_dict(d: dict[str, Any]) -> Layer:
    return Layer(
        name=str(d["name"]),
        color=str(d.get("color", "#000000")),
        lineweight=float(d.get("lineweight", 0.25)),
        linetype=str(d.get("linetype", "continuous")),
        visible=bool(d.get("visible", True)),
        locked=bool(d.get("locked", False)),
        printable=bool(d.get("printable", True)),
        # Layers from before workspaces belong to the circuit diagram, layer 0 to all.
        workspace=_layer_workspace(d),
    )


def _needs_version_3(doc: Document) -> bool:
    if doc.kind != DOC_SLD or any(s.kind or s.frame for s in doc.sheets):
        return True
    return any(isinstance(e, InterruptionPoint | RasterImage) for c in doc.containers() for e in c)


def _layer_workspace(d: dict[str, Any]) -> str:
    """Layers from before workspaces belong to the circuit diagram, layer 0 to all;
    those of the multi-line workspace of the development versions to the circuit
    diagram as well."""
    workspace = str(d.get("workspace", "" if str(d["name"]) == "0" else "sld"))
    return "sld" if workspace == "mld" else workspace


def document_to_dict(doc: Document) -> dict[str, Any]:
    d = {
        "format_version": FORMAT_VERSION if _needs_version_3(doc) else BASE_VERSION,
        "application": f"SLDGridy {__version__}",
        "properties": dict(doc.properties),
        "layers": [_layer_to_dict(layer) for layer in doc.layers],
        "blocks": [block_to_dict(b) for b in doc.blocks.values()],
        "model": {"entities": [entity_to_dict(e) for e in doc.model_space]},
        "sheets": [sheet_to_dict(s) for s in doc.sheets],
    }
    if doc.kind != DOC_SLD:
        d["kind"] = doc.kind
    return d


def _document_kind(data: dict[str, Any], sheets: list[SheetLayout]) -> str:
    """Files from before document kinds: pages with a type or the circuit diagram frame
    make a project, everything else is an overview diagram."""
    if "kind" in data:
        return _choice(data["kind"], tuple(DOC_KINDS))
    if any(s.frame or (s.kind and s.kind != DRAWING) for s in sheets):
        return DOC_PROJECT
    return DOC_SLD


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Bring ``data`` up to FORMAT_VERSION."""
    version = data.get("format_version")
    if not isinstance(version, int) or version < 1:
        raise FileFormatError("missing or invalid format_version")
    if version > FORMAT_VERSION:
        raise FileFormatError(
            f"file format version {version} is newer than supported version {FORMAT_VERSION}"
        )
    if version < FORMAT_VERSION:
        data = copy.deepcopy(data)  # migrations work on a copy, the caller's data stays
    while version < FORMAT_VERSION:
        data = MIGRATIONS[version](data)
        version += 1
        data["format_version"] = version
    return data


def document_from_dict(data: dict[str, Any]) -> Document:
    data = migrate(data)
    try:
        layers = [_layer_from_dict(d) for d in data.get("layers", [])]
        blocks = {b.name: b for b in (block_from_dict(d) for d in data.get("blocks", []))}
        if not any(layer.name == DEFAULT_LAYER for layer in layers):
            layers.insert(0, Layer(DEFAULT_LAYER))
        model = ModelSpace(entity_from_dict(d) for d in data["model"]["entities"])
        sheets = [sheet_from_dict(s) for s in data["sheets"]]
        if not sheets:
            raise FileFormatError("a drawing needs at least one sheet")
        # Development versions 1.3.0.dev3 to dev6 kept pages in a list of their own.
        dev_pages = [
            _dev_page(sheet_from_dict(p), str(p.get("report", ""))) for p in data.get("pages", [])
        ]
        for page in dev_pages:  # with the title block of the new frame
            width = schematic_title_width(*page.size)
            page.title_block = schematic_title_block_name(width)
            if page.title_block not in blocks:
                blocks[page.title_block] = schematic_title_block_definition(width)
        sheets += dev_pages
        properties = {str(k): str(v) for k, v in data.get("properties", {}).items()}
        kind = _document_kind(data, sheets)
    except (KeyError, TypeError, ValueError) as exc:
        raise FileFormatError(f"invalid drawing data: {exc}") from exc
    return Document(
        model_space=model,
        sheets=sheets,
        layers=layers,
        blocks=blocks,
        properties=properties,
        kind=kind,
    )


def sheet_to_dict(s: SheetLayout) -> dict[str, Any]:
    d = {
        "id": s.id,
        "name": s.name,
        "paper": s.paper,
        "orientation": s.orientation.value,
        "title_block": s.title_block,
        "fields": dict(s.fields),
        "entities": [entity_to_dict(e) for e in s.entities],
    }
    for key in ("kind", "frame", "plant", "location", "columns"):  # set on pages only
        if getattr(s, key):
            d[key] = getattr(s, key)
    return d


def _dev_page(page: SheetLayout, report: str) -> SheetLayout:
    """A page of a development version: circuit diagram (or its list type), new frame."""
    page.kind = report if report in PAGE_KINDS else "circuit"
    page.frame = SCHEMATIC_FRAME
    page.columns = page.columns or 10
    return page


def sheet_from_dict(s: dict[str, Any]) -> SheetLayout:
    paper = str(s["paper"])
    orientation = Orientation(s["orientation"])
    sheet_size(paper, orientation)  # validates the format
    return SheetLayout(
        id=str(s.get("id") or new_id()),
        name=str(s["name"]),
        paper=paper,
        orientation=orientation,
        title_block=str(s.get("title_block", TITLE_BLOCK_NAME)),
        fields={str(k): str(v) for k, v in s.get("fields", {}).items()},
        entities=EntityContainer(entity_from_dict(d) for d in s.get("entities", [])),
        plant=str(s.get("plant", "")),
        location=str(s.get("location", "")),
        columns=max(0, int(s.get("columns", 0))),
        kind=_choice(s.get("kind", ""), ("", *PAGE_KINDS)),
        frame=_choice(s.get("frame", ""), ("", SCHEMATIC_FRAME)),
    )
