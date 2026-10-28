"""Adding the blocks of an imported library to a library file. Pure Python.

A block whose name is taken by a different block asks ``decide``: keep the one there,
replace it, or add the new one under another name (its uses in the imported blocks
follow). Blocks equal to the one there are left out without asking.
"""

from collections.abc import Callable
from pathlib import Path

from sldgridy.fileio.files import load_library, save_library
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


def move_category(source: Path, target: Path, category: str, title: str) -> int:
    """Move the blocks of ``category`` from the library file ``source`` into ``target``
    (created with ``title`` when missing). A name taken in ``target`` by a different
    block gets a number; equal ones are just dropped from ``source``. How many moved."""
    if not source.exists():
        return 0
    source_title, blocks = load_library(source)
    moving = [b for b in blocks if b.category == category]
    if not moving:
        return 0
    there = load_library(target)[1] if target.exists() else []
    if target.exists():
        title = load_library(target)[0] or title
    taken = {b.name for b in there}

    def renamed(old: BlockDefinition, new: BlockDefinition) -> tuple[str, str]:
        n = 2
        while f"{new.name} ({n})" in taken:
            n += 1
        taken.add(f"{new.name} ({n})")
        return RENAME, f"{new.name} ({n})"

    merged = merged_library(there, moving, renamed)
    assert merged is not None
    save_library(merged, target, title)
    rest = [b for b in blocks if b.category != category]
    if rest:
        save_library(rest, source, source_title)
    else:
        source.unlink()
    return len(moving)
