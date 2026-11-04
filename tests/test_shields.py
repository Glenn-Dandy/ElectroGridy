import pytest
from PyQt6.QtCore import QSettings

from electrogridy.fileio.json_format import entity_from_dict, entity_to_dict
from electrogridy.model.document import DOC_PROJECT
from electrogridy.model.entities import Arc, CableShield, ConnectionPoint, Line, Wire
from electrogridy.model.geometry import Point
from electrogridy.model.routing import pins_of
from electrogridy.model.shields import fitted_shield, shield_connections, shield_geometry
from electrogridy.model.wires import follow_connections
from electrogridy.ui.main_window import MainWindow


def conductors(xs, top=0.0, bottom=50.0):
    return [Wire(id=f"w{x}", points=(Point(x, top), Point(x, bottom))) for x in xs]


def test_shield_around_the_conductors_with_connection_points_in_the_grid():
    shield = fitted_shield(
        CableShield(id="s", p1=Point(5, 20), p2=Point(20, 20)), conductors([10, 15, 20])
    )
    assert (shield.p1, shield.p2) == (Point(8.75, 20), Point(21.25, 20))
    parts = shield_geometry(shield)
    sides = [p for p in parts if isinstance(p, Line)]
    assert {(s.p1.y, s.linetype) for s in sides} == {
        (18.75, "dashdot_short"),
        (21.25, "dashdot_short"),
    }
    assert len([p for p in parts if isinstance(p, Arc)]) == 2
    assert not [p for p in parts if isinstance(p, ConnectionPoint)]  # not even helpers
    ends = [(c.position, c.direction) for c in shield_connections(shield)]
    assert ends == [(Point(7.5, 20), 180.0), (Point(22.5, 20), 0.0)]


def test_shield_across_horizontal_conductors_has_its_points_above_and_below():
    wires = [Wire(id=f"h{y}", points=(Point(0, y), Point(50, y))) for y in (10, 15)]
    shield = fitted_shield(CableShield(id="s", p1=Point(30, 2), p2=Point(30, 15)), wires)
    ends = [(c.position, c.direction) for c in shield_connections(shield)]
    assert ends == [(Point(30, 7.5), 90.0), (Point(30, 17.5), 270.0)]


def test_shield_is_saved_and_its_wire_follows_and_routes_from_it():
    shield = CableShield(id="s", p1=Point(8.75, 20), p2=Point(21.25, 20), layer="0")
    assert entity_from_dict(entity_to_dict(shield)) == shield
    lead = Wire(id="lead", points=(Point(22.5, 20), Point(27.5, 20), Point(27.5, 40)))
    moved = shield.translated(0, -5)
    followed = follow_connections([shield, lead], [shield], [moved], {})
    assert followed and followed[0].points[0] == Point(22.5, 15)
    assert [(p.name, p.position) for p in pins_of([shield], {})] == [
        ("1", Point(7.5, 20)),
        ("2", Point(22.5, 20)),
    ]


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


def test_shield_tool_draws_it_in_the_project(window):
    assert window.act_shield.isVisible()
    assert window.draw_menu.actions()[:3] == [
        window.wire_menu.menuAction(),
        window.act_interruption,
        window.cable_menu.menuAction(),
    ]
    assert window.wire_menu.actions() == [window.act_wire, window.act_busbar, window.act_rails]
    assert window.cable_menu.actions() == [window.act_cable, window.act_shield, window.act_outlet]
    assert window.cable_button_action.isVisible()
    window.btn_cable.menu().actions()[1].trigger()  # the button now repeats the shield
    assert window.btn_cable.defaultAction() is window.act_shield
    window.tools.cancel()
    for wire in conductors([100, 105, 110], 60, 140):
        window.container.add(wire)
    window.act_shield.trigger()
    for p in (Point(95, 80), Point(115, 81)):
        window.tools.active.pick(p)
    shields = [e for e in window.container if isinstance(e, CableShield)]
    assert len(shields) == 1
    assert [c.position for c in shield_connections(shields[0])] == [
        Point(97.5, 80),
        Point(112.5, 80),
    ]
    window.act_undo.trigger()
    assert not [e for e in window.container if isinstance(e, CableShield)]


def test_wiring_tool_bar_starts_a_wire_and_follows_the_kind_of_file(window):
    assert window.wiring_toolbar.isVisible()
    assert window.btn_wire.defaultAction() is window.act_wire
    window.btn_wire.menu().actions()[1].trigger()  # bus bar from the drop-down
    assert window.btn_wire.defaultAction() is window.act_wire  # the click stays a wire
    window.tools.cancel()
    from electrogridy.model.document import DOC_DRAWING, DOC_SLD

    window.new_document(DOC_SLD)
    assert not window.cable_menu.menuAction().isVisible()
    assert not window.cable_button_action.isVisible()
    assert window.wire_menu.menuAction().isVisible() and window.wiring_toolbar.isVisible()
    window.new_document(DOC_DRAWING)
    assert not window.wire_menu.menuAction().isVisible()
    assert not window.wiring_toolbar.isVisible()


def test_shield_fits_around_plain_lines_of_an_imported_plan():
    lines = [Line(id=f"l{x}", p1=Point(x, 0), p2=Point(x, 50)) for x in (10, 15)]
    shield = fitted_shield(CableShield(id="s", p1=Point(8, 20), p2=Point(17, 20)), lines)
    assert shield == fitted_shield(CableShield(id="s", p1=Point(5, 20), p2=Point(20, 20)), lines)
    assert [c.position for c in shield_connections(shield)] == [Point(7.5, 20), Point(17.5, 20)]
