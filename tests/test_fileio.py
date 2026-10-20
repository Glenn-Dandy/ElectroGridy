import json

import pytest

from factories import sample_entities
from sldgridy.fileio import json_format
from sldgridy.fileio.files import load_document, save_document
from sldgridy.fileio.json_format import (
    BASE_VERSION,
    FORMAT_VERSION,
    FileFormatError,
    document_from_dict,
    document_to_dict,
    entity_from_dict,
    entity_to_dict,
)
from sldgridy.model.document import Document
from sldgridy.model.layers import Layer
from sldgridy.model.paper import Orientation


@pytest.mark.parametrize("entity", sample_entities(), ids=lambda e: type(e).__name__)
def test_entity_roundtrip(entity):
    d = entity_to_dict(entity)
    assert entity_from_dict(json.loads(json.dumps(d))) == entity


def make_document() -> Document:
    doc = Document.new("Blatt 1")
    doc.layers.append(Layer("Leitungen", color="#0000ff", lineweight=0.5, locked=True))
    for e in sample_entities():
        doc.model_space.add(e)
    doc.sheets[0].orientation = Orientation.PORTRAIT
    doc.sheets[0].paper = "A3"
    return doc


def test_document_roundtrip_through_file(tmp_path):
    doc = make_document()
    path = tmp_path / "plan.sldg"
    save_document(doc, path)
    loaded = load_document(path)
    assert document_to_dict(loaded) == document_to_dict(doc)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format_version"] == BASE_VERSION  # no pages: readable by 1.2
    assert "Zeile 2 äöü" in path.read_text(encoding="utf-8")


def test_save_keeps_backup_and_leaves_no_temp_files(tmp_path):
    path = tmp_path / "plan.sldg"
    save_document(Document.new("Blatt 1"), path)
    first = path.read_text(encoding="utf-8")
    save_document(make_document(), path)
    assert (tmp_path / "plan.sldg.bak").read_text(encoding="utf-8") == first
    assert sorted(p.name for p in tmp_path.iterdir()) == ["plan.sldg", "plan.sldg.bak"]


def test_newer_format_version_is_rejected():
    data = document_to_dict(Document.new("Blatt 1"))
    data["format_version"] = FORMAT_VERSION + 1
    with pytest.raises(FileFormatError):
        document_from_dict(data)


def test_migrations_run_in_order(monkeypatch):
    calls = []

    def next_version(data):
        calls.append(1)
        data["model"]["entities"] = []
        return data

    data = document_to_dict(make_document())
    monkeypatch.setattr(json_format, "FORMAT_VERSION", FORMAT_VERSION + 1)
    monkeypatch.setitem(json_format.MIGRATIONS, FORMAT_VERSION, next_version)
    doc = document_from_dict(data)
    assert calls == [1]
    assert list(doc.model_space) == []


def test_version_1_file_gets_title_block_and_viewport():
    v1 = {
        "format_version": 1,
        "layers": [{"name": "0"}],
        "blocks": [],
        "model": {"entities": [{"type": "line", "id": "a", "p1": [0, 0], "p2": [1, 0]}]},
        "sheets": [{"name": "Blatt 1", "paper": "A3", "orientation": "portrait", "entities": []}],
    }
    doc = document_from_dict(v1)
    sheet = doc.sheets[0]
    assert sheet.title_block == "Schriftfeld" and "Schriftfeld" in doc.blocks
    (vp,) = sheet.viewports()
    assert (vp.p1.x, vp.p1.y, vp.p2.x, vp.p2.y) == (20, 10, 287, 410)
    assert document_to_dict(doc)["format_version"] == BASE_VERSION


def test_invalid_files_raise_format_error(tmp_path):
    bad = tmp_path / "bad.sldg"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(FileFormatError):
        load_document(bad)
    bad.write_text('{"format_version": 1}', encoding="utf-8")
    with pytest.raises(FileFormatError):
        load_document(bad)
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(FileFormatError):
        load_document(bad)


def test_missing_layer_zero_is_restored():
    data = document_to_dict(Document.new("Blatt 1"))
    data["layers"] = []
    assert [layer.name for layer in document_from_dict(data).layers] == ["0"]


def test_saved_file_gets_normal_permissions(tmp_path):
    import os

    path = tmp_path / "rechte.sldg"
    save_document(Document.new("Blatt 1"), path)
    umask = os.umask(0)
    os.umask(umask)
    assert path.stat().st_mode & 0o777 == 0o666 & ~umask
    os.chmod(path, 0o640)
    save_document(Document.new("Blatt 1"), path)
    assert path.stat().st_mode & 0o777 == 0o640


def test_wire_label_roundtrip():
    from sldgridy.model.entities import Wire
    from sldgridy.model.geometry import Point

    for align in ("left", "center", "right"):
        wire = Wire(
            id="w",
            points=(Point(0, 0), Point(40, 0)),
            label="NYY-J 5x16",
            label_side=-1,
            label_height=3.5,
            label_align=align,
        )
        d = entity_to_dict(wire)
        assert ("label_align" in d) == (align != "center")
        assert entity_from_dict(json.loads(json.dumps(d))) == wire


def test_wire_label_position_roundtrip():
    from sldgridy.model.entities import Wire
    from sldgridy.model.geometry import Point

    for pos, at in (("auto", 0.0), ("start", 0.0), ("end", 0.0), ("free", 12.5)):
        wire = Wire(
            id="w", points=(Point(0, 0), Point(40, 0)), label="L", label_pos=pos, label_at=at
        )
        d = entity_to_dict(wire)
        assert ("label_pos" in d) == (pos != "auto")
        assert entity_from_dict(json.loads(json.dumps(d))) == wire


def test_layer_workspace_roundtrip_and_old_files():
    from sldgridy.fileio.json_format import _layer_from_dict, _layer_to_dict
    from sldgridy.model.layers import Layer

    for workspace in ("", "sld", "drawing"):
        layer = Layer("X", workspace=workspace)
        assert _layer_from_dict(_layer_to_dict(layer)) == layer
    # Before workspaces: every layer but 0 belonged to the circuit diagram.
    assert _layer_from_dict({"name": "Kabel"}).workspace == "sld"
    assert _layer_from_dict({"name": "0"}).workspace == ""
