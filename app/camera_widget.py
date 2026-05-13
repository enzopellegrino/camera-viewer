import os
import cv2
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QSizePolicy
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QMutex, QMutexLocker
from PySide6.QtGui import QImage, QPixmap, QPainter, QCursor


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
        scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
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

    def run(self):
        self._running = True
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            self.error.emit("Impossibile aprire lo stream")
            return

        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break
            ret, frame = cap.read()
            if not ret:
                self.error.emit("Stream interrotto")
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
            self.frame_ready.emit(img)

        cap.release()

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
        self._thread.frame_ready.connect(self._on_frame)
        self._thread.error.connect(self._on_error)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_frame(self, img: QImage):
        if self._status_label.isVisible():
            self._status_label.hide()
        self._video.set_frame(img)

    def _on_error(self, message: str):
        self._status_label.setText(f"{message} — riconnessione...")
        self._status_label.show()
        self._status_label.setGeometry(0, 0, self.width(), self.height())

    def _on_thread_finished(self):
        if not self._reconnect_timer.isActive():
            self._reconnect_timer.start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)
        super().mousePressEvent(event)

    def stop(self):
        self._reconnect_timer.stop()
        if self._thread and self._thread.isRunning():
            self._thread.stop()
        self._thread = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._name_label.move(5, 5)
        self._name_label.raise_()
        self._status_label.setGeometry(0, 0, self.width(), self.height())

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)
