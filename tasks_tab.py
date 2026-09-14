#!/usr/bin/env python3
"""
Tasks tab of the DynaMix GUI (mixin for DynaMixGUI): the background tasks of
the session with their progress, and Stop; the status bar shows the newest
running task with a progress bar and a Stop button.
"""

import logging
import time
import tkinter as tk
from tkinter import ttk

from i18n import tr

log = logging.getLogger("dynamix.tasks")
MUTED = "#52514e"


def _clock(seconds: float) -> str:
    seconds = int(max(0, seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _state_text(state: str) -> str:
    """A task state (tasks.Task.state, or 'stopping') as shown in the Tasks tab."""
    return {"running": tr("running"), "done": tr("done"), "stopped": tr("stopped"), "failed": tr("failed"),
            "stopping": tr("stopping")}.get(state, state)


def _progress_text(task) -> str:
    """Task.progress_text() with its words translated (the numbers and the detail stay as they are)."""
    if task.state == "done":
        return tr("done")
    if task.state == "stopped":
        return tr("stopped")
    if task.state == "failed":
        return tr("failed: {error}", error=task.error)
    text = task.progress_text()
    stopping = text.startswith("stopping... ")
    if stopping:
        text = text[len("stopping... "):]
    if text == "working" or text.startswith("working · "):
        text = tr("working") + text[len("working"):]
    return tr("stopping... {progress}", progress=text) if stopping else text


class TasksTabMixin:
    """Needs: root, notebook, task_manager, task_status, task_progress, task_stop_button, update_status, _report_error."""

    def create_tasks_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=tr("Tasks"))
        self.tasks_frame = frame
        self._tasks_title = tr("Tasks")
        bar = ttk.Frame(frame)
        bar.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Button(bar, text=tr("■ Stop selected"), command=self.stop_selected_task).pack(side=tk.LEFT)
        ttk.Button(bar, text=tr("Clear finished"), command=self.clear_finished_tasks).pack(side=tk.LEFT, padx=6)
        ttk.Label(bar, text=tr("Stop ends a task after the track in progress; a stopped task leaves the project unchanged "
                               "(analyses already done stay in the cache)."), foreground=MUTED).pack(side=tk.LEFT, padx=8)
        self.tasks_tree = ttk.Treeview(frame, columns=("Task", "Project", "Progress", "Time", "State"), show="headings",
                                       selectmode="browse")
        for col, width, stretch in (("Task", 180, False), ("Project", 140, False), ("Progress", 480, True),
                                    ("Time", 60, False), ("State", 90, False)):
            self.tasks_tree.heading(col, text=tr(col))
            self.tasks_tree.column(col, width=width, stretch=stretch, anchor="w")
        self.tasks_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.root.after(300, self._poll_tasks)

    # ------------------------------------------------------------------ running tasks
    def _start_task(self, name, work, cancellable=True, on_stopped=None):
        """Run work(task) in the background as a task of the Tasks tab; on_stopped runs in the GUI thread."""
        project = getattr(self, "project", None)
        task = self.task_manager.start(name, project.name if project is not None else "", cancellable)

        def stopped(_task):
            log.info("%s: stopped", name)
            self.root.after(0, self.update_status, tr("{name}: stopped", name=name))
            if on_stopped:
                self.root.after(0, on_stopped)

        def failed(_task, exc):
            self._report_error(tr("{name} failed: {error}", name=name, error=exc), exc)

        self.task_manager.run(task, work, on_stopped=stopped, on_error=failed)
        self._refresh_tasks()
        return task

    def _task_failed(self, task, message, exc=None):
        """For workers that handle their own errors: mark the task failed and report the error."""
        task.fail(message)
        self._report_error(message, exc)

    def stop_latest_task(self):
        task = self.task_manager.latest_stoppable()
        if task is not None and task.cancel():
            self.update_status(tr("Stopping '{name}' after the track in progress ...", name=task.name))
            self._refresh_tasks()
        return task

    def stop_selected_task(self):
        sel = self.tasks_tree.selection()
        task = next((t for t in self.task_manager.tasks if sel and str(t.id) == sel[0]), None)
        if task is None:
            return None
        if task.cancel():
            self.update_status(tr("Stopping '{name}' after the track in progress ...", name=task.name))
        elif task.state == "running":
            self.update_status(tr("'{name}' cannot be stopped: it ends in a moment", name=task.name))
        self._refresh_tasks()
        return task

    def clear_finished_tasks(self):
        self.task_manager.clear_finished()
        self._refresh_tasks()

    # ------------------------------------------------------------------ display
    def _poll_tasks(self):
        try:
            self._refresh_tasks()
        except tk.TclError:
            return  # the window is closing
        self.root.after(300, self._poll_tasks)

    def _refresh_tasks(self):
        if not hasattr(self, "tasks_tree"):
            return  # a task started while the tabs are being built (library scan): shown at the first poll
        tasks = self.task_manager.tasks
        tree = self.tasks_tree
        now = time.time()
        wanted = [str(t.id) for t in tasks]
        for iid in tree.get_children():
            if iid not in wanted:
                tree.delete(iid)
        for position, task in enumerate(tasks):
            iid = str(task.id)
            state = _state_text("stopping" if task.stopping else task.state)
            if not task.cancellable and task.state == "running":
                state = tr("{state} (no stop)", state=state)
            values = (task.name, task.project, _progress_text(task), _clock(task.elapsed(now)), state)
            if tree.exists(iid):
                if tuple(tree.item(iid, "values")) != tuple(str(v) for v in values):
                    tree.item(iid, values=values)
                if tree.index(iid) != position:
                    tree.move(iid, "", position)
            else:
                tree.insert("", position, iid=iid, values=values)
        running = [t for t in tasks if t.state == "running"]
        title = tr("Tasks ({n})", n=len(running)) if running else tr("Tasks")
        if title != self._tasks_title:
            self._tasks_title = title
            self.notebook.tab(self.tasks_frame, text=title)
        latest = running[0] if running else None
        if latest is None:
            self.task_status.config(text="")
            self.task_progress.config(value=0)
            self.task_stop_button.state(["disabled"])
            return
        more = f" (+{len(running) - 1})" if len(running) > 1 else ""
        self.task_status.config(text=tr("{name}{more}: {progress}", name=latest.name, more=more, progress=_progress_text(latest)))
        self.task_progress.config(value=(latest.fraction or 0.0) * 100)
        stoppable = self.task_manager.latest_stoppable() is not None
        self.task_stop_button.state(["!disabled"] if stoppable else ["disabled"])
