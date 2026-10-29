"""Sample entities shared by several tests."""

from electrogridy.model.entities import Arc, Circle, Dimension, Line, Polyline, Rectangle, Text
from electrogridy.model.geometry import Point


def sample_entities():
    return [
        Line(id="l1", p1=Point(0, 0), p2=Point(10, 0)),
        Polyline(id="p1", points=(Point(0, 0), Point(5, 0), Point(5, 5)), closed=True),
        Rectangle(id="r1", p1=Point(10, 10), p2=Point(30, 20), color="#ff0000"),
        Circle(id="c1", center=Point(50, 50), radius=7.5, lineweight=0.5),
        Arc(id="a1", center=Point(0, 0), radius=5, start_angle=0, end_angle=90, linetype="dashed"),
        Text(id="t1", position=Point(1, 2), text="Zeile 1\nZeile 2 äöü", height=5.0, rotation=90),
        Dimension(
            id="d1",
            p1=Point(0, 0),
            p2=Point(4000, 0),
            position=Point(2000, -500),
            orientation="horizontal",
            lineweight=0.18,
        ),
        Dimension(id="d2", p1=Point(0, 0), p2=Point(30, 40), position=Point(-5, 5), text="ca. 5 m"),
        Dimension(
            id="d3",
            p1=Point(50, 0),
            p2=Point(30, -40),
            position=Point(20, -10),
            orientation="angular",
            vertex=Point(0, 0),
        ),
    ]
