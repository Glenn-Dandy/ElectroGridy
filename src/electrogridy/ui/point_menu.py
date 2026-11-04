"""Right-click menu on a point: connect, separate, remove point, extend."""

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from PyQt6.QtCore import QCoreApplication, QPointF

from electrogridy.commands.blocks import AddBlockCommand, ReplaceBlockCommand
from electrogridy.commands.entities import (
    AddEntitiesCommand,
    RemoveEntitiesCommand,
    ReplaceEntitiesCommand,
)
from electrogridy.fileio.files import load_library
from electrogridy.fileio.json_format import FileFormatError, block_signature
from electrogridy.fileio.paths import symbols_dir
from electrogridy.i18n import library_text
from electrogridy.model.blocks import BlockDefinition, dock_target, point_to_world
from electrogridy.model.document import DOC_DRAWING
from electrogridy.model.entities import (
    BlockReference,
    JunctionMark,
    Line,
    Polyline,
    Text,
    Wire,
    new_id,
)
from electrogridy.model.geometry import Point
from electrogridy.model.routing import split_wire
from electrogridy.model.terminals import (
    TERMINAL_PE,
    normalized_strip,
    place_terminal,
    strips,
    terminal_kind,
)
from electrogridy.model.text_fields import field_center
from electrogridy.model.wires import (
    entities_at,
    insert_point,
    junction_points,
    on_segment,
    remove_vertex,
    same,
    segments,
)
from electrogridy.tools.draw import ExtendTool, LineTool
from electrogridy.ui.anchor_picker import AnchorPicker, shown_anchor
from electrogridy.ui.space import BLOCK
from electrogridy.ui.terminal_dialog import TerminalDialog
from electrogridy.view.render import realigned, text_scene_center, text_scene_path

if TYPE_CHECKING:
    from electrogridy.ui.main_window import MainWindow


def tr(text: str) -> str:
    return QCoreApplication.translate("PointMenu", text)


def point_actions(w: "MainWindow", p: Point, raw: Point | None = None) -> list[tuple]:
    """Menu entries for the point ``p`` of the active container; ``raw`` is where the
    mouse really is (texts under it). An entry is (label, callback) or (label, [entries])
    for a submenu, whose entries may carry a third value: checked."""
    container = w.container
    entities = list(container)
    actions: list[tuple[str, Callable[[], None]]] = []

    def push(command) -> None:
        w.tools.cancel()
        w.push(command)

    marks = [e for e in entities if isinstance(e, JunctionMark) and same(e.position, p)]
    through = entities_at(entities, p)
    automatic = any(
        same(q, p) for q in junction_points(e for e in entities if not isinstance(e, JunctionMark))
    )
    if marks:
        mark = marks[0]
        label = tr("Verbindungspunkt entfernen") if mark.connected else tr("Trennung aufheben")
        actions.append((label, lambda: push(RemoveEntitiesCommand(container, [mark.id], label))))
    elif automatic:
        separate = JunctionMark(id=new_id(), position=p, connected=False)
        actions.append(
            (
                tr("Trennen (hier kein Verbindungspunkt)"),
                lambda: push(AddEntitiesCommand(container, [separate], tr("Trennen"))),
            )
        )
    elif len(through) >= 2:
        connect = JunctionMark(id=new_id(), layer=through[0].layer, position=p, connected=True)
        actions.append(
            (
                tr("Verbinden (Verbindungspunkt setzen)"),
                lambda: push(AddEntitiesCommand(container, [connect], tr("Verbinden"))),
            )
        )

    actions += _text_actions(w, raw or p, entities, push)
    actions += _dock_actions(w, p, entities, push)
    actions += _wire_actions(w, p, entities, push)

    for e in entities:
        if isinstance(e, Wire | Polyline):
            name = tr("Leitung") if isinstance(e, Wire) else tr("Polylinie")
            last = len(e.points) - 1
            added = insert_point(e.points, p)
            if added is not None:
                with_point = replace(e, points=added)
                actions.append(
                    (
                        tr("Punkt hinzufügen ({name})").format(name=name),
                        lambda n=with_point: push(
                            ReplaceEntitiesCommand(container, [n], tr("Punkt hinzufügen"))
                        ),
                    )
                )
            for i, q in enumerate(e.points):
                if not same(q, p):
                    continue
                new = _without_point(e, i)
                if new is not None:
                    actions.append(
                        (
                            tr("Punkt entfernen ({name})").format(name=name),
                            lambda n=new: push(
                                ReplaceEntitiesCommand(container, [n], tr("Punkt entfernen"))
                            ),
                        )
                    )
                closed = isinstance(e, Polyline) and e.closed
                if i in (0, last) and not closed:
                    end = 0 if i == 0 else -1
                    actions.append(
                        (
                            tr("Verlängern ({name})").format(name=name),
                            lambda eid=e.id, end=end: w.start_tool(
                                lambda ctx: ExtendTool(ctx, eid, end)
                            ),
                        )
                    )
        elif isinstance(e, Line) and (same(e.p1, p) or same(e.p2, p)):
            actions.append((tr("Verlängern (Linie)"), lambda: w.start_tool(_line_from(p))))
    return actions


