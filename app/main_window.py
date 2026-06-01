import os
import platform
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDialog, QMessageBox
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QPainter, QColor, QFont

from .config_manager import ConfigManager
from .grid_widget import GridWidget, LAYOUTS
from .settings_dialog import SettingsDialog
from .auth_dialog import AuthDialog, ROLE_LABELS
from .about_dialog import AboutDialog
from .license_manager import check_license, LicenseStatus
from .license_dialog import TrialBanner


_TOOLBAR_STYLE = "background-color: #1a1a1a; border-bottom: 1px solid #2e2e2e;"


# ── Scene Switcher Bar ────────────────────────────────────────────────────────

_SWITCHER_BTN = """
    QPushButton {
        background: rgba(255,255,255,12%); color: #ccd;
        border: 1px solid rgba(255,255,255,18%); border-radius: 16px;
        padding: 0 18px; font-size: 13px; min-height: 32px; font-weight: 500;
    }
    QPushButton:hover { background: rgba(255,255,255,22%); color: #fff; }
    QPushButton:checked {
        background: #4f72f7; color: #fff;
        border-color: #6888f9;
    }
"""


class SceneSwitcherBar(QWidget):
    """Transparent overlay bar at the bottom showing available views.

    Appears on mouse movement, auto-hides after 3 s of inactivity.
    Only visible when there are 2+ screens configured.
    """

    screen_requested = Signal(int)   # emits index of the requested screen

    _BAR_H = 58
    _AUTO_HIDE_MS = 3000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)

        self._hbox = QHBoxLayout(self)
        self._hbox.setContentsMargins(20, 10, 20, 10)
        self._hbox.setSpacing(8)
        self._hbox.addStretch()
        self._hbox.addStretch()

        self._buttons: list[QPushButton] = []

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self._AUTO_HIDE_MS)
        self._hide_timer.timeout.connect(self.hide)

        self.hide()

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh(self, screens: list[dict], active_idx: int) -> None:
        """Rebuild buttons to match current screens list."""
        for btn in self._buttons:
            self._hbox.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

        insert_pos = 1  # after first stretch
        for i, screen in enumerate(screens):
            name = screen.get("name", f"Vista {i + 1}")
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(i == active_idx)
            btn.setStyleSheet(_SWITCHER_BTN)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self.screen_requested.emit(idx))
            self._hbox.insertWidget(insert_pos, btn)
            self._buttons.append(btn)
            insert_pos += 1

        self.setVisible(len(screens) >= 2)

    def set_active(self, idx: int) -> None:
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == idx)

    def show_temporary(self) -> None:
        """Show the bar and (re)start the auto-hide timer."""
        if len(self._buttons) < 2:
            return
        self.show()
        self.raise_()
        self._hide_timer.start()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Semi-transparent dark gradient background
        gradient_color = QColor(0, 0, 0, 200)
        painter.fillRect(self.rect(), gradient_color)
        painter.end()

_BTN_BASE = """
    QPushButton {{
        background: {bg}; color: {fg};
        border: 1px solid #3a3a3a; border-radius: 4px;
        padding: 0 {px}; font-size: 12px; min-height: 28px;
    }}
    QPushButton:hover {{ background: #3a3a3a; }}
    QPushButton:pressed {{ background: #005bb5; color: white; }}
    QPushButton:checked {{ background: #0066cc; color: white; border-color: #0088ff; }}
"""

_SCREEN_BTN = _BTN_BASE.format(bg="#252525", fg="#cccccc", px="14px")
_LAYOUT_BTN = _BTN_BASE.format(bg="#1f1f1f", fg="#aaaaaa", px="6px")


