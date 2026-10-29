"""Reading and writing drawing files."""

import json
import os
import shutil
import tempfile
from pathlib import Path

from electrogridy.fileio.json_format import (
    FileFormatError,
    document_from_dict,
    document_to_dict,
    library_from_dict,
    library_to_dict,
)
from electrogridy.model.blocks import BlockDefinition
from electrogridy.model.document import Document

DRAWING_SUFFIX = ".grdy"
LIBRARY_SUFFIX = ".grdylib"
# Until 1.3.2 the program was called SLDGridy; its files still open.
LEGACY_DRAWING_SUFFIX = ".sldg"
LEGACY_LIBRARY_SUFFIX = ".sldglib"
DRAWING_SUFFIXES = (DRAWING_SUFFIX, LEGACY_DRAWING_SUFFIX)
LIBRARY_SUFFIXES = (LIBRARY_SUFFIX, LEGACY_LIBRARY_SUFFIX)


def patterns(suffixes: tuple[str, ...]) -> str:
    """File dialog patterns, e.g. "*.grdy *.sldg"."""
    return " ".join(f"*{s}" for s in suffixes)


def write_json_atomic(path: Path, data: dict) -> None:
    """Write ``data`` to ``path`` via a temporary file; keep the previous file as ``.bak``."""
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        # mkstemp creates 0600; keep the old file's mode or use the umask default.
        if path.exists():
            mode = path.stat().st_mode & 0o7777
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        else:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def save_document(doc: Document, path: Path) -> None:
    write_json_atomic(Path(path), document_to_dict(doc))


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise FileFormatError(f"not a valid JSON file: {exc}") from exc
    if not isinstance(data, dict):
        raise FileFormatError("unexpected file content")
    return data


def load_document(path: Path) -> Document:
    return document_from_dict(_read_json(path))


def save_library(
    blocks: list[BlockDefinition], path: Path, name: str = "", workspace: str | None = None
) -> None:
    """Write a library file; without ``workspace`` a file being overwritten keeps its
    own (editing an imported circuit diagram library left it shown everywhere)."""
    path = Path(path)
    if workspace is None:
        workspace = library_workspace(path) if path.exists() else ""
    write_json_atomic(path, library_to_dict(blocks, name, workspace))


def load_library(path: Path) -> tuple[str, list[BlockDefinition]]:
    return library_from_dict(_read_json(path))


def library_workspace(path: Path) -> str:
    """Workspace a library belongs to ("sld", "drawing"); empty means every workspace."""
    try:
        value = _read_json(path).get("workspace", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return value if isinstance(value, str) else ""
