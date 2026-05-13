import hashlib
import uuid
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QDialogButtonBox, QLabel, QWidget, QHBoxLayout,
    QPushButton, QComboBox, QMessageBox,
)
from PySide6.QtCore import Qt

_STYLE = """
    QDialog { background: #1e1e1e; color: #ddd; }
    QLabel  { color: #aaa; }
    QLineEdit, QComboBox {
        background: #2a2a2a; color: #ddd; border: 1px solid #444;
        border-radius: 4px; padding: 6px 8px; font-size: 13px;
    }
    QLineEdit:focus, QComboBox:focus { border-color: #0066cc; }
    QPushButton {
        background: #2a2a2a; color: #ccc; border: 1px solid #444;
        border-radius: 4px; padding: 6px 16px; font-size: 12px; min-height: 28px;
    }
    QPushButton:hover    { background: #3a3a3a; }
    QPushButton:default  { background: #0066cc; color: white; border-color: #0088ff; }
    QPushButton:default:hover { background: #0077dd; }
"""

ROLES = ["admin", "operator", "viewer"]
ROLE_LABELS = {"admin": "Admin", "operator": "Operator", "viewer": "Viewer"}


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ─── Login dialog ─────────────────────────────────────────────────────────────

class AuthDialog(QDialog):
    def __init__(self, users: list[dict], parent=None):
        super().__init__(parent)
        self._users = users
        self._result_user: dict | None = None
        self.setWindowTitle("Accesso")
        self.setFixedWidth(320)
        self.setStyleSheet(_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(16)

        title = QLabel("Inserisci le credenziali per continuare.")
        title.setWordWrap(True)
        title.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)

        self._user_field = QLineEdit()
        self._user_field.setPlaceholderText("Utente")
        form.addRow("Utente:", self._user_field)

        self._pwd_field = QLineEdit()
        self._pwd_field.setEchoMode(QLineEdit.Password)
        self._pwd_field.setPlaceholderText("Password")
        self._pwd_field.returnPressed.connect(self._validate)
        form.addRow("Password:", self._pwd_field)

        layout.addLayout(form)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #e05555; font-size: 11px;")
        self._error.hide()
        layout.addWidget(self._error)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Accedi")
        ok.setDefault(True)
        ok.clicked.connect(self._validate)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        layout.addLayout(btns)

    def result_user(self) -> dict | None:
        return self._result_user

    def _validate(self):
        username = self._user_field.text().strip()
        password = self._pwd_field.text()
        user = next((u for u in self._users if u["username"] == username), None)
        if user and hash_password(password) == user.get("password_hash", ""):
            self._result_user = user
            self.accept()
        else:
            self._error.setText("Credenziali non valide.")
            self._error.show()
            self._pwd_field.clear()
            self._pwd_field.setFocus()


# ─── Create / Edit user dialog ────────────────────────────────────────────────

class UserEditDialog(QDialog):
    def __init__(self, user: dict | None = None, parent=None):
        super().__init__(parent)
        self._is_new = user is None
        self._original = user or {}
        self._user_id = self._original.get("id") or uuid.uuid4().hex[:8]
        self._original_hash = self._original.get("password_hash", "")
        self._original_prefs = self._original.get("preferences", {})

        self.setWindowTitle("Nuovo utente" if self._is_new else "Modifica utente")
        self.setMinimumWidth(380)
        self.setStyleSheet(_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self._username = QLineEdit(self._original.get("username", ""))
        self._username.setPlaceholderText("Nome utente")
        form.addRow("Utente:", self._username)

        self._role = QComboBox()
        for r in ROLES:
            self._role.addItem(ROLE_LABELS[r], r)
        cur = self._original.get("role", "viewer")
        idx = ROLES.index(cur) if cur in ROLES else 0
        self._role.setCurrentIndex(idx)
        form.addRow("Ruolo:", self._role)

        self._pwd_new = QLineEdit()
        self._pwd_new.setEchoMode(QLineEdit.Password)
        self._pwd_new.setPlaceholderText("Nuova password" if self._is_new else "Nuova password (lascia vuoto per non cambiare)")
        form.addRow("Password:", self._pwd_new)

        self._pwd_confirm = QLineEdit()
        self._pwd_confirm.setEchoMode(QLineEdit.Password)
        self._pwd_confirm.setPlaceholderText("Conferma password")
        form.addRow("Conferma:", self._pwd_confirm)

        layout.addLayout(form)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #e05555; font-size: 11px;")
        self._error.hide()
        layout.addWidget(self._error)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Salva")
        save.setDefault(True)
        save.clicked.connect(self._validate)
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

    def _validate(self):
        if not self._username.text().strip():
            self._show_error("Il nome utente non può essere vuoto.")
            return
        pwd = self._pwd_new.text()
        if self._is_new and not pwd:
            self._show_error("La password è obbligatoria.")
            return
        if pwd and pwd != self._pwd_confirm.text():
            self._show_error("Le password non coincidono.")
            return
        self.accept()

    def _show_error(self, msg: str):
        self._error.setText(msg)
        self._error.show()

    def result_user(self) -> dict:
        pwd = self._pwd_new.text()
        return {
            "id": self._user_id,
            "username": self._username.text().strip(),
            "password_hash": hash_password(pwd) if pwd else self._original_hash,
            "role": self._role.currentData(),
            "preferences": self._original_prefs,
        }
