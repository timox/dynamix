#!/usr/bin/env python3
"""
Log tab of the DynaMix GUI (mixin for DynaMixGUI): what DynaMix printed and
every error with its traceback, as captured by app_log.
"""

import logging
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

import app_log

LEVELS = {"All": logging.DEBUG, "Warnings and errors": logging.WARNING, "Errors": logging.ERROR}


class LogTabMixin:
    """The Log tab: live application log, level filter, copy / clear / open folder."""

    def create_log_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Log")
        self.log_frame = frame
        self._log_unseen = 0
        self._log_title = "Log"
        bar = ttk.Frame(frame)
        bar.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(bar, text="Show:").pack(side=tk.LEFT)
        self.log_level_var = tk.StringVar(value="All")
        combo = ttk.Combobox(bar, textvariable=self.log_level_var, values=list(LEVELS), width=20, state="readonly")
        combo.pack(side=tk.LEFT, padx=4)
        combo.bind("<<ComboboxSelected>>", lambda e: self._log_rebuild())
        ttk.Button(bar, text="Copy", command=self._log_copy).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Clear view", command=self._log_clear).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Open log folder", command=self._log_open_folder).pack(side=tk.LEFT, padx=4)
        body = ttk.Frame(frame)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(body, wrap=tk.NONE, font=("Consolas", 9), state=tk.DISABLED)
        vsb = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.log_text.yview)
        hsb = ttk.Scrollbar(body, orient=tk.HORIZONTAL, command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_text.tag_configure("WARNING", foreground="#b25e00")
        self.log_text.tag_configure("ERROR", foreground="#c0262d")
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._log_tab_changed(), add="+")
        if self.log_buffer is None:
            self._log_append("Log capture is not installed (start DynaMix with gui.py to see the application log).",
                             logging.WARNING)
            return
        self._log_rebuild()
        self.root.after(200, self._poll_log)

    def _log_min_level(self):
        return LEVELS.get(self.log_level_var.get(), logging.DEBUG)

    def _log_append(self, text, levelno):
        at_bottom = self.log_text.yview()[1] >= 0.999
        tag = "ERROR" if levelno >= logging.ERROR else ("WARNING" if levelno >= logging.WARNING else None)
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + "\n", (tag,) if tag else ())
        self.log_text.configure(state=tk.DISABLED)
        if at_bottom:
            self.log_text.see(tk.END)

    def _log_rebuild(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        if self.log_buffer is None:
            return
        self.log_buffer.drain()
        for record in self.log_buffer.records(self._log_min_level()):
            self._log_append(app_log.format_record(record), record.levelno)
        self.log_text.see(tk.END)

    def _poll_log(self):
        try:
            visible = self._log_tab_visible()
            for record in self.log_buffer.drain():
                if record.levelno >= self._log_min_level():
                    self._log_append(app_log.format_record(record), record.levelno)
                if record.levelno >= logging.WARNING and not visible:
                    self._log_unseen += 1
            self._log_update_title()
        finally:
            self.root.after(200, self._poll_log)

    def _log_tab_visible(self):
        try:
            return self.notebook.select() == str(self.log_frame)
        except tk.TclError:
            return False

    def _log_update_title(self):
        title = f"Log ({self._log_unseen} ⚠)" if self._log_unseen else "Log"
        if title != self._log_title:
            self._log_title = title
            self.notebook.tab(self.log_frame, text=title)

    def _log_tab_changed(self):
        if self._log_tab_visible() and self._log_unseen:
            self._log_unseen = 0
            self._log_update_title()

    def _log_copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", tk.END))
        self.update_status("Log copied to the clipboard")

    def _log_clear(self):
        if self.log_buffer is not None:
            self.log_buffer.clear()
        self._log_rebuild()

    def _log_open_folder(self):
        folder = app_log.log_dir()
        if not folder:
            return
        if sys.platform.startswith("win"):
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
