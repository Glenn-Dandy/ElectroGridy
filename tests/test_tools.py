import pytest
from PyQt6.QtGui import QUndoStack

from electrogridy.model.document import Document
from electrogridy.model.entities import Arc, Circle, Line, Polyline, Rectangle, Text
from electrogridy.model.geometry import Point
from electrogridy.tools.controller import ToolController
from electrogridy.tools.draw import (
    ArcTool,
    CircleTool,
    LineTool,
    PolylineTool,
    RectangleTool,
    TextTool,
)
from electrogridy.tools.edit import (
    CopyTool,
    GripEditTool,
    MirrorTool,
    MoveTool,
    PasteTool,
    RotateTool,
)
from factories import sample_entities


class FakeContext:
    def __init__(self):
        self.document = Document.new("Blatt 1")
        self.stack = QUndoStack()
        self.selection: list[str] = []
        self.text_answer: tuple[str, float] | None = ("Hallo", 5.0)
        self.messages: list[str] = []

    @property
    def container(self):
        return self.document.model_space

    @property
    def current_layer(self):
        return "0"

    def push(self, command):
        self.stack.push(command)

    def selected_ids(self):
        return list(self.selection)

    def ask_text(self, text="", height=None):
        return self.text_answer

    def message(self, text):
        self.messages.append(text)

    choice_answer = 0

    def ask_choice(self, key, options):
        return self.choice_answer


@pytest.fixture
def ctx():
    return FakeContext()


@pytest.fixture
def tools(ctx):
    return ToolController(ctx)


def entities(ctx):
    return list(ctx.container)


def test_line_tool_chains_segments_until_finish(ctx, tools):
    tools.start(LineTool)
    for p in (Point(0, 0), Point(10, 0), Point(10, 10)):
        tools.pick(p)
    tools.finish()
    assert tools.active is None
    lines = entities(ctx)
    assert [(e.p1, e.p2) for e in lines] == [
        (Point(0, 0), Point(10, 0)),
        (Point(10, 0), Point(10, 10)),
    ]
    assert all(isinstance(e, Line) for e in lines)
    assert ctx.stack.count() == 2


def test_line_tool_preview_and_base_point(ctx, tools):
    tools.start(LineTool)
    assert tools.base_point() is None
    tools.pick(Point(1, 1))
    tools.hover(Point(5, 1))
    assert tools.base_point() == Point(1, 1)
    (preview,) = tools.preview()
    assert (preview.p1, preview.p2) == (Point(1, 1), Point(5, 1))
    assert entities(ctx) == []


def test_cancel_discards_pending_points(ctx, tools):
    tools.start(LineTool)
    tools.pick(Point(0, 0))
    tools.cancel()
    assert tools.active is None and entities(ctx) == []


def test_polyline_open_on_finish(ctx, tools):
    tools.start(PolylineTool)
    for p in (Point(0, 0), Point(10, 0), Point(10, 5)):
        tools.pick(p)
    tools.finish()
    (poly,) = entities(ctx)
    assert isinstance(poly, Polyline) and not poly.closed and len(poly.points) == 3


def test_polyline_closes_on_start_point(ctx, tools):
    tools.start(PolylineTool)
    for p in (Point(0, 0), Point(10, 0), Point(10, 5), Point(0, 0)):
        tools.pick(p)
    assert tools.active is None
    (poly,) = entities(ctx)
    assert poly.closed and len(poly.points) == 3


def test_polyline_with_one_point_creates_nothing(ctx, tools):
    tools.start(PolylineTool)
    tools.pick(Point(0, 0))
    tools.finish()
    assert entities(ctx) == []


def test_rectangle(ctx, tools):
    tools.start(RectangleTool)
    tools.pick(Point(0, 0))
    tools.pick(Point(0, 5))  # degenerate, ignored
    tools.pick(Point(20, 10))
    (rect,) = entities(ctx)
    assert isinstance(rect, Rectangle) and (rect.p1, rect.p2) == (Point(0, 0), Point(20, 10))


def test_circle(ctx, tools):
    tools.start(CircleTool)
    tools.pick(Point(10, 10))
    tools.pick(Point(13, 14))
    (circle,) = entities(ctx)
    assert isinstance(circle, Circle) and circle.radius == 5


def test_arc_counter_clockwise_from_start_to_end(ctx, tools):
    tools.start(ArcTool)
    tools.pick(Point(0, 0))
    tools.pick(Point(10, 0))
    tools.pick(Point(0, -10))
    (arc,) = entities(ctx)
    assert isinstance(arc, Arc)
    assert (arc.radius, arc.start_angle, arc.end_angle, arc.sweep) == (10, 0, 90, 90)


def test_text_tool_uses_dialog_answer(ctx, tools):
    tools.start(TextTool)
    tools.pick(Point(3, 4))
    (text,) = entities(ctx)
    assert isinstance(text, Text)
    assert (text.position, text.text, text.height) == (Point(3, 4), "Hallo", 5.0)


