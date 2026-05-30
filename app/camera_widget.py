"""Camera widget — GstVideoOverlay architecture.

Video frames NEVER pass through Python. GStreamer decodes and renders
directly into the Qt widget's native X11 window via GstVideoOverlay.
Python only handles events (click, resize) and pipeline control (start,
stop, reconnect). CPU usage drops from ~300% to ~5-10% per stream.

Requires: gstreamer1.0-x, gir1.2-gstvideo-1.0
Qt must run in X11 mode: QT_QPA_PLATFORM=xcb (via XWayland on Wayland desktops)
"""
import os

import gi
gi.require_version('Gst', '1.0')
gi.require_version('GstVideo', '1.0')
from gi.repository import Gst, GstVideo

from PySide6.QtWidgets import QWidget, QLabel, QSizePolicy
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCursor

Gst.init(None)

_DEFAULT_FPS = 25  # used only by main.py for the render_fps setting


def _make_pipeline(url: str) -> str:
    """GStreamer pipeline: RTSP H.264 → SW decode → xvimagesink.

    avdec_h264 max-threads=1 limits decode threads so 8 simultaneous streams
    don't overwhelm the scheduler.  Video goes directly to the X11 window via
    GstVideoOverlay — zero frame copies in Python.
    H.264 is lighter to decode than H.265 and produces no artifacts under load.
    """
    return (
        f'rtspsrc location="{url}" protocols=udp latency=100 '
        f'do-retransmission=false ! '
        'rtph264depay ! h264parse ! avdec_h264 max-threads=2 ! '
        'queue max-size-buffers=1 leaky=downstream ! '
        'videoconvert ! xvimagesink name=videosink sync=false force-aspect-ratio=true'
    )


class CameraWidget(QWidget):
    clicked = Signal(object)

    def __init__(
        self,
        camera_config: dict,
        reconnect_delay_ms: int = 5000,
        startup_delay_ms: int = 0,
        render_fps: int = _DEFAULT_FPS,  # kept for API compatibility, unused here
        parent=None,
    ):
        super().__init__(parent)
        self.camera_config = camera_config
        self._reconnect_delay_ms = reconnect_delay_ms
        self._startup_delay_ms = startup_delay_ms
        self._pipeline = None
        self._started = False

        # WA_NativeWindow is essential: ensures Qt creates a real X11 window
        # so winId() returns a valid XID that GStreamer can render into.
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
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

        self._status_label = QLabel("In attesa...", self)
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet(
            "color: #888; font-size: 13px; background: transparent;"
        )
        self._status_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.setInterval(reconnect_delay_ms)
        self._reconnect_timer.timeout.connect(self._start_stream)

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

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def _start_stream(self):
        url = self.camera_config.get("url", "").strip()
        if not url:
            self._status_label.setText("Nessun URL")
            self._status_label.show()
            return

        self._status_label.setText("Connessione...")
        self._status_label.show()
        self._status_label.setGeometry(0, 0, self.width(), self.height())

        self._cleanup_pipeline()

        self._pipeline = Gst.parse_launch(_make_pipeline(url))

        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        # sync-message is needed to intercept the window-handle request
        # before the pipeline tries to create its own window.
        bus.enable_sync_message_emission()
        bus.connect("sync-message::element", self._on_sync_message)
        bus.connect("message", self._on_bus_message)

        self._pipeline.set_state(Gst.State.PLAYING)

    def _on_sync_message(self, bus, msg):
        """GStreamer asks for the native window handle — give it our XID."""
        if GstVideo.is_video_overlay_prepare_window_handle_message(msg):
            msg.src.set_window_handle(int(self.winId()))
            self._status_label.hide()

    def _on_bus_message(self, bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, _ = msg.parse_error()
            self._status_label.setText("Stream interrotto — riconnessione...")
            self._status_label.show()
            self._status_label.setGeometry(0, 0, self.width(), self.height())
            self._cleanup_pipeline()
            self._reconnect_timer.start()
        elif msg.type == Gst.MessageType.EOS:
            self._cleanup_pipeline()
            self._reconnect_timer.start()

    def _cleanup_pipeline(self):
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None

    # ── Public API (used by main.py) ──────────────────────────────────────────

    def request_stop(self):
        self._reconnect_timer.stop()
        if self._pipeline:
            self._pipeline.set_state(Gst.State.PAUSED)

    def wait_stop(self):
        self._cleanup_pipeline()

    def stop(self):
        self._reconnect_timer.stop()
        self._cleanup_pipeline()

    # ── Qt events ─────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._name_label.move(5, 5)
        self._name_label.raise_()
        self._status_label.setGeometry(0, 0, self.width(), self.height())
        # Inform GStreamer of the new geometry so it can rescale
        if self._pipeline:
            sink = self._pipeline.get_by_name("videosink")
            if sink and hasattr(sink, "set_window_handle"):
                sink.set_window_handle(int(self.winId()))
