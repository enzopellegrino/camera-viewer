import uuid
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QListWidget, QListWidgetItem, QPushButton, QLabel,
    QLineEdit, QComboBox, QDialogButtonBox, QMessageBox, QFormLayout,
)
from PySide6.QtCore import Qt, Signal

from .config_manager import ConfigManager
from .grid_widget import LAYOUTS
from .auth_dialog import UserEditDialog, ROLE_LABELS

_LAYOUTS = ["auto"] + list(LAYOUTS.keys())

_DIALOG_STYLE = """
    QDialog, QWidget { background: #1e1e1e; color: #dddddd; }
    QTabWidget::pane { border: 1px solid #3a3a3a; }
    QTabBar::tab { background: #2a2a2a; color: #aaa; padding: 6px 16px; }
    QTabBar::tab:selected { background: #0066cc; color: white; }
    QListWidget { background: #141414; border: 1px solid #333; alternate-background-color: #1a1a1a; }
    QListWidget::item:selected { background: #0055aa; }
    QLineEdit, QComboBox {
        background: #2a2a2a; color: #ddd; border: 1px solid #444; border-radius: 3px; padding: 4px 6px;
    }
    QPushButton {
        background: #2a2a2a; color: #ccc; border: 1px solid #444;
        border-radius: 4px; padding: 4px 12px; min-height: 26px;
    }
    QPushButton:hover { background: #3a3a3a; }
    QPushButton:pressed { background: #0066cc; }
    QLabel { color: #aaa; }
"""


# ─────────────────────────── Camera edit dialog ───────────────────────────

class _CameraEditDialog(QDialog):
    def __init__(self, camera: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifica telecamera" if camera else "Nuova telecamera")
        self.setMinimumWidth(440)
        self.setStyleSheet(_DIALOG_STYLE)
        self._id = (camera or {}).get("id") or uuid.uuid4().hex[:8]

        form = QFormLayout(self)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)

        self._name = QLineEdit((camera or {}).get("name", ""))
        self._name.setPlaceholderText("es. Ingresso principale")
        form.addRow("Nome:", self._name)

        self._url = QLineEdit((camera or {}).get("url", "rtsp://"))
        self._url.setPlaceholderText("rtsp://utente:password@192.168.1.x:554/stream")
        form.addRow("URL RTSP:", self._url)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _validate(self):
        if not self._name.text().strip():
            QMessageBox.warning(self, "Campo obbligatorio", "Inserisci un nome per la telecamera.")
            return
        if not self._url.text().strip():
            QMessageBox.warning(self, "Campo obbligatorio", "Inserisci l'URL RTSP.")
            return
        self.accept()

    def result_camera(self) -> dict:
        return {
            "id": self._id,
            "name": self._name.text().strip(),
            "url": self._url.text().strip(),
        }


# ─────────────────────────── Screen edit dialog ───────────────────────────

