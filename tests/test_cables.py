import pytest
from PyQt6.QtCore import QSettings

from sldgridy.fileio.json_format import document_from_dict, document_to_dict
from sldgridy.model.cables import (
    cable_mark_geometry,
    crossings,
    default_cores,
    mark_cores,
    next_cable_name,
)
from sldgridy.model.document import DOC_PROJECT, Document
from sldgridy.model.entities import CableMark, Line, Text, Wire
from sldgridy.model.geometry import Point
from sldgridy.model.grips import move_grip
from sldgridy.model.reports import cable_rows
from sldgridy.ui import cable_dialog
from sldgridy.ui.main_window import MainWindow


def conductors(xs, top=0.0, bottom=50.0):
    return [Wire(id=f"w{x}", points=(Point(x, top), Point(x, bottom))) for x in xs]


def test_crossings_in_order_along_the_mark():
    wires = conductors([20, 10, 15]) + [Wire(id="h", points=(Point(0, 30), Point(40, 30)))]
    mark = CableMark(id="m", p1=Point(30, 25), p2=Point(5, 25), name="-W1")
    assert [(p, w.id) for p, w in crossings(mark, wires)] == [
        (Point(10, 25), "w10"), (Point(15, 25), "w15"), (Point(20, 25), "w20")
    ]  # fmt: skip
    across = CableMark(id="v", p1=Point(35, 20), p2=Point(35, 40), name="-W2")
    assert [w.id for _p, w in crossings(across, wires)] == ["h"]


def test_default_cores():
    assert default_cores(5) == ["BN", "BK", "GY", "BU", "GNYE"]
    assert default_cores(3) == ["BN", "BU", "GNYE"]
    assert default_cores(7) == ["1", "2", "3", "4", "5", "6", "GNYE"]
    assert next_cable_name(["-W1", "-W3", "-X1"]) == "-W4"
    assert next_cable_name([]) == "-W1"


def test_geometry_name_left_and_cores_beside_the_conductors():
    mark = CableMark(id="m", p1=Point(5, 25), p2=Point(30, 25), name="-W2")
    parts = cable_mark_geometry(mark, [(Point(10, 25), "BN"), (Point(15, 25), "")])
    line = next(p for p in parts if isinstance(p, Line))
    assert (line.p1, line.p2) == (Point(5, 25), Point(30, 25))
    texts = {p.text: p for p in parts if isinstance(p, Text)}
    assert set(texts) == {"-W2", "BN"}
    assert texts["-W2"].halign == "right" and texts["-W2"].position.x < 5
    assert texts["BN"].position.x > 10 and texts["BN"].position.y > 25  # below, right


def test_grip_keeps_the_mark_across_and_file_roundtrip():
    mark = CableMark(id="m", p1=Point(5, 25), p2=Point(30, 25), name="-W2", cable_type="NYM")
    assert move_grip(mark, 1, Point(40, 31)).p2 == Point(40, 25)
    doc = Document.new("Blatt 1", kind=DOC_PROJECT)
    sheet = doc.sheets[0]
    for e in [*conductors([10, 15]), mark]:
        sheet.entities.add(e)
    loaded = document_from_dict(document_to_dict(doc))
    assert loaded.sheets[0].entities.get("m") == mark
    assert [core for _p, core in mark_cores(loaded)["m"]] == ["", ""]


@pytest.fixture
def window(qapp):
    QSettings().clear()
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    w.new_document(DOC_PROJECT)
    w.sheets.show_sheet(w.document.sheets[-1].id)
    qapp.processEvents()
    yield w
    for space in w.spaces():
        space.stack.setClean()
    w.undo_stack.setClean()
    w.close()


def answer(monkeypatch, values):
    class Fake:
        DialogCode = cable_dialog.CableDialog.DialogCode

        def __init__(self, name, kind, types, cores, parent):
            Fake.offered = (name, kind, cores)

        def exec(self):
            return self.DialogCode.Accepted

        def values(self):
            return values

    monkeypatch.setattr(cable_dialog, "CableDialog", Fake)
    return Fake


def test_cable_tool_sets_cable_and_cores_on_the_wires(window, monkeypatch):
    for wire in conductors([100, 105, 110, 115, 120], 60, 140):
        window.container.add(wire)
    fake = answer(monkeypatch, ("-W1", "NYM-J 5x2,5", ["BN", "BK", "GY", "BU", "GNYE"]))
    window.act_cable.trigger()
    for p in (Point(90, 120), Point(130, 121)):
        window.tools.active.pick(p)
    assert fake.offered == ("-W1", "", ["BN", "BK", "GY", "BU", "GNYE"])
    marks = [e for e in window.container if isinstance(e, CableMark)]
    assert len(marks) == 1 and marks[0].p2 == Point(130, 120)
    wires = sorted(
        (e for e in window.container if isinstance(e, Wire)), key=lambda w: w.points[0].x
    )
    assert [(w.cable, w.core) for w in wires][::4] == [("-W1", "BN"), ("-W1", "GNYE")]
    rows = cable_rows(window.document)
    assert rows[0][:2] == ["-W1", "NYM-J 5x2,5"]
    # Double click edits it again; one undo step each.
    answer(monkeypatch, ("-W7", "NYY-J 5x10", ["1", "2", "3", "4", "PE"]))
    window._edit_entity(marks[0].id)
    assert {w.cable for w in window.container if isinstance(w, Wire)} == {"-W7"}
    window.act_undo.trigger()
    assert {w.cable for w in window.container if isinstance(w, Wire)} == {"-W1"}
    window.act_undo.trigger()
    assert not [e for e in window.container if isinstance(e, CableMark)]
    assert {w.cable for w in window.container if isinstance(w, Wire)} == {""}


def test_clicked_on_the_outer_conductors_with_cores_from_the_terminals(window, monkeypatch):
    from sldgridy.ui import point_menu

    xs = [100, 105, 110, 115]
    for wire in conductors(xs, 60, 140):
        window.container.add(wire)
    numbers = iter([("-X1", "1"), ("-X1", "2"), ("-X1", "3"), ("-X1", "PEN")])

    class FakeTerminal:
        DialogCode = point_menu.TerminalDialog.DialogCode

        def __init__(self, *args):
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def values(self):
            return next(numbers)

    monkeypatch.setattr(point_menu, "TerminalDialog", FakeTerminal)
    for x in xs:
        wire = next(
            e
            for e in window.container
            if isinstance(e, Wire) and e.points[0] == Point(x, 60) and e.points[-1].y == 140
        )
        point_menu.set_terminal(window, Point(x, 80), [wire])
    fake = answer(monkeypatch, ("-W1", "", ["BN", "BK", "GY", "GNYE"]))
    window.act_cable.trigger()
    for p in (Point(100, 120), Point(115, 120)):  # right on the outer conductors
        window.tools.active.pick(p)
    assert fake.offered[2] == ["BN", "BK", "GY", "GNYE"]  # PEN is the protective one
    (mark,) = [e for e in window.container if isinstance(e, CableMark)]
    assert (mark.p1, mark.p2) == (Point(97.5, 120), Point(117.5, 120))  # beyond them
    # The tool stays for the next cable.
    answer(monkeypatch, ("-W2", "", ["BN", "BK", "GY", "GNYE"]))
    for p in (Point(100, 130), Point(115, 130)):
        window.tools.active.pick(p)
    assert sorted(e.name for e in window.container if isinstance(e, CableMark)) == ["-W1", "-W2"]
