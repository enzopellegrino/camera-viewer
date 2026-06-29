"""Camera widget — embedded mpv backend.

Each camera runs a dedicated mpv process embedded into the Qt widget's
native X11 window via --wid=<XID>. mpv handles decode, network buffering
and GPU rendering (--vo=gpu, V3D). Video frames never pass through Python.

Why mpv instead of GStreamer:
  - Far more robust network buffering: absorbs VPN/internet jitter that made
    the GStreamer pipeline stutter ("ferma e va").
  - --vo=gpu uses the Pi 5 V3D GPU for scaling/render (glimagesink crashed
    under XWayland multi-widget; mpv embeds cleanly via --wid).
  - --hwdec=auto-safe uses HW decode where usable, SW fallback otherwise.

Qt runs in X11 mode (QT_QPA_PLATFORM=xcb); winId() returns a valid XID for
each child widget. For judder-free 25fps playback set the monitor to a
refresh that is a multiple of the source fps (1080p@50Hz).
"""
import os
import signal
import subprocess

from PySide6.QtWidgets import QWidget, QLabel, QSizePolicy
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QPixmap

_DEFAULT_FPS = 25  # kept for main.py settings compatibility


def _mpv_command(url: str, wid: int, passphrase: str = "", hw_decode: bool = False) -> list[str]:
    """Build the mpv command line for an embedded camera stream.

    Network caching (cache-secs) absorbs jitter for smooth playback; keep it
    modest so latency stays low. On a local LAN the cache drains instantly.
    """
    cmd = [
        "mpv",
        f"--wid={wid}",                      # embed into the Qt widget's X11 window
        "--no-config",                       # ignore user mpv config
        "--no-audio",
        "--no-osc",                          # no on-screen controls
        "--no-input-default-bindings",
        "--input-conf=/dev/null",
        "--input-cursor=no",                 # mpv must NOT capture mouse events → Qt handles them
        "--really-quiet",
        "--no-border",
        "--keepaspect=yes",
        "--vo=gpu",
        # hwdec set per-protocol and quality mode (see set_quality() below).
        # Grid mode: SW decode for all (no GPU contention, all cameras visible).
        # Fullscreen/focus mode: HW decode for the single focused camera (fluid).
        "--profile=low-latency",   # sets cache=no, readahead=0, sync=audio
        "--untimed",               # ignore PTS, render immediately
        "--video-sync=desync",     # no clock sync (no audio reference)
        "--framedrop=decoder+vo",  # drop late frames at decode AND VO stage
        "--cache=no",              # no local buffer: play live edge only
        "--demuxer-readahead-secs=0",
        "--vd-lavc-threads=1",
        "--network-timeout=10",
        # auto-reconnect on stream drop
        "--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=5",
    ]
    if url.startswith("rtsp://"):
        cmd.append("--rtsp-transport=tcp")

    if os.environ.get("CV_HWDEC_BACKEND") == "vaapi":
        # NUC / Intel Quick Sync: usa VAAPI sempre, anche in griglia.
        # Quick Sync gestisce 8+ stream H.264 in parallelo con CPU minima.
        # Nessuna limitazione di contesti GPU come sul Pi.
        cmd.append("--hwdec=vaapi")
    elif hw_decode:
        # Raspberry Pi 5 V3D: HW decode solo in zoom (EGL per DMABuf import).
        # GLX non può importare DMABuf → schermo blu senza gpu-context=x11egl.
        cmd += ["--hwdec=auto-safe", "--gpu-context=x11egl"]
    else:
        # Raspberry Pi 5: SW decode in griglia (risparmia contesti GPU limitati).
        cmd.append("--hwdec=no")
    if url.startswith("srt://") and passphrase:
        # mpv passes SRT options via the URL query string
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}passphrase={passphrase}&latency=500000"
    cmd.append(url)
    return cmd


