import platform
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QDialog, QMessageBox
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut

from .config_manager import ConfigManager
from .grid_widget import GridWidget, LAYOUTS
from .settings_dialog import SettingsDialog
from .auth_dialog import AuthDialog, ROLE_LABELS
from .about_dialog import AboutDialog
from .license_manager import check_license, LicenseStatus
from .license_dialog import TrialBanner


_TOOLBAR_STYLE = "background-color: #1a1a1a; border-bottom: 1px solid #2e2e2e;"

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

        self._grid = GridWidget(self.config.settings.get("reconnect_delay_ms", 5000))
        self._grid.camera_clicked.connect(self._on_camera_clicked)
        self._root_vbox.addWidget(self._grid, 1)

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

    def _force_layout(self, layout: str):
        if not self.config.screens:
            return
        overridden = dict(self.config.screens[self._current_idx])
        overridden["layout"] = layout
        self._grid.load_screen(overridden, self.config.camera_lookup())

    # ----------------------------------------------------------- single cam

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