def test_text_tool_cancelled_dialog_creates_nothing(ctx, tools):
    ctx.text_answer = None
    tools.start(TextTool)
    tools.pick(Point(3, 4))
    assert entities(ctx) == [] and tools.active is None


def select_samples(ctx):
    for e in sample_entities():
        ctx.container.add(e)
    ctx.selection = ["l1", "c1"]


def test_edit_tool_without_selection_asks_for_objects(ctx, tools):
    for e in sample_entities():
        ctx.container.add(e)
    tools.start(MoveTool)
    assert tools.selecting()
    tools.pick(Point(0, 0))  # ignored while selecting
    assert tools.base_point() is None
    ctx.selection = ["l1"]
    tools.finish()  # Enter confirms the selection
    assert not tools.selecting()
    tools.pick(Point(0, 0))
    tools.pick(Point(0, 10))
    assert ctx.container.get("l1").p1 == Point(0, 10)


def test_edit_tool_finish_without_selection_ends(ctx, tools):
    tools.start(RotateTool)
    tools.finish()
    assert tools.active is None


def test_mirror_tool_horizontal_axis(ctx, tools):
    select_samples(ctx)
    tools.start(MirrorTool)
    tools.pick(Point(0, 20))
    tools.pick(Point(10, 20))  # horizontal axis y = 20
    line = ctx.container.get("l1")
    assert (line.p1, line.p2) == (Point(0, 40), Point(10, 40))


def test_mirror_tool_can_keep_the_original(ctx, tools):
    select_samples(ctx)
    count = len(ctx.container)
    ctx.choice_answer = 1  # copy, original stays
    tools.start(MirrorTool)
    tools.pick(Point(0, 20))
    tools.pick(Point(10, 20))
    line = ctx.container.get("l1")
    assert (line.p1, line.p2) == (Point(0, 0), Point(10, 0))
    assert len(ctx.container) == count + 2  # l1 and c1 were selected
    mirrored = [e for e in ctx.container if e.id != "l1" and getattr(e, "p1", None) == Point(0, 40)]
    assert mirrored and tools.active is None


def test_mirror_tool_cancelled_choice_keeps_asking(ctx, tools):
    select_samples(ctx)
    ctx.choice_answer = None
    tools.start(MirrorTool)
    tools.pick(Point(0, 20))
    tools.pick(Point(10, 20))
    assert ctx.container.get("l1").p1 == Point(0, 0)
    assert tools.active is not None


def test_paste_tool_places_new_entities(ctx, tools):
    entities = sample_entities()[:2]
    tools.start(lambda c: PasteTool(c, entities, Point(0, 0)))
    tools.pick(Point(100, 50))
    placed = list(ctx.container)
    assert len(placed) == 2
    assert {e.id for e in placed}.isdisjoint({"l1", "p1"})
    assert placed[0].p1 == Point(100, 50)


def test_grip_tool_moves_line_end(ctx, tools):
    select_samples(ctx)
    tools.start(lambda c: GripEditTool(c, "l1", 1))
    assert tools.base_point() == Point(10, 0)
    tools.pick(Point(10, 25))
    line = ctx.container.get("l1")
    assert (line.p1, line.p2) == (Point(0, 0), Point(10, 25))


def test_controller_remembers_last_point(ctx, tools):
    tools.start(LineTool)
    tools.pick(Point(3, 4))
    assert tools.last_point == Point(3, 4)


def test_move_tool(ctx, tools):
    select_samples(ctx)
    tools.start(MoveTool)
    tools.pick(Point(0, 0))
    tools.hover(Point(5, 5))
    assert [e.id for e in tools.preview()] == ["l1", "c1"]
    tools.pick(Point(5, -5))
    assert tools.active is None
    assert ctx.container.get("l1").p1 == Point(5, -5)
    assert ctx.container.get("c1").center == Point(55, 45)
    assert ctx.container.get("r1").p1 == Point(10, 10)
    ctx.stack.undo()
    assert ctx.container.get("l1").p1 == Point(0, 0)


def test_copy_tool_places_multiple_copies(ctx, tools):
    select_samples(ctx)
    n = len(ctx.container)
    tools.start(CopyTool)
    tools.pick(Point(0, 0))
    tools.pick(Point(100, 0))
    tools.pick(Point(200, 0))
    tools.finish()
    assert len(ctx.container) == n + 4
    new_lines = [e for e in ctx.container if isinstance(e, Line) and e.id != "l1"]
    assert sorted(e.p1.x for e in new_lines) == [100, 200]


def test_rotate_tool_quarter_from_direction(ctx, tools):
    select_samples(ctx)
    tools.start(RotateTool)
    tools.pick(Point(0, 0))
    tools.pick(Point(0, -20))  # straight up = 90 degrees
    line = ctx.container.get("l1")
    assert (line.p1, line.p2) == (Point(0, 0), Point(0, -10))


def test_repeat_restarts_last_tool(ctx, tools):
    tools.start(CircleTool)
    tools.pick(Point(0, 0))
    tools.pick(Point(1, 0))
    assert tools.active is None
    tools.repeat()
    assert isinstance(tools.active, CircleTool)
