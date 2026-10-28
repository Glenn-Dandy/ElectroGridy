"""Adding the blocks of an imported library to a library file. Pure Python.

A block whose name is taken by a different block asks ``decide``: keep the one there,
replace it, or add the new one under another name (its uses in the imported blocks
follow). Blocks equal to the one there are left out without asking.
"""

from collections.abc import Callable

from sldgridy.fileio.json_format import block_signature
from sldgridy.model.blocks import BlockDefinition, rename_references

KEEP, REPLACE, RENAME = "keep", "replace", "rename"

# (block there, imported block) -> (KEEP or REPLACE, "") or (RENAME, new name); None cancels.
Decide = Callable[[BlockDefinition, BlockDefinition], tuple[str, str] | None]


def merged_library(
    existing: list[BlockDefinition], incoming: list[BlockDefinition], decide: Decide
) -> list[BlockDefinition] | None:
    """``existing`` with ``incoming`` added; None if ``decide`` cancelled."""
    result = {b.name: b for b in existing}
    renames: dict[str, str] = {}
    added: list[BlockDefinition] = []
    for block in incoming:
        there = result.get(block.name)
        if there is None:
            added.append(block)
            continue
        if block_signature(there) == block_signature(block):
            continue
        answer = decide(there, block)
        if answer is None:
            return None
        action, name = answer
        if action == REPLACE:
            added.append(block)
        elif action == RENAME and name and name not in result:
            renames[block.name] = name
            added.append(block.copy(name))
    for block in added:
        result[block.name] = rename_references(block, renames)
    return list(result.values())
