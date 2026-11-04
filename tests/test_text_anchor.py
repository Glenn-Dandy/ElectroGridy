import pytest
from PyQt6.QtCore import QSettings

from electrogridy.model.document import DOC_PROJECT
from electrogridy.model.entities import Line, Rectangle, Text
from electrogridy.model.geometry import Point
from electrogridy.model.text_fields import field_around, field_center
from electrogridy.ui.main_window import MainWindow
from electrogridy.ui.point_menu import point_actions
from electrogridy.view.render import realigned, text_scene_center, text_scene_path


def box(e: Text):
    r = text_scene_path(e).boundingRect()
    return [round(v, 6) for v in (r.left(), r.top(), r.right(), r.bottom())]


@pytest.mark.parametrize("rotation", [0, 90, 30])
def test_new_reference_point_leaves_the_text_where_it_is(qapp, rotation):
    text = Text(id="t", position=Point(10, 20), text="Stromlaufplan\nSeite 2", rotation=rotation)
    for halign in ("left", "center", "right"):
        for valign in ("baseline", "middle"):
            moved = realigned(text, halign, valign)
            assert (moved.halign, moved.valign) == (halign, valign)
            assert box(moved) == box(text)
    centred = realigned(text, "center", "middle")
    assert centred.position != text.position
    if rotation == 0:  # across the reading direction "middle" is that of the capitals
        assert round(centred.position.x, 6) == round(text_scene_center(text).x, 6)


def test_field_from_lines_and_rectangles():
    lines = [
        Line(id="a", p1=Point(0, 0), p2=Point(100, 0)),
        Line(id="b", p1=Point(0, 10), p2=Point(100, 10)),
        Line(id="c", p1=Point(40, 0), p2=Point(40, 10)),
        Rectangle(id="r", p1=Point(0, -20), p2=Point(100, 30)),
    ]
    assert field_around(Point(10, 4), lines) == (Point(0, 0), Point(40, 10))
    assert field_center(Point(60, 4), lines) == Point(70, 5)
    assert field_center(Point(10, 4), lines[:3]) is None  # open on the left


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


def test_right_click_on_a_text_sets_its_point_and_centres_it_in_its_field(window):
    window.container.add(Rectangle(id="field", p1=Point(50, 50), p2=Point(110, 60)))
    window.container.add(Text(id="t", position=Point(55, 57), text="Klemmleiste", height=2.5))
    text = window.container.get("t")
    inside = text_scene_center(text)
    actions = dict(point_actions(window, Point(0, 0), inside))
    anchors = actions["Bezugspunkt"]
    assert [checked for _label, _cb, checked in anchors] == [True] + [False] * 5
    dict((label, cb) for label, cb, _c in anchors)["Rechts, Mitte"]()
    moved = window.container.get("t")
    assert (moved.halign, moved.valign) == ("right", "middle") and box(moved) == box(text)
    actions = dict(point_actions(window, Point(0, 0), inside))
    actions["In Feld zentrieren"]()
    centred = window.container.get("t")
    assert centred.position == Point(80, 55)
    assert (centred.halign, centred.valign) == ("center", "middle")
    window.act_undo.trigger()
    assert window.container.get("t") == moved
    assert "Bezugspunkt" not in dict(point_actions(window, Point(0, 0), Point(200, 200)))


def test_text_tool_and_double_click_use_the_reference_point(window, monkeypatch):
    from electrogridy.ui import main_window as mw

    class Fake:
        DialogCode = mw.TextDialog.DialogCode
        chosen = ("center", "middle")

        def __init__(self, parent, text="", height=None, anchor=None):
            Fake.offered = anchor
            self._text = text or "Neu"

        def exec(self):
            return self.DialogCode.Accepted

        def text(self):
            return self._text

        def text_height(self):
            return 3.5

        def anchor(self):
            return Fake.chosen

    monkeypatch.setattr(mw, "TextDialog", Fake)
    window.act_text.trigger()
    window.tools.pick(Point(80, 55))
    (text,) = [e for e in window.container if isinstance(e, Text)]
    assert (text.position, text.halign, text.valign) == (Point(80, 55), "center", "middle")
    assert Fake.offered == ("left", "baseline")
    window.act_text.trigger()
    window.tools.pick(Point(80, 75))
    assert Fake.offered == ("center", "middle")  # the choice made last
    Fake.chosen = ("left", "baseline")
    window._edit_entity(text.id)
    edited = window.container.get(text.id)
    assert (edited.halign, edited.valign) == ("left", "baseline")
    assert box(edited) == box(text)
