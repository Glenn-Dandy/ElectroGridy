"""Undo commands that add, remove or replace entities in a container."""

from collections.abc import Iterable

from PyQt6.QtGui import QUndoCommand

from electrogridy.model.container import EntityContainer
from electrogridy.model.entities import Entity


class AddEntitiesCommand(QUndoCommand):
    def __init__(self, container: EntityContainer, entities: Iterable[Entity], text: str) -> None:
        super().__init__(text)
        self._container = container
        self._entities = list(entities)

    def redo(self) -> None:
        with self._container.batch():
            for e in self._entities:
                self._container.add(e)

    def undo(self) -> None:
        with self._container.batch():
            for e in reversed(self._entities):
                self._container.remove(e.id)


class RemoveEntitiesCommand(QUndoCommand):
    def __init__(self, container: EntityContainer, ids: Iterable[str], text: str) -> None:
        super().__init__(text)
        self._container = container
        self._ids = list(ids)
        self._removed: list[tuple[int, Entity]] = []

    def redo(self) -> None:
        with self._container.batch():
            self._removed = [self._container.remove(i) for i in self._ids]

    def undo(self) -> None:
        # Reinsert in reverse removal order so every index is valid again.
        with self._container.batch():
            for index, entity in reversed(self._removed):
                self._container.add(entity, index)
        self._removed = []


class ReplaceEntitiesCommand(QUndoCommand):
    """Swap entities for modified versions with the same ids. Entities whose id is not
    in the container yet (e.g. junction marks created by a move) are added."""

    def __init__(self, container: EntityContainer, new: Iterable[Entity], text: str) -> None:
        super().__init__(text)
        self._container = container
        entities = list(new)
        self._new = [e for e in entities if e.id in container]
        self._added = [e for e in entities if e.id not in container]
        self._old = [container.get(e.id) for e in self._new]

    def redo(self) -> None:
        with self._container.batch():
            for e in self._new:
                self._container.replace(e)
            for e in self._added:
                self._container.add(e)

    def undo(self) -> None:
        with self._container.batch():
            for e in reversed(self._added):
                self._container.remove(e.id)
            for e in self._old:
                self._container.replace(e)
