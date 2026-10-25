import pytest
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QColor

from sldgridy.model.document import Document
from sldgridy.model.entities import Line
from sldgridy.model.geometry import Point
from sldgridy.ui.main_window import MainWindow
from sldgridy.view import theme
from sldgridy.view.display import OutputOptions, resolve_style


@pytest.fixture
def dark():
    theme.set_dark(True)
    yield
    theme.set_dark(False)


def test_light_theme_keeps_colours():
    assert not theme.is_dark()
    for name in ("#000000", "#ffffff", "#c62828"):
        assert theme.ink(QColor(name)) == QColor(name)


def test_dark_theme_turns_black_light_and_keeps_hues(dark):
    assert theme.ink(QColor("black")).lightness() > 220
    assert theme.ink(QColor("white")).lightness() < 50
    red = theme.ink(QColor("#8b0000"))
    assert red.hslHue() == QColor("#8b0000").hslHue()
    assert red.lightnessF() >= theme.MIN_COLOUR_LIGHTNESS - 0.01
    assert theme.surface(theme.LIGHT_PALETTE.background) == theme.DARK_PALETTE.background


def test_output_keeps_drawing_colours_in_dark_theme(dark):
    doc = Document.new("Blatt 1")
    line = Line(id="a", p1=Point(0, 0), p2=Point(10, 0), color="#000000")
    assert resolve_style(doc, line, OutputOptions(helpers=False)).color == QColor("black")
    assert resolve_style(doc, line).color.lightness() > 220  # screen


def test_resolve_choice():
    assert theme.resolve(theme.DARK, system_dark=False)
    assert not theme.resolve(theme.LIGHT, system_dark=True)
    assert theme.resolve(theme.SYSTEM, system_dark=True)
    assert not theme.resolve(theme.SYSTEM, system_dark=False)


def test_menu_switches_the_drawing_area(qapp):
    QSettings().clear()
    w = MainWindow()
    try:
        w.document.model_space.add(Line(id="a", p1=Point(0, 0), p2=Point(10, 0), color="#000000"))
        qapp.processEvents()
        item = w.model_view.sync.item("a")
        assert item._styles[0].color == QColor("black")
        actions = {a.data(): a for a in w.theme_menu.actions()}
        assert actions[theme.LIGHT].isChecked()
        actions[theme.DARK].trigger()
        assert theme.is_dark()
        assert QSettings().value(theme.SETTINGS_KEY) == theme.DARK
        assert item._styles[0].color.lightness() > 220
        actions[theme.LIGHT].trigger()
        assert not theme.is_dark()
        assert item._styles[0].color == QColor("black")
    finally:
        theme.set_dark(False)
        w.undo_stack.setClean()
        w.close()
