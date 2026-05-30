import os
import sys
import time
import cv2
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizePolicy
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QMutex, QMutexLocker
from PySide6.QtGui import QImage, QPixmap, QPainter, QCursor

_DEFAULT_FPS = 25

# Hardware decode via v4l2h264dec offloads the CPU for pure GStreamer pipelines
# (e.g. fakesink), but when frames must pass through Python (cap.read →
# cvtColor → QImage) the bottleneck is the Python processing, not the decode.
# In that case HW decode adds DMABuf↔system-memory transfer overhead and is
# slower than software decode.  Keep this False until the viewer moves to a
# GPU-composited pipeline that never copies frames into Python.
# Override with CAMERA_VIEWER_HWDEC=1 to experiment with hardware decode.
_USE_HWDEC = os.environ.get("CAMERA_VIEWER_HWDEC", "0") == "1"


def _gst_hw_pipeline(url: str) -> str:
    """GStreamer pipeline: RTSP H.264 -> hardware decode -> BGR -> appsink.

    v4l2h264dec outputs DMABuf memory; v4l2convert bridges to system memory
    (I420) so that videoconvert can then produce BGR for OpenCV.

    Requires gpu_mem >= 128 in /boot/firmware/config.txt — the bcm2835-codec
    VCHIQ component needs enough GPU RAM to initialise the hardware decoder.
    """
    return (
        f'rtspsrc location="{url}" protocols=tcp latency=200 drop-on-latency=true ! '
        "rtph264depay ! h264parse ! v4l2h264dec ! "
        "v4l2convert ! video/x-raw,format=I420 ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=2 sync=false"
    )


def _gst_sw_pipeline(url: str) -> str:
    """GStreamer pipeline: RTSP -> software H.264/H.265 decode -> BGR -> appsink.

    Uses avdec_h264 with max-threads=1 so that 8 simultaneous streams don't
    spawn 8×N decode threads competing for CPU.  Single-threaded avdec_h264
    is fast enough for 720p@25fps; the bottleneck is the Python/Qt rendering
    path, not the decoder.
    """
    return (
        f'rtspsrc location="{url}" protocols=tcp latency=200 drop-on-latency=true ! '
        "rtph264depay ! h264parse ! avdec_h264 max-threads=1 ! "
        "videoconvert ! video/x-raw,format=BGR ! "
        "appsink drop=true max-buffers=1 sync=false"
    )


# ─── Widget video con paintEvent ─────────────────────────────────────────────

class _VideoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.setStyleSheet("background-color: #0d0d0d;")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_frame(self, img: QImage):
        self._pixmap = QPixmap.fromImage(img)
        self.update()

    def paintEvent(self, event):
        if self._pixmap.isNull():
            return
        painter = QPainter(self)
        scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.FastTransformation)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)


# ─── Thread di lettura RTSP ──────────────────────────────────────────────────

class _StreamThread(QThread):
    frame_ready = Signal(QImage)
    error = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._running = False
        self._mutex = QMutex()
        # Latest decoded frame (as QImage), shared between capture loop and render timer.
        self._frame_mutex = QMutex()
        self._pending_frame: QImage | None = None

    def _open_capture(self):
        """Open the stream via GStreamer (HW or SW decode) or FFmpeg fallback."""
        if _USE_HWDEC:
            cap = cv2.VideoCapture(_gst_hw_pipeline(self._url), cv2.CAP_GSTREAMER)
            if cap.isOpened():
                return cap
            # Hardware path failed: fall through to software GStreamer pipeline.

        # Software decode via GStreamer (avdec_h264 max-threads=1).
        # Using GStreamer instead of CAP_FFMPEG gives explicit thread control:
        # FFmpeg through CAP_FFMPEG spawns cpu_count threads per stream by
        # default (4 on Pi 4), creating 32+ threads for 8 streams and causing
        # heavy OS scheduling overhead.
        cap = cv2.VideoCapture(_gst_sw_pipeline(self._url), cv2.CAP_GSTREAMER)
        if cap.isOpened():
            return cap

        # Last resort: FFmpeg (handles H.265 and other codecs automatically).
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    # How many consecutive read() failures before treating the stream as dead.
    # A single NULL sample from GStreamer is transient (e.g. key-frame boundary,
    # brief network glitch); we only reconnect after a sustained run of failures.
    _MAX_CONSECUTIVE_FAILURES = 40

    def run(self):
        self._running = True
        cap = self._open_capture()

        if not cap.isOpened():
            self.error.emit("Impossibile aprire lo stream")
            return

        consecutive_failures = 0
        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break
            ret, frame = cap.read()
            if not ret:
                consecutive_failures += 1
                if consecutive_failures >= self._MAX_CONSECUTIVE_FAILURES:
                    self.error.emit("Stream interrotto")
                    break
                # Transient glitch — brief pause to avoid a CPU spin loop,
                # then let the pipeline recover on its own.
                time.sleep(0.01)
                continue
            consecutive_failures = 0
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
            # Overwrite pending frame — older frames are dropped if the UI
            # render timer hasn't consumed them yet (runs at _DEFAULT_FPS).
            with QMutexLocker(self._frame_mutex):
                self._pending_frame = img

        cap.release()

    def take_frame(self) -> QImage | None:
        with QMutexLocker(self._frame_mutex):
            frame = self._pending_frame
            self._pending_frame = None
            return frame

    def stop(self):
        with QMutexLocker(self._mutex):
            self._running = False
        self.wait(3000)


