import pytest
from PyQt6.QtCore import QSettings

from electrogridy.fileio.json_format import entity_from_dict, entity_to_dict
from electrogridy.model.document import DOC_PROJECT
from electrogridy.model.entities import Busbar, JunctionMark, Wire
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
