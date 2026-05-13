from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QWidget,
)
from PySide6.QtCore import Qt

from .license_manager import activate_license, trial_days_remaining, TRIAL_DAYS

_STYLE = """
    QDialog, QWidget { background: #1a1a1a; color: #ddd; }
    QLabel  { color: #aaa; }
    QLineEdit {
        background: #2a2a2a; color: #ddd; border: 1px solid #444;
        border-radius: 4px; padding: 6px 8px; font-size: 13px;
    }
    QLineEdit:focus { border-color: #0066cc; }
    QPushButton {
        background: #2a2a2a; color: #ccc; border: 1px solid #444;
        border-radius: 4px; padding: 6px 16px; font-size: 12px; min-height: 28px;
    }
    QPushButton:hover    { background: #3a3a3a; }
    QPushButton:default  { background: #0066cc; color: white; border-color: #0088ff; }
    QPushButton:default:hover { background: #0077dd; }
"""


class LicenseDialog(QDialog):
    """Shown when trial expired. Also usable to activate a key anytime."""

    def __init__(self, expired: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Licenza Camera Viewer")
        self.setFixedWidth(420)
        self.setStyleSheet(_STYLE)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
            | Qt.WindowStaysOnTopHint
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(10)

        if expired:
            banner = QLabel("Il periodo di prova è scaduto.")
            banner.setStyleSheet(
                "color: #ff6060; font-size: 14px; font-weight: bold; padding: 8px;"
                "background: #2a1010; border-radius: 4px; border: 1px solid #552020;"
            )
            banner.setAlignment(Qt.AlignCenter)
            layout.addWidget(banner)
            layout.addSpacing(4)

        info = QLabel(
            "Inserisci la tua chiave di licenza lifetime per continuare ad usare Camera Viewer."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(info)

        layout.addSpacing(4)

        self._key_field = QLineEdit()
        self._key_field.setPlaceholderText("xxxxxxxx.xxxxxxxx")
        self._key_field.returnPressed.connect(self._activate)
        layout.addWidget(self._key_field)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #e05555; font-size: 11px;")
        self._error.hide()
        layout.addWidget(self._error)

        layout.addSpacing(8)

        btns = QHBoxLayout()
        btns.addStretch()
        if not expired:
            cancel = QPushButton("Annulla")
            cancel.clicked.connect(self.reject)
            btns.addWidget(cancel)
        activate_btn = QPushButton("Attiva licenza")
        activate_btn.setDefault(True)
        activate_btn.clicked.connect(self._activate)
        btns.addWidget(activate_btn)
        layout.addLayout(btns)

        if expired:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)

    def _activate(self):
        key = self._key_field.text().strip()
        if not key:
            self._show_error("Inserisci una chiave di licenza.")
            return
        ok, msg = activate_license(key)
        if ok:
            self.accept()
        else:
            self._show_error(msg)

    def _show_error(self, msg: str):
        self._error.setText(msg)
        self._error.show()


class TrialBanner(QWidget):
    """Small inline banner shown in toolbar during trial."""

    def __init__(self, parent=None):
        super().__init__(parent)
        days = trial_days_remaining()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        color = "#ffaa00" if days > 2 else "#ff6060"
        lbl = QLabel(f"Trial: {days} giorn{'o' if days == 1 else 'i'} rimanent{'e' if days == 1 else 'i'}")
        lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; padding: 0 6px;"
            f"border: 1px solid {color}44; border-radius: 3px;"
        )
        layout.addWidget(lbl)

        btn = QPushButton("Attiva")
        btn.setFixedHeight(22)
        btn.setStyleSheet(
            "QPushButton { background: #252525; color: #aaa; border: 1px solid #3a3a3a;"
            "border-radius: 3px; padding: 0 8px; font-size: 10px; }"
            "QPushButton:hover { background: #3a3a3a; }"
        )
        btn.clicked.connect(self._open_activation)
        layout.addWidget(btn)

    def _open_activation(self):
        dlg = LicenseDialog(expired=False, parent=self.window())
        if dlg.exec() == QDialog.Accepted:
            # Rebuild toolbar to remove banner
            win = self.window()
            if hasattr(win, "_rebuild_toolbar"):
                win._rebuild_toolbar()
