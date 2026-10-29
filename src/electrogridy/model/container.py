"""Ordered entity collection with change notification."""

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager

from electrogridy.model.entities import Entity

# Listener signature: (event, entity) with event in {"added", "removed", "changed"};
# around many changes at once also "batch_start" and "batch_end" with entity None.
Listener = Callable[[str, Entity | None], None]


class EntityContainer:
    def __init__(self, entities: Iterable[Entity] = ()) -> None:
        self._items: list[Entity] = []
        # id -> position; rebuilt lazily after inserts and removals (lookups by id are
        # constant time, drawings with hundreds of modules stay fast).
        self._index: dict[str, int] | None = {}
        self._listeners: list[Listener] = []
        self._batch_depth = 0
        for e in entities:
            self.add(e)

    def __iter__(self) -> Iterator[Entity]:
        return iter(list(self._items))

    def __len__(self) -> int:
        return len(self._items)

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Listener) -> None:
        self._listeners.remove(listener)

    @contextmanager
    def batch(self):
        """Many changes as one: listeners may defer work until "batch_end"."""
        if self._batch_depth == 0:
            self._notify("batch_start", None)
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                self._notify("batch_end", None)

    @property
    def in_batch(self) -> bool:
        return self._batch_depth > 0

    def _notify(self, event: str, entity: Entity | None) -> None:
        for listener in list(self._listeners):
            listener(event, entity)

    def _positions(self) -> dict[str, int]:
        if self._index is None:
            self._index = {e.id: i for i, e in enumerate(self._items)}
        return self._index

    def index_of(self, entity_id: str) -> int:
        try:
            return self._positions()[entity_id]
        except KeyError:
            raise KeyError(entity_id) from None

    def get(self, entity_id: str) -> Entity:
        return self._items[self.index_of(entity_id)]

    def __contains__(self, entity_id: object) -> bool:
        return entity_id in self._positions()

    def add(self, entity: Entity, index: int | None = None) -> None:
        if entity.id in self:
            raise ValueError(f"duplicate entity id {entity.id}")
        if index is None or index >= len(self._items):
            self._items.append(entity)
            if self._index is not None:
                self._index[entity.id] = len(self._items) - 1
        else:
            self._items.insert(index, entity)
            self._index = None
        self._notify("added", entity)

    def remove(self, entity_id: str) -> tuple[int, Entity]:
        i = self.index_of(entity_id)
        entity = self._items.pop(i)
        if i == len(self._items) and self._index is not None:
            del self._index[entity_id]
        else:
            self._index = None
        self._notify("removed", entity)
        return i, entity

    def replace(self, entity: Entity) -> None:
        self._items[self.index_of(entity.id)] = entity
        self._notify("changed", entity)
