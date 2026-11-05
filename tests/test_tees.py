import pytest
from PyQt6.QtCore import QSettings

from electrogridy.fileio.json_format import entity_from_dict, entity_to_dict
from electrogridy.model.document import DOC_PROJECT
from electrogridy.model.entities import Busbar, JunctionMark, Line, Wire
from electrogridy.model.geometry import Point
from electrogridy.model.wires import TEE_STYLE_KEY, tees
from electrogridy.ui.main_window import MainWindow
from electrogridy.ui.point_menu import point_actions


def wire(wid, *points):
    return Wire(id=wid, points=tuple(Point(*p) for p in points))


def test_branch_on_a_rail_and_three_ends_are_tees_crossings_stay_dots():
    entities = [
        wire("rail", (0, 10), (100, 10)),
        wire("down", (20, 10), (20, 40)),  # end inside the rail
        wire("a", (40, 50), (60, 50)),
        wire("b", (60, 50), (80, 50)),
        wire("up", (60, 50), (60, 30)),  # three ends, two of them in a line
        wire("x1", (90, 60), (90, 70)),
        wire("x2", (90, 70), (90, 80)),
        wire("x3", (80, 70), (90, 70)),
        wire("x4", (90, 70), (100, 70)),  # four ends: a crossing
    ]
    dots, found = tees(entities)
    assert [(t.position, t.wire.id, t.branch, t.side) for t in found] == [
        (Point(20, 10), "down", (0.0, 1.0), (1.0, 0.0)),
        (Point(60, 50), "up", (0.0, -1.0), (1.0, 0.0)),
    ]
    assert [p for p, _e in dots] == [Point(90, 70)]


def test_wire_end_on_the_corner_of_another_wire_is_a_tee():
    """Florian 2026-11-05: Q1 goes up, right and down again; the next wire starts at
    the corner and runs on to the right. That is a T, the branch goes down."""
    q1 = wire("q1", (0, 50), (0, 20), (30, 20), (30, 60))
    right = wire("right", (30, 20), (80, 20))
    dots, (tee,) = tees([q1, right])
    assert dots == []
    # Q1 runs through, the docked wire has the diagonal towards the leg going down.
    assert (tee.position, tee.wire.id, tee.branch, tee.side) == (
        Point(30, 20),
        "right",
        (1.0, 0.0),
        (0.0, 1.0),
    )
    # Wired: Q1 to the device on the leg going down, from there the docked wire.
    assert tee.wiring() == ((0.0, 1.0), (1.0, 0.0))
    turned = JunctionMark(id="m", position=Point(30, 20), side=-1)
    (tee,) = tees([q1, right, turned])[1]
    assert (tee.wire.id, tee.branch, tee.side) == ("q1", (0.0, 1.0), (1.0, 0.0))
    assert tee.wiring() == ((0.0, 1.0), (1.0, 0.0))
    # Docked going up, in a line with the leg going down: the diagonal goes left.
    up = wire("up", (30, 20), (30, 0))
    (tee,) = tees([q1, up])[1]
    assert (tee.wire.id, tee.branch, tee.side) == ("up", (0.0, -1.0), (-1.0, 0.0))


def test_set_connection_point_on_plain_lines_gives_a_tee():
    lines = [
        Line(id="a", p1=Point(0, 20), p2=Point(30, 20)),
        Line(id="b", p1=Point(30, 20), p2=Point(80, 20)),
        Line(id="c", p1=Point(30, 20), p2=Point(30, 60)),
    ]
    assert tees(lines) == ([], [])  # lines alone are no conductors
    mark = JunctionMark(id="m", position=Point(30, 20))
    (tee,) = tees([*lines, mark])[1]
    assert tee.branch == (0.0, 1.0)