# ─── Widget telecamera ───────────────────────────────────────────────────────

class CameraWidget(QWidget):
    clicked = Signal(object)

    def __init__(
        self,
        camera_config: dict,
        reconnect_delay_ms: int = 5000,
        startup_delay_ms: int = 0,
        render_fps: int = _DEFAULT_FPS,
        parent=None,
    ):
        super().__init__(parent)
        self.camera_config = camera_config
        self.reconnect_delay_ms = reconnect_delay_ms
        self._startup_delay_ms = startup_delay_ms
        self._started = False
        self._thread: _StreamThread | None = None

        self.setMinimumSize(160, 90)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background-color: #0d0d0d;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._video = _VideoWidget(self)
        layout.addWidget(self._video)

        self._name_label = QLabel(camera_config.get("name", ""), self)
        self._name_label.setStyleSheet(
            "color: white; background: rgba(0,0,0,170);"
            "padding: 2px 8px; border-radius: 3px; font-size: 11px;"
        )
        self._name_label.adjustSize()
        self._name_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._status_label = QLabel("In attesa...", self)
        self._status_label.setAlignment(Qt.AlignCenter)
        self._status_label.setStyleSheet("color: #555; font-size: 13px; background: transparent;")
        self._status_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.setCursor(QCursor(Qt.PointingHandCursor))

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.setInterval(reconnect_delay_ms)
        self._reconnect_timer.timeout.connect(self._start_stream)

        # UI refresh timer — pulls latest frame at TARGET_FPS, drops the rest
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(1000 // max(1, render_fps))
        self._render_timer.timeout.connect(self._pull_frame)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._started:
            self._started = True
            if self._startup_delay_ms > 0:
                QTimer.singleShot(self._startup_delay_ms, self._start_stream)
            else:
                self._start_stream()

    def _start_stream(self):
        url = self.camera_config.get("url", "").strip()
        if not url:
            self._status_label.setText("Nessun URL")
            self._status_label.setGeometry(0, 0, self.width(), self.height())
            return
        self._status_label.setText("Connessione...")
        self._status_label.show()
        self._status_label.setGeometry(0, 0, self.width(), self.height())
        self._thread = _StreamThread(url, self)
        self._thread.error.connect(self._on_error)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()
        self._render_timer.start()

    def _pull_frame(self):
        if self._thread is None:
            return
        img = self._thread.take_frame()
        if img is not None:
            if self._status_label.isVisible():
                self._status_label.hide()
            self._video.set_frame(img)

    def _on_error(self, message: str):
        self._status_label.setText(f"{message} — riconnessione...")
        self._status_label.show()
        self._status_label.setGeometry(0, 0, self.width(), self.height())

    def _on_thread_finished(self):
        self._render_timer.stop()
        if not self._reconnect_timer.isActive():
            self._reconnect_timer.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def request_stop(self):
        """Signal the thread to stop without blocking. Call wait_stop() after."""
        self._render_timer.stop()
        self._reconnect_timer.stop()
        if self._thread and self._thread.isRunning():
            with QMutexLocker(self._thread._mutex):
                self._thread._running = False

    def wait_stop(self):
        """Wait for the thread to finish after request_stop()."""
        if self._thread:
            self._thread.wait(3000)
            self._thread = None

    def stop(self):
        self.request_stop()
        self.wait_stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._name_label.move(5, 5)
        self._name_label.raise_()
        self._status_label.setGeometry(0, 0, self.width(), self.height())

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
