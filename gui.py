#!/usr/bin/env python3
"""
DynaMix GUI - build a DJ set as a project: library, selection, proposals,
transitions, pre-master, transition FX, playlist and Mixxx export.
"""

import logging
import os
import sys
import tkinter as tk
from tkinter import ttk

from analysis_store import dynamix_home

if getattr(sys, "frozen", False):
    # shareable build: numba cannot write its compilation cache inside the application folder
    os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(dynamix_home(), "numba_cache"))

from set_builder import SetBuilderMixin, ConfigTabMixin
from config import Config
from log_tab import LogTabMixin
from tasks import TaskManager
from tasks_tab import TasksTabMixin


class DynaMixGUI(SetBuilderMixin, ConfigTabMixin, LogTabMixin, TasksTabMixin):
    """Main GUI application for DynaMix"""

    def __init__(self, root, log_buffer=None):
        self.root = root
        self.root.title("DynaMix - DJ Set Builder")
        self.root.geometry("1200x800")

        self.config = Config()
        self.log_buffer = log_buffer  # app_log.LogBuffer shown by the Log tab (None: not captured)
        self.apply_font_size(self.config.get("font_size"), redraw=False)  # before any widget uses the fonts
        import audio_tools
        audio_tools.apply_ffmpeg_path(self.config.get("ffmpeg_path"))  # the M4A/AAC decoders find it on the PATH

        self.task_manager = TaskManager()

        # Status bar (created first: tabs may report while they load a project): message, then the newest running task
        bar = ttk.Frame(root)
        bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.task_stop_button = ttk.Button(bar, text="■ Stop", width=8, command=self.stop_latest_task)
        self.task_stop_button.pack(side=tk.RIGHT, padx=(4, 2), pady=1)
        self.task_stop_button.state(["disabled"])
        self.task_progress = ttk.Progressbar(bar, length=160, maximum=100)
        self.task_progress.pack(side=tk.RIGHT, padx=4)
        self.task_status = ttk.Label(bar, text="", foreground="#52514e")
        self.task_status.pack(side=tk.RIGHT, padx=6)
        self.status_bar = tk.Label(bar, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.create_playlist_tab()
        self.create_config_tab()
        self.create_log_tab()
        self.create_tasks_tab()

    def update_status(self, message: str):
        """Update status bar"""
        self.status_bar.config(text=message)
        self.root.update_idletasks()


def main():
    """Main entry point for GUI (--self-test [report file]: check this installation and exit)"""
    if "--self-test" in sys.argv:
        import selftest
        i = sys.argv.index("--self-test")
        sys.exit(selftest.run(sys.argv[i + 1] if i + 1 < len(sys.argv) else None))
    import app_log
    log_buffer = app_log.install(os.path.join(dynamix_home(), "logs"))
    root = tk.Tk()
    root.report_callback_exception = lambda exc_type, exc, tb: app_log.log_exception(exc_type, exc, tb, "Error in the interface")
    app = DynaMixGUI(root, log_buffer=log_buffer)
    logging.getLogger("dynamix.gui").info("DynaMix started")
    root.mainloop()


if __name__ == "__main__":
    main()
