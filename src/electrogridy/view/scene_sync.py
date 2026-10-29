"""Keeps the items of a QGraphicsScene in sync with an entity container."""

from collections.abc import Callable

from PyQt6.QtWidgets import QGraphicsScene

from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import Entity
from electrogridy.view.items import EntityItem, Expander, StyleResolver, _identity

# Returns (visible, locked) for an entity, derived from its layer.
LayerState = Callable[[Entity], tuple[bool, bool]]


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
        for e in container:
            self._add(e)
        self._restack()
        container.subscribe(self._on_change)

    def detach(self) -> None:
        self._container.unsubscribe(self._on_change)
        for item in self._items.values():
            self._scene.removeItem(item)
        self._items.clear()

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
            return
        if event == "batch_end":
            self._scene.blockSignals(bool(self._batch_blocked))
            self._batch_blocked = None
            if self._batch_restack:
                self._restack()
            if self._batch_selection:
                self._scene.selectionChanged.emit()
            self._scene.update()
            return
        assert e is not None
        batch = self._batch_blocked is not None
        if event == "added":
            self._add(e)
            if self._container.index_of(e.id) == len(self._container) - 1:
                self._items[e.id].setZValue(self._next_z)
                self._next_z += 1
            elif batch:
                self._batch_restack = True
            else:
                self._restack()
        elif event == "removed":
            item = self._items.pop(e.id)
            if batch and item.isSelected():
                self._batch_selection = True
            self._scene.removeItem(item)
        elif event == "changed":
            item = self._items[e.id]
            item.set_entity(e)
            item.set_layer_state(*self._layer_state(e))