class _ScreenEditDialog(QDialog):
    def __init__(self, screen: dict | None, all_cameras: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifica schermata" if screen else "Nuova schermata")
        self.setMinimumSize(520, 460)
        self.setStyleSheet(_DIALOG_STYLE)
        self._all_cameras = all_cameras
        screen = screen or {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self._name = QLineEdit(screen.get("name", ""))
        self._name.setPlaceholderText("es. Vista interna")
        form.addRow("Nome schermata:", self._name)

        self._layout_combo = QComboBox()
        self._layout_combo.addItems(_LAYOUTS)
        current = screen.get("layout", "auto")
        idx = self._layout_combo.findText(current)
        self._layout_combo.setCurrentIndex(max(idx, 0))
        form.addRow("Layout:", self._layout_combo)

        layout.addLayout(form)
        layout.addWidget(QLabel("Seleziona e ordina le telecamere per questa schermata:"))

        lists_row = QHBoxLayout()

        avail_col = QVBoxLayout()
        avail_col.addWidget(QLabel("Disponibili"))
        self._avail = QListWidget()
        self._avail.setAlternatingRowColors(True)
        avail_col.addWidget(self._avail)

        btn_col = QVBoxLayout()
        btn_col.addStretch()
        for label, slot in [("→", self._move_to_selected), ("←", self._move_to_avail)]:
            b = QPushButton(label)
            b.setFixedWidth(34)
            b.clicked.connect(slot)
            btn_col.addWidget(b)
        btn_col.addStretch()

        sel_col = QVBoxLayout()
        sel_col.addWidget(QLabel("In schermata (trascina per riordinare)"))
        self._sel = QListWidget()
        self._sel.setAlternatingRowColors(True)
        self._sel.setDragDropMode(QListWidget.InternalMove)
        sel_col.addWidget(self._sel)

        ud_col = QVBoxLayout()
        ud_col.addStretch()
        for label, delta in [("▲", -1), ("▼", 1)]:
            b = QPushButton(label)
            b.setFixedWidth(28)
            b.clicked.connect(lambda _, d=delta: self._move_sel(d))
            ud_col.addWidget(b)
        ud_col.addStretch()

        lists_row.addLayout(avail_col)
        lists_row.addLayout(btn_col)
        lists_row.addLayout(sel_col)
        lists_row.addLayout(ud_col)
        layout.addLayout(lists_row, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._populate(screen.get("cameras", []))

    def _populate(self, selected_ids: list[str]):
        selected_set = set(selected_ids)
        for cam_id in selected_ids:
            cam = next((c for c in self._all_cameras if c["id"] == cam_id), None)
            if cam:
                self._sel.addItem(self._make_item(cam))
        for cam in self._all_cameras:
            if cam["id"] not in selected_set:
                self._avail.addItem(self._make_item(cam))

    @staticmethod
    def _make_item(cam: dict) -> QListWidgetItem:
        item = QListWidgetItem(f"{cam['name']}  [{cam['id']}]")
        item.setData(Qt.UserRole, cam["id"])
        return item

    def _move_to_selected(self):
        for item in self._avail.selectedItems():
            self._avail.takeItem(self._avail.row(item))
            self._sel.addItem(item)

    def _move_to_avail(self):
        for item in self._sel.selectedItems():
            self._sel.takeItem(self._sel.row(item))
            self._avail.addItem(item)

    def _move_sel(self, delta: int):
        row = self._sel.currentRow()
        new_row = row + delta
        if 0 <= new_row < self._sel.count():
            item = self._sel.takeItem(row)
            self._sel.insertItem(new_row, item)
            self._sel.setCurrentRow(new_row)

    def _validate(self):
        if not self._name.text().strip():
            QMessageBox.warning(self, "Campo obbligatorio", "Inserisci un nome per la schermata.")
            return
        self.accept()

    def result_screen(self) -> dict:
        ids = [self._sel.item(i).data(Qt.UserRole) for i in range(self._sel.count())]
        return {
            "name": self._name.text().strip(),
            "layout": self._layout_combo.currentText(),
            "cameras": ids,
        }


# ─────────────────────────── Main settings dialog ─────────────────────────

class SettingsDialog(QDialog):
    saved = Signal()

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Impostazioni")
        self.setMinimumSize(620, 520)
        self.setStyleSheet(_DIALOG_STYLE)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.addTab(self._build_cameras_tab(), "Telecamere")
        tabs.addTab(self._build_screens_tab(), "Schermate")
        tabs.addTab(self._build_users_tab(), "Utenti")
        root.addWidget(tabs)

        footer = QWidget()
        footer.setStyleSheet("background:#1a1a1a; border-top:1px solid #333;")
        hbox = QHBoxLayout(footer)
        hbox.setContentsMargins(12, 8, 12, 8)
        save_btn = QPushButton("Salva")
        save_btn.setDefault(True)
        cancel_btn = QPushButton("Annulla")
        save_btn.clicked.connect(self._save)
        cancel_btn.clicked.connect(self.reject)
        hbox.addStretch()
        hbox.addWidget(cancel_btn)
        hbox.addWidget(save_btn)
        root.addWidget(footer)

    # ── Cameras tab ──────────────────────────────────────────────────────

    def _build_cameras_tab(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(12, 12, 12, 8)
        vbox.setSpacing(8)

        self._cam_list = QListWidget()
        self._cam_list.setAlternatingRowColors(True)
        self._cam_list.itemDoubleClicked.connect(self._edit_camera)
        vbox.addWidget(self._cam_list)

        bar = QHBoxLayout()
        for label, slot in [("+ Aggiungi", self._add_camera),
                             ("Modifica", self._edit_camera),
                             ("Elimina", self._delete_camera)]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch()
        vbox.addLayout(bar)

        self._refresh_cameras()
        return w

    def _refresh_cameras(self):
        self._cam_list.clear()
        for cam in self.config.cameras:
            self._cam_list.addItem(QListWidgetItem(f"[{cam['id']}]  {cam['name']}  —  {cam['url']}"))

    def _add_camera(self):
        dlg = _CameraEditDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.config.cameras.append(dlg.result_camera())
            self._refresh_cameras()

    def _edit_camera(self):
        row = self._cam_list.currentRow()
        if row < 0:
            return
        dlg = _CameraEditDialog(self.config.cameras[row], parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.config.cameras[row] = dlg.result_camera()
            self._refresh_cameras()

    def _delete_camera(self):
        row = self._cam_list.currentRow()
        if row < 0:
            return
        cam_id = self.config.cameras[row]["id"]
        if QMessageBox.question(self, "Conferma", "Eliminare questa telecamera?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.config.cameras.pop(row)
        for scr in self.config.screens:
            scr["cameras"] = [c for c in scr.get("cameras", []) if c != cam_id]
        self._refresh_cameras()

    # ── Screens tab ──────────────────────────────────────────────────────

    def _build_screens_tab(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(12, 12, 12, 8)
        vbox.setSpacing(8)

        self._scr_list = QListWidget()
        self._scr_list.setAlternatingRowColors(True)
        self._scr_list.itemDoubleClicked.connect(self._edit_screen)
        vbox.addWidget(self._scr_list)

        bar = QHBoxLayout()
        for label, slot in [("+ Aggiungi", self._add_screen),
                             ("Modifica", self._edit_screen),
                             ("Elimina", self._delete_screen)]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            bar.addWidget(b)

        default_btn = QPushButton("★ Predefinita")
        default_btn.setToolTip("Imposta come schermata all'avvio")
        default_btn.clicked.connect(self._set_default_screen)
        bar.addWidget(default_btn)

        bar.addStretch()
        for label, delta in [("▲", -1), ("▼", 1)]:
            b = QPushButton(label)
            b.setFixedWidth(32)
            b.clicked.connect(lambda _, d=delta: self._move_screen(d))
            bar.addWidget(b)
        vbox.addLayout(bar)

        self._refresh_screens()
        return w

    def _refresh_screens(self):
        default_idx = self.config.settings.get("default_screen", 0)
        self._scr_list.clear()
        for i, scr in enumerate(self.config.screens):
            n = len(scr.get("cameras", []))
            marker = "★ " if i == default_idx else "    "
            self._scr_list.addItem(
                QListWidgetItem(f"{marker}{scr['name']}  [{scr.get('layout', 'auto')}]  —  {n} telecamere"))

    def _add_screen(self):
        dlg = _ScreenEditDialog(None, self.config.cameras, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.config.screens.append(dlg.result_screen())
            self._refresh_screens()

    def _edit_screen(self):
        row = self._scr_list.currentRow()
        if row < 0:
            return
        dlg = _ScreenEditDialog(self.config.screens[row], self.config.cameras, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.config.screens[row] = dlg.result_screen()
            self._refresh_screens()

    def _delete_screen(self):
        row = self._scr_list.currentRow()
        if row < 0:
            return
        if QMessageBox.question(self, "Conferma", "Eliminare questa schermata?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.config.screens.pop(row)
        self._refresh_screens()

    def _set_default_screen(self):
        row = self._scr_list.currentRow()
        if row < 0:
            return
        self.config.settings["default_screen"] = row
        self._refresh_screens()
        self._scr_list.setCurrentRow(row)

    def _move_screen(self, delta: int):
        row = self._scr_list.currentRow()
        new_row = row + delta
        if 0 <= new_row < len(self.config.screens):
            self.config.screens.insert(new_row, self.config.screens.pop(row))
            self._refresh_screens()
            self._scr_list.setCurrentRow(new_row)

    # ── Users tab ─────────────────────────────────────────────────────────

    def _build_users_tab(self) -> QWidget:
        w = QWidget()
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(12, 12, 12, 8)
        vbox.setSpacing(8)

        info = QLabel("Gestisci gli utenti che possono accedere all'applicazione.")
        info.setStyleSheet("color: #777; font-size: 11px;")
        vbox.addWidget(info)

        self._usr_list = QListWidget()
        self._usr_list.setAlternatingRowColors(True)
        self._usr_list.itemDoubleClicked.connect(self._edit_user)
        vbox.addWidget(self._usr_list)

        bar = QHBoxLayout()
        for label, slot in [("+ Aggiungi", self._add_user),
                             ("Modifica", self._edit_user),
                             ("Elimina", self._delete_user)]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch()
        vbox.addLayout(bar)

        self._refresh_users()
        return w

    def _refresh_users(self):
        self._usr_list.clear()
        for u in self.config.users:
            role_label = ROLE_LABELS.get(u.get("role", "viewer"), u.get("role", ""))
            self._usr_list.addItem(QListWidgetItem(f"{u['username']}  [{role_label}]"))

    def _add_user(self):
        dlg = UserEditDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.config.users.append(dlg.result_user())
            self._refresh_users()

    def _edit_user(self):
        row = self._usr_list.currentRow()
        if row < 0:
            return
        dlg = UserEditDialog(self.config.users[row], parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.config.users[row] = dlg.result_user()
            self._refresh_users()

    def _delete_user(self):
        row = self._usr_list.currentRow()
        if row < 0:
            return
        user = self.config.users[row]
        admins = [u for u in self.config.users if u.get("role") == "admin"]
        if user.get("role") == "admin" and len(admins) <= 1:
            QMessageBox.warning(self, "Operazione non consentita",
                                "Deve esserci almeno un amministratore.")
            return
        if QMessageBox.question(self, "Conferma", f"Eliminare l'utente «{user['username']}»?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.config.users.pop(row)
        self._refresh_users()

    # ── Save ─────────────────────────────────────────────────────────────

    def _save(self):
        self.config.save()
        self.saved.emit()
        self.accept()
