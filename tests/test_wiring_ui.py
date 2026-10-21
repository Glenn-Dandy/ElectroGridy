"""Circuit diagram projects: rails, symbols placed into wires, routed wires, terminals."""

import pytest
from PyQt6.QtCore import QSettings

from sldgridy.fileio.paths import system_library_dir
from sldgridy.model.devices import devices
from sldgridy.model.document import DOC_PROJECT
from sldgridy.model.entities import BlockReference, InterruptionPoint, Wire
from sldgridy.model.geometry import Point
from sldgridy.ui.block_dialogs import AttributeValuesDialog
from sldgridy.ui.main_window import MainWindow

MLD = str(system_library_dir() / "mld_symbole.sldglib")


@pytest.fixture
def window(qapp, monkeypatch):
    QSettings().clear()
    w = MainWindow()
    w.show()
    w.new_document(DOC_PROJECT)  # cover, then the circuit diagram page shown
    monkeypatch.setattr(AttributeValuesDialog, "exec", lambda self: 1)
    qapp.processEvents()
    yield w
    w.undo_stack.setClean()
    w.close()


def page_wires(w):
    return [e for e in w.container if isinstance(e, Wire)]


def refs(w):
    return [e for e in w.container if isinstance(e, BlockReference)]


def test_rails_across_the_page_with_page_transitions(window, monkeypatch):
    from sldgridy.ui import main_window as mw

    class Fake:
        DialogCode = mw.RailsDialog.DialogCode

        def __init__(self, parent):
            pass

        def exec(self):
            return self.DialogCode.Accepted

        def values(self):
            return ["L1", "L2", "L3", "N", "PE"], True

    monkeypatch.setattr(mw, "RailsDialog", Fake)
    window.act_rails.trigger()
    window.tools.pick(Point(100, 30))
    wires = page_wires(window)
    assert [w.points[0].y for w in wires] == [30, 35, 40, 45, 50]
    assert {(w.points[0].x, w.points[-1].x) for w in wires} == {(27.5, 385.0)}
    points = [e for e in window.container if isinstance(e, InterruptionPoint)]
    assert len(points) == 10 and {p.name for p in points} == {"L1", "L2", "L3", "N", "PE"}


def test_symbol_placed_on_wires_opens_them_and_bmk_counts_up(window):
    for x in (100, 105, 110):
        window.container.add(Wire(id=f"w{x}", points=(Point(x, 30), Point(x, 120))))
    window.blocks.insert_from_source(MLD, "Leitungsschutzschalter 3-polig", Point(100, 60))
    (ls,) = refs(window)
    assert ls.attribute("BMK") == "-F1"
    pieces = sorted((w.points[0].x, w.points[0].y, w.points[-1].y) for w in page_wires(window))
    assert pieces == [
        (100, 30, 60), (100, 75, 120), (105, 30, 60), (105, 75, 120), (110, 30, 60),
        (110, 75, 120),
    ]  # fmt: skip
    window.act_undo.trigger()  # one step: symbol and wires
    assert not refs(window) and len(page_wires(window)) == 3
    window.act_redo.trigger()
    window.blocks.insert_from_source(MLD, "Leitungsschutzschalter 1-polig", Point(200, 60))
    assert sorted(r.attribute("BMK") for r in refs(window)) == ["-F1", "-F2"]


def test_wire_tool_routes_all_poles_from_terminal_to_terminal(window):
    window.blocks.insert_from_source(MLD, "Leitungsschutzschalter 3-polig", Point(100, 40))
    window.blocks.insert_from_source(MLD, "Schütz Hauptkontakte 3-polig", Point(130, 90))
    window.act_wire.trigger()
    window.tools.pick(Point(100, 55))  # pole 1 bottom (2) of the breaker
    window.tools.pick(Point(130, 90))  # pole 1 top (1) of the contactor
    wires = page_wires(window)
    assert len(wires) == 3
    ends = sorted(((w.points[0], w.points[-1]) for w in wires), key=lambda e: e[0].x)
    assert ends == [
        (Point(100, 55), Point(130, 90)),
        (Point(105, 55), Point(135, 90)),
        (Point(110, 55), Point(140, 90)),
    ]
    assert window.tools.active  # waits for the next connection
    window.act_undo.trigger()
    assert not page_wires(window)


def test_set_terminal_on_a_wire_offers_free_numbers(window, monkeypatch):
    from sldgridy.model.terminals import free_numbers, strips
    from sldgridy.ui import point_menu

    window.container.add(Wire(id="w", points=(Point(50, 30), Point(50, 100))))
    window.container.add(Wire(id="h", points=(Point(80, 50), Point(160, 50))))
    answers = iter([("-X2", "1", False), ("X2", "2", True)])

    class Fake:
        DialogCode = point_menu.TerminalDialog.DialogCode

        def __init__(self, found, last, parent):
            self.found = found

        def exec(self):
            return self.DialogCode.Accepted

        def values(self):
            return next(answers)

    monkeypatch.setattr(point_menu, "TerminalDialog", Fake)
    labels = [label for label, _ in point_menu.point_actions(window, Point(50, 60))]
    assert "Klemme setzen …" in labels and "Leitung hier auftrennen" in labels
    point_menu.set_terminal(window, Point(50, 60), page_wires(window)[:1])
    point_menu.set_terminal(window, Point(120, 50), [window.container.get("h")])
    assert sorted(devices(window.document)) == ["-X2:1", "-X2:2"]
    assert strips(window.document) == {"-X2": ["1", "2"]}
    assert free_numbers(["1", "2", "5"])[:3] == ["3", "4", "6"]
    vertical = sorted((w.points[0].y, w.points[-1].y) for w in page_wires(window) if
                      w.points[0].x == 50)  # fmt: skip
    assert vertical == [(30, 57.5), (62.5, 100)]
    horizontal = sorted((w.points[0].x, w.points[-1].x) for w in page_wires(window) if
                        w.points[0].y == 50)  # fmt: skip
    assert horizontal == [(80, 117.5), (122.5, 160)]
    assert "Klemme PE" in window.document.blocks


def test_menu_cuts_a_wire(window):
    from sldgridy.ui import point_menu

    window.container.add(Wire(id="w", points=(Point(50, 30), Point(50, 100))))
    actions = dict(point_menu.point_actions(window, Point(50, 60)))
    actions["Leitung hier auftrennen"]()
    assert sorted((w.points for w in page_wires(window)), key=lambda p: p[0].y) == [
        (Point(50, 30), Point(50, 60)), (Point(50, 60), Point(50, 100))
    ]  # fmt: skip