def _text_actions(w, raw: Point, entities, push) -> list[tuple]:
    """Reference point and centring of the selected texts, or of the text under the
    mouse (Florian 2026-11-04: a text in the middle of a field)."""
    selected = set(w.selected_ids())
    texts = [e for e in entities if isinstance(e, Text) and e.id in selected]
    if not texts:
        at = QPointF(raw.x, raw.y)
        texts = [e for e in entities if isinstance(e, Text) and text_scene_path(e).contains(at)]
    if not texts:
        return []
    container = w.container
    current = {shown_anchor(t) for t in texts}
    picker = AnchorPicker(current.pop() if len(current) == 1 else None)

    def set_anchor(halign: str, valign: str) -> None:
        changed = [realigned(t, halign, valign) for t in texts]
        push(ReplaceEntitiesCommand(container, changed, tr("Bezugspunkt ändern")))

    picker.chosen.connect(set_anchor)

    def centre() -> None:
        parts = w.field_parts({t.id for t in texts})
        changed, missing = [], 0
        for t in texts:
            middle = field_center(text_scene_center(t), parts)
            if middle is None:
                missing += 1
                continue
            changed.append(replace(t, halign="center", valign="middle", position=middle))
        if changed:
            push(ReplaceEntitiesCommand(container, changed, tr("In Feld zentrieren")))
        if missing:
            w.message(tr("Kein geschlossenes Feld um den Text gefunden"))

    return [(tr("Bezugspunkt"), picker), (tr("In Feld zentrieren"), centre)]


def _wire_actions(w, p: Point, entities, push) -> list[tuple[str, Callable[[], None]]]:
    """Set a terminal into the wire (projects) or cut the wire to wire it anew."""
    container = w.container
    wires = [e for e in entities if isinstance(e, Wire)]
    on = [e for e in wires if any(on_segment(p, a, b) for a, b in segments(e.points))]
    if not on or w.document.kind == DOC_DRAWING:
        return []
    actions: list[tuple[str, Callable[[], None]]] = []
    if w.document.is_project and w.space.kind != BLOCK:
        actions.append((tr("Klemme setzen …"), lambda: set_terminal(w, p, on)))
    for wire in on:
        pieces = split_wire(wire, p)
        if pieces:

            def cut(wire=wire, pieces=pieces) -> None:
                w.begin_macro(tr("Leitung auftrennen"))
                push(RemoveEntitiesCommand(container, [wire.id], ""))
                push(AddEntitiesCommand(container, pieces, ""))
                w.end_macro()

            actions.append((tr("Leitung hier auftrennen"), cut))
            break
    return actions


