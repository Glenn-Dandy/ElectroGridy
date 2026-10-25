"""Block related commands of the main window: create, insert, explode, edit, libraries."""

import math
import re
import shutil
from collections import ChainMap
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QCoreApplication, QObject, QPointF, QSettings, Qt
from PyQt6.QtGui import QAction, QColor, QPainter, QPen, QUndoCommand, QUndoStack
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from sldgridy.commands.blocks import (
    AddBlockCommand,
    ChangeBlockInfoCommand,
    RemoveBlockCommand,
    ReplaceBlockCommand,
    SetBasePointCommand,
)
from sldgridy.commands.entities import (
    AddEntitiesCommand,
    RemoveEntitiesCommand,
    ReplaceEntitiesCommand,
)
from sldgridy.fileio.dxf import DxfError, read_dxf
from sldgridy.fileio.files import LIBRARY_SUFFIX, load_library, save_library
from sldgridy.fileio.json_format import (
    FileFormatError,
    block_from_dict,
    block_signature,
    block_to_dict,
)
from sldgridy.fileio.paths import user_library_dir
from sldgridy.i18n import library_text
from sldgridy.model.blocks import (
    BlockDefinition,
    BlockError,
    bounds,
    dependencies,
    expand,
    explode,
    world_connections,
    would_create_cycle,
)
from sldgridy.model.container import EntityContainer
from sldgridy.model.devices import BMK, suggest_bmk
from sldgridy.model.document import DOC_DRAWING
from sldgridy.model.entities import (
    AttributeDefinition,
    BlockReference,
    ConnectionPoint,
    Entity,
    new_id,
)
from sldgridy.model.geometry import Point
from sldgridy.model.routing import open_wires
from sldgridy.tools.blocks import InsertBlockTool, PointTool
from sldgridy.tools.edit import SelectObjectsTool
from sldgridy.ui.block_dialogs import (
    KEEP,
    RENAME,
    REPLACE,
    AttributeDefinitionDialog,
    AttributeValueEdit,
    AttributeValuesDialog,
    BlockChooserDialog,
    BlockPropertiesDialog,
    ConnectionPointDialog,
    CreateBlockDialog,
    ask_block_conflict,
)
from sldgridy.ui.space import BLOCK, Space

if TYPE_CHECKING:
    from sldgridy.ui.main_window import MainWindow
    from sldgridy.ui.properties_dock import PropertiesDock

USER_LIBRARY_FILE = "eigene" + LIBRARY_SUFFIX
BASE_MARKER_COLOR = QColor("#d81b60")


def unique_name(name: str, taken: Mapping[str, object]) -> str:
    n = 2
    while f"{name} ({n})" in taken:
        n += 1
    return f"{name} ({n})"


def rename_references(definition: BlockDefinition, mapping: dict[str, str]) -> BlockDefinition:
    if not mapping:
        return definition
    entities = [
        replace(e, name=mapping[e.name])
        if isinstance(e, BlockReference) and e.name in mapping
        else e
        for e in definition.entities
    ]
    copy = definition.copy()
    copy.entities = EntityContainer(entities)
    return copy


def default_attributes(definition: BlockDefinition) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((a.tag, a.default) for a in definition.attribute_definitions()))


