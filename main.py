import sys
import os
import signal
import atexit
import tempfile
from pathlib import Path

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

from PySide6.QtWidgets import QApplication, QDialog

from app.config_manager import ConfigManager
from app.main_window import MainWindow
from app.license_manager import check_license, LicenseStatus
from app.license_dialog import LicenseDialog

_PID_FILE = Path(tempfile.gettempdir()) / "camera-viewer.pid"


def _kill_existing():
    if not _PID_FILE.exists():
        return
    try:
        pid = int(_PID_FILE.read_text().strip())
        if pid != os.getpid():
            os.kill(pid, signal.SIGTERM)
            import time; time.sleep(0.5)
    except (ProcessLookupError, ValueError, PermissionError, OSError):
        pass
    _PID_FILE.unlink(missing_ok=True)


def _write_pid():
    _PID_FILE.write_text(str(os.getpid()))


def _remove_pid():
    _PID_FILE.unlink(missing_ok=True)


def _config_path() -> Path:
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home())) / "Camera Viewer"
        else:
            base = Path.home() / "Library" / "Application Support" / "Camera Viewer"
        base.mkdir(parents=True, exist_ok=True)
        return base / "config.json"
    return Path("config.json")


def main():
    _kill_existing()
    _write_pid()
    atexit.register(_remove_pid)

    app = QApplication(sys.argv)
    app.setApplicationName("Camera Viewer")

    status = check_license()
    if status == LicenseStatus.TRIAL_EXPIRED:
        dlg = LicenseDialog(expired=True)
        if dlg.exec() != QDialog.Accepted:
            sys.exit(0)

    config = ConfigManager(_config_path())
    window = MainWindow(config)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