class CameraWidget(QWidget):
    clicked = Signal(object)

    def __init__(
        self,
        camera_config: dict,
        reconnect_delay_ms: int = 5000,
        startup_delay_ms: int = 0,
        render_fps: int = _DEFAULT_FPS,  # API compat, unused
        parent=None,
    ):
        super().__init__(parent)
        self.camera_config = camera_config
        self._reconnect_delay_ms = reconnect_delay_ms
        self._startup_delay_ms = startup_delay_ms
        self._proc: subprocess.Popen | None = None
        self._started = False
        self._hw_decode = False  # SW decode in grid; HW when focused/fullscreen

        # Native X11 window so winId() is a real XID for mpv --wid.
        self.setAttribute(Qt.WA_NativeWindow)
        # WA_OpaquePaintEvent rimosso: con esso attivo paintEvent non viene
        # invocato correttamente su native X11 window → placeholder non visibile.
        self.setStyleSheet("background-color: #0d0d0d;")
        self.setMinimumSize(160, 90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(QCursor(Qt.PointingHandCursor))

        self._name_label = QLabel(camera_config.get("name", ""), self)
        self._name_label.setStyleSheet(
            "color: white; background: rgba(0,0,0,170);"
            "padding: 2px 8px; border-radius: 3px; font-size: 11px;"
        )
        self._name_label.adjustSize()
        self._name_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._status_label = QLabel("", self)
        self._status_label.setAlignment(Qt.AlignCenter | Qt.AlignBottom)
        self._status_label.setStyleSheet(
            "color: rgba(255,255,255,160); font-size: 11px; background: transparent;"
            "padding-bottom: 6px;"
        )
        self._status_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        # Placeholder image — mostrata quando lo stream non è attivo.
        # Path: stessa dir del config (CAMERA_VIEWER_CONFIG o ~/.config/camera-viewer/).
        cfg_env = os.environ.get("CAMERA_VIEWER_CONFIG", "")
        cfg_dir = os.path.dirname(cfg_env) if cfg_env else os.path.expanduser(
            "~/.config/camera-viewer")
        self._placeholder_path = os.path.join(cfg_dir, "placeholder.jpg")
        self._placeholder_pixmap: QPixmap | None = None
        self._show_placeholder_flag = False  # controlla paintEvent

        # Timer di riconnessione: usato da _check_process per ritardare il
        # restart dopo un drop dello stream. Named timer (non singleShot anonimo)
        # così stop() può cancellarlo (es. durante zoom).
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.setInterval(self._reconnect_delay_ms)
        self._reconnect_timer.timeout.connect(self._start_stream)

        # Polls the mpv process; restarts it if it exits (stream drop).
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(2000)
        self._watchdog.timeout.connect(self._check_process)

        # Periodic live-edge resync: restart mpv every 20 min to clear
        # accumulated network buffer lag. Brief reconnect (~1.5s), transparent
        # to the user. TCP buffering causes visible lag if left running for hours.
        _LAG_RESET_MS = 20 * 60 * 1000  # 20 minutes
        self._lag_reset_timer = QTimer(self)
        self._lag_reset_timer.setInterval(_LAG_RESET_MS)
        self._lag_reset_timer.timeout.connect(self._resync_live_edge)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if not self._started:
            self._started = True
            if self._startup_delay_ms > 0:
                QTimer.singleShot(self._startup_delay_ms, self._start_stream)
            else:
                self._start_stream()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

    # ── Placeholder image ─────────────────────────────────────────────────────
    # Usa paintEvent direttamente: i QLabel figlio non si vedono correttamente
    # su widget con WA_NativeWindow (finestra X11 reale usata da mpv).

    def _load_placeholder(self) -> None:
        """Carica (o ricarica) il placeholder dal disco."""
        if os.path.exists(self._placeholder_path):
            px = QPixmap(self._placeholder_path)
            if not px.isNull():
                self._placeholder_pixmap = px
                return
        self._placeholder_pixmap = None

    def _show_placeholder(self) -> None:
        self._load_placeholder()
        self._show_placeholder_flag = True
        self.update()   # richiede repaint → paintEvent disegna il logo
        self._status_label.raise_()

    def _hide_placeholder(self) -> None:
        self._show_placeholder_flag = False
        self.update()   # cancella il logo

    # ── mpv process ─────────────────────────────────────────────────────────────

    def _start_stream(self):
        url = self.camera_config.get("url", "").strip()
        if not url:
            # Riquadro senza telecamera: mostra solo il logo, nessun testo.
            self._status_label.hide()
            self._show_placeholder()
            return

        self._status_label.setText("Connessione...")
        self._status_label.show()
        self._status_label.setGeometry(0, 0, self.width(), self.height())
        self._show_placeholder()

        self._kill_proc()

        passphrase = self.camera_config.get("passphrase", "").strip()
        cmd = _mpv_command(url, int(self.winId()), passphrase, self._hw_decode)

        # New session so we can kill the whole mpv process group cleanly.
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # mpv paints over the widget once it has the first frame.
        QTimer.singleShot(1500, self._status_label.hide)
        QTimer.singleShot(1500, self._hide_placeholder)
        self._watchdog.start()
        self._lag_reset_timer.start()

    def _resync_live_edge(self):
        """Kill and restart mpv to clear accumulated network buffer lag.

        Called every 20 minutes. mpv accumulates TCP buffer delay over hours
        even with --cache=no; restarting resets the live edge instantly.
        The reconnect takes ~1.5s (same as a normal stream reconnect).
        Does nothing if the stream is currently stopped (e.g. widget hidden).
        """
        if self._proc is not None:
            self._start_stream()

    def _check_process(self):
        """Restart mpv if it exited (stream dropped / network error)."""
        if self._proc is not None and self._proc.poll() is not None:
            self._proc = None
            self._status_label.setText("Riconnessione...")
            self._status_label.show()
            self._status_label.setGeometry(0, 0, self.width(), self.height())
            self._show_placeholder()
            self._watchdog.stop()
            # Use self._reconnect_timer (a named QTimer that stop() can cancel).
            # DO NOT use QTimer.singleShot — those anonymous timers cannot be
            # cancelled by stop(), causing cameras to restart after zoom.
            # Lazy init: crea il timer se __init__ non l'ha fatto (race/pyc issue).
            if not hasattr(self, '_reconnect_timer'):
                self._reconnect_timer = QTimer(self)
                self._reconnect_timer.setSingleShot(True)
                self._reconnect_timer.setInterval(self._reconnect_delay_ms)
                self._reconnect_timer.timeout.connect(self._start_stream)
            self._reconnect_timer.start()

    def _kill_proc(self):
        """Send SIGTERM and release the reference — do NOT block waiting.

        Blocking wait() on 9 simultaneous kills freezes the Qt main thread
        for up to 27s, causing timers to fire and cameras to restart.
        The OS reaps the process; the 500ms zoom delay gives mpv time to die.
        """
        self._watchdog.stop()
        if self._proc is not None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            self._proc = None  # release reference; OS handles cleanup

    # ── Public API (used by main.py) ──────────────────────────────────────────

    def set_quality(self, high: bool):
        """Switch between grid quality (SW decode) and focus quality (HW decode).

        Called by grid_widget when the user clicks to zoom in/out. Always
        starts the stream (even if stopped) with the new hwdec setting.
        """
        self._hw_decode = high
        self._start_stream()  # always start, regardless of current proc state

    def request_stop(self):
        self._reconnect_timer.stop()
        self._watchdog.stop()
        self._lag_reset_timer.stop()
        self._kill_proc()

    def wait_stop(self):
        self._reconnect_timer.stop()
        self._lag_reset_timer.stop()
        self._kill_proc()

    def stop(self):
        self._reconnect_timer.stop()
        self._watchdog.stop()
        self._lag_reset_timer.stop()
        self._kill_proc()

    # ── Qt events ─────────────────────────────────────────────────────────────

    def mouseDoubleClickEvent(self, event):
        """Doppio click → zoom in/out (più intuitivo del singolo click)."""
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        """Disegna il placeholder logo quando lo stream non è attivo."""
        super().paintEvent(event)
        if self._show_placeholder_flag and self._placeholder_pixmap:
            from PySide6.QtGui import QPainter
            painter = QPainter(self)
            scaled = self._placeholder_pixmap.scaled(
                self.width(), self.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._name_label.move(5, 5)
        self._name_label.raise_()
        self._status_label.setGeometry(0, 0, self.width(), self.height())
        if self._show_placeholder_flag:
            self.update()  # ridisegna il placeholder alla nuova dimensione
        # mpv tracks the embedding window size automatically via --wid.
