import pytest
from PyQt6.QtCore import QPointF, QRectF, QSettings, Qt
from PyQt6.QtTest import QTest

from blocks_fixtures import blocks, fuse
from sldgridy.fileio.files import load_library, save_library
from sldgridy.fileio.paths import user_library_dir
from sldgridy.model.entities import BlockReference, Circle, Line, Text
from sldgridy.model.geometry import Point
from sldgridy.ui import block_controller, block_dialogs
from sldgridy.ui.block_dialogs import (
    AttributeValuesDialog,
    BlockChooserDialog,
    BlockPropertiesDialog,
    ConnectionPointDialog,
    CreateBlockDialog,
)
from sldgridy.ui.main_window import MainWindow
from sldgridy.ui.space import BLOCK, MODEL


@pytest.fixture
def window(qapp, monkeypatch):
    QSettings().clear()
    # Dialogs are answered automatically.
    monkeypatch.setattr(AttributeValuesDialog, "exec", lambda self: 1)
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    w.canvas.fit_rect(QRectF(0, 0, 200, 150))
    w.act_osnap.setChecked(False)
    yield w
    w.blocks.close_editor(save=False)
    w.undo_stack.setClean()
    for space in w.spaces():
        space.stack.setClean()
    w.close()


def click(window, x, y, button=Qt.MouseButton.LeftButton):
    pos = window.canvas.map_from_scene_f(QPointF(x, y)).toPoint()
    QTest.mouseClick(window.canvas.viewport(), button, pos=pos)


def refs(window):
    return [e for e in window.container if isinstance(e, BlockReference)]


def with_blocks(window):
    window.document.blocks.update(blocks())
    window._on_blocks_changed("")


def test_create_block_from_selection(window, monkeypatch):
    ms = window.document.model_space
    ms.add(Line(id="a", p1=Point(10, 10), p2=Point(10, 30)))
    ms.add(Circle(id="b", center=Point(10, 20), radius=3))
    window.act_select_all.trigger()

    def fake_exec(self):
        self.name.setText("Mein Block")
        self.in_editor.setChecked(False)
        return 1

    monkeypatch.setattr(CreateBlockDialog, "exec", fake_exec)
    window.blocks.act_create.trigger()
    click(window, 10, 10)
    assert "Mein Block" in window.document.blocks
    definition = window.document.blocks["Mein Block"]
    assert {type(e).__name__ for e in definition.entities} == {"Line", "Circle"}
    assert definition.entities.get("a").p1 == Point(0, 0)
    (ref,) = refs(window)
    assert ref.insert == Point(10, 10)
    window.act_undo.trigger()
    assert "Mein Block" not in window.document.blocks
    assert len(ms) == 2 and not refs(window)


def test_insert_block_with_tool_and_attributes(window, monkeypatch):
    with_blocks(window)
    monkeypatch.setattr(AttributeValuesDialog, "values", lambda self: {"BMK": "-F3"})
    window.blocks.insert_from_source("", "Sicherung")
    assert window.tools.active is not None
    click(window, 50, 50)
    (ref,) = refs(window)
    assert ref.insert == Point(50, 50) and ref.attribute("BMK") == "-F3"


def test_explode_reference(window):
    with_blocks(window)
    window.document.model_space.add(BlockReference(id="r", name="Sicherung", insert=Point(50, 50)))
    window._sync.item("r").setSelected(True)
    window.act_explode.trigger()
    kinds = sorted(type(e).__name__ for e in window.document.model_space)
    assert kinds == ["Circle", "Line", "Text"]
    window.act_undo.trigger()
    assert [e.id for e in window.document.model_space] == ["r"]


def test_block_editor_changes_all_references(window):
    with_blocks(window)
    ms = window.document.model_space
    ms.add(BlockReference(id="r1", name="Sicherung", insert=Point(20, 20)))
    ms.add(BlockReference(id="r2", name="Sicherung", insert=Point(60, 20)))
    window.blocks.open_editor("Sicherung")
    assert window.space.kind == BLOCK
    assert "Blockeditor" in window.windowTitle()
    # Draw an extra line inside the definition.
    window.act_line.trigger()
    click(window, -5, 0)
    click(window, 5, 0)
    window.tools.cancel()
    assert len(window.document.blocks["Sicherung"].entities) == 5  # unchanged until saved
    window.blocks.close_editor(save=True)
    assert window.space.kind == MODEL
    assert len(window.document.blocks["Sicherung"].entities) == 6
    item_rect = window._sync.item("r1").sceneBoundingRect()
    assert item_rect.left() <= 15.1  # new line reaches 5 mm left of the insert point
    window.act_undo.trigger()
    assert len(window.document.blocks["Sicherung"].entities) == 5


