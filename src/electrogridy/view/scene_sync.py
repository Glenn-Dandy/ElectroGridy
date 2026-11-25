"""Keeps the items of a QGraphicsScene in sync with an entity container."""

from collections.abc import Callable

from PyQt6.QtCore import QRectF, QTimer
from PyQt6.QtWidgets import QGraphicsScene

from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import Entity
from electrogridy.view.items import EntityItem, Expander, StyleResolver, _identity

# Returns (visible, locked) for an entity, derived from its layer.
LayerState = Callable[[Entity], tuple[bool, bool]]
BATCH_RECTS_MAX = 200


def _always_visible(_e: Entity) -> tuple[bool, bool]:
    return True, False


class SceneSync:
    def __init__(
        self,
        scene: QGraphicsScene,
        container: EntityContainer,
        resolve_style: StyleResolver,
        layer_state: LayerState = _always_visible,
        expand: Expander = _identity,
        item_factory: Callable[[Entity], EntityItem | None] | None = None,
    ) -> None:
        self._layer_state = layer_state
        self._expand = expand
        self._item_factory = item_factory
        self._scene = scene
        self._container = container
        self._resolve_style = resolve_style
        self._items: dict[str, EntityItem] = {}
        self._next_z = 0
        # During a batch: scene signals held back, selection change and restack once.
        self._batch_blocked: bool | None = None
        self._batch_selection = False
        self._batch_restack = False
        # Scene areas the batch touched (before and after), drawn again at its end.
        self._batch_rects: list[QRectF] = []
        # Removed items, hidden and taken out of the scene once Qt has drawn their area
        # anew (removing a visible item makes Qt redraw the whole scene).
        self._hidden: list[EntityItem] = []
        for e in container:
            self._add(e)
        self._restack()
        container.subscribe(self._on_change)

    def detach(self) -> None:
        self._container.unsubscribe(self._on_change)
        for item in self._items.values():
            self._scene.removeItem(item)
        self._items.clear()
        self._remove_hidden()

    def _discard(self, item: EntityItem) -> None:
        item.hide()
        if not self._hidden:
            QTimer.singleShot(0, self._remove_hidden)
        self._hidden.append(item)

    def _remove_hidden(self) -> None:
        hidden, self._hidden = self._hidden, []
        for item in hidden:
            try:
                if item.scene() is self._scene:
                    self._scene.removeItem(item)
            except RuntimeError:  # the scene is gone already
                return

    def item(self, entity_id: str) -> EntityItem:
        return self._items[entity_id]

    def items(self) -> list[EntityItem]:
        return list(self._items.values())

    def refresh(self) -> None:
        """Re-read styles and layer states, e.g. after a layer change."""
        for item in self._items.values():
            item.refresh()
            item.set_layer_state(*self._layer_state(item.entity))

    def _add(self, e: Entity) -> None:
        item = self._item_factory(e) if self._item_factory is not None else None
        if item is None:
            item = EntityItem(e, self._resolve_style, self._expand)
        item.set_layer_state(*self._layer_state(e))
        self._items[e.id] = item
        self._scene.addItem(item)

    def _restack(self) -> None:
        for z, e in enumerate(self._container):
            self._items[e.id].setZValue(z)
        self._next_z = len(self._container)

    def _on_change(self, event: str, e: Entity | None) -> None:
        if event == "batch_start":
            self._batch_blocked = self._scene.blockSignals(True)
            self._batch_selection = self._batch_restack = False
            self._batch_rects = []
            return
        if event == "batch_end":
            self._scene.blockSignals(bool(self._batch_blocked))
            self._batch_blocked = None
            if self._batch_restack:
                self._restack()
            if self._batch_selection:
                self._scene.selectionChanged.emit()
            # Only what changed (a full update redrew the whole view after each edit);
            # many changes at once: everything.
            rects, self._batch_rects = self._batch_rects, []
            if len(rects) > BATCH_RECTS_MAX:
                self._scene.update()
            else:
                for r in rects:
                    self._scene.update(r)
            return
        assert e is not None
        batch = self._batch_blocked is not None
        if event == "added":
            self._add(e)
            if batch:
                self._batch_rects.append(self._items[e.id].sceneBoundingRect())
            if self._container.index_of(e.id) == len(self._container) - 1:
                self._items[e.id].setZValue(self._next_z)
                self._next_z += 1
            elif batch:
                self._batch_restack = True
            else:
                self._restack()
        elif event == "removed":
            item = self._items.pop(e.id)
            if batch:
                self._batch_rects.append(item.sceneBoundingRect())
            if batch and item.isSelected():
                self._batch_selection = True
            self._discard(item)
        elif event == "changed":
            item = self._items[e.id]
            if batch:
                self._batch_rects.append(item.sceneBoundingRect())
            item.set_entity(e)
            item.set_layer_state(*self._layer_state(e))
            if batch:
                self._batch_rects.append(item.sceneBoundingRect())
