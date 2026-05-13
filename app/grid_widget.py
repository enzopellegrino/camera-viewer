import math
from PySide6.QtWidgets import QWidget, QGridLayout
from PySide6.QtCore import Signal
from .camera_widget import CameraWidget

LAYOUTS: dict[str, tuple[int, int]] = {
    "1x1": (1, 1),
    "1x2": (1, 2),
    "2x1": (2, 1),
    "2x2": (2, 2),
    "3x2": (3, 2),
    "2x3": (2, 3),
    "3x3": (3, 3),
    "4x4": (4, 4),
}


def auto_grid(n: int) -> tuple[int, int]:
    if n <= 0:
        return (1, 1)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return (rows, cols)


def resolve_layout(layout_str: str, n_cameras: int) -> tuple[int, int]:
    if layout_str == "auto":
        return auto_grid(n_cameras)
    return LAYOUTS.get(layout_str, auto_grid(n_cameras))


class GridWidget(QWidget):
    camera_clicked = Signal(object)  # CameraWidget

    def __init__(self, reconnect_delay_ms: int = 5000, render_fps: int = 30, parent=None):
        super().__init__(parent)
        self.reconnect_delay_ms = reconnect_delay_ms
        self.render_fps = render_fps
        self.setStyleSheet("background-color: #000000;")
        self._grid = QGridLayout(self)
        self._grid.setSpacing(2)
        self._grid.setContentsMargins(2, 2, 2, 2)
        self._widgets: list[CameraWidget] = []
        self._rows = 1
        self._cols = 1
        self._single: CameraWidget | None = None

    # ---------------------------------------------------------------- load

    def load_screen(self, screen_config: dict, camera_lookup: dict[str, dict]):
        self._exit_single_cam_internal()
        self._clear()

        camera_ids: list[str] = screen_config.get("cameras", [])
        self._rows, self._cols = resolve_layout(screen_config.get("layout", "auto"), len(camera_ids))

        for r in range(self._grid.rowCount()):
            self._grid.setRowStretch(r, 0)
        for c in range(self._grid.columnCount()):
            self._grid.setColumnStretch(c, 0)

        idx = 0
        for row in range(self._rows):
            self._grid.setRowStretch(row, 1)
            for col in range(self._cols):
                self._grid.setColumnStretch(col, 1)
                cfg = camera_lookup.get(camera_ids[idx]) if idx < len(camera_ids) else {}
                startup_delay = idx * 500
                widget = CameraWidget(cfg or {}, self.reconnect_delay_ms, startup_delay, self.render_fps, self)
                widget.clicked.connect(self.camera_clicked)
                self._grid.addWidget(widget, row, col)
                self._widgets.append(widget)
                idx += 1

    # ---------------------------------------------------------------- single cam

    def enter_single_cam(self, target: CameraWidget):
        if self._single is not None:
            return
        self._single = target
        self._grid.removeWidget(target)
        target.setParent(self)
        target.setGeometry(0, 0, self.width(), self.height())
        target.raise_()
        target.show()
        for w in self._widgets:
            if w is not target:
                w.hide()

    def exit_single_cam(self):
        self._exit_single_cam_internal()

    def _exit_single_cam_internal(self):
        if self._single is None:
            return
        target = self._single
        self._single = None
        idx = self._widgets.index(target)
        row = idx // self._cols
        col = idx % self._cols
        self._grid.addWidget(target, row, col)
        for w in self._widgets:
            w.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._single:
            self._single.setGeometry(0, 0, self.width(), self.height())

    # ---------------------------------------------------------------- stop / clear

    def stop_all(self):
        for w in self._widgets:
            w.stop()

    def _clear(self):
        for w in self._widgets:
            w.stop()
            w.setParent(None)
            w.deleteLater()
        self._widgets.clear()
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item and item.widget():
                item.widget().setParent(None)