class MainWindow(QMainWindow):
    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self._current_idx = config.settings.get("default_screen", 0)
        self._screen_buttons: list[QPushButton] = []
        self._grid: GridWidget | None = None
        self._toolbar: QWidget | None = None
        self._root_vbox: QVBoxLayout | None = None
        self._current_user: dict | None = None
        self._single_cam_mode = False

        self._build_ui()
        self._setup_shortcuts()

        if self._is_kiosk():
            self._enter_kiosk()
        else:
            self._load_screen(self._current_idx)

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        self.setWindowTitle("Camera Viewer")
        self.setStyleSheet("background-color: #0a0a0a; color: white;")
        self.resize(1280, 720)

        root = QWidget()
        self.setCentralWidget(root)
        self._root_vbox = QVBoxLayout(root)
        self._root_vbox.setContentsMargins(0, 0, 0, 0)
        self._root_vbox.setSpacing(0)

        self._toolbar = self._build_toolbar()
        self._root_vbox.addWidget(self._toolbar)

        self._grid = GridWidget(
            self.config.settings.get("reconnect_delay_ms", 5000),
            self.config.settings.get("render_fps", 30),
        )
        self._grid.camera_clicked.connect(self._on_camera_clicked)
        self._grid.setMouseTracking(True)
        self._root_vbox.addWidget(self._grid, 1)

        # Scene switcher bar — floats over the bottom of the grid
        self._switcher = SceneSwitcherBar(root)
        self._switcher.screen_requested.connect(self._load_screen)
        self._switcher.raise_()

        self._start_cmd_watcher()
        self._refresh_switcher()

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        bar.setStyleSheet(_TOOLBAR_STYLE)
        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(10, 5, 10, 5)
        hbox.setSpacing(6)

        # Screen buttons — always visible
        self._screen_buttons.clear()
        for i, screen in enumerate(self.config.screens):
            btn = QPushButton(screen.get("name", f"Schermata {i + 1}"))
            btn.setCheckable(True)
            btn.setChecked(i == self._current_idx)
            btn.setStyleSheet(_SCREEN_BTN)
            btn.clicked.connect(lambda _checked, idx=i: self._load_screen(idx))
            hbox.addWidget(btn)
            self._screen_buttons.append(btn)

        hbox.addStretch()

        # Trial banner (hidden when licensed)
        if check_license() == LicenseStatus.TRIAL_ACTIVE:
            hbox.addWidget(TrialBanner())
            hbox.addSpacing(4)

        role = self._current_user.get("role") if self._current_user else None

        # Layout quick-switch — admin and operator
        if role in ("admin", "operator") or role is None:
            lbl = QLabel("Layout:")
            lbl.setStyleSheet("color: #777; font-size: 11px;")
            hbox.addWidget(lbl)
            for name in ["auto", "1x1", "1x2", "2x2", "3x2", "3x3", "4x4"]:
                btn = QPushButton(name)
                btn.setFixedWidth(48 if name == "auto" else 46)
                btn.setStyleSheet(_LAYOUT_BTN)
                btn.clicked.connect(lambda _checked, l=name: self._force_layout(l))
                hbox.addWidget(btn)
            hbox.addSpacing(8)

        # Auth badge — when logged in
        if self._current_user:
            username = self._current_user["username"]
            role_lbl = ROLE_LABELS.get(role, role)
            badge = QLabel(f"🔐 {username} · {role_lbl}")
            badge.setStyleSheet(
                "color: #ffaa00; font-size: 11px; padding: 0 8px;"
                "border: 1px solid #554400; border-radius: 3px; background: #2a2000;"
            )
            hbox.addWidget(badge)

            logout_btn = QPushButton("Esci")
            logout_btn.setFixedWidth(46)
            logout_btn.setToolTip("Chiudi sessione")
            logout_btn.setStyleSheet(_LAYOUT_BTN)
            logout_btn.clicked.connect(self._logout)
            hbox.addWidget(logout_btn)
            hbox.addSpacing(4)

        # Settings button — admin only
        if role == "admin" or role is None:
            cfg_btn = QPushButton("⚙")
            cfg_btn.setFixedWidth(34)
            cfg_btn.setToolTip("Impostazioni telecamere e schermate")
            cfg_btn.setStyleSheet(_LAYOUT_BTN)
            cfg_btn.clicked.connect(self._open_settings)
            hbox.addWidget(cfg_btn)

        # About button — always
        about_btn = QPushButton("ℹ")
        about_btn.setFixedWidth(34)
        about_btn.setToolTip("Informazioni")
        about_btn.setStyleSheet(_LAYOUT_BTN)
        about_btn.clicked.connect(lambda: AboutDialog(self).exec())
        hbox.addWidget(about_btn)

        # Fullscreen button — always
        fs_btn = QPushButton("⛶")
        fs_btn.setFixedWidth(34)
        fs_btn.setToolTip("Fullscreen  [F]")
        fs_btn.setStyleSheet(_LAYOUT_BTN)
        fs_btn.clicked.connect(self.toggle_fullscreen)
        hbox.addWidget(fs_btn)

        return bar

    def _rebuild_toolbar(self):
        toolbar_visible = self._toolbar.isVisible() if self._toolbar else True

        if self._toolbar:
            self._root_vbox.removeWidget(self._toolbar)
            self._toolbar.deleteLater()

        self._toolbar = self._build_toolbar()
        self._root_vbox.insertWidget(0, self._toolbar)
        self._toolbar.setVisible(toolbar_visible)
        self._setup_shortcuts()

    # ----------------------------------------------------------- shortcuts

    def _setup_shortcuts(self):
        for sc in self.findChildren(QShortcut):
            sc.setParent(None)

        QShortcut(QKeySequence("F"), self, self.toggle_fullscreen)
        QShortcut(QKeySequence("H"), self, self._toggle_toolbar)
        QShortcut(QKeySequence("Escape"), self, self._exit_fullscreen)
        QShortcut(QKeySequence("Q"), self, self.close)

        # ← → to switch views + show switcher bar
        QShortcut(QKeySequence(Qt.Key_Left),  self, self._prev_screen)
        QShortcut(QKeySequence(Qt.Key_Right), self, self._next_screen)

        for i in range(min(9, len(self.config.screens))):
            QShortcut(QKeySequence(str(i + 1)), self, lambda idx=i: self._load_screen(idx))

    # ----------------------------------------------------------- screen/layout

    def _load_screen(self, idx: int):
        self._current_idx = max(0, min(idx, len(self.config.screens) - 1))
        for i, btn in enumerate(self._screen_buttons):
            btn.setChecked(i == self._current_idx)

        if not self.config.screens:
            return
        screen_cfg = self.config.screens[self._current_idx]
        self._grid.load_screen(screen_cfg, self.config.camera_lookup())
        self._switcher.set_active(self._current_idx)

    def _prev_screen(self):
        n = len(self.config.screens)
        if n <= 1:
            return
        self._load_screen((self._current_idx - 1) % n)
        self._switcher.show_temporary()

    def _next_screen(self):
        n = len(self.config.screens)
        if n <= 1:
            return
        self._load_screen((self._current_idx + 1) % n)
        self._switcher.show_temporary()

    def _refresh_switcher(self):
        self._switcher.refresh(self.config.screens, self._current_idx)

    def _force_layout(self, layout: str):
        if not self.config.screens:
            return
        overridden = dict(self.config.screens[self._current_idx])
        overridden["layout"] = layout
        self._grid.load_screen(overridden, self.config.camera_lookup())

    # ----------------------------------------------------------- single cam

    # ── Portal IPC ────────────────────────────────────────────────────────────

    _CMD_FILE = "/tmp/cv-viewer-cmd"

    def _start_cmd_watcher(self):
        """Poll /tmp/cv-viewer-cmd for zoom commands from the portal.

        File content:
          "zoom:<camera_id>"  → zoom that camera
          "grid"              → return to grid
        """
        t = QTimer(self)
        t.setInterval(500)
        t.timeout.connect(self._check_cmd)
        t.start()

    def _check_cmd(self):
        try:
            if not os.path.exists(self._CMD_FILE):
                return
            cmd = open(self._CMD_FILE).read().strip()
            os.remove(self._CMD_FILE)
        except OSError:
            return

        if cmd == "grid":
            if self._single_cam_mode:
                QTimer.singleShot(0, self._exit_single_cam)
        elif cmd.startswith("zoom:"):
            cam_id = cmd[5:]
            if self._grid:
                for w in self._grid._widgets:
                    if w.camera_config.get("id") == cam_id:
                        if self._single_cam_mode:
                            QTimer.singleShot(0, self._exit_single_cam)
                            QTimer.singleShot(300, lambda widget=w: self._enter_single_cam(widget))
                        else:
                            QTimer.singleShot(0, lambda widget=w: self._enter_single_cam(widget))
                        break
        elif cmd.startswith("screen:"):
            # Switch to a named screen/view by id (from portal).
            # Reload config from disk first: portal may have added new screens
            # that ConfigManager doesn't know about yet (it caches on startup).
            self.config.load()
            screen_id = cmd[7:]
            screens = self.config.screens
            idx = next((i for i, s in enumerate(screens) if s.get("id") == screen_id), None)
            if idx is not None:
                if self._single_cam_mode:
                    QTimer.singleShot(0, self._exit_single_cam)
                # Rebuild toolbar and switcher to reflect current screens
                QTimer.singleShot(0, self._rebuild_toolbar)
                QTimer.singleShot(0, self._refresh_switcher)
                QTimer.singleShot(0, lambda i=idx: self._load_screen(i))

    def _on_camera_clicked(self, widget):
        if self._single_cam_mode:
            QTimer.singleShot(0, self._exit_single_cam)
        else:
            QTimer.singleShot(0, lambda: self._enter_single_cam(widget))

    def _enter_single_cam(self, widget):
        self._single_cam_mode = True
        self._grid.enter_single_cam(widget)
        if self._toolbar:
            self._toolbar.hide()

    def _exit_single_cam(self):
        self._single_cam_mode = False
        self._grid.exit_single_cam()
        if self._toolbar and not self._is_kiosk():
            self._toolbar.show()

    # ----------------------------------------------------------- settings / auth

    def _open_settings(self):
        if self._current_user is None:
            auth_dlg = AuthDialog(self.config.users, parent=self)
            if auth_dlg.exec() != QDialog.Accepted:
                return
            self._current_user = auth_dlg.result_user()
            self._rebuild_toolbar()

            if self._current_user.get("role") != "admin":
                QMessageBox.information(
                    self, "Accesso effettuato",
                    f"Accesso come «{self._current_user['username']}» ({ROLE_LABELS.get(self._current_user['role'], '')}).\n"
                    "Le impostazioni sono riservate agli amministratori."
                )
                return

        if self._current_user.get("role") != "admin":
            return

        dlg = SettingsDialog(self.config, parent=self)
        dlg.saved.connect(self._on_settings_saved)
        dlg.exec()

    def _on_settings_saved(self):
        self._rebuild_toolbar()
        self._load_screen(self._current_idx)

    def _logout(self):
        self._current_user = None
        self._rebuild_toolbar()

    # ----------------------------------------------------------- fullscreen / kiosk

    # ── Mouse / resize (scene switcher) ──────────────────────────────────────

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        # Show switcher only when mouse is in the lower 20% of the window
        if event.position().y() > self.height() * 0.75:
            self._switcher.show_temporary()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_switcher()

    def _position_switcher(self):
        w = self.centralWidget().width()
        h = self.centralWidget().height()
        bh = SceneSwitcherBar._BAR_H
        self._switcher.setGeometry(0, h - bh, w, bh)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            if self._toolbar:
                self._toolbar.show()
        else:
            self.showFullScreen()

    def _exit_fullscreen(self):
        if self._single_cam_mode:
            self._exit_single_cam()
        elif self.isFullScreen():
            self.showNormal()
            if self._toolbar:
                self._toolbar.show()

    def _toggle_toolbar(self):
        if self._toolbar:
            self._toolbar.setVisible(not self._toolbar.isVisible())

    def _enter_kiosk(self):
        self.showFullScreen()
        self.setCursor(Qt.BlankCursor)
        if self._toolbar:
            self._toolbar.hide()
        self._load_screen(self._current_idx)

    def _is_kiosk(self) -> bool:
        if self.config.settings.get("kiosk_mode", False):
            return True
        return self._is_raspberry_pi()

    # ----------------------------------------------------------- close

    def closeEvent(self, event):
        if self._grid:
            self._grid.stop_all()
        super().closeEvent(event)

    # ----------------------------------------------------------- helpers

    @staticmethod
    def _is_raspberry_pi() -> bool:
        try:
            with open("/proc/device-tree/model", "r") as f:
                return "Raspberry Pi" in f.read()
        except Exception:
            return False
