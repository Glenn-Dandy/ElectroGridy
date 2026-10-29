"""A drawing area the canvas can show: model space, a sheet or a block in the editor."""

from dataclasses import dataclass, field

from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QTransform, QUndoStack
from PyQt6.QtWidgets import QGraphicsScene

from electrogridy.model.container import EntityContainer
from electrogridy.view.scene_sync import SceneSync

MODEL, SHEET, BLOCK = "model", "sheet", "block"


@dataclass
class Space:
    kind: str
    container: EntityContainer
    scene: QGraphicsScene
    sync: SceneSync
    stack: QUndoStack
    # Saved view (transform and centre) while another space is shown.
    view: tuple[QTransform, QPointF] | None = None
    extra: dict = field(default_factory=dict)

    def detach(self) -> None:
        self.sync.detach()
