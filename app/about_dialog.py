import sys
from pathlib import Path
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


def _read_version() -> str:
    for p in [Path(__file__).resolve().parent.parent / "VERSION",
              Path(sys.argv[0]).resolve().parent / "VERSION"]:
        if p.exists():
            return p.read_text().strip()
    return "0.0.0"


APP_VERSION = _read_version()

_STYLE = """
    QDialog { background: #1e1e1e; color: #ddd; }
    QLabel  { color: #aaa; }
"""


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Informazioni")
        self.setFixedWidth(340)
        self.setStyleSheet(_STYLE)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(6)

        # App icon — works both in dev and PyInstaller bundle
        base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
        icon_path = base / "app" / "icon_128.png" if getattr(sys, "frozen", False) else Path(__file__).parent / "icon_128.png"
        if icon_path.exists():
            pix = QPixmap(str(icon_path)).scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_lbl = QLabel()
            icon_lbl.setPixmap(pix)
            icon_lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(icon_lbl)
            layout.addSpacing(4)

        name = QLabel("Camera Viewer")
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold;")
        layout.addWidget(name)

        version = QLabel(f"Versione {APP_VERSION}")
        version.setAlignment(Qt.AlignCenter)
        version.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(version)

        layout.addSpacing(16)

        def _row(label: str, value: str, link: str | None = None):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #555; font-size: 12px; min-width: 60px;")
            val = QLabel(f'<a href="{link}" style="color:#4a9eff;">{value}</a>' if link else value)
            val.setStyleSheet("color: #ccc; font-size: 12px;")
            if link:
                val.setOpenExternalLinks(True)
            row.addWidget(lbl)
            row.addWidget(val)
            row.addStretch()
            layout.addLayout(row)

        _row("Sviluppatore:", "Enzo Pellegrino")
        _row("Email:", "enzo@n1computer.it", "mailto:enzo@n1computer.it")

        layout.addSpacing(20)

        copy = QLabel("© 2025 Enzo Pellegrino. Tutti i diritti riservati.")
        copy.setAlignment(Qt.AlignCenter)
        copy.setWordWrap(True)
        copy.setStyleSheet("color: #444; font-size: 10px;")
        layout.addWidget(copy)

        layout.addSpacing(12)

        btn = QPushButton("Chiudi")
        btn.setFixedWidth(80)
        btn.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: #ccc; border: 1px solid #444;
                border-radius: 4px; padding: 6px 16px; font-size: 12px; min-height: 28px;
            }
            QPushButton:hover { background: #3a3a3a; }
        """)
        btn.clicked.connect(self.accept)
        row_btn = QHBoxLayout()
        row_btn.addStretch()
        row_btn.addWidget(btn)
        layout.addLayout(row_btn)