def test_block_editor_discard_and_base_point(window):
    with_blocks(window)
    window.blocks.open_editor("Sicherung")
    window.blocks.act_base.trigger()
    click(window, 0, 10)
    assert window.space.extra["definition"].base_point == Point(0, 10)
    window.act_undo.trigger()
    assert window.space.extra["definition"].base_point == Point(0, 0)
    window.act_redo.trigger()
    window.blocks.close_editor(save=False)
    assert window.document.blocks["Sicherung"].base_point == Point(0, 0)


def test_editor_rejects_self_reference(window):
    with_blocks(window)
    window.blocks.open_editor("Sicherung")
    window.blocks.insert_from_source("", "Feld", Point(0, 0))
    assert not refs(window)
    window.blocks.close_editor(save=False)


def test_attribute_edit_in_properties_dock(window):
    with_blocks(window)
    window.document.model_space.add(BlockReference(id="r", name="Sicherung", insert=Point(50, 50)))
    window._sync.item("r").setSelected(True)
    dock = window.properties_dock
    from PyQt6.QtWidgets import QPushButton

    from sldgridy.ui.block_dialogs import AttributeValueEdit

    edits = dock.widget().findChildren(AttributeValueEdit)
    edit = [e for e in edits if e.text() == "F1"][0]
    edit.setText("-F9")
    [b for b in dock.widget().findChildren(QPushButton) if "Attribute" in b.text()][0].click()
    assert window.document.model_space.get("r").attribute("BMK") == "-F9"
    # Shift+Enter starts a new line, Enter applies.
    edit = [e for e in dock.widget().findChildren(AttributeValueEdit) if e.text() == "-F9"][0]
    edit.setFocus()
    edit.moveCursor(edit.textCursor().MoveOperation.End)
    QTest.keyClick(edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    QTest.keyClicks(edit, "NH00")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert window.document.model_space.get("r").attribute("BMK") == "-F9\nNH00"


def write_library(name="test"):
    path = user_library_dir() / f"{name}.sldglib"
    path.parent.mkdir(parents=True, exist_ok=True)
    save_library(list(blocks().values()), path, "Testbibliothek")
    return path


def test_library_drop_copies_definitions(window):
    path = write_library()
    window.library_dock.reload()
    assert str(path) in window.library_dock.libraries
    window.canvas.block_dropped.emit({"path": str(path), "name": "Feld"}, QPointF(40, 40))
    assert {"Feld", "Sicherung"} <= set(window.document.blocks)
    (ref,) = refs(window)
    assert ref.name == "Feld" and ref.insert == Point(40, 40)
    window.act_undo.trigger()
    assert not refs(window)


def test_library_conflict_rename(window, monkeypatch):
    path = write_library("konflikt")
    window.library_dock.reload()
    other = fuse()
    other.entities.remove("c")
    window.document.blocks["Sicherung"] = other
    monkeypatch.setattr(block_controller, "ask_block_conflict", lambda *_: block_dialogs.RENAME)
    window.blocks.insert_from_source(str(path), "Feld", Point(0, 0))
    assert "Sicherung (2)" in window.document.blocks
    nested = [
        e.name for e in window.document.blocks["Feld"].entities if isinstance(e, BlockReference)
    ]
    assert nested == ["Sicherung (2)", "Sicherung (2)"]


def test_library_conflict_keep(window, monkeypatch):
    path = write_library("behalten")
    window.library_dock.reload()
    other = fuse()
    other.entities.remove("c")
    window.document.blocks["Sicherung"] = other
    monkeypatch.setattr(block_controller, "ask_block_conflict", lambda *_: block_dialogs.KEEP)
    window.blocks.insert_from_source(str(path), "Sicherung", Point(0, 0))
    assert window.document.blocks["Sicherung"] is other
    assert len(refs(window)) == 1


def test_save_to_user_library(window, monkeypatch):
    with_blocks(window)
    window.document.model_space.add(BlockReference(id="r", name="Feld", insert=Point(0, 0)))
    window._sync.item("r").setSelected(True)
    window.blocks.save_to_user_library()
    _, loaded = load_library(user_library_dir() / "eigene.sldglib")
    assert {b.name for b in loaded} >= {"Feld", "Sicherung"}


def test_clipboard_carries_block_definitions(window):
    with_blocks(window)
    window.document.model_space.add(BlockReference(id="r", name="Sicherung", insert=Point(10, 10)))
    window.act_select_all.trigger()
    window.act_copy_clip.trigger()
    window._set_document(type(window.document).new("Blatt 1"), None)
    window.act_paste.trigger()
    click(window, 30, 30)
    assert "Sicherung" in window.document.blocks
    assert len(refs(window)) == 1


def test_snap_to_reference_connection_point(window):
    with_blocks(window)
    window.act_osnap.setChecked(True)
    window.act_snap.setChecked(False)
    window.document.model_space.add(BlockReference(id="r", name="Sicherung", insert=Point(50, 50)))
    window.act_line.trigger()
    click(window, 50.5, 60.4)
    click(window, 50.5, 90)
    window.tools.cancel()
    (line,) = [e for e in window.document.model_space if isinstance(e, Line)]
    assert line.p1 == Point(50, 60)


def test_insert_dialog_lists_blocks(window, monkeypatch):
    with_blocks(window)

    def fake_exec(self):
        self.list.setCurrentRow(0)
        self.list.item(0).setSelected(True)
        return 1

    monkeypatch.setattr(BlockChooserDialog, "exec", fake_exec)
    window.blocks.act_insert.trigger()
    assert window.tools.active is not None
    window.tools.cancel()


def test_attribute_and_connection_definition_tools(window, monkeypatch):
    from sldgridy.ui.block_dialogs import AttributeDefinitionDialog, ConnectionPointDialog

    def att_exec(self):
        self.tag.setText("typ")
        return 1

    monkeypatch.setattr(AttributeDefinitionDialog, "exec", att_exec)
    monkeypatch.setattr(ConnectionPointDialog, "exec", lambda self: 1)
    window.blocks.act_attribute.trigger()
    click(window, 10, 10)
    window.blocks.act_connection.trigger()
    click(window, 20, 10)
    kinds = [type(e).__name__ for e in window.document.model_space]
    assert kinds == ["AttributeDefinition", "ConnectionPoint"]
    att = list(window.document.model_space)[0]
    assert att.tag == "TYP"


def test_text_entities_in_blocks_render(window):
    with_blocks(window)
    window.document.model_space.add(BlockReference(id="r", name="Feld", insert=Point(80, 80)))
    item = window._sync.item("r")
    assert not item.boundingRect().isEmpty()
    assert any(isinstance(p, Text) for p in item._parts)


def test_create_block_asks_for_objects_first(window, monkeypatch, qapp):
    ms = window.document.model_space
    ms.add(Line(id="a", p1=Point(10, 10), p2=Point(10, 30)))

    def fake_exec(self):
        self.name.setText("Nachgefragt")
        return 1

    monkeypatch.setattr(CreateBlockDialog, "exec", fake_exec)
    window.blocks.act_create.trigger()  # nothing selected yet
    assert window.tools.selecting()
    assert "Block erstellen" in window.tools.prompt()
    click(window, 10, 20)
    QTest.keyClick(window.canvas, Qt.Key.Key_Return)
    QTest.qWait(50)  # the dialog opens after the key event
    assert window.blocks.editor_space is not None  # block editor is the default
    window.blocks.act_editor_save.trigger()
    assert "Nachgefragt" in window.document.blocks
    assert window.blocks.act_create.text().replace("&", "") == "Block erstellen …"


def fill_properties(monkeypatch, name, category="", description=""):
    def fake_exec(self):
        self.name.setText(name)
        self.category.setCurrentText(category)
        self.description.setText(description)
        self.accept()
        return self.result()

    monkeypatch.setattr(BlockPropertiesDialog, "exec", fake_exec)


def test_rename_drawing_block_updates_references(window, monkeypatch):
    with_blocks(window)
    window.document.model_space.add(BlockReference(id="r", name="Sicherung", insert=Point(0, 0)))
    fill_properties(monkeypatch, "NH-Sicherung", "Schutz", "neu")
    window.blocks.edit_block_info("", "Sicherung")
    doc = window.document
    assert "Sicherung" not in doc.blocks
    assert doc.blocks["NH-Sicherung"].category == "Schutz"
    assert doc.model_space.get("r").name == "NH-Sicherung"
    nested = {e.name for e in doc.blocks["Feld"].entities if isinstance(e, BlockReference)}
    assert nested == {"NH-Sicherung"}
    window.act_undo.trigger()
    assert "Sicherung" in doc.blocks and "NH-Sicherung" not in doc.blocks
    assert doc.model_space.get("r").name == "Sicherung"
    assert doc.blocks["Sicherung"].category == "Schalten"


def test_rename_to_existing_name_is_refused(window, monkeypatch):
    with_blocks(window)
    fill_properties(monkeypatch, "Feld")
    window.blocks.edit_block_info("", "Sicherung")
    assert {"Feld", "Sicherung"} <= set(window.document.blocks)


def test_delete_drawing_block_only_when_unused(window):
    with_blocks(window)
    window.blocks.delete_block("", "Sicherung")
    assert "Sicherung" in window.document.blocks
    window.blocks.delete_block("", "Feld")
    assert "Feld" not in window.document.blocks
    window.act_undo.trigger()
    assert "Feld" in window.document.blocks


def test_edit_and_delete_in_user_library(window, monkeypatch):
    path = write_library("verwalten")
    window.library_dock.reload()
    fill_properties(monkeypatch, "Schmelzsicherung", "Schutz")
    window.blocks.edit_block_info(str(path), "Sicherung")
    _, loaded = load_library(path)
    by_name = {b.name: b for b in loaded}
    assert by_name["Schmelzsicherung"].category == "Schutz"
    nested = {e.name for e in by_name["Feld"].entities if isinstance(e, BlockReference)}
    assert nested == {"Schmelzsicherung"}
    assert "Schmelzsicherung" in window.library_dock.library(str(path))

    monkeypatch.setattr(block_controller.QMessageBox, "information", lambda *a: None)
    monkeypatch.setattr(
        block_controller.QMessageBox,
        "question",
        lambda *a: block_controller.QMessageBox.StandardButton.Yes,
    )
    window.blocks.delete_block(str(path), "Schmelzsicherung")  # used by Feld
    assert len(load_library(path)[1]) == 2
    window.blocks.delete_block(str(path), "Feld")
    assert [b.name for b in load_library(path)[1]] == ["Schmelzsicherung"]


def test_shipped_libraries_are_read_only(window):
    dock = window.library_dock
    shipped = [k for k, lib in dock.libraries.items() if lib.shipped]
    assert shipped and not any(dock.editable(k) for k in shipped)
    assert dock.editable("")


def test_edit_user_library_symbol_in_block_editor(window):
    path = write_library("editor")
    window.library_dock.reload()
    window.blocks.open_library_editor(str(path), "Feld")
    space = window.blocks.editor_space
    assert space is not None and window.space is space
    # Nested symbols resolve from the library although the drawing has none.
    assert "Sicherung" not in window.document.blocks
    assert window._expand(space.container.get("f1"))
    window.push(AddLine(space.container))
    assert window.blocks.close_editor(save=True)
    by_name = {b.name: b for b in load_library(path)[1]}
    assert "neu" in by_name["Feld"].entities
    assert "Sicherung" in by_name
    assert "Feld" not in window.document.blocks
    assert window.undo_stack.isClean()


def test_library_editor_discard_keeps_file(window):
    path = write_library("verwerfen")
    window.library_dock.reload()
    before = path.read_bytes()
    window.blocks.open_library_editor(str(path), "Sicherung")
    window.push(AddLine(window.blocks.editor_space.container))
    assert window.blocks.close_editor(save=False)
    assert path.read_bytes() == before


class AddLine(block_controller.QUndoCommand):
    def __init__(self, container):
        super().__init__("Linie")
        self._container = container

    def redo(self):
        self._container.add(Line(id="neu", p1=Point(0, 0), p2=Point(5, 5)))

    def undo(self):
        self._container.remove("neu")


def test_create_block_in_editor_base_follows_first_connection(window, monkeypatch):
    ms = window.document.model_space
    ms.add(Line(id="a", p1=Point(10, 10), p2=Point(10, 30)))
    ms.add(Circle(id="b", center=Point(10, 20), radius=3))
    window.act_select_all.trigger()

    def fake_exec(self):
        self.name.setText("Gerät")
        return 1

    monkeypatch.setattr(CreateBlockDialog, "exec", fake_exec)
    monkeypatch.setattr(ConnectionPointDialog, "exec", lambda self: 1)
    window.blocks.act_create.trigger()
    space = window.blocks.editor_space
    assert space is not None and "Gerät" not in window.document.blocks
    definition = space.extra["definition"]
    assert definition.base_point == Point(10, 20)  # centre of the selection
    window.blocks.define_connection()
    click(window, 10, 10)
    assert definition.base_point == Point(10, 10)
    window.blocks.define_connection()
    click(window, 10, 30)
    assert definition.base_point == Point(10, 10)  # only the first one moves it
    window.blocks.act_editor_save.trigger()
    assert window.space is window.model_view
    block = window.document.blocks["Gerät"]
    assert block.base_point == Point(0, 0)
    positions = sorted((c.position.x, c.position.y) for c in block.connection_points())
    assert positions == [(0, 0), (0, 20)]
    (ref,) = refs(window)
    assert ref.insert == Point(10, 10)
    window.act_undo.trigger()
    assert "Gerät" not in window.document.blocks and len(ms) == 2


def test_discarding_new_block_creates_nothing(window, monkeypatch):
    window.document.model_space.add(Line(id="a", p1=Point(0, 0), p2=Point(0, 10)))
    window.act_select_all.trigger()

    def fake_exec(self):
        self.name.setText("Weg")
        return 1

    monkeypatch.setattr(CreateBlockDialog, "exec", fake_exec)
    window.blocks.act_create.trigger()
    assert window.blocks.close_editor(save=False)
    assert "Weg" not in window.document.blocks
    assert len(window.document.model_space) == 1


def test_drop_is_handled_after_the_drag_ends(window, qapp):
    import json

    from PyQt6.QtCore import QMimeData
    from PyQt6.QtGui import QDropEvent

    from sldgridy.view.canvas import BLOCK_MIME

    path = write_library("ziehen")
    window.library_dock.reload()
    data = QMimeData()
    data.setData(BLOCK_MIME, json.dumps({"path": str(path), "name": "Sicherung"}).encode())
    pos = window.canvas.map_from_scene_f(QPointF(40, 40))
    event = QDropEvent(
        pos,
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.canvas.dropEvent(event)
    assert event.isAccepted()
    assert not refs(window)  # nothing happens inside the drag
    qapp.processEvents()
    (ref,) = refs(window)
    assert ref.name == "Sicherung"


def test_dragged_block_is_previewed_in_the_drawing(window, qapp):
    import json

    from PyQt6.QtCore import QMimeData
    from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent

    from sldgridy.view.canvas import BLOCK_MIME

    path = write_library("vorschau")
    window.library_dock.reload()
    data = QMimeData()
    data.setData(BLOCK_MIME, json.dumps({"path": str(path), "name": "Feld"}).encode())
    canvas = window.canvas
    pos = canvas.map_from_scene_f(QPointF(40, 40)).toPoint()
    args = (
        Qt.DropAction.CopyAction,
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.dragEnterEvent(QDragEnterEvent(pos, *args))
    canvas.dragMoveEvent(QDragMoveEvent(pos, *args))
    parts = canvas._drag_preview_entities()
    assert parts and any(isinstance(p, Line) for p in parts)  # nested fuses included
    assert "Sicherung" not in window.document.blocks  # nothing inserted while dragging
    canvas.viewport().repaint()
    canvas.dragLeaveEvent(QDragLeaveEvent())
    assert canvas._drag_preview_entities() == []


def test_block_editor_returns_to_the_page_it_came_from(window):
    from sldgridy.model.document import DOC_PROJECT

    window.new_document(DOC_PROJECT)
    page = window.document.sheets[-1]
    window.sheets.show_sheet(page.id)
    origin = window.space
    with_blocks(window)
    window.blocks.open_editor("Sicherung")
    assert window.space is window.blocks.editor_space
    window.container.add(Circle(id="extra", center=Point(0, 0), radius=1))
    window.blocks.close_editor(save=True)
    # A project has no model view: it used to land on an empty canvas.
    assert window.space is origin
    window.blocks.open_editor("Sicherung")
    window.blocks.close_editor(save=False)
    assert window.space is origin