class BlockController(QObject):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.w = window
        self.editor_space: Space | None = None
        self._editor_bar: QFrame | None = None

    # -- helpers ------------------------------------------------------------

    @property
    def doc(self):
        return self.w.document

    def tr(self, text: str) -> str:  # noqa: D102 - QObject.tr with a stable context
        return self.w.tr(text)

    def in_editor(self) -> bool:
        return self.w.space.kind == BLOCK

    def _doc_push(self, command: QUndoCommand) -> None:
        """Document level changes (block definitions) always go to the drawing's stack."""
        if self.in_editor():
            self.w.undo_stack.push(command)
        else:
            self.w.push(command)

    # -- actions and menu ---------------------------------------------------

    def create_actions(self) -> None:
        a = self.w._action
        self.act_create = a(self.tr("Block &erstellen …"), self.create_from_selection, "Ctrl+B")
        self.act_insert = a(self.tr("Block &einfügen …"), self.insert_dialog, "Ctrl+I")
        self.act_edit = a(self.tr("Block &bearbeiten …"), self.edit_block)
        self.act_attribute = a(self.tr("A&ttribut definieren …"), self.define_attribute)
        self.act_connection = a(self.tr("A&nschlusspunkt setzen …"), self.define_connection)
        self.act_to_library = a(
            self.tr("In Benutzerbibliothek &speichern …"), self.save_to_user_library
        )
        self.act_import = a(self.tr("Bibliothek &importieren …"), self.import_library)
        self.act_import_dxf = a(self.tr("Symbole aus &DXF importieren …"), self.import_dxf)
        self.act_export = a(self.tr("Bibliothek e&xportieren …"), self.export_library)
        self.act_base = a(self.tr("Basispunkt setzen"), self.set_base_point)
        self.act_editor_save = a(
            self.tr("Speichern und schließen"), lambda: self.close_editor(save=True)
        )
        self.act_editor_discard = a(
            self.tr("Verwerfen"), lambda: self.close_editor(save=False, ask=True)
        )

    def create_menu(self, bar: QMenuBar) -> None:
        m = bar.addMenu(self.tr("Bl&ock"))
        m.addActions([self.act_create, self.act_insert, self.act_edit, self.w.act_explode])
        m.addSeparator()
        m.addActions([self.act_attribute, self.act_connection])
        m.addSeparator()
        m.addActions([self.act_to_library, self.act_import, self.act_import_dxf, self.act_export])

    def toolbar_actions(self) -> list[QAction]:
        return [self.act_insert, self.act_create, self.act_edit]

    # -- properties dock ----------------------------------------------------

    def attach_properties(self, dock: "PropertiesDock") -> None:
        dock.extra_type_names.update(
            {
                BlockReference: self.tr("Blockreferenz"),
                AttributeDefinition: self.tr("Attributdefinition"),
                ConnectionPoint: self.tr("Anschlusspunkt"),
            }
        )
        dock.extra_editors.append(self._attribute_editor)

    def _attribute_editor(self, entities: list[Entity], layout: QVBoxLayout) -> None:
        if len(entities) != 1 or not isinstance(entities[0], BlockReference):
            return
        ref = entities[0]
        layout.addWidget(QLabel(self.tr("Block: {name}").format(name=library_text(ref.name))))
        definition = self.doc.blocks.get(ref.name)
        attdefs = definition.attribute_definitions() if definition else []
        if not attdefs:
            return
        box = QGroupBox(self.tr("Attribute"))
        form = QFormLayout(box)
        edits: dict[str, AttributeValueEdit] = {}
        for d in attdefs:
            edit = AttributeValueEdit(ref.attribute(d.tag, d.default))
            form.addRow(f"{d.tag}:", edit)
            edits[d.tag] = edit
        apply = QPushButton(self.tr("Attribute übernehmen"))
        form.addRow(apply)
        layout.addWidget(box)

        def on_apply() -> None:
            current = self.w.container.get(ref.id)
            new = current
            for tag, edit in edits.items():
                new = new.with_attribute(tag, edit.text())
            if new != current:
                self.w.push(
                    ReplaceEntitiesCommand(self.w.container, [new], self.tr("Attribute ändern"))
                )

        apply.clicked.connect(on_apply)
        for edit in edits.values():
            edit.submitted.connect(on_apply)

    # -- create -------------------------------------------------------------

    def create_from_selection(self) -> None:
        if self.in_editor():
            self.w.message(self.tr("Im Blockeditor können keine neuen Blöcke erstellt werden"))
            return
        ids = self.w.selected_ids()
        if not ids:
            # Like the modify commands: ask for the objects first.
            self.w.start_tool(
                lambda ctx: SelectObjectsTool(
                    ctx, self.tr("Block erstellen"), self._create_block_for
                )
            )
            return
        self._create_block_for(ids)

    def _create_block_for(self, ids: list[str]) -> None:
        dialog = CreateBlockDialog(set(self.doc.blocks), self.w)
        dialog.in_editor.setChecked(QSettings().value("blocks/create_in_editor", True, type=bool))
        if dialog.exec() != CreateBlockDialog.DialogCode.Accepted:
            return
        name = dialog.name.text().strip()
        category = dialog.category.text().strip()
        description = dialog.description.text().strip()
        replace_selection = dialog.replace_selection.isChecked()
        QSettings().setValue("blocks/create_in_editor", dialog.in_editor.isChecked())
        if dialog.in_editor.isChecked():
            self._open_new_block_editor(name, category, description, replace_selection, ids)
            return
        self.w.start_tool(
            lambda ctx: PointTool(
                ctx,
                self.tr("Block {name}: Basispunkt angeben").format(name=name),
                lambda p: self._finish_create(
                    name, category, description, replace_selection, ids, p
                ),
            )
        )

    def _finish_create(
        self,
        name: str,
        category: str,
        description: str,
        replace_selection: bool,
        ids: list[str],
        base: Point,
    ) -> None:
        container = self.w.container
        entities = [container.get(i) for i in ids if i in container]
        definition = BlockDefinition(name, base, EntityContainer(entities), category, description)
        self._commit_new_block(definition, self.w.space, ids if replace_selection else [])

    def _commit_new_block(self, definition: BlockDefinition, space: Space, ids: list[str]) -> None:
        """Add ``definition`` (world coordinates around its base point) to the drawing and
        replace the objects ``ids`` of ``space`` with a reference at the base point."""
        base = definition.base_point
        name = definition.name
        if name in self.doc.blocks:
            name = unique_name(name, self.doc.blocks)
        local = BlockDefinition(
            name,
            Point(0.0, 0.0),
            EntityContainer([e.translated(-base.x, -base.y) for e in definition.entities]),
            definition.category,
            definition.description,
        )
        container = space.container
        ids = [i for i in ids if i in container]
        stack = space.stack
        stack.beginMacro(self.tr("Block {name} erstellen").format(name=name))
        stack.push(AddBlockCommand(self.doc, local, self.tr("Block anlegen")))
        if ids:
            ref = BlockReference(
                id=new_id(),
                layer=self.w.current_layer,
                name=name,
                insert=base,
                attributes=default_attributes(local),
            )
            stack.push(RemoveEntitiesCommand(container, ids, ""))
            stack.push(AddEntitiesCommand(container, [ref], ""))
        stack.endMacro()
        self.w.message(self.tr("Block {name} erstellt").format(name=name))

    def _open_new_block_editor(
        self, name: str, category: str, description: str, replace_selection: bool, ids: list[str]
    ) -> None:
        """Edit a block that does not exist yet; it is created on save."""
        origin = self.w.space
        entities = [origin.container.get(i) for i in ids if i in origin.container]
        base = self._initial_base(entities)
        working = BlockDefinition(name, base, EntityContainer(entities), category, description)
        space = self._open_editor(working, self.tr("{name} (neu)").format(name=name))
        space.extra["new_block"] = (origin, ids if replace_selection else [])
        space.extra["auto_base"] = base
        self.w.message(
            self.tr(
                "Anschlusspunkte und Attribute festlegen, dann „Speichern und schließen“. "
                "Der Basispunkt springt auf den ersten Anschlusspunkt, bis du ihn selbst setzt."
            )
        )

    def _initial_base(self, entities: list[Entity]) -> Point:
        for e in entities:
            if isinstance(e, ConnectionPoint) and e.name == "1":
                return e.position
        box = bounds([part for e in entities for part in self.w.expand_with(None, e)])
        if box is None:
            return Point(0.0, 0.0)
        step = self.w.canvas.snap_spacing or 1.0
        x = math.floor((box[0] + box[2]) / 2 / step + 0.5) * step
        y = math.floor((box[1] + box[3]) / 2 / step + 0.5) * step
        return Point(x, y)

    # -- insert -------------------------------------------------------------

    def insert_dialog(self) -> None:
        if not self.doc.blocks:
            self.w.message(
                self.tr("Die Zeichnung enthält keine Blöcke. Blöcke aus der Bibliothek ziehen.")
            )
            return
        dialog = BlockChooserDialog(self.doc.blocks, self.tr("Block einfügen"), self.w)
        if dialog.exec() == BlockChooserDialog.DialogCode.Accepted and dialog.selected_names():
            self.insert_from_source("", dialog.selected_names()[0])

    def insert_from_source(self, path: str, name: str, at: Point | None = None) -> None:
        if path:
            plan = self._plan_import(name, self.w.library_dock.library(path))
            if plan is None:
                return
            final_name, to_add, to_replace, merged = plan
        else:
            if name not in self.doc.blocks:
                return
            final_name, to_add, to_replace, merged = name, [], [], self.doc.blocks
        definition = merged[final_name]

        def prepare() -> None:
            for d in to_add:
                self._doc_push(AddBlockCommand(self.doc, d, self.tr("Block anlegen")))
            for d in to_replace:
                self._doc_push(ReplaceBlockCommand(self.doc, d, self.tr("Block ersetzen")))

        template = BlockReference(
            id=new_id(),
            name=final_name,
            insert=Point(0.0, 0.0),
            attributes=default_attributes(definition),
            scale=self.w.drawing_scale(),  # a page at 1:5 gets the symbol at 1:5
        )
        on_place = self._placer(prepare, merged)
        if at is not None:
            on_place(replace(template, insert=at, layer=self.w.current_layer))
            return
        self.w.start_tool(
            lambda ctx: InsertBlockTool(
                ctx,
                template,
                merged,
                self.tr("Block {name}: Einfügepunkt angeben").format(name=final_name),
                on_place,
            )
        )

    def _placer(
        self, prepare: Callable[[], None], blocks: Mapping[str, BlockDefinition]
    ) -> Callable[[BlockReference], None]:
        def place(ref: BlockReference) -> None:
            if self.in_editor() and would_create_cycle(self.editor_name(), [ref], blocks):
                self.w.message(self.tr("Ein Block kann sich nicht selbst enthalten"))
                return
            definition = blocks[ref.name]
            attdefs = definition.attribute_definitions()
            if attdefs:
                values = dict(ref.attributes)
                bmk = next((d for d in attdefs if d.tag == BMK), None)
                if bmk is not None and values.get(BMK, "") in ("", bmk.default):
                    values[BMK] = suggest_bmk(self.doc, bmk.default, definition.function)
                dialog = AttributeValuesDialog(ref.name, attdefs, values, self.w)
                if dialog.exec() != AttributeValuesDialog.DialogCode.Accepted:
                    return
                ref = replace(ref, attributes=tuple(sorted(dialog.values().items())))
            ref = replace(ref, id=new_id())
            text = self.tr("Block {name} einfügen").format(name=ref.name)
            # Placed into wires (circuit diagrams): each pole opens its conductor.
            removed, added = [], []
            if not self.in_editor() and self.doc.kind != DOC_DRAWING:
                removed, added = open_wires(self.w.container, world_connections(ref, blocks))
            if removed:
                self.w.begin_macro(text)
            prepare()
            self.w.push(AddEntitiesCommand(self.w.container, [ref], text))
            if removed:
                self.w.push(RemoveEntitiesCommand(self.w.container, removed, ""))
                self.w.push(AddEntitiesCommand(self.w.container, added, ""))
                self.w.end_macro()

        return place

    def _plan_import(
        self, name: str, library: Mapping[str, BlockDefinition]
    ) -> tuple[str, list, list, dict] | None:
        """Decide which library definitions to copy. None if the user cancelled."""
        if name not in library:
            return None
        to_add: list[BlockDefinition] = []
        to_replace: list[BlockDefinition] = []
        renames: dict[str, str] = {}
        taken: dict[str, object] = dict(self.doc.blocks)
        for dep in dependencies(name, library):
            source = library.get(dep)
            if source is None:
                continue
            existing = self.doc.blocks.get(dep)
            if existing is None:
                to_add.append(source.copy())
                taken[dep] = True
                continue
            if block_signature(existing) == block_signature(source):
                continue
            choice = ask_block_conflict(self.w, dep)
            if choice is None:
                return None
            if choice == REPLACE:
                to_replace.append(source.copy())
            elif choice == RENAME:
                new = unique_name(dep, taken)
                taken[new] = True
                renames[dep] = new
                to_add.append(source.copy(new))
            else:
                assert choice == KEEP
        to_add = [rename_references(d, renames) for d in to_add]
        to_replace = [rename_references(d, renames) for d in to_replace]
        merged = dict(self.doc.blocks)
        for d in to_add + to_replace:
            merged[d.name] = d
        for d in to_add + to_replace:
            if would_create_cycle(d.name, d.entities, merged):
                self.w.message(
                    self.tr("Der Block {name} würde sich selbst enthalten").format(name=d.name)
                )
                return None
        return renames.get(name, name), to_add, to_replace, merged

    def drag_preview(self, payload: dict, at: Point) -> list[Entity]:
        """Geometry of a block dragged from the library dock, inserted at ``at``."""
        name = str(payload.get("name", ""))
        library = self.w.library_dock.library(str(payload.get("path", "")))
        blocks = ChainMap(library, self.doc.blocks)
        if name not in blocks:
            return []
        ref = BlockReference(
            id="drag-preview",
            name=name,
            insert=at,
            layer=self.w.current_layer,
            attributes=default_attributes(blocks[name]),
            scale=self.w.drawing_scale(),
        )
        try:
            return expand(ref, blocks)
        except BlockError:
            return []

    def on_drop(self, payload: dict, point: QPointF) -> None:
        if not isinstance(payload, dict):
            return
        path, name = str(payload.get("path", "")), str(payload.get("name", ""))
        self.insert_from_source(path, name, Point(point.x(), point.y()))

    # -- explode ------------------------------------------------------------

    def explode_selection(self) -> None:
        refs = [e for e in self.w.selected_entities() if isinstance(e, BlockReference)]
        if not refs:
            self.w.message(self.tr("Zuerst Blockreferenzen auswählen"))
            return
        self.w.tools.cancel()
        container = self.w.container
        self.w.begin_macro(self.tr("Auflösen"))
        for ref in refs:
            parts = explode(ref, self.doc.blocks)
            index = container.index_of(ref.id)
            self.w.push(RemoveEntitiesCommand(container, [ref.id], ""))
            if parts:
                self.w.push(_InsertAtCommand(container, index, parts))
        self.w.end_macro()

    # -- attributes and connection points -----------------------------------

    def edit_entity(self, entity: Entity) -> bool:
        """Double-click handling. True if the entity type was handled here."""
        container = self.w.container
        if isinstance(entity, BlockReference):
            definition = self.doc.blocks.get(entity.name)
            attdefs = definition.attribute_definitions() if definition else []
            if not attdefs:
                self.w.message(
                    self.tr("Block {name} hat keine Attribute; Block > Block bearbeiten").format(
                        name=entity.name
                    )
                )
                return True
            dialog = AttributeValuesDialog(entity.name, attdefs, dict(entity.attributes), self.w)
            if dialog.exec() == AttributeValuesDialog.DialogCode.Accepted:
                new = replace(entity, attributes=tuple(sorted(dialog.values().items())))
                if new != entity:
                    self.w.push(
                        ReplaceEntitiesCommand(container, [new], self.tr("Attribute ändern"))
                    )
            return True
        if isinstance(entity, AttributeDefinition):
            dialog = AttributeDefinitionDialog(self.w, entity)
            if dialog.exec() == AttributeDefinitionDialog.DialogCode.Accepted:
                new = replace(entity, **dialog.values())
                if new != entity:
                    self.w.push(
                        ReplaceEntitiesCommand(container, [new], self.tr("Attribut ändern"))
                    )
            return True
        if isinstance(entity, ConnectionPoint):
            dialog = ConnectionPointDialog(self.w, entity.name, entity.direction)
            if dialog.exec() == ConnectionPointDialog.DialogCode.Accepted:
                name, direction = dialog.values()
                new = replace(entity, name=name, direction=direction)
                if new != entity:
                    self.w.push(
                        ReplaceEntitiesCommand(container, [new], self.tr("Anschlusspunkt ändern"))
                    )
            return True
        return False

    def define_attribute(self) -> None:
        dialog = AttributeDefinitionDialog(self.w)
        if dialog.exec() != AttributeDefinitionDialog.DialogCode.Accepted:
            return
        values = dialog.values()

        def make(p: Point, entity_id: str = "preview") -> AttributeDefinition:
            return AttributeDefinition(
                id=entity_id, layer=self.w.current_layer, position=p, **values
            )

        def place(p: Point) -> None:
            self.w.push(
                AddEntitiesCommand(
                    self.w.container, [make(p, new_id())], self.tr("Attribut definieren")
                )
            )

        self.w.start_tool(
            lambda ctx: PointTool(
                ctx,
                self.tr("Attribut {tag}: Position angeben").format(tag=values["tag"]),
                place,
                lambda p: [make(p)],
            )
        )

    def _next_connection_name(self) -> str:
        names = {e.name for e in self.w.container if isinstance(e, ConnectionPoint)}
        n = 1
        while str(n) in names:
            n += 1
        return str(n)

    def define_connection(self) -> None:
        dialog = ConnectionPointDialog(self.w, self._next_connection_name())
        if dialog.exec() != ConnectionPointDialog.DialogCode.Accepted:
            return
        name, direction = dialog.values()

        def make(p: Point, entity_id: str = "preview") -> ConnectionPoint:
            return ConnectionPoint(
                id=entity_id, layer=self.w.current_layer, name=name, position=p, direction=direction
            )

        def place(p: Point) -> None:
            command = AddEntitiesCommand(
                self.w.container, [make(p, new_id())], self.tr("Anschlusspunkt setzen")
            )
            space = self.editor_space
            definition = space.extra["definition"] if space is not None else None
            follow = (
                definition is not None
                and "auto_base" in space.extra
                and definition.base_point == space.extra["auto_base"]
                and not any(isinstance(e, ConnectionPoint) for e in self.w.container)
            )
            if not follow:
                self.w.push(command)
                return
            self.w.begin_macro(command.text())
            self.w.push(command)
            self.w.push(SetBasePointCommand(definition, p, self.tr("Basispunkt setzen")))
            self.w.end_macro()

        self.w.start_tool(
            lambda ctx: PointTool(
                ctx,
                self.tr("Anschlusspunkt {name}: Position angeben").format(name=name),
                place,
                lambda p: [make(p)],
            )
        )

    # -- block editor -------------------------------------------------------

    def editor_name(self) -> str:
        if self.editor_space is None:
            return ""
        return self.editor_space.extra["definition"].name

    def _choose_block(self, title: str) -> str | None:
        refs = [e for e in self.w.selected_entities() if isinstance(e, BlockReference)]
        if len(refs) == 1:
            return refs[0].name
        if not self.doc.blocks:
            self.w.message(self.tr("Die Zeichnung enthält keine Blöcke"))
            return None
        dialog = BlockChooserDialog(self.doc.blocks, title, self.w)
        if dialog.exec() == BlockChooserDialog.DialogCode.Accepted and dialog.selected_names():
            return dialog.selected_names()[0]
        return None

    def edit_block(self) -> None:
        if self.editor_space is not None:
            self.w.message(self.tr("Der Blockeditor ist bereits geöffnet"))
            return
        name = self._choose_block(self.tr("Block bearbeiten"))
        if name is not None:
            self.open_editor(name)

    def open_editor(self, name: str) -> None:
        self._open_editor(self.doc.blocks[name].copy(), name)

    def open_library_editor(self, path: str, name: str) -> None:
        """Edit a symbol of a user library; saving writes the library file."""
        if self.editor_space is not None:
            self.w.message(self.tr("Der Blockeditor ist bereits geöffnet"))
            return
        if not path:
            if name in self.doc.blocks:
                self.open_editor(name)
            return
        if not self.w.library_dock.editable(path):
            return
        loaded = self._load_user_library(Path(path))
        if loaded is None:
            return
        title, blocks = loaded
        by_name = {b.name: b for b in blocks}
        if name not in by_name:
            self.w.library_dock.reload()
            return
        # Nested symbols come from the library first, then from the drawing.
        lookup = ChainMap(by_name, self.doc.blocks)
        label = self.tr("{name} (Bibliothek {library})").format(
            name=name, library=library_text(title)
        )
        space = self._open_editor(by_name[name].copy(), label, lookup)
        space.extra["library"] = (Path(path), title)

    def _open_editor(
        self,
        working: BlockDefinition,
        label: str,
        blocks: Mapping[str, BlockDefinition] | None = None,
    ) -> Space:
        stack = QUndoStack(self.w)
        back = self.w.space  # where saving or discarding returns to
        space = self.w._make_space(BLOCK, working.entities, stack, blocks=blocks)
        space.extra["definition"] = working
        space.extra["return_to"] = back
        space.extra["overlay"] = self._draw_base_point
        self.editor_space = space
        self._show_bar(label)
        self.w.activate_space(space)
        self.w.canvas.zoom_extents()
        return space

    def _show_bar(self, name: str) -> None:
        if self._editor_bar is None:
            bar = QFrame()
            # Dark text of its own: the bar stays yellow in dark mode too.
            bar.setStyleSheet(
                "QFrame { background: #fff3c4; border-bottom: 1px solid #d0b050; }"
                " QLabel { color: #202020; }"
            )
            layout = QHBoxLayout(bar)
            layout.setContentsMargins(8, 4, 8, 4)
            self._bar_label = QLabel()
            layout.addWidget(self._bar_label)
            layout.addStretch(1)
            for action in (
                self.act_base,
                self.act_attribute,
                self.act_connection,
                self.act_editor_save,
                self.act_editor_discard,
            ):
                button = QToolButton()
                button.setDefaultAction(action)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                layout.addWidget(button)
            self.w.central_layout.insertWidget(0, bar)
            self._editor_bar = bar
        self._bar_label.setText(self.tr("<b>Blockeditor:</b> {name}").format(name=name))
        self._editor_bar.show()

    def _draw_base_point(self, painter: QPainter, scale: float) -> None:
        if self.editor_space is None or self.w.space is not self.editor_space:
            return
        base = self.editor_space.extra["definition"].base_point
        r = 8.0 / scale
        pen = QPen(BASE_MARKER_COLOR, 0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        c = QPointF(base.x, base.y)
        painter.drawEllipse(c, r / 2, r / 2)
        painter.drawLine(c - QPointF(r, 0), c + QPointF(r, 0))
        painter.drawLine(c - QPointF(0, r), c + QPointF(0, r))

    def set_base_point(self) -> None:
        if self.editor_space is None:
            return
        definition = self.editor_space.extra["definition"]
        self.w.start_tool(
            lambda ctx: PointTool(
                ctx,
                self.tr("Neuen Basispunkt angeben"),
                lambda p: self.w.push(
                    SetBasePointCommand(definition, p, self.tr("Basispunkt setzen"))
                ),
            )
        )

    def close_editor(self, save: bool | None = None, ask: bool = False) -> bool:
        """Leave the block editor. ``save`` None asks if there are changes.

        Returns False if the user cancelled.
        """
        space = self.editor_space
        if space is None:
            return True
        working: BlockDefinition = space.extra["definition"]
        dirty = not space.stack.isClean() or "new_block" in space.extra
        if save is None:
            if not dirty:
                save = False
            elif ask:
                buttons = QMessageBox.StandardButton
                answer = QMessageBox.question(
                    self.w,
                    self.tr("Blockeditor"),
                    self.tr("Änderungen am Block {name} speichern?").format(name=working.name),
                    buttons.Save | buttons.Discard | buttons.Cancel,
                    buttons.Save,
                )
                if answer == buttons.Cancel:
                    return False
                save = answer == buttons.Save
            else:
                save = False
        elif save is False and ask and dirty:
            buttons = QMessageBox.StandardButton
            answer = QMessageBox.question(
                self.w,
                self.tr("Blockeditor"),
                self.tr("Änderungen am Block {name} verwerfen?").format(name=working.name),
                buttons.Discard | buttons.Cancel,
                buttons.Cancel,
            )
            if answer != buttons.Discard:
                return False
        lookup = space.extra.get("blocks", self.doc.blocks)
        if save:
            new = working.copy()
            if would_create_cycle(new.name, new.entities, lookup):
                self.w.message(self.tr("Der Block würde sich selbst enthalten"))
                return False
        self.w.tools.cancel()
        self.editor_space = None
        if self._editor_bar is not None:
            self._editor_bar.hide()
        origin, replace_ids = space.extra.get("new_block", (space.extra.get("return_to"), []))
        if origin not in self.w.spaces():
            # The page or model it was opened from is gone; a project has no model view.
            origin, replace_ids = self.w.sheets.fallback_space(), []
        self.w.activate_space(origin)
        self.w._drop_space(space)
        if save and "new_block" in space.extra:
            self._commit_new_block(new, origin, replace_ids)
        elif save and "library" in space.extra:
            self._save_library_symbol(new, *space.extra["library"], lookup)
        elif save:
            old = self.doc.blocks.get(new.name)
            if old is not None and block_signature(old) != block_signature(new):
                self.w.push(
                    ReplaceBlockCommand(
                        self.doc, new, self.tr("Block {name} ändern").format(name=new.name)
                    )
                )
        self.w._update_title()
        return True

    def _save_library_symbol(
        self,
        definition: BlockDefinition,
        path: Path,
        title: str,
        lookup: Mapping[str, BlockDefinition],
    ) -> None:
        """Write an edited symbol back to its library, with nested blocks it now needs."""
        loaded = self._load_user_library(path)
        if loaded is None:
            return
        title, blocks = loaded
        by_name = {b.name: b for b in blocks}
        by_name[definition.name] = definition
        for name in dependencies(definition.name, ChainMap(by_name, lookup)):
            if name not in by_name and name in lookup:
                by_name[name] = lookup[name]
        save_library(list(by_name.values()), path, title)
        self.w.library_dock.reload()
        self.w.message(
            self.tr("Block {name} in {path} gespeichert").format(name=definition.name, path=path)
        )

    # -- libraries ----------------------------------------------------------

    def _definitions_with_dependencies(self, names: list[str]) -> list[BlockDefinition]:
        result: dict[str, BlockDefinition] = {}
        for name in names:
            for dep in dependencies(name, self.doc.blocks):
                if dep in self.doc.blocks:
                    result[dep] = self.doc.blocks[dep]
        return list(result.values())

    def save_to_user_library(self) -> None:
        name = self._choose_block(self.tr("In Benutzerbibliothek speichern"))
        if name is not None:
            self.save_block_to_user_library(name)

    def save_block_to_user_library(self, name: str) -> None:
        path = user_library_dir() / USER_LIBRARY_FILE
        title, existing = self.tr("Eigene Symbole"), []
        if path.exists():
            try:
                title, existing = load_library(path)
            except (OSError, FileFormatError) as exc:
                self.w.message(str(exc))
                return
        by_name = {b.name: b for b in existing}
        new = self._definitions_with_dependencies([name])
        conflicts = [
            d.name
            for d in new
            if d.name in by_name and block_signature(by_name[d.name]) != block_signature(d)
        ]
        if conflicts:
            answer = QMessageBox.question(
                self.w,
                self.tr("Benutzerbibliothek"),
                self.tr(
                    "Diese Blöcke gibt es in der Bibliothek schon anders:\n{names}\n\nErsetzen?"
                ).format(names=", ".join(conflicts)),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        for d in new:
            by_name[d.name] = d
        path.parent.mkdir(parents=True, exist_ok=True)
        save_library(list(by_name.values()), path, title)
        self.w.library_dock.reload()
        self.w.message(self.tr("Block {name} in {path} gespeichert").format(name=name, path=path))

    # -- managing blocks from the library dock ------------------------------

    def _categories(self) -> list[str]:
        """Categories in use anywhere, offered when editing a block."""
        found = {b.category for b in self.doc.blocks.values()}
        for lib in self.w.library_dock.libraries.values():
            found |= {b.category for b in lib.blocks.values()}
        return sorted(found - {""}, key=str.casefold)

    def _block_open_in_editor(self, path: str, name: str) -> bool:
        space = self.editor_space
        if space is None or self.editor_name() != name:
            return False
        library = space.extra.get("library")
        if (str(library[0]) if library else "") == path:
            self.w.message(self.tr("Block {name} ist im Blockeditor geöffnet").format(name=name))
            return True
        return False

    def _load_user_library(self, path: Path) -> tuple[str, list[BlockDefinition]] | None:
        try:
            return load_library(path)
        except (OSError, FileFormatError) as exc:
            self.w.message(str(exc))
            return None

    def edit_block_info(self, path: str, name: str) -> None:
        """Change name, category and description of a drawing or user library block."""
        if not path:
            if name not in self.doc.blocks or self._block_open_in_editor(path, name):
                return
            definition = self.doc.blocks[name]
            dialog = BlockPropertiesDialog(
                definition, set(self.doc.blocks), self._categories(), self.w
            )
            if dialog.exec() != BlockPropertiesDialog.DialogCode.Accepted:
                return
            new_name, category, description = dialog.values()
            function, contact = dialog.role()
            if (new_name, category, description, function, contact) == (
                name,
                definition.category,
                definition.description,
                definition.function,
                definition.contact,
            ):
                return
            self._doc_push(
                ChangeBlockInfoCommand(
                    self.doc,
                    name,
                    new_name,
                    category,
                    description,
                    self.tr("Blockeigenschaften {name} ändern").format(name=name),
                    function=function,
                    contact=contact,
                )
            )
            return
        if self._block_open_in_editor(path, name):
            return
        loaded = self._load_user_library(Path(path))
        if loaded is None:
            return
        title, blocks = loaded
        by_name = {b.name: b for b in blocks}
        if name not in by_name:
            self.w.library_dock.reload()
            return
        dialog = BlockPropertiesDialog(by_name[name], set(by_name), self._categories(), self.w)
        if dialog.exec() != BlockPropertiesDialog.DialogCode.Accepted:
            return
        new_name, category, description = dialog.values()
        changed = by_name[name].copy(new_name)
        changed.category = category
        changed.description = description
        changed.function, changed.contact = dialog.role()
        mapping = {name: new_name} if new_name != name else {}
        result = [changed if b.name == name else rename_references(b, mapping) for b in blocks]
        save_library(result, Path(path), title)
        self.w.library_dock.reload()
        self.w.message(self.tr("Block {name} geändert").format(name=new_name))

    def delete_block(self, path: str, name: str) -> None:
        """Remove an unused block from the drawing (undoable) or from a user library."""
        if not path:
            if name not in self.doc.blocks or self._block_open_in_editor(path, name):
                return
            if self.doc.block_in_use(name) or any(s.title_block == name for s in self.doc.sheets):
                self.w.message(
                    self.tr(
                        "Block {name} wird in der Zeichnung verwendet und kann nicht "
                        "gelöscht werden"
                    ).format(name=name)
                )
                return
            self._doc_push(
                RemoveBlockCommand(
                    self.doc, name, self.tr("Block {name} löschen").format(name=name)
                )
            )
            self.w.message(self.tr("Block {name} gelöscht").format(name=name))
            return
        if self._block_open_in_editor(path, name):
            return
        loaded = self._load_user_library(Path(path))
        if loaded is None:
            return
        title, blocks = loaded
        users = [
            b.name
            for b in blocks
            if any(isinstance(e, BlockReference) and e.name == name for e in b.entities)
        ]
        if users:
            QMessageBox.information(
                self.w,
                self.tr("Aus Bibliothek löschen"),
                self.tr(
                    "Block {name} wird von diesen Symbolen der Bibliothek verwendet:\n"
                    "{users}\n\nBitte diese zuerst löschen."
                ).format(name=name, users=", ".join(users)),
            )
            return
        answer = QMessageBox.question(
            self.w,
            self.tr("Aus Bibliothek löschen"),
            self.tr("Block {name} endgültig aus {library} löschen?").format(
                name=name, library=library_text(title)
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        save_library([b for b in blocks if b.name != name], Path(path), title)
        self.w.library_dock.reload()
        self.w.message(self.tr("Block {name} gelöscht").format(name=name))

    def import_dxf(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self.w,
            self.tr("Symbole aus DXF importieren"),
            self.w.last_dir(),
            self.tr("DXF-Zeichnung (*.dxf *.DXF)"),
        )
        if name:
            self.import_dxf_file(Path(name))

    def import_dxf_file(self, source: Path, ask: bool = True) -> Path | None:
        """Read symbols from a DXF file into a user library named after the file."""
        try:
            result = read_dxf(source)
        except (OSError, DxfError) as exc:
            QMessageBox.critical(
                self.w,
                self.tr("DXF-Import"),
                self.tr("{name} kann nicht gelesen werden:\n{error}").format(
                    name=source.name, error=exc
                ),
            )
            return None
        self.w.remember_dir(source)
        found = {d.name: d for d in result.blocks}
        names = list(found)
        if ask:
            dialog = BlockChooserDialog(
                found,
                self.tr("Symbole aus {name} übernehmen").format(name=source.name),
                self.w,
                multi=True,
                select_all=True,
            )
            if dialog.exec() != BlockChooserDialog.DialogCode.Accepted:
                return None
            names = dialog.selected_names()
            if not names:
                return None
        category = source.stem
        chosen = []
        for n in names:
            d = found[n]
            d.category = d.category or category
            d.description = d.description or self.tr("Importiert aus {file}").format(
                file=source.name
            )
            chosen.append(d)
        safe = re.sub(r"[^\w\-]+", "_", source.stem).strip("_") or "dxf_import"
        target = user_library_dir() / f"{safe}{LIBRARY_SUFFIX}"
        existing: list[BlockDefinition] = []
        if target.exists():
            if ask:
                answer = QMessageBox.question(
                    self.w,
                    self.tr("DXF-Import"),
                    self.tr(
                        "Die Bibliothek {name} gibt es schon. Symbole hinzufügen "
                        "(gleichnamige werden ersetzt)?"
                    ).format(name=target.name),
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return None
            try:
                _, existing = load_library(target)
            except (OSError, FileFormatError):
                existing = []
        merged = {d.name: d for d in existing}
        merged.update({d.name: d for d in chosen})
        target.parent.mkdir(parents=True, exist_ok=True)
        save_library(list(merged.values()), target, category)
        self.w.library_dock.reload()
        index = self.w.library_dock.source.findData(str(target))
        if index >= 0:
            self.w.library_dock.source.setCurrentIndex(index)
        without = [d.name for d in chosen if not d.connection_points()]
        parts = [
            self.tr("{n} Symbole nach {file} importiert").format(n=len(chosen), file=target.name)
        ]
        if result.units != "mm":
            unit = QCoreApplication.translate("dxf", result.units)
            parts.append(self.tr("Einheit {u} in mm umgerechnet").format(u=unit))
        if result.skipped:
            skipped = ", ".join(f"{k} ({v})" for k, v in sorted(result.skipped.items()))
            parts.append(self.tr("übersprungen: {s}").format(s=skipped))
        if without:
            parts.append(self.tr("ohne Anschlusspunkte: {n}").format(n=len(without)))
        self.w.message("; ".join(parts))
        return target

    def import_library(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self.w,
            self.tr("Bibliothek importieren"),
            self.w.last_dir(),
            self.tr("SLDGridy-Bibliothek (*{suffix})").format(suffix=LIBRARY_SUFFIX),
        )
        if not name:
            return
        source = Path(name)
        try:
            load_library(source)
        except (OSError, FileFormatError) as exc:
            QMessageBox.critical(self.w, self.tr("Bibliothek"), str(exc))
            return
        target = user_library_dir() / source.name
        if target.exists() and not target.samefile(source):
            answer = QMessageBox.question(
                self.w,
                self.tr("Bibliothek"),
                self.tr("{name} gibt es in der Benutzerbibliothek schon. Ersetzen?").format(
                    name=source.name
                ),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target.exists() and target.samefile(source)):
            shutil.copyfile(source, target)
        self.w.remember_dir(source)
        self.w.library_dock.reload()
        self.w.message(self.tr("Bibliothek {name} importiert").format(name=source.name))

    def export_library(self) -> None:
        if not self.doc.blocks:
            self.w.message(self.tr("Die Zeichnung enthält keine Blöcke"))
            return
        dialog = BlockChooserDialog(
            self.doc.blocks, self.tr("Blöcke exportieren"), self.w, multi=True
        )
        if dialog.exec() != BlockChooserDialog.DialogCode.Accepted or not dialog.selected_names():
            return
        name, _ = QFileDialog.getSaveFileName(
            self.w,
            self.tr("Bibliothek exportieren"),
            self.w.last_dir(),
            self.tr("SLDGridy-Bibliothek (*{suffix})").format(suffix=LIBRARY_SUFFIX),
        )
        if not name:
            return
        path = Path(name)
        if path.suffix != LIBRARY_SUFFIX:
            path = path.with_name(path.name + LIBRARY_SUFFIX)
        save_library(self._definitions_with_dependencies(dialog.selected_names()), path, path.stem)
        self.w.remember_dir(path)
        self.w.message(self.tr("Bibliothek {path} gespeichert").format(path=path))

    # -- clipboard ----------------------------------------------------------

    def clipboard_extra(self, entities: list[Entity]) -> dict:
        names = sorted({e.name for e in entities if isinstance(e, BlockReference)})
        if not names:
            return {}
        return {"blocks": [block_to_dict(d) for d in self._definitions_with_dependencies(names)]}

    def prepare_paste(self, payload: dict, entities: list[Entity]) -> bool:
        """Add block definitions the pasted references need. False to abort."""
        names = {e.name for e in entities if isinstance(e, BlockReference)}
        if not names:
            return True
        try:
            carried = {d.name: d for d in (block_from_dict(b) for b in payload.get("blocks", []))}
        except FileFormatError:
            carried = {}
        merged = {**carried, **self.doc.blocks}
        if self.in_editor() and would_create_cycle(self.editor_name(), entities, merged):
            self.w.message(self.tr("Ein Block kann sich nicht selbst enthalten"))
            return False
        missing = [n for n in carried if n not in self.doc.blocks]
        for n in missing:
            self._doc_push(AddBlockCommand(self.doc, carried[n], self.tr("Block anlegen")))
        unknown = [n for n in names if n not in self.doc.blocks]
        if unknown:
            self.w.message(
                self.tr("Unbekannte Blöcke: {names}").format(names=", ".join(sorted(unknown)))
            )
        return True


class _InsertAtCommand(QUndoCommand):
    """Insert entities at a given index (keeps the draw order when exploding)."""

    def __init__(self, container: EntityContainer, index: int, entities: list[Entity]) -> None:
        super().__init__("")
        self._container = container
        self._index = index
        self._entities = entities

    def redo(self) -> None:
        for offset, e in enumerate(self._entities):
            self._container.add(e, self._index + offset)

    def undo(self) -> None:
        for e in self._entities:
            self._container.remove(e.id)
