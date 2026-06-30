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
from .license_manager import check_license, check_kiosk_license, LicenseStatus
from .license_dialog import TrialBanner


_TOOLBAR_STYLE = "background-color: #1a1a1a; border-bottom: 1px solid #2e2e2e;"


# ── License expired overlay (kiosk / NUC) ─────────────────────────────────────

class LicenseExpiredOverlay(QWidget):
    """Full-screen overlay shown when the kiosk license has expired.

    Shows the lock icon, the 'Licenza scaduta' message and the portal URL
    so the operator can connect via browser and enter a new license key.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: rgba(0,0,0,230);")

        vbox = QVBoxLayout(self)
        vbox.setAlignment(Qt.AlignCenter)
        vbox.setSpacing(16)
        vbox.setContentsMargins(40, 40, 40, 40)

        icon = QLabel("🔒")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 72px; background: transparent;")
        vbox.addWidget(icon)

        title = QLabel("Licenza scaduta")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #ff5c5c; font-size: 32px; font-weight: bold; background: transparent;"
        )
        vbox.addWidget(title)

        sub = QLabel(
            "Collega un dispositivo alla rete e accedi al portale per rinnovare la licenza:"
        )
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #aaa; font-size: 14px; background: transparent;")
        vbox.addWidget(sub)

        self._ip_label = QLabel("")
        self._ip_label.setAlignment(Qt.AlignCenter)
        self._ip_label.setStyleSheet(
            "color: #4fc8f7; font-size: 24px; font-weight: bold; font-family: monospace;"
            "background: #0a1a2a; border: 2px solid #4fc8f7; border-radius: 10px;"
            "padding: 12px 28px;"
        )
        vbox.addWidget(self._ip_label, alignment=Qt.AlignCenter)

        note = QLabel("Impostazioni → Licenza → inserisci la nuova chiave")
        note.setAlignment(Qt.AlignCenter)
        note.setStyleSheet("color: #666; font-size: 12px; background: transparent;")
        vbox.addWidget(note)

        self._update_ip()
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._update_ip)
        self._timer.start()

    def _update_ip(self):
        import subprocess
        try:
            raw = subprocess.check_output(["hostname", "-I"], timeout=2, text=True).strip()
            ip = raw.split()[0] if raw.split() else ""
            self._ip_label.setText(f"http://{ip}" if ip else "http://<ip-dispositivo>")
        except Exception:
            self._ip_label.setText("http://<ip-dispositivo>")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.parent():
            self.setGeometry(0, 0, self.parent().width(), self.parent().height())


# ── Scene Switcher Bar ────────────────────────────────────────────────────────

_SWITCHER_BTN = """
    QPushButton {
        background: rgba(255,255,255,12%); color: #ccd;
        border: 1px solid rgba(255,255,255,18%); border-radius: 16px;
        padding: 0 18px; font-size: 13px; min-height: 34px; font-weight: 500;
    }
    QPushButton:hover { background: rgba(255,255,255,22%); color: #fff; }
    QPushButton:checked {
        background: #4f72f7; color: #fff;
        border-color: #6888f9;
    }
"""

_HINT_STYLE = "color: rgba(255,255,255,40%); font-size: 11px;"
_IP_STYLE   = "color: rgba(79,200,247,80%); font-size: 11px; font-family: monospace;"


class SceneSwitcherBar(QWidget):
    """Overlay bar at the bottom showing available views.

    Always visible as a thin 6-px strip (with small dots indicating views).
    Expands to full height on any mouse movement over the main window.
    Auto-collapses after 3 s of inactivity.
    Only active when 2+ screens are configured.
    """

    screen_requested = Signal(int)

    _BAR_FULL = 60   # expanded height
    _BAR_MINI = 6    # collapsed strip height
    _AUTO_HIDE_MS = 3000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

        self._expanded = False
        self._screens: list[dict] = []
        self._active_idx = 0
        self._buttons: list[QPushButton] = []

        # Layout for the full-expanded state
        self._hbox = QHBoxLayout(self)
        self._hbox.setContentsMargins(20, 10, 20, 10)
        self._hbox.setSpacing(8)
        self._hbox.addStretch()
        self._hbox.addStretch()

        # "double-click to zoom" hint label
        self._hint = QLabel("↕ trascina mouse qui per le viste  ·  doppio click su telecamera per zoom")
        self._hint.setStyleSheet(_HINT_STYLE)
        self._hint.setAlignment(Qt.AlignCenter)
        self._hbox.insertWidget(1, self._hint)

        # Label IP portale — visibile quando la barra è espansa
        self._ip_label = QLabel("")
        self._ip_label.setStyleSheet(_IP_STYLE)
        self._ip_label.setAlignment(Qt.AlignCenter)
        self._ip_label.hide()
        self._hbox.addWidget(self._ip_label)

        # Aggiorna IP ogni 30 secondi
        self._ip_timer = QTimer(self)
        self._ip_timer.setInterval(30000)
        self._ip_timer.timeout.connect(self._update_ip)
        self._ip_timer.start()
        self._update_ip()

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(self._AUTO_HIDE_MS)
        self._collapse_timer.timeout.connect(self._collapse)

        # Start collapsed but visible
        self._set_expanded(False)

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh(self, screens: list[dict], active_idx: int) -> None:
        self._screens = screens
        self._active_idx = active_idx

        for btn in self._buttons:
            self._hbox.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

        # Remove hint label temporarily, rebuild, re-insert
        self._hbox.removeWidget(self._hint)

        insert_pos = 1
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

        # Add hint after buttons
        self._hbox.insertWidget(insert_pos, self._hint)

        # Only show if 2+ screens
        has_multi = len(screens) >= 2
        self.setVisible(has_multi)
        if not has_multi:
            return
        self._set_expanded(False)   # start collapsed

    def set_active(self, idx: int) -> None:
        self._active_idx = idx
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == idx)

    def _update_ip(self) -> None:
        """Aggiorna la label con l'IP del portale."""
        import subprocess
        try:
            ip = subprocess.check_output(
                ["hostname", "-I"], timeout=2, text=True
            ).strip().split()[0]
            self._ip_label.setText(f"🌐 http://{ip}")
        except Exception:
            self._ip_label.setText("")

    def expand_temporarily(self) -> None:
        """Show full-height bar and schedule collapse."""
        if len(self._screens) < 2:
            return
        self._set_expanded(True)
        self._collapse_timer.start()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _collapse(self):
        self._set_expanded(False)

    def _set_expanded(self, expanded: bool):
        self._expanded = expanded
        h = self._BAR_FULL if expanded else self._BAR_MINI
        # Resize keeping position (bottom of parent)
        if self.parent():
            pw = self.parent().width()
            ph = self.parent().height()
            self.setGeometry(0, ph - h, pw, h)
        for btn in self._buttons:
            btn.setVisible(expanded)
        self._hint.setVisible(not expanded)
        self._ip_label.setVisible(expanded and bool(self._ip_label.text()))
        self.update()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._expanded:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 210))
        else:
            # Thin strip: draw small dots for each view
            painter.fillRect(self.rect(), QColor(0, 0, 0, 140))
            n = len(self._screens)
            if n >= 2:
                dot_r = 3
                spacing = 12
                total = n * (dot_r * 2) + (n - 1) * spacing
                start_x = (self.width() - total) // 2
                y = self._BAR_MINI // 2
                for i in range(n):
                    x = start_x + i * (dot_r * 2 + spacing) + dot_r
                    if i == self._active_idx:
                        painter.setBrush(QColor(79, 114, 247))
                    else:
                        painter.setBrush(QColor(255, 255, 255, 80))
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(x - dot_r, y - dot_r, dot_r * 2, dot_r * 2)
        painter.end()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self.expand_temporarily()

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
        self._license_overlay: LicenseExpiredOverlay | None = None

        self._build_ui()
        self._setup_shortcuts()

        if self._is_kiosk():
            self._enter_kiosk()
        else:
            self._load_screen(self._current_idx)

        # Kiosk license check — runs only on Linux
        if platform.system() == "Linux":
            QTimer.singleShot(800, self._check_kiosk_license)
            self._lic_poll = QTimer(self)
            self._lic_poll.setInterval(3_600_000)   # ogni ora
            self._lic_poll.timeout.connect(self._check_kiosk_license)
            self._lic_poll.start()

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        self.setWindowTitle("Camera Viewer")
        self.setStyleSheet("background-color: #0a0a0a; color: white;")
        self.resize(1280, 720)

        root = QWidget()
        root.setMouseTracking(True)
        root.setAttribute(Qt.WA_AcceptTouchEvents, True)
        self.setMouseTracking(True)
        self.setCentralWidget(root)
        self._touch_start_x: float | None = None
        self._touch_start_y: float | None = None
        self._touch_is_swipe: bool = False   # True solo se il dito si è mosso intenzionalmente
        self._pinch_start_dist: float | None = None
        self._pinch_start_zoom: float = 0.0
        self._pinch_start_pan_x: float = 0.0
        self._pinch_start_pan_y: float = 0.0
        self._pinch_center_x: float = 0.0   # punto medio pinch, norm. [-0.5, 0.5]
        self._pinch_center_y: float = 0.0
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

        # Global wheel event filter: scroll anywhere → switch view
        from PySide6.QtWidgets import QApplication as _QApp
        _QApp.instance().installEventFilter(self)

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
        # In single-cam mode: telecamera precedente nella stessa vista
        if self._single_cam_mode and self._grid:
            self._grid.prev_single_cam()
            return
        n = len(self.config.screens)
        if n <= 1 or self._current_idx <= 0:
            return   # già alla prima vista, non ciclare
        self._load_screen(self._current_idx - 1)
        self._switcher.expand_temporarily()

    def _next_screen(self):
        # In single-cam mode: telecamera successiva nella stessa vista
        if self._single_cam_mode and self._grid:
            self._grid.next_single_cam()
            return
        n = len(self.config.screens)
        if n <= 1 or self._current_idx >= n - 1:
            return   # già all'ultima vista, non ciclare
        self._load_screen(self._current_idx + 1)
        self._switcher.expand_temporarily()

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
        elif cmd == "license:reload":
            QTimer.singleShot(0, self._check_kiosk_license)

    def _on_camera_clicked(self, widget):
        if self._single_cam_mode:
            QTimer.singleShot(0, self._exit_single_cam)
        else:
            QTimer.singleShot(0, lambda: self._enter_single_cam(widget))

    def _enter_single_cam(self, widget):
        self._single_cam_mode = True
        self._grid.enter_single_cam(widget)
        # Annulla il rilevamento swipe: il tap che ha aperto la cam
        # non deve essere interpretato come swipe al TouchEnd.
        self._touch_start_x = None
        self._pinch_start_dist = None
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

    def eventFilter(self, obj, event):
        """Cattura rotella del mouse e swipe touch → cambia vista."""
        from PySide6.QtCore import QEvent
        et = event.type()

        # ── Rotella del mouse ─────────────────────────────────────────────────
        if et == QEvent.Wheel and len(self.config.screens) > 1:
            delta = event.angleDelta().y()
            if delta > 0:
                self._prev_screen()
            elif delta < 0:
                self._next_screen()
            return True   # evento consumato

        # ── Touch: pinch (2 dita) e swipe (1 dito) ───────────────────────────
        if et == QEvent.TouchBegin:
            pts = event.points()
            # TouchBegin arriva sempre con 1 sola dita — registra solo lo swipe start.
            # Il secondo dito arriva nel primo TouchUpdate con len(pts)==2.
            self._pinch_start_dist = None
            self._touch_is_swipe = False
            if pts:
                self._touch_start_x = pts[0].position().x()
                self._touch_start_y = pts[0].position().y()
            return False

        if et == QEvent.TouchUpdate:
            pts = event.points()
            cam = self._grid._single if (self._grid and self._single_cam_mode) else None
            if len(pts) >= 2:
                mx = (pts[0].position().x() + pts[1].position().x()) / 2
                my = (pts[0].position().y() + pts[1].position().y()) / 2

                if self._pinch_start_dist is None:
                    # Secondo dito appena aggiunto: inizializza pinch
                    self._pinch_start_dist = self._touch_dist(pts[0], pts[1])
                    self._pinch_start_zoom = cam._video_zoom if cam else 0.0
                    self._pinch_start_pan_x = cam._video_pan_x if cam else 0.0
                    self._pinch_start_pan_y = cam._video_pan_y if cam else 0.0
                    self._pinch_center_x = mx
                    self._pinch_center_y = my
                    self._touch_start_x = None   # annulla swipe
                else:
                    dist = self._touch_dist(pts[0], pts[1])
                    if self._pinch_start_dist > 0:
                        import math
                        scale = dist / self._pinch_start_dist

                        if not self._single_cam_mode:
                            # Griglia: entra in single-cam quando pinch supera soglia
                            if scale > 1.3:
                                target = self._cam_widget_at(mx, my)
                                if target:
                                    self._enter_single_cam(target)
                                    cam = target
                                    # Inizializza zoom/pan dal punto corrente
                                    self._pinch_start_zoom = 0.0
                                    self._pinch_start_pan_x = 0.0
                                    self._pinch_start_pan_y = 0.0
                                    self._pinch_start_dist = dist
                        else:
                            # Single-cam: zoom + pan centrato sul punto di pizzico
                            if cam:
                                new_zoom = self._pinch_start_zoom + math.log2(max(scale, 0.01))
                                new_zoom = max(-1.0, min(4.0, new_zoom))
                                s = 2 ** (new_zoom - self._pinch_start_zoom)
                                w = max(cam.width(), 1)
                                h = max(cam.height(), 1)
                                cx = self._pinch_center_x / w - 0.5
                                cy = self._pinch_center_y / h - 0.5
                                pan_x = cx - (cx - self._pinch_start_pan_x) * s
                                pan_y = cy - (cy - self._pinch_start_pan_y) * s
                                cam.set_video_zoom(new_zoom, pan_x, pan_y)
            elif len(pts) == 1 and self._touch_start_x is not None:
                dx = pts[0].position().x() - self._touch_start_x
                dy = pts[0].position().y() - (self._touch_start_y or 0)
                # Marca come swipe solo se il dito si muove orizzontalmente in modo intenzionale
                if abs(dx) > 60 and abs(dx) > abs(dy) * 2.5:
                    self._touch_is_swipe = True
                if self._touch_is_swipe and len(self.config.screens) > 1:
                    self._switcher.expand_temporarily()
            return False

        if et == QEvent.TouchEnd:
            self._pinch_start_dist = None
            # Swipe valido solo se il flag è stato impostato durante TouchUpdate
            # (movimento orizzontale intenzionale rilevato in tempo reale).
            # Un tap non imposta mai _touch_is_swipe → nessun cambio vista accidentale.
            if self._touch_is_swipe and len(self.config.screens) > 1:
                pts = event.points()
                if pts and self._touch_start_x is not None:
                    delta_x = pts[0].position().x() - self._touch_start_x
                    if delta_x < 0:
                        self._next_screen()
                    else:
                        self._prev_screen()
                    self._touch_start_x = None
                    self._touch_start_y = None
                    self._touch_is_swipe = False
                    return True
            self._touch_start_x = None
            self._touch_start_y = None
            self._touch_is_swipe = False
            return False

        return False

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._switcher.expand_temporarily()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_switcher()
        if self._license_overlay:
            root = self.centralWidget()
            if root:
                self._license_overlay.setGeometry(0, 0, root.width(), root.height())

    def _position_switcher(self):
        # Let the bar reposition itself based on expanded state
        self._switcher._set_expanded(self._switcher._expanded)

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
        # Nasconde il cursore a livello di QApplication — sovrascrive qualsiasi
        # widget figlio e non viene resettato dagli eventi touch sintetici su X11.
        from PySide6.QtWidgets import QApplication as _QApp
        _QApp.setOverrideCursor(Qt.BlankCursor)
        if self._toolbar:
            self._toolbar.hide()
        self._load_screen(self._current_idx)

    def _is_kiosk(self) -> bool:
        if self.config.settings.get("kiosk_mode", False):
            return True
        return self._is_raspberry_pi()

    # ----------------------------------------------------------- kiosk license

    def _check_kiosk_license(self):
        """Show or hide the license expired overlay (Linux kiosk only)."""
        status = check_kiosk_license()
        root = self.centralWidget()
        if status == LicenseStatus.LICENSED:
            if self._license_overlay:
                self._license_overlay.hide()
                self._license_overlay.deleteLater()
                self._license_overlay = None
        else:
            if not self._license_overlay and root:
                self._license_overlay = LicenseExpiredOverlay(root)
                self._license_overlay.setGeometry(0, 0, root.width(), root.height())
                self._license_overlay.raise_()
                self._license_overlay.show()

    # ----------------------------------------------------------- close

    def closeEvent(self, event):
        if self._grid:
            self._grid.stop_all()
        super().closeEvent(event)

    # ----------------------------------------------------------- helpers

    def _cam_widget_at(self, x: float, y: float):
        """Ritorna il CameraWidget sotto il punto (x,y) in coordinate del widget root."""
        from PySide6.QtWidgets import QApplication
        from .camera_widget import CameraWidget
        root = self.centralWidget()
        if root is None:
            return None
        global_pos = root.mapToGlobal(root.rect().topLeft())
        # Converti in coordinate globali
        from PySide6.QtCore import QPoint
        gx = int(global_pos.x() + x)
        gy = int(global_pos.y() + y)
        widget = QApplication.widgetAt(gx, gy)
        # Risali finché non troviamo un CameraWidget
        while widget is not None:
            if isinstance(widget, CameraWidget):
                return widget
            widget = widget.parent()
        # Fallback: cerca nella lista dei widget del grid
        if self._grid:
            for w in self._grid._widgets:
                if w.geometry().contains(int(x), int(y)):
                    return w
        return None

    @staticmethod
    def _touch_dist(p1, p2) -> float:
        """Distanza euclidea tra due QEventPoint."""
        dx = p1.position().x() - p2.position().x()
        dy = p1.position().y() - p2.position().y()
        return (dx * dx + dy * dy) ** 0.5

    @staticmethod
    def _is_raspberry_pi() -> bool:
        try:
            with open("/proc/device-tree/model", "r") as f:
                return "Raspberry Pi" in f.read()
        except Exception:
            return False
