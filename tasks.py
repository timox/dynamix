#!/usr/bin/env python3
"""
Background tasks of the DynaMix GUI: each long operation (analysis, planning,
reports, pre-master, FX render...) runs in a worker thread as a Task that
reports its progress and can be stopped.

Stopping is cooperative: the worker's progress callback raises TaskCancelled
at its next call, i.e. between two tracks. TaskCancelled derives from
BaseException so the `except Exception` blocks of the analysis code let it
through; a stopped task never applies its results to the project.
"""

import itertools
import threading
import time
from typing import Callable, List, Optional


class TaskCancelled(BaseException):
    """Raised in a worker when its task was stopped."""


class Task:
    _ids = itertools.count(1)

    def __init__(self, name: str, project: str = "", cancellable: bool = True):
        self.id = next(Task._ids)
        self.name = name
        self.project = project
        self.cancellable = cancellable
        self.state = "running"            # running | done | stopped | failed
        self.started = time.time()
        self.ended: Optional[float] = None
        self.done = 0
        self.total = 0
        self.detail = ""
        self.error = ""
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    # ---- worker side
    def progress(self, done: int, total: int, detail: str = "") -> None:
        """Report progress (done of total, what is being worked on); raises TaskCancelled when stopped."""
        with self._lock:
            self.done, self.total, self.detail = int(done), int(total), str(detail or "")
        self.check()

    def check(self) -> None:
        if self._cancel.is_set():
            raise TaskCancelled(self.name)

    # ---- controller side
    def cancel(self) -> bool:
        """Ask the task to stop; False when it cannot be stopped or is not running."""
        if not self.cancellable or self.state != "running":
            return False
        self._cancel.set()
        return True

    def finish(self, state: str, error: str = "") -> None:
        if self.state == "running":
            self.state, self.error, self.ended = state, error, time.time()

    def fail(self, error: str) -> None:
        self.finish("failed", error)

    @property
    def stopping(self) -> bool:
        return self.state == "running" and self._cancel.is_set()

    @property
    def fraction(self) -> Optional[float]:
        return min(1.0, self.done / self.total) if self.total else None

    def elapsed(self, now: Optional[float] = None) -> float:
        return (self.ended or now or time.time()) - self.started

    def progress_text(self) -> str:
        if self.state == "done":
            return "done"
        if self.state == "stopped":
            return "stopped"
        if self.state == "failed":
            return f"failed: {self.error}"
        with self._lock:
            done, total, detail = self.done, self.total, self.detail
        text = f"{done}/{total} ({done / total * 100:.0f}%)" if total else "working"
        if detail:
            text += f" · {detail}"
        return ("stopping... " + text) if self.stopping else text


class TaskManager:
    """The tasks of the session, newest first (finished ones are kept up to `keep`)."""

    def __init__(self, keep: int = 50):
        self.keep = keep
        self._tasks: List[Task] = []
        self._lock = threading.Lock()

    def start(self, name: str, project: str = "", cancellable: bool = True) -> Task:
        task = Task(name, project, cancellable)
        with self._lock:
            self._tasks.insert(0, task)
            finished = [t for t in self._tasks if t.state != "running"]
            for old in finished[self.keep:]:
                self._tasks.remove(old)
        return task

    @property
    def tasks(self) -> List[Task]:
        with self._lock:
            return list(self._tasks)

    def running(self) -> List[Task]:
        return [t for t in self.tasks if t.state == "running"]

    def latest_stoppable(self) -> Optional[Task]:
        return next((t for t in self.running() if t.cancellable and not t.stopping), None)

    def clear_finished(self) -> int:
        with self._lock:
            before = len(self._tasks)
            self._tasks = [t for t in self._tasks if t.state == "running"]
            return before - len(self._tasks)

    def run(self, task: Task, work: Callable[[Task], None],
            on_stopped: Optional[Callable[[Task], None]] = None,
            on_error: Optional[Callable[[Task, Exception], None]] = None) -> threading.Thread:
        """Run work(task) in a daemon thread; the task ends done, stopped or failed."""
        def runner():
            try:
                work(task)
            except TaskCancelled:
                task.finish("stopped")
                if on_stopped:
                    on_stopped(task)
            except Exception as exc:  # noqa: BLE001 - reported through on_error
                task.fail(str(exc))
                if on_error:
                    on_error(task, exc)
            else:
                task.finish("done")

        thread = threading.Thread(target=runner, daemon=True, name=f"dynamix-task-{task.id}")
        thread.start()
        return thread
