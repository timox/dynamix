#!/usr/bin/env python3
"""
GUI smoke check (needs a display; not collected by the unit test runs):
builds the whole DynaMix window against a throwaway DynaMix home, drives the
Set Builder, and fails when an assertion fails or anything is logged as ERROR.

    venv/Scripts/python.exe tests/gui_smoke.py
"""
import json
import logging
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
HOME = tempfile.mkdtemp(prefix="dynamix_gui_")
os.environ["DYNAMIX_HOME"] = HOME

import numpy as np
import soundfile as sf

LIBRARY = os.path.join(HOME, "Mixes")
os.makedirs(os.path.join(LIBRARY, "2025"))
for name, seconds in (("one.wav", 2), (os.path.join("2025", "two.wav"), 3)):
    sf.write(os.path.join(LIBRARY, name), np.zeros(8000 * seconds, dtype="float32"), 8000)
with open(os.path.join(HOME, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"projects_root": os.path.join(HOME, "projects"), "library_folder": LIBRARY}, f)

import tkinter as tk
from tkinter import messagebox

import app_log

messagebox.showinfo = lambda *a, **k: print("info:", a)
messagebox.showwarning = lambda *a, **k: print("warning:", a)
messagebox.showerror = lambda *a, **k: print("error dialog:", a)
messagebox.askyesno = lambda *a, **k: True

buffer = app_log.install(os.path.join(HOME, "logs"))
import gui
from set_project import SetProject


def pump(until=lambda: False, seconds=10.0):
    """Run the Tk loop until until() is true or the time is up; returns until()."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        if until():
            return True
        time.sleep(0.05)
    return until()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


root = tk.Tk()
root.withdraw()
root.report_callback_exception = lambda t, e, tb: app_log.log_exception(t, e, tb, "Error in the interface")
errors = []
try:
    app = gui.DynaMixGUI(root, log_buffer=buffer)
    project = SetProject.create(app.config.projects_root, "smoke")
    app.load_project(project.folder)
    pump(seconds=0.5)

    logging.getLogger("dynamix.smoke").warning("smoke warning")
    check(pump(lambda: app.notebook.tab(app.log_frame, "text").startswith("Log ("), 2.0),
          "the Log tab title counts new warnings")
    app.notebook.select(app.log_frame)
    check(pump(lambda: app.notebook.tab(app.log_frame, "text") == "Log", 2.0), "opening the Log tab resets the counter")
    check("smoke warning" in app.log_text.get("1.0", tk.END), "the Log tab shows the records")
    app.notebook.select(0)

    check(app.cfg_library_var.get() == LIBRARY, "the Configuration tab shows the library folder")

    check(pump(lambda: not app._library_scanning and len(app._library_rows) == 2, 10.0),
          "the library lists the 2 tracks of the library folder")
    app.library_filter_var.set("two")
    check(len(app._library_rows) == 1, "the filter narrows the library")
    app.library_filter_var.set("")
    app.library_tree.selection_set(app.library_tree.get_children())
    app.selection_add()
    check(len(app.project.selection) == 2, "both tracks are selected")
    check([r["state"] for r in app._selection_rows] == ["pending", "pending"], "new selection rows are pending")
    app.selection_tree.selection_set("C1")
    app.selection_remove()
    check(len(app.project.selection) == 1, "remove drops a track from the selection")
    app.library_tree.selection_set(app.library_tree.get_children())
    app.selection_add()
    check(len(app.project.selection) == 2, "adding again keeps one entry per track")

    # --- checks added by later tasks go above this line ---
finally:
    errors = buffer.records(logging.ERROR)
    try:
        root.destroy()
    except tk.TclError:
        pass
    app_log.uninstall()
    shutil.rmtree(HOME, ignore_errors=True)
for record in errors:
    print(app_log.format_record(record))
if errors:
    sys.exit(1)
print("GUI smoke OK")
