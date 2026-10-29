"""Undo commands for layers."""

from dataclasses import replace

from PyQt6.QtGui import QUndoCommand

from electrogridy.model.document import Document
from electrogridy.model.layers import Layer


class AddLayerCommand(QUndoCommand):
    def __init__(self, doc: Document, layer: Layer, text: str) -> None:
        super().__init__(text)
        self._doc = doc
        self._layer = layer
        self._index = len(doc.layers)

    def redo(self) -> None:
        self._doc.insert_layer(self._index, self._layer)

    def undo(self) -> None:
        self._doc.remove_layer(self._layer.name)


class RemoveLayerCommand(QUndoCommand):
    """Remove an unused layer."""

    def __init__(self, doc: Document, name: str, text: str) -> None:
        super().__init__(text)
        if doc.layer_in_use(name):
            raise ValueError(f"layer {name!r} is in use")
        self._doc = doc
        self._name = name
        self._removed: tuple[int, Layer] | None = None

    def redo(self) -> None:
        self._removed = self._doc.remove_layer(self._name)

    def undo(self) -> None:
        assert self._removed is not None
        self._doc.insert_layer(*self._removed)


class ChangeLayerCommand(QUndoCommand):
    """Change layer properties; a new name is carried over to all entities on the layer."""

    def __init__(self, doc: Document, old_name: str, new: Layer, text: str) -> None:
        super().__init__(text)
        self._doc = doc
        self._index = doc.layer_index(old_name)
        self._old = doc.layers[self._index]
        self._new = new

    def _apply(self, layer: Layer, rename_from: str) -> None:
        if layer.name != rename_from:
            # Set the layer first so entities never point to a missing name for long.
            self._doc.set_layer(self._index, layer)
            for container in self._doc.containers():
                for e in container:
                    if e.layer == rename_from:
                        container.replace(replace(e, layer=layer.name))
        else:
            self._doc.set_layer(self._index, layer)

    def redo(self) -> None:
        self._apply(self._new, self._old.name)

    def undo(self) -> None:
        self._apply(self._old, self._new.name)