def set_terminal(w: "MainWindow", p: Point, wires: list[Wire]) -> None:
    """Ask for strip and number, then place the terminal into the wire at ``p``."""
    dialog = TerminalDialog(strips(w.document), w.last_terminal_strip, w)
    if dialog.exec() != TerminalDialog.DialogCode.Accepted:
        return
    strip, number = dialog.values()
    strip = normalized_strip(strip)
    if not strip or not number:
        return
    w.last_terminal_strip = strip
    name, color = terminal_kind(number)
    shipped = terminal_definitions().get(name)
    own = w.document.blocks.get(name)
    # A terminal from an older version lacks attributes the terminal plan reads.
    upgrade = (
        own is not None
        and shipped is not None
        and (
            _missing_tags(own, shipped)
            # PE terminals were a crossed circle up to 1.3.1.dev5.
            or (name == TERMINAL_PE and block_signature(own) != block_signature(shipped))
        )
    )
    definition = shipped if upgrade or own is None else own
    if definition is None:
        w.message(tr("Klemmensymbol nicht gefunden"))
        return
    placed = place_terminal(wires, p, definition, f"{strip}:{number}", w.current_layer, color)
    if placed is None:
        w.message(tr("Hier liegt kein gerades Stück Leitung"))
        return
    ref, removed, added = placed
    container = w.container
    w.tools.cancel()
    w.begin_macro(tr("Klemme {bmk} setzen").format(bmk=f"{strip}:{number}"))
    if name not in w.document.blocks:
        w.push(AddBlockCommand(w.document, definition, ""))
    elif upgrade:
        w.push(ReplaceBlockCommand(w.document, definition, ""))
    w.push(AddEntitiesCommand(container, [ref], ""))
    if removed:
        w.push(RemoveEntitiesCommand(container, removed, ""))
        w.push(AddEntitiesCommand(container, added, ""))
    w.end_macro()


def _missing_tags(own: BlockDefinition, shipped: BlockDefinition) -> bool:
    have = {a.tag for a in own.attribute_definitions()}
    return any(a.tag not in have for a in shipped.attribute_definitions())


def terminal_definitions() -> dict[str, BlockDefinition]:
    try:
        _title, blocks = load_library(symbols_dir() / "klemmen.grdylib")
    except (OSError, FileFormatError):
        return {}
    return {b.name: b for b in blocks}


DOCK_TOLERANCE = 1.0  # mm around the symbol where a dock may be set


def _dock_actions(w, p: Point, entities, push) -> list[tuple[str, Callable[[], None]]]:
    """Set or remove an instance-only connection point ("dock") of a block at ``p``."""
    container = w.container
    blocks = w.block_definitions
    actions: list[tuple[str, Callable[[], None]]] = []
    for e in entities:
        if not isinstance(e, BlockReference) or e.name not in blocks:
            continue
        label = e.attribute("BMK") or library_text(e.name)
        base = blocks[e.name].base_point
        for i, local in enumerate(e.docks):
            if same(point_to_world(e, base, local), p):
                new = replace(e, docks=e.docks[:i] + e.docks[i + 1 :])
                actions.append(
                    (
                        tr("Andockpunkt entfernen ({name})").format(name=label),
                        lambda n=new: push(
                            ReplaceEntitiesCommand(container, [n], tr("Andockpunkt entfernen"))
                        ),
                    )
                )
        target = dock_target(e, blocks, p, DOCK_TOLERANCE)
        if target is not None:
            new = replace(e, docks=(*e.docks, target))
            actions.append(
                (
                    tr("Andockpunkt hier setzen ({name})").format(name=label),
                    lambda n=new: push(
                        ReplaceEntitiesCommand(container, [n], tr("Andockpunkt setzen"))
                    ),
                )
            )
    return actions


def _without_point(e: Wire | Polyline, index: int) -> Wire | Polyline | None:
    if isinstance(e, Wire):
        return remove_vertex(e, index)
    minimum = 3 if e.closed else 2
    if len(e.points) <= minimum:
        return None
    pts = list(e.points)
    del pts[index]
    return replace(e, points=tuple(pts))


def _line_from(p: Point):
    def factory(ctx):
        tool = LineTool(ctx)
        tool.pick(p)
        return tool

    return factory
