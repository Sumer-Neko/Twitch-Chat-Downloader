"""Download worker — runs chat download in a background thread."""
from threading import Event

from PyQt6.QtCore import QThread, pyqtSignal

from chat_downloader import download_chat as _download_chat


class DownloadWorker(QThread):
    """Fetches all chat messages for a VOD without blocking the GUI."""

    progress = pyqtSignal(int, int, float, int, str)
    #  pct, count, remaining_sec, total_sec, error_string (empty = ok)

    finished = pyqtSignal(object)  # result dict
    error_happened = pyqtSignal(str)

    def __init__(self, url: str, threads: int = 4, parent=None,
                 start_sec=None, end_sec=None):
        super().__init__(parent)
        self.url = url
        self.threads = threads
        self.start_sec = start_sec
        self.end_sec = end_sec
        self._cancelled = False
        self._pause_event = Event()

    def cancel(self):
        self._cancelled = True
        self._pause_event.set()   # unblock any pause wait so cancel runs through

    def pause(self):
        self._pause_event.set()

    def resume(self):
        self._pause_event.clear()

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set() and not self._cancelled

    def run(self):
        try:
            def cb(pct, count, remaining, total, error=None):
                self.progress.emit(pct, count, remaining, total, error or "")

            result = _download_chat(
                self.url, cb,
                threads=self.threads,
                start_sec=self.start_sec,
                end_sec=self.end_sec,
                cancel_check=lambda: self._cancelled,
                pause_event=self._pause_event,
            )
            if self._cancelled:
                return
            self.finished.emit(result)
        except Exception as e:
            self.error_happened.emit(str(e))
