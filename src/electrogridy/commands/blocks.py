"""Undo commands for block definitions."""

from dataclasses import replace

from PyQt6.QtGui import QUndoCommand

from electrogridy.model.blocks import BlockDefinition
from electrogridy.model.document import Document
from electrogridy.model.entities import BlockReference


class AddBlockCommand(QUndoCommand):
    def __init__(self, doc: Document, definition: BlockDefinition, text: str) -> None:
        super().__init__(text)
        if definition.name in doc.blocks:
            raise ValueError(f"block {definition.name!r} exists")
        self._doc = doc
        self._definition = definition

    def redo(self) -> None:
        self._doc.set_block(self._definition)

    def undo(self) -> None:
        self._doc.remove_block(self._definition.name)


class ReplaceBlockCommand(QUndoCommand):
    """Swap a definition for a new one with the same name; references follow."""

    def __init__(self, doc: Document, definition: BlockDefinition, text: str) -> None:
        super().__init__(text)
        self._doc = doc
        self._old = doc.blocks[definition.name]
        self._new = definition

    def redo(self) -> None:
        self._doc.set_block(self._new)

    def undo(self) -> None:
        self._doc.set_block(self._old)


class SetBasePointCommand(QUndoCommand):
    """Change the base point of a definition being edited in the block editor."""

    def __init__(self, definition: BlockDefinition, point, text: str) -> None:
        super().__init__(text)
        self._definition = definition
        self._old = definition.base_point
        self._new = point

    def redo(self) -> None:
        self._definition.base_point = self._new

    def undo(self) -> None:
        self._definition.base_point = self._old


class ChangeBlockInfoCommand(QUndoCommand):
    """Rename a definition or change its category and description.

    A new name is carried over to every reference in the drawing (model,
    sheets, other definitions) and to sheets that use it as title block.
    """

    def __init__(
        self,
        doc: Document,
        old_name: str,
        name: str,
        category: str,
        description: str,
        text: str,
        function: str | None = None,
        contact: str | None = None,
    ) -> None:
        super().__init__(text)
        if name != old_name and name in doc.blocks:
            raise ValueError(f"block {name!r} exists")
        self._doc = doc
        self._old = doc.blocks[old_name]
        self._new = self._old.copy(name)
        self._new.category = category
        self._new.description = description
        if function is not None:
            self._new.function = function
        if contact is not None:
            self._new.contact = contact

    def _swap(self, remove: BlockDefinition, add: BlockDefinition) -> None:
        doc = self._doc
        doc.set_block(add)
        if remove.name == add.name:
            return
        for container in list(doc.containers()):
            for e in list(container):
                if isinstance(e, BlockReference) and e.name == remove.name:
                    container.replace(replace(e, name=add.name))
        doc.remove_block(remove.name)
        renamed_title = False
        for sheet in doc.sheets:
            if sheet.title_block == remove.name:
                sheet.title_block = add.name
                renamed_title = True
        if renamed_title:
            doc.sheets_changed()

    def redo(self) -> None:
        self._swap(self._old, self._new)

    def undo(self) -> None:
        self._swap(self._new, self._old)


class RemoveBlockCommand(QUndoCommand):
    """Delete a definition that is used nowhere in the drawing."""

    def __init__(self, doc: Document, name: str, text: str) -> None:
        super().__init__(text)
        if doc.block_in_use(name) or any(s.title_block == name for s in doc.sheets):
            raise ValueError(f"block {name!r} is in use")
        self._doc = doc
        self._definition = doc.blocks[name]

    def redo(self) -> None:
        self._doc.remove_block(self._definition.name)

    def undo(self) -> None:
        self._doc.set_block(self._definition)
