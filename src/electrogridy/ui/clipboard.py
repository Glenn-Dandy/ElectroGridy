"""Copy and paste of entities through the system clipboard."""

import json

from PyQt6.QtCore import QMimeData
from PyQt6.QtWidgets import QApplication

from electrogridy.fileio.json_format import FileFormatError, entity_from_dict, entity_to_dict
from electrogridy.model.entities import Entity
from electrogridy.model.geometry import Point

MIME_TYPE = "application/x-electrogridy-entities"


def copy_entities(entities: list[Entity], base: Point, extra: dict | None = None) -> None:
    payload = {
        "base": [base.x, base.y],
        "entities": [entity_to_dict(e) for e in entities],
        **(extra or {}),
    }
    data = QMimeData()
    data.setData(MIME_TYPE, json.dumps(payload).encode("utf-8"))
    QApplication.clipboard().setMimeData(data)


def clipboard_payload() -> dict | None:
    data = QApplication.clipboard().mimeData()
    if data is None or not data.hasFormat(MIME_TYPE):
        return None
    try:
        payload = json.loads(bytes(data.data(MIME_TYPE)).decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None


def paste_entities(payload: dict) -> tuple[list[Entity], Point] | None:
    try:
        entities = [entity_from_dict(d) for d in payload["entities"]]
        x, y = payload["base"]
        return entities, Point(float(x), float(y))
    except (KeyError, TypeError, ValueError, FileFormatError):
        return None
