def _bootstrap():
    import subprocess
    import sys
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"])

_bootstrap()

"""Twitch Chat Downloader — Desktop app (PyQt6)."""
import csv
import os
import sys
import tempfile
import time
import webbrowser
from typing import Optional

import httpx

from PyQt6.QtCore import QRectF, Qt, QTimer, QUrl
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chat_downloader import extract_video_id, get_video_info
from worker import DownloadWorker
from l10n import tr

# ================================================================
#  Assets directory (for icons etc.)
# ================================================================
_BASE = os.path.dirname(os.path.abspath(__file__))
_ASSETS = os.path.join(_BASE, "assets")



# ================================================================
#  Circular progress widget
# ================================================================

class CircularProgress(QWidget):
    """Draws an animated circular progress indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 150)
        self._pct = 0
        self._sub_text = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._target = 0
        self._current = 0.0

    def set_value(self, pct: int, smooth: bool = True):
        self._target = min(pct, 100)
        if smooth:
            self._current = float(self._pct)
            self._timer.start(20)
        else:
            self._current = float(self._target)
            self._pct = self._target
            self.update()

    def _tick(self):
        diff = self._target - self._current
        if abs(diff) < 0.5:
            self._current = float(self._target)
            self._pct = self._target
            self._timer.stop()
        else:
            self._current += diff * 0.12
            self._pct = int(self._current)
        self.update()

    def set_sub_text(self, text: str):
        self._sub_text = text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        side = min(w, h) - 20
        x = (w - side) // 2
        y = (h - side) // 2
        rect = QRectF(x, y, side, side)

        # Background arc
        pen_bg = QPen(QColor("#2d3548"), 6)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_bg)
        painter.drawArc(rect, 0, 360 * 16)

        # Foreground arc
        if self._pct > 0:
            pen_fg = QPen(QColor("#7c5cfc"), 6)
            pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen_fg)
            angle = int(360 * self._pct / 100 * 16)
            painter.drawArc(rect, 90 * 16, -angle)

        # Percentage text
        painter.setPen(QColor("#e6edf3"))
        font_big = QFont("Segoe UI", 28, QFont.Weight.Bold)
        painter.setFont(font_big)
        painter.drawText(QRectF(0, h * 0.28, w, h * 0.35), Qt.AlignmentFlag.AlignCenter, f"{self._pct}%")

        # Sub text
        if self._sub_text:
            painter.setPen(QColor("#8b949e"))
            font_small = QFont("Segoe UI", 11)
            painter.setFont(font_small)
            painter.drawText(QRectF(0, h * 0.6, w, h * 0.3), Qt.AlignmentFlag.AlignCenter, self._sub_text)


# ================================================================
#  Main window
# ================================================================

class MainWindow(QMainWindow):
    TITLE = "Twitch Chat Downloader"
    WIDTH, HEIGHT = 540, 700

    def __init__(self):
        super().__init__()
        self._result = None  # last download result
        self._worker = None
        self._lang = "en"
        self._progress_start = 0.0
        self._preview_info = None
        # Download queue
        self._queue = []          # list of download tasks
        self._queue_id = 0        # unique id per queued item
        self._is_downloading = False

        # Debounce timer for URL validation
        self._url_check_timer = QTimer(self)
        self._url_check_timer.setSingleShot(True)
        self._url_check_timer.timeout.connect(self._on_url_check)

        # Debounce timer for queue URL validation
        self._queue_url_check_timer = QTimer(self)
        self._queue_url_check_timer.setSingleShot(True)
        self._queue_url_check_timer.timeout.connect(self._on_queue_url_check)

        self._setup_window()
        self._build_ui()
        self._apply_language()
        self._apply_styles()

    # ------------------------------------------------------------
    #  Window
    # ------------------------------------------------------------
    def _setup_window(self):
        self.setWindowTitle(self.TITLE)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setStyleSheet("""
            QMainWindow { background: #0d1117; }
            QWidget     { font-family: "Segoe UI", sans-serif; color: #e6edf3; }
        """)
        # App icon
        logo_path = os.path.join(_ASSETS, "logo.png")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))

    # ------------------------------------------------------------
    #  UI construction
    # ------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(28, 14, 28, 14)
        vbox.setSpacing(0)

        # --- header ---
        header = QFrame()
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(0, 0, 0, 6)
        self.lbl_logo = QLabel("")
        self.lbl_logo.setStyleSheet("font-size: 17px; font-weight: 600; color: #e6edf3;")
        hbox.addWidget(self.lbl_logo)
        hbox.addStretch()
        vbox.addWidget(header)

        # separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2d3548;")
        vbox.addWidget(sep)
        vbox.addSpacing(4)

        # --- card ---
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet("""
            #card {
                background: #1c2333;
                border: 1px solid #2d3548;
                border-radius: 14px;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 4, 16, 10)
        card_layout.setSpacing(0)
        vbox.addWidget(card, 0)

        # ---- Queue area (visible only during download) ----
        self._build_queue_ui()
        vbox.addWidget(self.queue_widget, 1)  # fills space when visible

        # Stretch spacer — fills space when queue is hidden, hidden alongside queue
        self._layout_spacer = QWidget()
        self._layout_spacer.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        vbox.addWidget(self._layout_spacer, 1)

        # ---- Step 1: Input ----
        self.step_input = QWidget()
        si_layout = QVBoxLayout(self.step_input)
        si_layout.setContentsMargins(0, 0, 0, 0)
        si_layout.setSpacing(6)

        title = QLabel("VOD Link")
        title.setStyleSheet("font-size: 15px; font-weight: 600; color: #e6edf3;")
        desc = QLabel("Paste a Twitch VOD URL to download its chat.")
        desc.setStyleSheet("font-size: 13px; color: #8b949e;")
        si_layout.addWidget(title)
        si_layout.addWidget(desc)
        self._lbl_vod_title = title
        self._lbl_vod_desc = desc

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.twitch.tv/videos/2796577649")
        self.url_input.setStyleSheet("""
            QLineEdit {
                background: #0d1117; border: 1px solid #2d3548;
                border-radius: 8px; padding: 10px 14px;
                font-size: 14px; color: #e6edf3;
            }
            QLineEdit:focus { border-color: #7c5cfc; }
        """)
        self.url_input.returnPressed.connect(self._on_download)
        self.url_input.textChanged.connect(self._on_url_text_changed)
        si_layout.addWidget(self.url_input)

        # ---- Video Preview (info after URL validation) ----
        self._preview_widget = QFrame()
        self._preview_widget.setObjectName("preview")
        self._preview_widget.setStyleSheet("""
            #preview {
                background: #0d1117; border: 1px solid #2d3548;
                border-radius: 10px;
            }
        """)
        self._preview_widget.setFixedHeight(120)
        self._preview_widget.hide()
        pw_layout = QHBoxLayout(self._preview_widget)
        pw_layout.setContentsMargins(5, 5, 0, 5)
        pw_layout.setSpacing(14)

        # Thumbnail (160x90, 5px padding top/bottom, rounded to match parent)
        self._preview_thumb = QLabel()
        self._preview_thumb.setFixedSize(160, 90)
        self._preview_thumb.setStyleSheet(
            "background: #1c2333; border-radius: 10px;")
        pw_layout.addWidget(self._preview_thumb)

        # Info column — vertically centered, fills the remaining space
        info_col = QVBoxLayout()
        info_col.setSpacing(1)
        info_col.setContentsMargins(0, 0, 10, 0)
        self._preview_title = QLabel("")
        self._preview_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #e6edf3;")
        self._preview_title.setWordWrap(True)
        self._preview_title.setFixedHeight(40)
        self._preview_channel = QLabel("")
        self._preview_channel.setStyleSheet("font-size: 12px; color: #8b949e;")
        self._preview_channel.setFixedHeight(18)
        self._preview_duration = QLabel("")
        self._preview_duration.setStyleSheet("font-size: 12px; color: #484f58;")
        self._preview_duration.setFixedHeight(18)
        info_col.addStretch()
        info_col.addWidget(self._preview_title)
        info_col.addWidget(self._preview_channel)
        info_col.addWidget(self._preview_duration)
        info_col.addStretch()
        pw_layout.addLayout(info_col, 1)

        # ---- Time range row (shown after preview loads) ----
        self._timerange_widget = QWidget()
        self._timerange_widget.hide()
        tr_layout = QHBoxLayout(self._timerange_widget)
        tr_layout.setContentsMargins(0, 0, 0, 0)
        tr_layout.setSpacing(6)

        time_edit_style = """
            QLineEdit {
                background: #0d1117; border: 1px solid #2d3548;
                border-radius: 6px; padding: 6px 8px;
                font-size: 13px; color: #e6edf3;
            }
            QLineEdit:focus { border-color: #7c5cfc; }
        """

        self._lbl_start = QLabel("Start:")
        self._lbl_start.setStyleSheet("font-size: 13px; color: #8b949e;")
        tr_layout.addWidget(self._lbl_start)
        self._input_start = QLineEdit()
        self._input_start.setPlaceholderText("00:00:00")
        self._input_start.setFixedWidth(80)
        self._input_start.setStyleSheet(time_edit_style)
        tr_layout.addWidget(self._input_start)

        tr_layout.addSpacing(4)

        self._lbl_end = QLabel("End:")
        self._lbl_end.setStyleSheet("font-size: 13px; color: #8b949e;")
        tr_layout.addWidget(self._lbl_end)
        self._input_end = QLineEdit()
        self._input_end.setPlaceholderText("00:00:00")
        self._input_end.setFixedWidth(80)
        self._input_end.setStyleSheet(time_edit_style)
        tr_layout.addWidget(self._input_end)

        tr_layout.addStretch()
        si_layout.addWidget(self._timerange_widget)

        # Threads control row
        threads_row = QHBoxLayout()
        threads_row.setSpacing(8)
        self._lbl_threads = QLabel("Threads:")
        self._lbl_threads.setStyleSheet("font-size: 13px; color: #8b949e;")
        threads_label = self._lbl_threads
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 16)
        self.threads_spin.setValue(4)
        self.threads_spin.setFixedWidth(60)
        self.threads_spin.setStyleSheet("""
            QSpinBox {
                background: #0d1117; border: 1px solid #2d3548;
                border-radius: 6px; padding: 4px 8px;
                font-size: 13px; color: #e6edf3;
            }
            QSpinBox:focus { border-color: #7c5cfc; }
            QSpinBox::up-button { width: 18px; }
            QSpinBox::down-button { width: 18px; }
        """)
        threads_row.addWidget(threads_label)
        threads_row.addWidget(self.threads_spin)
        threads_row.addStretch()
        si_layout.addLayout(threads_row)

        self.btn_download = QPushButton("  Download Chat")
        self.btn_download.setIcon(QIcon(os.path.join(_ASSETS, "download.svg")))
        self.btn_download.setEnabled(False)
        self.btn_download.setObjectName("btnPrimary")
        self.btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_download.setStyleSheet("""
            QPushButton {
                background: #7c5cfc; color: #fff; font-weight: 600;
                font-size: 14px; border: none; border-radius: 8px;
                padding: 10px 20px;
            }
            QPushButton:hover { background: #6a4de6; }
            QPushButton:disabled { background: #3d2e7a; color: #8b949e; }
        """)
        self.btn_download.clicked.connect(self._on_download)
        si_layout.addWidget(self.btn_download)

        card_layout.addWidget(self._preview_widget)   # shown across all steps
        card_layout.addWidget(self.step_input)

        # ---- Step 2: Progress ----
        self.step_progress = QWidget()
        sp_layout = QVBoxLayout(self.step_progress)
        sp_layout.setContentsMargins(0, 0, 0, 0)
        sp_layout.setSpacing(8)

        self._lbl_progress_title = QLabel("Downloading…")
        self._lbl_progress_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        sp_layout.addWidget(self._lbl_progress_title)

        # Ring + info
        ring_row = QHBoxLayout()
        ring_row.setSpacing(20)

        self.circular_progress = CircularProgress()
        ring_row.addWidget(self.circular_progress, alignment=Qt.AlignmentFlag.AlignCenter)

        info_col = QVBoxLayout()
        self.lbl_msgs = QLabel("")
        self.lbl_msgs.setStyleSheet("font-size: 14px; color: #8b949e;")
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("font-size: 13px; color: #484f58;")
        info_col.addWidget(self.lbl_msgs)
        info_col.addWidget(self.lbl_status)
        info_col.addStretch()
        ring_row.addLayout(info_col)

        sp_layout.addLayout(ring_row)

        # Progress action buttons: pause / resume + cancel
        progress_btn_row = QHBoxLayout()
        progress_btn_row.setSpacing(12)
        progress_btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_pause = QPushButton("⏸  Pause")
        self.btn_pause.setStyleSheet("""
            QPushButton {
                background: transparent; border: 1px solid #484f58;
                border-radius: 6px; padding: 6px 14px;
                font-size: 13px; color: #e6edf3;
            }
            QPushButton:hover { background: #222a3a; border-color: #7c5cfc; color: #7c5cfc; }
        """)
        self.btn_pause.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pause.clicked.connect(self._on_pause)
        progress_btn_row.addWidget(self.btn_pause)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("""
            QPushButton {
                background: transparent; border: 1px solid #484f58;
                border-radius: 6px; padding: 6px 14px;
                font-size: 13px; color: #8b949e;
            }
            QPushButton:hover { background: #222a3a; color: #f85149; border-color: #f85149; }
        """)
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._on_cancel)
        progress_btn_row.addWidget(self.btn_cancel)

        sp_layout.addLayout(progress_btn_row)

        self.step_progress.hide()
        card_layout.addWidget(self.step_progress)

        # ---- Step 3: Error ----
        self.step_error = QWidget()
        se_layout = QVBoxLayout(self.step_error)
        se_layout.setContentsMargins(0, 0, 0, 0)
        se_layout.setSpacing(10)

        err_box = QFrame()
        err_box.setStyleSheet("background: rgba(248,81,73,0.12); border: 1px solid rgba(248,81,73,0.25);"
                              "border-radius: 10px; padding: 14px 16px;")
        err_layout = QHBoxLayout(err_box)
        err_layout.setContentsMargins(14, 12, 14, 12)
        err_icon = QLabel("✕")
        err_icon.setStyleSheet("font-size: 20px; color: #f85149;")
        err_text_col = QVBoxLayout()
        self._lbl_err_title = QLabel("Error")
        self._lbl_err_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #f85149;")
        self.lbl_error = QLabel("")
        self.lbl_error.setStyleSheet("font-size: 13px; color: #8b949e;")
        self.lbl_error.setWordWrap(True)
        err_text_col.addWidget(self._lbl_err_title)
        err_text_col.addWidget(self.lbl_error)
        err_layout.addWidget(err_icon)
        err_layout.addLayout(err_text_col, 1)
        se_layout.addWidget(err_box)

        self.btn_retry = QPushButton("← Try again")
        self.btn_retry.setStyleSheet("""
            QPushButton { background: transparent; color: #8b949e; font-size: 13px;
                          border: none; padding: 8px 12px; border-radius: 6px; }
            QPushButton:hover { background: #222a3a; color: #e6edf3; }
        """)
        self.btn_retry.clicked.connect(self._reset_ui)
        se_layout.addWidget(self.btn_retry)

        self.step_error.hide()
        card_layout.addWidget(self.step_error)

        # ---- Step 4: Done ----
        self.step_done = QWidget()
        sd_layout = QVBoxLayout(self.step_done)
        sd_layout.setContentsMargins(0, 0, 0, 0)
        sd_layout.setSpacing(6)

        self._lbl_done_title = QLabel("✓  Chat Downloaded")
        self._lbl_done_title.setStyleSheet("font-size: 15px; font-weight: 600; color: #3fb950;")
        sd_layout.addWidget(self._lbl_done_title)

        self.done_info_title = QLabel("")
        self.done_info_title.setStyleSheet("font-size: 13px; color: #8b949e;")
        self.done_info_title.setWordWrap(True)
        sd_layout.addWidget(self.done_info_title)
        sd_layout.addSpacing(6)

        # Action buttons
        actions = QHBoxLayout()
        actions.setSpacing(8)

        def make_action(text, icon, obj_name):
            btn = QPushButton(f"{icon} {text}")
            btn.setObjectName(obj_name)
            btn.setStyleSheet("""
                QPushButton {
                    background: transparent; border: 1px solid #2d3548;
                    border-radius: 8px; padding: 9px 10px;
                    font-size: 13px; color: #e6edf3;
                }
                QPushButton:hover { background: #222a3a; border-color: #484f58; }
            """)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            return btn

        self.btn_txt = make_action("TXT", "📄", "btnTxt")
        self.btn_csv = make_action("CSV", "📊", "btnCsv")
        self.btn_web = make_action("Browser", "🌐", "btnWeb")
        self.btn_clear = make_action("Clear", "🗑", "btnClear")

        self.btn_txt.clicked.connect(self._export_txt)
        self.btn_csv.clicked.connect(self._export_csv)
        self.btn_web.clicked.connect(self._open_web)
        self.btn_clear.clicked.connect(self._clear)

        actions.addWidget(self.btn_txt)
        actions.addWidget(self.btn_csv)
        actions.addWidget(self.btn_web)
        actions.addWidget(self.btn_clear)
        sd_layout.addLayout(actions)

        self.step_done.hide()
        card_layout.addWidget(self.step_done)

        # ---- Footer ----
        vbox.addSpacing(8)
        footer_frame = QFrame()
        footer_frame.setObjectName("footer")
        footer_frame.setStyleSheet("""
            #footer {
                background: #151b24;
                border: 1px solid #2d3548;
                border-radius: 10px;
            }
        """)
        footer_inner = QHBoxLayout(footer_frame)
        footer_inner.setContentsMargins(14, 8, 14, 8)
        footer_inner.setSpacing(6)
        footer_inner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_powered = QLabel("")
        self.lbl_powered.setStyleSheet("font-size: 12px; color: #8b949e; font-weight: 600;")
        self.lbl_powered.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_powered.linkActivated.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/ZetHor3")))
        footer_inner.addWidget(self.lbl_powered)

        footer_inner.addSpacing(4)

        # Flag language switchers (painted directly — guaranteed to render)
        self._flag_labels = {}
        for code in ("en", "ru", "uk"):
            flag = QLabel()
            flag.setPixmap(self._make_flag_pixmap(code))
            flag.setToolTip(code.upper())
            flag.setFixedSize(32, 24)
            flag.setCursor(Qt.CursorShape.PointingHandCursor)
            flag.code = code
            flag.mousePressEvent = lambda _, c=code: self._set_lang(c)
            footer_inner.addWidget(flag)
            self._flag_labels[code] = flag

        footer_inner.addSpacing(4)

        # Support us link
        self.lbl_support = QLabel("")
        self.lbl_support.setStyleSheet("font-size: 12px;")
        self.lbl_support.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl_support.linkActivated.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://boosty.to/mr3ster/donate")))
        footer_inner.addWidget(self.lbl_support)

        vbox.addWidget(footer_frame)

    # ------------------------------------------------------------
    #  Queue UI
    # ------------------------------------------------------------
    def _build_queue_ui(self):
        """Build the download-queue input area (shown beneath the card during downloads)."""
        self.queue_widget = QWidget()
        self.queue_widget.setObjectName("queueWidget")
        self.queue_widget.setStyleSheet("""
            #queueWidget {
                background: #1c2333;
                border: 1px solid #2d3548;
                border-radius: 14px;
                margin-top: 5px;
            }
        """)
        self.queue_widget.hide()

        qw_layout = QVBoxLayout(self.queue_widget)
        qw_layout.setContentsMargins(16, 5, 16, 10)
        qw_layout.setSpacing(6)

        # Title row with Cancel all button
        queue_header = QHBoxLayout()
        queue_header.setSpacing(6)
        self._lbl_queue_title = QLabel("Download queue")
        self._lbl_queue_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #e6edf3;")
        queue_header.addWidget(self._lbl_queue_title)
        queue_header.addStretch()

        self.btn_queue_cancel_all = QPushButton("Cancel all")
        self.btn_queue_cancel_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_queue_cancel_all.setStyleSheet("""
            QPushButton {
                background: transparent; border: 1px solid #484f58;
                border-radius: 6px; padding: 4px 12px;
                font-size: 12px; color: #8b949e;
            }
            QPushButton:hover { background: #222a3a; color: #f85149; border-color: #f85149; }
        """)
        self.btn_queue_cancel_all.clicked.connect(self._on_cancel_all)
        queue_header.addWidget(self.btn_queue_cancel_all)

        qw_layout.addLayout(queue_header)

        # Input row 1: URL + threads + add button
        input_row1 = QHBoxLayout()
        input_row1.setSpacing(8)

        self._queue_url_input = QLineEdit()
        self._queue_url_input.setPlaceholderText("https://www.twitch.tv/videos/2796577649")
        self._queue_url_input.setStyleSheet("""
            QLineEdit {
                background: #0d1117; border: 1px solid #2d3548;
                border-radius: 8px; padding: 10px 14px;
                font-size: 14px; color: #e6edf3;
            }
            QLineEdit:focus { border-color: #7c5cfc; }
        """)
        self._queue_url_input.returnPressed.connect(self._on_add_to_queue)
        self._queue_url_input.textChanged.connect(self._on_queue_url_text_changed)

        self._queue_threads_spin = QSpinBox()
        self._queue_threads_spin.setRange(1, 16)
        self._queue_threads_spin.setValue(4)
        self._queue_threads_spin.setFixedWidth(60)
        self._queue_threads_spin.setStyleSheet("""
            QSpinBox {
                background: #0d1117; border: 1px solid #2d3548;
                border-radius: 6px; padding: 4px 8px;
                font-size: 13px; color: #e6edf3;
            }
            QSpinBox:focus { border-color: #7c5cfc; }
            QSpinBox::up-button { width: 18px; }
            QSpinBox::down-button { width: 18px; }
        """)

        self.btn_queue_add = QPushButton("Add in queue")
        self.btn_queue_add.setObjectName("btnQueueAdd")
        self.btn_queue_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_queue_add.setStyleSheet("""
            QPushButton {
                background: #7c5cfc; color: #fff; font-weight: 600;
                font-size: 14px; border: none; border-radius: 8px;
                padding: 10px 20px;
            }
            QPushButton:hover { background: #6a4de6; }
            QPushButton:disabled { background: #3d2e7a; color: #8b949e; }
        """)
        self.btn_queue_add.clicked.connect(self._on_add_to_queue)

        input_row1.addWidget(self._queue_url_input, 1)
        input_row1.addWidget(self._queue_threads_spin)
        input_row1.addWidget(self.btn_queue_add)
        qw_layout.addLayout(input_row1)

        # Input row 2: start / end time range (optional)
        input_row2 = QHBoxLayout()
        input_row2.setSpacing(6)

        time_edit_style = """
            QLineEdit {
                background: #0d1117; border: 1px solid #2d3548;
                border-radius: 6px; padding: 6px 8px;
                font-size: 13px; color: #e6edf3;
            }
            QLineEdit:focus { border-color: #7c5cfc; }
        """

        lbl_start = QLabel("Start:")
        lbl_start.setStyleSheet("font-size: 13px; color: #8b949e;")
        input_row2.addWidget(lbl_start)

        self._queue_input_start = QLineEdit()
        self._queue_input_start.setPlaceholderText("00:00:00")
        self._queue_input_start.setFixedWidth(80)
        self._queue_input_start.setStyleSheet(time_edit_style)
        input_row2.addWidget(self._queue_input_start)

        lbl_end = QLabel("End:")
        lbl_end.setStyleSheet("font-size: 13px; color: #8b949e;")
        input_row2.addWidget(lbl_end)

        self._queue_input_end = QLineEdit()
        self._queue_input_end.setPlaceholderText("00:00:00")
        self._queue_input_end.setFixedWidth(80)
        self._queue_input_end.setStyleSheet(time_edit_style)
        input_row2.addWidget(self._queue_input_end)

        input_row2.addStretch()

        self._queue_dur_label = QLabel("")
        self._queue_dur_label.setStyleSheet("font-size: 12px; color: #484f58;")
        input_row2.addWidget(self._queue_dur_label)

        qw_layout.addLayout(input_row2)

        # Queue item list (scrollable — stretches to fill space)
        self._queue_scroll = QScrollArea()
        self._queue_scroll.setWidgetResizable(True)
        self._queue_scroll.setStyleSheet("""
            QScrollArea {
                background: #0d1117;
                border: 1px solid #2d3548;
                border-radius: 8px;
            }
        """)
        self._queue_list_widget = QWidget()
        self._queue_list_layout = QVBoxLayout(self._queue_list_widget)
        self._queue_list_layout.setSpacing(2)
        self._queue_list_layout.setContentsMargins(8, 6, 8, 6)
        self._queue_list_layout.addStretch()
        self._queue_scroll.setWidget(self._queue_list_widget)
        qw_layout.addWidget(self._queue_scroll)

    # ------------------------------------------------------------
    #  Styles
    # ------------------------------------------------------------
    @staticmethod
    def _apply_styles():
        pass  # everything is inline styles

    # ------------------------------------------------------------
    #  Locale / language
    # ------------------------------------------------------------
    def _tr(self, key: str, **kwargs) -> str:
        return tr(self._lang, key, **kwargs)

    def _set_lang(self, code: str):
        self._lang = code
        self._apply_language()

    def _apply_language(self):
        t = self._tr

        self.setWindowTitle(t("app_title"))
        self.lbl_logo.setText(t("app_title"))
        self._lbl_vod_title.setText(t("vod_link"))
        self._lbl_vod_desc.setText(t("paste_hint"))
        self.url_input.setPlaceholderText(t("url_placeholder"))
        self._lbl_threads.setText(t("threads"))
        self.btn_download.setText(t("download_btn"))
        self._lbl_progress_title.setText(t("progress_title"))
        self._lbl_err_title.setText(t("error"))
        self.btn_retry.setText(t("try_again"))
        self._lbl_done_title.setText(t("done_title"))
        self.btn_txt.setText(f"📄 {t('txt_btn')}")
        self.btn_csv.setText(f"📊 {t('csv_btn')}")
        self.btn_web.setText(f"🌐 {t('web_btn')}")
        self.btn_clear.setText(f"🗑 {t('clear_btn')}")
        # Queue area
        self._lbl_queue_title.setText(t("queue_title"))
        self.btn_queue_add.setText(t("in_queue"))
        self.btn_queue_cancel_all.setText(t("cancel_all_btn"))
        self._queue_url_input.setPlaceholderText(t("url_placeholder"))
        self._rebuild_queue_list()  # refresh empty-label text
        # Pause / Resume button (depends on current worker state)
        if self._worker and self._worker.is_paused:
            self.btn_pause.setText("▶  " + t("resume_btn"))
        else:
            self.btn_pause.setText("⏸  " + t("pause_btn"))
        base_powered = t("powered_by")  # e.g. "Powered by Mr3ster"
        linked = base_powered.replace(
            "Mr3ster",
            '<a href="#" style="color: #7c5cfc; text-decoration: none;">Mr3ster</a>'
        )
        self.lbl_powered.setText(
            f'<span style="color: #8b949e; font-size: 12px; font-weight: 600;">{linked}</span>'
        )
        self.lbl_support.setText(
            f'<a href="#" style="color: #7c5cfc; text-decoration: none;">'
            f'<span style="color: #3fb950;">$</span> {t("support")}</a>')
        # Reset progress labels to translated defaults
        self.lbl_msgs.setText(t("zero_msgs"))
        self.lbl_status.setText("")

    # ------------------------------------------------------------
    #  URL validation / video preview
    # ------------------------------------------------------------
    def _on_url_text_changed(self, text: str):
        """Enable/disable download btn + start debounced validation."""
        has_text = bool(text.strip())
        self.btn_download.setEnabled(has_text)
        if has_text:
            self._url_check_timer.start(600)  # 600ms debounce
        else:
            self._url_check_timer.stop()
            self._hide_preview()

    def _on_url_check(self):
        """Debounced: fetch video info and show preview card."""
        url = self.url_input.text().strip()
        if not url:
            self._hide_preview()
            return

        try:
            video_id = extract_video_id(url)
        except ValueError:
            self._hide_preview()
            return

        # Show loading
        self._preview_title.setText("…")
        self._preview_channel.setText("")
        self._preview_duration.setText("")
        self._preview_widget.show()
        self._preview_thumb.clear()
        self._preview_thumb.setStyleSheet("background: #1c2333; border-radius: 6px;")

        try:
            info = get_video_info(video_id)
            self._show_preview(info)
        except Exception:
            self._hide_preview()

    def _show_preview(self, info: dict):
        """Fill preview card with video info."""
        self._preview_info = info

        # Clamp title length
        title = info.get("title", "?")
        if len(title) > 60:
            title = title[:57] + "…"
        self._preview_title.setText(title)

        channel = info.get("channel", "?")
        dur = self._fmt_duration(info.get("length_seconds", 0))
        self._preview_channel.setText(f"📺 {channel}")
        self._preview_duration.setText(f"⏱ {dur}")
        self._preview_widget.show()

        # Show time range inputs; set End placeholder to video duration
        dur_sec = info.get("length_seconds", 0)
        self._input_end.setPlaceholderText(self._fmt_tc(dur_sec))
        self._timerange_widget.show()

        # Try to load thumbnail
        thumb_url = info.get("thumbnail_url", "")
        if thumb_url:
            self._load_thumbnail(thumb_url)

    def _show_done_preview(self, info: dict):
        """Show preview card on done step (no timerange)."""
        title = info.get("title", "?")
        if len(title) > 60:
            title = title[:57] + "…"
        self._preview_title.setText(title)
        channel = info.get("channel", "?")
        dur = self._fmt_duration(info.get("length_seconds", 0))
        self._preview_channel.setText(f"📺 {channel}")
        self._preview_duration.setText(f"⏱ {dur}")
        self._preview_widget.show()
        self._timerange_widget.hide()
        thumb_url = info.get("thumbnail_url", "")
        if thumb_url:
            self._load_thumbnail(thumb_url)

    def _hide_preview(self):
        self._preview_info = None
        self._preview_widget.hide()
        self._timerange_widget.hide()
        self._preview_thumb.clear()

    def _load_thumbnail(self, url: str):
        """Download thumbnail image in background and display it."""
        try:
            resp = httpx.get(url, timeout=8.0)
            resp.raise_for_status()
            data = resp.content
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                scaled = pixmap.scaled(160, 90, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                self._preview_thumb.setPixmap(scaled)
                self._preview_thumb.setStyleSheet("border-radius: 6px;")
        except Exception:
            pass  # thumb is optional, keep grey

    # ------------------------------------------------------------
    #  Queue URL validation
    # ------------------------------------------------------------
    def _on_queue_url_text_changed(self, text: str):
        """Debounced validation for queue URL input."""
        if text.strip():
            self._queue_url_check_timer.start(600)
        else:
            self._queue_url_check_timer.stop()
            self._queue_input_end.setPlaceholderText("00:00:00")
            self._queue_dur_label.setText("")

    def _on_queue_url_check(self):
        """Debounced: fetch video info for queue URL and show duration."""
        url = self._queue_url_input.text().strip()
        if not url:
            self._queue_dur_label.setText("")
            return

        try:
            video_id = extract_video_id(url)
        except ValueError:
            self._queue_dur_label.setText("")
            return

        self._queue_dur_label.setText("⏳ …")

        try:
            info = get_video_info(video_id)
            dur_sec = info.get("length_seconds", 0)
            self._queue_dur_label.setText(f"⏱ {self._fmt_duration(dur_sec)}")
            self._queue_input_end.setPlaceholderText(self._fmt_tc(dur_sec))
        except Exception:
            self._queue_dur_label.setText("⚠ error")
            self._queue_input_end.setPlaceholderText("00:00:00")

    # ------------------------------------------------------------
    #  Step visibility
    # ------------------------------------------------------------
    def _show_step(self, step: str):
        for s in ("step_input", "step_progress", "step_error", "step_done"):
            w = getattr(self, s)
            w.hide()
        if step:
            getattr(self, step).show()

    # ------------------------------------------------------------
    #  Download & Queue
    # ------------------------------------------------------------
    def _on_download(self):
        url = self.url_input.text().strip()
        if not url:
            self.url_input.setFocus()
            return

        start_sec = self._parse_timecode(self._input_start.text())
        end_sec = self._parse_timecode(self._input_end.text())
        threads = self.threads_spin.value()

        if self._is_downloading:
            # Already downloading — add to queue instead
            item = self._queue_add(url, threads, start_sec, end_sec)
            self._rebuild_queue_list()
            self.url_input.clear()
            self._input_start.clear()
            self._input_end.clear()
            return

        self._start_download(url, threads, start_sec, end_sec)

    def _start_download(self, url: str, threads: int, start_sec, end_sec):
        """Start (or continue) a download, switching to the progress view."""
        self._is_downloading = True
        self._show_step("step_progress")
        self.circular_progress.set_value(0, smooth=False)
        self.circular_progress.set_sub_text("")
        self.lbl_msgs.setText(self._tr("zero_msgs"))
        self.lbl_status.setText(self._tr("connecting"))
        self._progress_start = time.monotonic()
        self.btn_download.setEnabled(False)
        self.btn_download.setText(self._tr("downloading_btn"))

        self._worker = DownloadWorker(
            url,
            threads=threads,
            start_sec=start_sec,
            end_sec=end_sec,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error_happened.connect(self._on_error)
        self._worker.start()

        # Reset pause button to default state
        self.btn_pause.setText("⏸  " + self._tr("pause_btn"))

        # Show queue area so user can add more items
        self._update_queue_title()
        self.queue_widget.show()
        self._layout_spacer.hide()
        self._queue_url_input.setFocus()

    def _on_progress(self, pct: int, count: int, remaining: float, total: int, error: str):
        if error:
            self.lbl_status.setText(f"⚠ {error}")
            return

        self.circular_progress.set_value(pct)
        self.lbl_msgs.setText(self._tr("messages", count=f"{count:,}") if count else self._tr("zero_msgs"))

        elapsed = time.monotonic() - self._progress_start
        if pct > 0 and elapsed > 3:
            total_est = elapsed / (pct / 100)
            eta_sec = max(0, int(total_est - elapsed))
            self.circular_progress.set_sub_text(f"~{self._fmt_duration(eta_sec)}")
        else:
            self.circular_progress.set_sub_text("")

        status = self._tr("scanned_status", pct=pct)
        self.lbl_status.setText(status)

    def _on_finished(self, result: dict):
        self._result = result
        self._handle_done()

    def _handle_done(self):
        """Show the done/export screen or start the next queued download."""
        if self._queue:
            self._process_queue()
        else:
            self._is_downloading = False
            self.queue_widget.hide()
            self._layout_spacer.show()
            self.btn_download.setEnabled(True)
            self.btn_download.setText(self._tr("download_btn"))

            if self._result:
                info = self._result["video_info"]
                self._show_done_preview(info)
                msgs_label = self._tr("messages", count=f"{self._result['total_comments']:,}")
                self.done_info_title.setText(f"📝 {msgs_label}")
                self.circular_progress.set_value(100)
                self._show_step("step_done")

    def _on_error(self, msg: str):
        self.lbl_error.setText(msg)
        if self._queue:
            self._process_queue()
        else:
            self._is_downloading = False
            self.queue_widget.hide()
            self._layout_spacer.show()
            self.btn_download.setEnabled(True)
            self.btn_download.setText(self._tr("download_btn"))
            self._show_step("step_error")

    def _on_pause(self):
        """Toggle pause / resume for the current download."""
        if not self._worker:
            return
        if self._worker.is_paused:
            self._worker.resume()
            self.btn_pause.setText("⏸  " + self._tr("pause_btn"))
        else:
            self._worker.pause()
            self.btn_pause.setText("▶  " + self._tr("resume_btn"))

    def _on_cancel(self):
        """Cancel the running download. If queue has items, start next."""
        if self._worker:
            self._worker.cancel()
            self._worker.quit()
            self._worker.wait(2000)

        if self._queue:
            self._process_queue()
        else:
            self._is_downloading = False
            self.queue_widget.hide()
            self._layout_spacer.show()
            self.btn_download.setEnabled(True)
            self.btn_download.setText(self._tr("download_btn"))
            self._show_step("step_input")
            self.url_input.setFocus()

    # ------------------------------------------------------------
    #  Queue management
    # ------------------------------------------------------------
    def _on_add_to_queue(self):
        """Called when user clicks 'Add in queue' or presses Enter in queue URL input."""
        url = self._queue_url_input.text().strip()
        if not url:
            self._queue_url_input.setFocus()
            return
        start_sec = self._parse_timecode(self._queue_input_start.text())
        end_sec = self._parse_timecode(self._queue_input_end.text())
        item = self._queue_add(url, self._queue_threads_spin.value(), start_sec, end_sec)
        self._rebuild_queue_list()
        self._queue_url_input.clear()
        self._queue_input_start.clear()
        self._queue_input_end.clear()
        self._queue_url_input.setFocus()

    def _queue_add(self, url: str, threads: int, start_sec, end_sec) -> dict:
        """Append a task to the queue and return the item dict."""
        self._queue_id += 1
        item = {
            "id": self._queue_id,
            "url": url,
            "threads": threads,
            "start_sec": start_sec,
            "end_sec": end_sec,
        }
        self._queue.append(item)
        return item

    def _process_queue(self):
        """Pop the first item from the queue and start downloading it."""
        if not self._queue:
            return
        item = self._queue.pop(0)
        self._rebuild_queue_list()
        self._start_download(item["url"], item["threads"], item["start_sec"], item["end_sec"])

    def _rebuild_queue_list(self):
        """Clear the queue list widget and rebuild from self._queue."""
        while self._queue_list_layout.count() > 1:
            item = self._queue_list_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        if self._queue_list_layout.count() == 0:
            self._queue_list_layout.addStretch()

        if not self._queue:
            empty = QLabel(self._tr("queue_empty"))
            empty.setStyleSheet("font-size: 12px; color: #484f58; padding: 4px 0;")
            self._queue_list_layout.insertWidget(0, empty)
            return

        for i, item in enumerate(self._queue):
            row = self._make_queue_row(i, item)
            self._queue_list_layout.insertWidget(i, row)

        self._update_queue_title()

    def _make_queue_row(self, index: int, item: dict) -> QFrame:
        """Create a single row widget for a queued download."""
        row = QFrame()
        row.setStyleSheet("""
            QFrame {
                background: #1c2333;
                border: 1px solid #2d3548;
                border-radius: 6px;
            }
        """)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 5, 10, 5)
        row_layout.setSpacing(8)

        num = QLabel(f"#{index + 1}")
        num.setFixedWidth(24)
        num.setStyleSheet("font-size: 12px; color: #7c5cfc; font-weight: 600; border: none;")
        row_layout.addWidget(num)

        url = item["url"]
        display_url = url if len(url) <= 45 else url[:42] + "…"
        url_label = QLabel(display_url)
        url_label.setStyleSheet("font-size: 13px; color: #e6edf3; border: none;")
        row_layout.addWidget(url_label, 1)

        # Time range badge (only when set)
        if item.get("start_sec") is not None or item.get("end_sec") is not None:
            start_str = self._fmt_tc(item["start_sec"]) if item["start_sec"] is not None else "0:00"
            end_str = self._fmt_tc(item["end_sec"]) if item["end_sec"] is not None else "∞"
            time_label = QLabel(f"{start_str}–{end_str}")
            time_label.setStyleSheet("font-size: 11px; color: #484f58; border: none;")
            time_label.setFixedWidth(110)
            row_layout.addWidget(time_label)

        threads_label = QLabel(f"{item['threads']}t")
        threads_label.setFixedWidth(24)
        threads_label.setStyleSheet("font-size: 11px; color: #8b949e; border: none;")
        row_layout.addWidget(threads_label)

        btn_remove = QPushButton("✕")
        btn_remove.setFixedSize(22, 22)
        btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_remove.setStyleSheet("""
            QPushButton {
                background: transparent; color: #484f58;
                border: none; border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover { color: #f85149; background: rgba(248,81,73,0.15); }
        """)
        item_id = item["id"]
        btn_remove.clicked.connect(lambda checked, qid=item_id: self._on_remove_queue_item(qid))
        row_layout.addWidget(btn_remove)

        return row

    def _on_remove_queue_item(self, item_id: int):
        """Remove a specific item from the queue by its id."""
        self._queue = [item for item in self._queue if item["id"] != item_id]
        self._rebuild_queue_list()

    def _on_cancel_all(self):
        """Cancel all queued items without interrupting the current download."""
        self._queue.clear()
        self._rebuild_queue_list()

    def _clear_queue(self):
        """Remove all items from the queue and reset UI state."""
        self._queue.clear()
        self._rebuild_queue_list()
        self.queue_widget.hide()
        self._layout_spacer.show()
        self._is_downloading = False
        self.btn_download.setEnabled(True)
        self.btn_download.setText(self._tr("download_btn"))

    def _update_queue_title(self):
        """Update the queue title to show number of pending items."""
        count = len(self._queue)
        if count:
            self._lbl_queue_title.setText(f"{self._tr('queue_title')} ({count})")
        else:
            self._lbl_queue_title.setText(self._tr("queue_title"))

    # ------------------------------------------------------------
    #  Exports
    # ------------------------------------------------------------
    def _export_txt(self):
        if not self._result:
            return
        path, _ = QFileDialog.getSaveFileName(self, self._tr("save_txt"), "", self._tr("txt_filter"))
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            for c in self._result["comments"]:
                f.write(f"[{c['time_str']}] {c['username']}: {c['message']}\n")
        QMessageBox.information(self, self._tr("saved"), self._tr("chat_saved", path=path))

    def _export_csv(self):
        if not self._result:
            return
        path, _ = QFileDialog.getSaveFileName(self, self._tr("save_csv"), "", self._tr("csv_filter"))
        if not path:
            return
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Timestamp", "TimeInVideo", "Username", "Login", "Message"])
            for c in self._result["comments"]:
                w.writerow([c.get("timestamp", ""), c.get("time_str", ""),
                            c.get("username", ""), c.get("login", ""), c.get("message", "")])
        QMessageBox.information(self, self._tr("saved"), self._tr("chat_saved", path=path))

    def _open_web(self):
        if not self._result:
            return
        html = self._build_viewer(self._result)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8")
        tmp.write(html)
        tmp_path = tmp.name
        tmp.close()
        webbrowser.open(f"file://{os.path.abspath(tmp_path)}")

    @staticmethod
    def _build_viewer(data: dict) -> str:
        comments = data.get("comments", [])
        info = data.get("video_info", {})
        total = len(comments)
        title = info.get("title", "Twitch Chat")
        channel = info.get("channel", "")

        rows = []
        for c in comments:
            uname = c.get("username", "?")
            text = c.get("message", "")
            text_esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            ts = c.get("time_str", "00:00")
            rows.append(
                f'<div class="msg">'
                f'<span class="time">[{ts}]</span>'
                f'<span class="name">{uname}</span>'
                f'<span class="text">{text_esc}</span>'
                f"</div>"
            )
        msg_html = "\n".join(rows)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Twitch Chat — {title}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0d1117;color:#e6edf3;font-family:'Segoe UI',sans-serif;display:flex;justify-content:center}}
  .c{{max-width:1000px;width:100%;padding:24px 16px}}
  h1{{font-size:22px;color:#9146ff;margin-bottom:2px}}
  .sub{{font-size:13px;color:#8b949e;margin-bottom:16px}}
  .s{{display:flex;gap:12px;flex-wrap:wrap;background:#161b22;border-radius:10px;padding:14px 18px;
      align-items:center;border:1px solid #30363d;margin-bottom:16px}}
  .s input{{flex:1;min-width:160px;background:#0d1117;border:1px solid #30363d;border-radius:6px;
            padding:8px 12px;color:#e6edf3;font-size:14px;outline:none;transition:border .2s}}
  .s input:focus{{border-color:#9146ff}}
  .s input::placeholder{{color:#484f58}}
  .cnt{{font-size:13px;color:#8b949e;white-space:nowrap}}
  #ch{{border:1px solid #30363d;border-radius:10px;overflow-y:auto;max-height:78vh}}
  .msg{{display:flex;gap:10px;padding:6px 14px;border-bottom:1px solid #161b22;font-size:14px;line-height:1.5}}
  .msg:hover{{background:#161b22}}
  .time{{color:#484f58;font-family:monospace;font-size:12px;min-width:70px;flex-shrink:0;padding-top:1px}}
  .name{{color:#58a6ff;font-weight:600;flex-shrink:0;min-width:120px;overflow:hidden;text-overflow:ellipsis}}
  .text{{color:#e6edf3;word-break:break-word}}
  .empty{{text-align:center;padding:32px;color:#484f58}}
</style>
</head>
<body>
<div class="c">
  <h1>💬 Twitch Chat</h1>
  <div class="sub">{title} — {channel} · {total} messages</div>
  <div class="s">
    <input type="text" id="qMsg" placeholder="Search messages…" oninput="f()">
    <input type="text" id="qUser" placeholder="Filter by username…" oninput="f()">
    <span class="cnt" id="cnt">{total}</span>
  </div>
  <div id="ch">{msg_html or '<div class="empty">No messages</div>'}</div>
</div>
<script>
function f(){{
  const m=document.getElementById('qMsg').value.toLowerCase()
  const u=document.getElementById('qUser').value.toLowerCase()
  const msgs=document.querySelectorAll('.msg');let n=0
  msgs.forEach(x=>{{const t=x.querySelector('.text').textContent.toLowerCase()
                   const na=x.querySelector('.name').textContent.toLowerCase()
                   const ok=t.includes(m)&&na.includes(u)
                   x.style.display=ok?'flex':'none';if(ok)n++}})
  document.getElementById('cnt').textContent=n+' / '+msgs.length+' messages'
}}
</script>
</body>
</html>"""

    # ------------------------------------------------------------
    #  Clear / Reset
    # ------------------------------------------------------------
    def _clear(self):
        self._result = None
        self.url_input.clear()
        self._show_step("step_input")
        self.url_input.setFocus()

    def _reset_ui(self):
        self._result = None
        self._clear_queue()
        self.url_input.setFocus()
        self._show_step("step_input")

    # ------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------
    @staticmethod
    def _parse_timecode(tc: str) -> Optional[int]:
        """Convert MM:SS or HH:MM:SS to seconds. Returns None for empty."""
        tc = tc.strip()
        if not tc:
            return None
        try:
            parts = tc.split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            else:
                return None
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _fmt_tc(sec) -> str:
        """Format seconds as HH:MM:SS."""
        s = max(0, int(sec))
        h, m = divmod(s, 3600)
        m, s = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def _fmt_duration(sec) -> str:
        s = max(0, int(sec))
        h, m = divmod(s, 3600)
        m, s = divmod(m, 60)
        parts = []
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        parts.append(f"{s}s")
        return " ".join(parts)

    @staticmethod
    def _make_flag_pixmap(code: str) -> QPixmap:
        """Draw a 32×24 flag pixmap using QPainter (no SVG, no emoji)."""
        pixmap = QPixmap(32, 24)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if code == "ru":
            p.fillRect(0, 0, 32, 8, QColor("#ffffff"))
            p.fillRect(0, 8, 32, 8, QColor("#0039a6"))
            p.fillRect(0, 16, 32, 8, QColor("#d52b1e"))
        elif code == "uk":
            p.fillRect(0, 0, 32, 12, QColor("#0057b7"))
            p.fillRect(0, 12, 32, 12, QColor("#ffd700"))
        elif code == "en":
            # Red field
            p.fillRect(0, 0, 32, 24, QColor("#b22234"))
            # White stripes every 3px (2px white visible)
            p.fillRect(0, 3, 32, 2, QColor("#ffffff"))
            p.fillRect(0, 8, 32, 2, QColor("#ffffff"))
            p.fillRect(0, 13, 32, 2, QColor("#ffffff"))
            p.fillRect(0, 18, 32, 2, QColor("#ffffff"))
            # Dark blue canton
            p.fillRect(0, 0, 14, 12, QColor("#041e42"))
            # White stars (small ellipses)
            p.setBrush(QBrush(QColor("#ffffff")))
            p.setPen(Qt.PenStyle.NoPen)
            for sx, sy in [(3, 2), (9, 2), (6, 5), (3, 8), (9, 8)]:
                p.drawEllipse(sx, sy, 3, 3)

        # Border
        p.setPen(QPen(QColor("#8b949e"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(0, 0, 31, 23)

        p.end()
        return pixmap


# ================================================================
#  Entry point
# ================================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Application-wide icon (taskbar)
    logo_path = os.path.join(_ASSETS, "logo.png")
    if os.path.exists(logo_path):
        app.setWindowIcon(QIcon(logo_path))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
