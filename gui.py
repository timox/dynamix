#!/usr/bin/env python3
"""
DynaMix GUI - build a DJ set as a project: library, selection, proposals,
transitions, pre-master, transition FX, playlist and Mixxx export.
"""

import logging
import tkinter as tk
from tkinter import ttk
import os

from set_builder import SetBuilderMixin, ConfigTabMixin
from config import Config
from log_tab import LogTabMixin


class DynaMixGUI(SetBuilderMixin, ConfigTabMixin, LogTabMixin):
    """Main GUI application for DynaMix"""

    def __init__(self, root, log_buffer=None):
        self.root = root
        self.root.title("DynaMix - DJ Set Builder")
        self.root.geometry("1200x800")

        self.config = Config()
        self.log_buffer = log_buffer  # app_log.LogBuffer shown by the Log tab (None: not captured)

        # Status bar (created first: tabs may report while they load a project)
        self.status_bar = tk.Label(root, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.create_playlist_tab()
        self.create_config_tab()
        self.create_log_tab()

    def update_status(self, message: str):
        """Update status bar"""
        self.status_bar.config(text=message)
        self.root.update_idletasks()


def main():
    """Main entry point for GUI"""
    import app_log
    from analysis_store import dynamix_home
    log_buffer = app_log.install(os.path.join(dynamix_home(), "logs"))
    root = tk.Tk()
    root.report_callback_exception = lambda exc_type, exc, tb: app_log.log_exception(exc_type, exc, tb, "Error in the interface")
    app = DynaMixGUI(root, log_buffer=log_buffer)
    logging.getLogger("dynamix.gui").info("DynaMix started")
    root.mainloop()


if __name__ == "__main__":
    main()
