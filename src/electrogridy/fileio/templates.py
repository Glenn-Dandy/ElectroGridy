"""Frame templates (.grdyframe): a sheet layout without model content."""

import json
from pathlib import Path
from typing import Any

from electrogridy.fileio.files import write_json_atomic
from electrogridy.fileio.json_format import (
    BASE_VERSION,
    FileFormatError,
    block_from_dict,
    block_to_dict,
    entity_from_dict,
    entity_to_dict,
    migrate,
)
from electrogridy.model.blocks import BlockDefinition, dependencies
from electrogridy.model.container import EntityContainer
from electrogridy.model.document import SheetLayout
from electrogridy.model.entities import BlockReference
from electrogridy.model.paper import Orientation, sheet_size

TEMPLATE_SUFFIX = ".grdyframe"
LEGACY_TEMPLATE_SUFFIX = ".sldgframe"  # SLDGridy until 1.3.2
TEMPLATE_SUFFIXES = (TEMPLATE_SUFFIX, LEGACY_TEMPLATE_SUFFIX)


def frame_to_dict(
    sheet: SheetLayout, blocks: dict[str, BlockDefinition], name: str
) -> dict[str, Any]:
    names = {e.name for e in sheet.entities if isinstance(e, BlockReference)}
    if sheet.title_block:
        names.add(sheet.title_block)
    needed: dict[str, BlockDefinition] = {}
    for n in sorted(names):
        for dep in dependencies(n, blocks):
            if dep in blocks:
                needed[dep] = blocks[dep]
    return {
        "format_version": BASE_VERSION,
        "type": "frame",
        "name": name,
        "paper": sheet.paper,
        "orientation": sheet.orientation.value,
        "title_block": sheet.title_block,
        "blocks": [block_to_dict(b) for b in needed.values()],
        "entities": [entity_to_dict(e) for e in sheet.entities],
    }


def frame_from_dict(data: dict[str, Any]) -> tuple[str, SheetLayout, list[BlockDefinition]]:
    """Template name, a new sheet (fresh id, no field values) and the blocks it uses."""
    data = migrate(data)
    if data.get("type") != "frame":
        raise FileFormatError("not a frame template")
    try:
        paper = str(data["paper"])
        orientation = Orientation(data["orientation"])
        sheet_size(paper, orientation)
        sheet = SheetLayout(
            name=str(data.get("name", "")),
            paper=paper,
            orientation=orientation,
            title_block=str(data.get("title_block", "")),
            entities=EntityContainer(entity_from_dict(e) for e in data.get("entities", [])),
        )
        blocks = [block_from_dict(b) for b in data.get("blocks", [])]
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, FileFormatError):
            raise
        raise FileFormatError(f"invalid frame template: {exc}") from exc
    return str(data.get("name", "")), sheet, blocks


def save_frame(sheet: SheetLayout, blocks: dict[str, BlockDefinition], path: Path, name: str):
    write_json_atomic(Path(path), frame_to_dict(sheet, blocks, name))


def load_frame(path: Path) -> tuple[str, SheetLayout, list[BlockDefinition]]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise FileFormatError(f"not a valid JSON file: {exc}") from exc
    if not isinstance(data, dict):
        raise FileFormatError("not a frame template")
    return frame_from_dict(data)