def test_branch_on_a_bus_bar_and_turned_round_by_a_mark():
    bar = Busbar(id="bar", p1=Point(10, 0), p2=Point(10, 100))
    branch = wire("w", (10, 30), (40, 30))
    (tee,) = tees([bar, branch])[1]
    assert (tee.branch, tee.side) == ((1.0, 0.0), (0.0, 1.0))
    mark = JunctionMark(id="m", position=Point(10, 30), side=-1)
    (tee,) = tees([bar, branch, mark])[1]
    assert tee.side == (0.0, -1.0)
    assert entity_from_dict(entity_to_dict(mark)) == mark


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


def test_project_setting_draws_tees_and_the_menu_turns_them(window, monkeypatch):
    from electrogridy.ui import main_window as mw

    window.container.add(wire("rail", (50, 40), (150, 40)))
    window.container.add(wire("down", (80, 40), (80, 80)))
    junctions = window.space.extra["junctions"]
    junctions.recompute()
    assert len(junctions._dots) == 1 and not junctions._tees
    assert "T-Abzweig andersherum" not in dict(point_actions(window, Point(80, 40)))

    class Fake:
        DialogCode = mw.ProjectDialog.DialogCode

        def __init__(self, properties, *args):
            self._properties = {**properties, TEE_STYLE_KEY: "tee"}

        def exec(self):
            return self.DialogCode.Accepted

        def properties(self):
            return self._properties

    monkeypatch.setattr(mw, "ProjectDialog", Fake)
    window.edit_project_data()
    assert window.tee_style()
    assert not junctions._dots and len(junctions._tees) == 1
    from electrogridy.printing.output import sheet_image
    from electrogridy.view.display import OutputOptions

    sheet = window.sheets.current_sheet()
    image = sheet_image(window.document, sheet, 150, OutputOptions(helpers=False))
    px = 150 / 25.4  # the branch is covered just below the rail, the diagonal ends right
    assert image.pixelColor(round(80 * px), round(40.6 * px)).lightness() > 200
    assert image.pixelColor(round(80 * px), round(60 * px)).lightness() < 128
    dict(point_actions(window, Point(80, 40)))["T-Abzweig andersherum"]()
    junctions.recompute()
    assert junctions._tees[0][0].side == (-1.0, 0.0)
    window.act_undo.trigger()  # the turn
    window.act_undo.trigger()  # the setting
    assert not window.tee_style() and len(junctions._dots) == 1


def test_sheet_menu_switches_the_junction_style(window):
    junctions = window.space.extra["junctions"]
    window.container.add(wire("rail", (50, 40), (150, 40)))
    window.container.add(wire("down", (80, 40), (80, 80)))
    assert window.sheets.junction_menu.menuAction() in window.project_menu.actions()
    window.sheets.sync_junction_actions()
    assert window.sheets.act_dots.isChecked() and not window.sheets.act_tees.isChecked()
    window.sheets.act_tees.trigger()
    assert window.tee_style()
    junctions.recompute()
    assert len(junctions._tees) == 1
    window.sheets.sync_junction_actions()
    assert window.sheets.act_tees.isChecked()
    window.act_undo.trigger()
    assert not window.tee_style()


def test_lines_under_the_mouse_or_selected_become_wires(window):
    from electrogridy.model.entities import Line

    window.container.add(Line(id="rail", p1=Point(50, 40), p2=Point(150, 40)))
    window.container.add(Line(id="down", p1=Point(80, 41.25), p2=Point(80, 80)))
    window.container.add(Line(id="diag", p1=Point(80, 41.25), p2=Point(81.25, 40)))
    actions = dict(point_actions(window, Point(120, 40)))
    assert "In Leitung umwandeln" in actions  # only the line under the mouse
    window._sync.item("rail").setSelected(True)
    window._sync.item("down").setSelected(True)
    window._sync.item("diag").setSelected(True)
    actions = dict(point_actions(window, Point(120, 40)))
    actions["3 Linien in Leitungen umwandeln"]()
    wires = [e for e in window.container if isinstance(e, Wire)]
    assert len(wires) == 2
    assert not [e for e in window.container if isinstance(e, Line)]
    assert "T-Abzweig" in window.statusBar().currentMessage()
    window.act_undo.trigger()
    assert not [e for e in window.container if isinstance(e, Wire)]
