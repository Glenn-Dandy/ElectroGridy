from PyQt6.QtGui import QUndoStack

from electrogridy.commands.entities import (
    AddEntitiesCommand,
    RemoveEntitiesCommand,
    ReplaceEntitiesCommand,
)
from electrogridy.fileio.json_format import document_to_dict
from electrogridy.model.document import Document
from electrogridy.model.geometry import Point
from factories import sample_entities


def make_doc() -> Document:
    doc = Document.new("Blatt 1")
    for e in sample_entities():
        doc.model_space.add(e)
    return doc


def check_do_undo_redo(doc: Document, make_command) -> None:
    stack = QUndoStack()
    before = document_to_dict(doc)
    stack.push(make_command(doc))
    after = document_to_dict(doc)
    assert after != before
    stack.undo()
    assert document_to_dict(doc) == before
    stack.redo()
    assert document_to_dict(doc) == after


def test_add_entities():
    new = [e.with_new_id() for e in sample_entities()[:2]]
    check_do_undo_redo(make_doc(), lambda d: AddEntitiesCommand(d.model_space, new, "add"))


def test_remove_entities_restores_order():
    check_do_undo_redo(
        make_doc(), lambda d: RemoveEntitiesCommand(d.model_space, ["a1", "l1", "r1"], "remove")
    )


def test_replace_entities():
    def make(d):
        moved = [d.model_space.get(i).translated(5, 5) for i in ("l1", "t1")]
        return ReplaceEntitiesCommand(d.model_space, moved, "move")

    check_do_undo_redo(make_doc(), make)


def test_rotate_via_replace():
    def make(d):
        rotated = [e.rotated(Point(0, 0), 1) for e in d.model_space]
        return ReplaceEntitiesCommand(d.model_space, rotated, "rotate")

    check_do_undo_redo(make_doc(), make)
