"""Sequential background job queue for exports and other long tasks.

One worker thread runs one job at a time, in submission order.  Work functions
must not touch widgets; they receive a ``log`` callable and may open their own
database connection.  All signals are Qt signals, so slots run in the GUI
thread.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from datetime import datetime

from PySide6.QtCore import QObject, Signal


class JobQueue(QObject):
    """FIFO queue with one worker thread.

    A job is a callable ``work(log)`` returning either a summary string or a
    ``(summary, path)`` tuple.  ``on_done(ok, summary, path)`` runs in the GUI
    thread after the job.
    """

    queued = Signal(str)                    # job name
    started = Signal(str)                   # job name
    log = Signal(str)                       # ready-to-show log line
    finished = Signal(str, str, bool, str, str)   # name, summary, ok, path, seconds
    pending_changed = Signal(int)           # jobs waiting or running
    _done = Signal(str, bool, str, str)     # internal: job id, ok, summary, path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue()
        self._callbacks: dict[str, object] = {}
        self._lock = threading.Lock()
        self._pending = 0
        self._current = ""
        # ``_done`` is emitted from the worker thread and delivered here in the
        # GUI thread, so ``on_done`` callbacks may touch widgets.
        self._done.connect(self._deliver)
        self._worker = threading.Thread(target=self._loop, name="epbs-jobs", daemon=True)
        self._worker.start()

    # -- public ---------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self._pending > 0

    @property
    def current(self) -> str:
        return self._current

    def submit(self, name: str, work, on_done=None) -> str:
        """Queue ``work``; returns the job id."""
        job_id = uuid.uuid4().hex[:8]
        with self._lock:
            self._callbacks[job_id] = on_done
            self._pending += 1
        self.log.emit(f"{self._stamp()}  Queued  {name}")
        self.queued.emit(name)
        self.pending_changed.emit(self._pending)
        self._queue.put((job_id, name, work))
        return job_id

    # -- worker ---------------------------------------------------------
    @staticmethod
    def _stamp() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _loop(self) -> None:
        while True:
            job_id, name, work = self._queue.get()
            self._current = name
            started = time.perf_counter()
            self.started.emit(name)
            self.log.emit(f"{self._stamp()}  Started {name}")
            ok = True
            path = ""
            try:
                result = work(lambda message: self.log.emit(
                    f"{self._stamp()}  [{name}] {message}"))
                if isinstance(result, tuple):
                    summary = str(result[0])
                    path = str(result[1] or "")
                else:
                    summary = "" if result is None else str(result)
            except Exception as exc:  # keep the queue alive
                ok = False
                summary = str(exc).strip() or exc.__class__.__name__
                self.log.emit(f"{self._stamp()}  FAILED  {name}: {summary}")
                if not isinstance(exc, (ValueError, RuntimeError, OSError)):
                    first = traceback.format_exc().strip().splitlines()[-3:]
                    for line in first:
                        self.log.emit(f"{self._stamp()}  [{name}] {line.strip()}")
            seconds = time.perf_counter() - started
            if ok:
                self.log.emit(f"{self._stamp()}  Done    {name} ({seconds:.1f} s)"
                              + (f" — {summary}" if summary else ""))
            self._current = ""
            with self._lock:
                self._pending = max(0, self._pending - 1)
            self.pending_changed.emit(self._pending)
            self.finished.emit(name, summary, ok, path, f"{seconds:.1f}")
            self._done.emit(job_id, ok, summary, path)

    def _deliver(self, job_id: str, ok: bool, summary: str, path: str) -> None:
        """Run the ``on_done`` callback (GUI thread, via ``_done``)."""
        with self._lock:
            callback = self._callbacks.pop(job_id, None)
        if callback:
            try:
                callback(ok, summary, path)
            except Exception:
                pass
