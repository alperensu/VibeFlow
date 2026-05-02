"""
Filesystem watcher engine.

Token saving:
- Changed files are re-skeletonized incrementally.
- Warm requests reuse the current project index instead of rescanning the tree.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from config import SUPPORTED_EXTENSIONS, WATCHER_DEBOUNCE_MS
from core.indexer import ProjectIndex

logger = logging.getLogger("vibeflow.watcher")


class _IndexEventHandler(FileSystemEventHandler):
    def __init__(self, index: ProjectIndex) -> None:
        self.index = index
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def on_created(self, event: FileSystemEvent) -> None:
        self._schedule(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._schedule(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self.index.remove_file(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self.index.remove_file(event.src_path)
        self._schedule_path(getattr(event, "dest_path", ""))

    def _schedule(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule_path(event.src_path)

    def _schedule_path(self, value: str) -> None:
        path = Path(value)
        if path.suffix not in SUPPORTED_EXTENSIONS:
            return

        key = str(path)
        with self._lock:
            previous = self._timers.pop(key, None)
            if previous:
                previous.cancel()
            timer = threading.Timer(WATCHER_DEBOUNCE_MS / 1000.0, self._index_path, args=(path,))
            self._timers[key] = timer
            timer.daemon = True
            timer.start()

    def _index_path(self, path: Path) -> None:
        try:
            self.index.index_file(path)
        except Exception:
            logger.exception("failed to index changed file: %s", path)
        finally:
            with self._lock:
                self._timers.pop(str(path), None)


class WatcherEngine:
    def __init__(self, index: ProjectIndex) -> None:
        self.index = index
        self._observer: Observer | None = None

    @property
    def running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()

    def start(self) -> None:
        if self.running:
            return
        observer = Observer()
        observer.schedule(_IndexEventHandler(self.index), str(self.index.root), recursive=True)
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=2)
        self._observer = None
