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


def scenario():
        global app
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

        fake = [{"file_path": p, "filename": os.path.basename(p), "duration": 300.0, "bpm": 120.0 + i, "key": "A minor",
                 "energy_level": 3.0 + i, "has_beat": True} for i, p in enumerate(app.project.selection)]
        app.project.set_tracks(fake)
        app.project.mark("analyze", count=len(fake))
        app._refresh_tables()
        check([r["state"] for r in app._selection_rows] == ["analysed", "analysed"], "analysed rows are shown as analysed")
        app.energy_curve_var.set("all")
        app.set_duration_var.set(15)
        app.create_set_list()
        check(pump(lambda: len(app.project.proposal_variants()) == 4, 15.0), "curve 'all' gives one proposal per curve")
        check(pump(lambda: app._previewing, 3.0), "the first proposal is previewed")
        app.set_move(1)
        check(not app._previewing, "an edit closes the preview first")
        app.proposal_tree.selection_set("P2")
        check(pump(lambda: app._previewing, 3.0), "selecting a proposal previews it")
        app.use_selected_proposal()
        check(len(app.project.set_list) == 2 and app.project.is_done("setlist"), "the proposal became the set list")
        check(app.project.options["energy_curve"] != "all", "'all' is not saved as the project's energy curve")

        open(os.path.join(app.project.exports_dir, "old.m3u"), "w").close()
        result = app._do_reset()
        check(result == {"files_deleted": 1, "bytes_deleted": 0}, f"reset deletes the exports, got {result}")
        check(app.project.selection == [] and app._selection_rows == [] and app.project.set_list == [],
              "reset empties the selection and the set list")
        app.library_tree.selection_set(app.library_tree.get_children())
        app.selection_add()
        from analysis_store import get_store
        first = app.project.selection[0]
        get_store().put(first, "features", {"duration": 2.0, "bpm": 120.0})
        check(app._do_clear_analysis_cache(list(app.project.selection)) == 1, "the selection's cache entries are removed")
        check(get_store().get(first, "features") is None, "the cache entry is gone")
        check(pump(lambda: not app._library_scanning, 10.0), "the library is rescanned after clearing the cache")

        fake = [{"file_path": p, "filename": os.path.basename(p), "duration": 300.0, "bpm": 120.0, "key": "A minor",
                 "energy_level": 4.0, "has_beat": True} for p in app.project.selection]
        app.project.set_tracks(fake)
        app.project.mark("analyze", count=len(fake))
        tracks_before = [dict(t) for t in app.project.tracks]
        app.clear_whole_cache()
        check(app.project.tracks == tracks_before and app.project.is_done("analyze"),
              "clearing the whole cache keeps the open project's analysed tracks and workflow")
        check(pump(lambda: not app._library_scanning and not app._library_rescan_pending, 10.0),
              "the library is rescanned after clearing the whole cache")

        app.rescan_library()
        app.rescan_library()
        check(app._library_rescan_pending, "a rescan asked during a scan is queued")
        check(pump(lambda: not app._library_scanning and not app._library_rescan_pending and len(app._library_rows) == 2, 10.0),
              "the queued rescan runs and the library lists the 2 tracks again")

        for frame in (app.overview_frame, app.track_frame, app.premaster_frame):
            app.set_notebook.select(frame._notebook_tab)  # raised TclError when given the inner frame
            check(app.set_notebook.select() == str(frame._notebook_tab), "scrollable tabs can be selected")
        app.set_notebook.select(0)

        sr = 22050
        fx_tracks = []
        for k, freq in enumerate((220, 330)):
            path = os.path.join(HOME, f"fx_t{k}.wav")
            t = np.arange(12 * sr) / sr
            sf.write(path, (0.3 * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)
            get_store().put(path, "beats", {"beats": [i * 0.5 for i in range(25)], "bpm": 120.0, "has_beat": True,
                                            "duration": 12.0})
            fx_tracks.append(path)
        fx_samples = os.path.join(HOME, "fx_samples")
        os.makedirs(fx_samples)
        sf.write(os.path.join(fx_samples, "riser.wav"), np.full(sr, 0.2, dtype="float32"), sr)
        app.config.set("fx_samples_folder", fx_samples)
        project = app.project
        project.set_tracks([{"file_path": p, "filename": os.path.basename(p), "duration": 12.0, "bpm": 120.0} for p in fx_tracks])
        project.set_order(fx_tracks)
        profiles = [{"file_path": p, "filename": os.path.basename(p), "duration": 12.0, "bpm": 120.0, "key": "A minor",
                     "intro_start": 1.0, "intro_end": 3.0, "outro_start": 8.0, "outro_end": 10.0} for p in fx_tracks]
        project.data["transitions"] = {"tracks": profiles, "transitions": [{"score": 55}]}
        project.mark("transitions", count=1)
        project.save()
        app.load_project(project.folder)
        original = open(fx_tracks[0], "rb").read()

        class FakePlayer:
            def __init__(self):
                self.loops, self.once, self.stops = [], [], 0

            def play_loop(self, path):
                self.loops.append(path)
                return True

            def play_once(self, path):
                self.once.append(path)

            def stop(self):
                self.stops += 1

        player = FakePlayer()
        win = app.open_fx_window(player=player)
        check(win is not None, "the Transition FX window opens once transitions are planned")
        check(pump(lambda: len(win.samples) == 1, 5.0), "the FX samples folder is scanned")
        win.trans_tree.selection_set("T0")
        check(pump(lambda: win.pair_index == 0, 2.0), "a transition can be selected")
        win.add_effect("freeze")
        win.add_effect("sample")
        check(pump(lambda: hasattr(win, "sample_list") and win.sample_list.size() == 1, 5.0), "the sample list is shown")
        win.sample_list.selection_set(0)
        win.pick_sample()
        check(win.effects()[1]["file"].endswith("riser.wav"), "a sample can be picked")
        win.fx_tree.selection_set("F0")
        check(pump(lambda: win.fx_index == 0, 2.0), "an effect can be selected")
        win.update_effect({"steps": [{"beats": 2, "repeats": 2}]}, rebuild_settings=True)
        win.update_effect({"steps": [{"beats": 4, "repeats": 1}]})  # an edit saved without rebuilding the panel
        win.add_freeze_step()
        check(win.effects()[0]["steps"] == [{"beats": 4, "repeats": 1}, {"beats": 1, "repeats": 2}], "+ step keeps the edited steps")
        win.remove_freeze_step(1)
        check(win.effects()[0]["steps"] == [{"beats": 4, "repeats": 1}], "- removes the chosen step")
        win.update_effect({"steps": [{"beats": 2, "repeats": 2}]}, rebuild_settings=True)
        win.start_preview()
        check(pump(lambda: player.loops and os.path.exists(player.loops[-1]), 20.0), "the preview is rendered and looped")
        win.nudge_var.set("10")
        check(app.project.fx_for_pair(*fx_tracks)["nudge_ms"] == 10.0, "the nudge is stored")
        check(pump(lambda: len(player.loops) >= 2, 20.0), "a change re-renders the looped preview")
        win.apply_all()
        check(win._applying, "Apply all FX is running")
        win.apply_all()  # a second click while rendering is ignored
        check(pump(lambda: app.project.data["fx"]["render"] is not None, 30.0), "Apply all FX renders the copies")
        check(app.project.is_done("fx"), "the FX step is marked done")
        _, counts = app.project.rendered_profiles(app.transition_planner.profiles)
        check(counts["fx"] == 2, f"the export uses the two FX copies, got {counts}")
        check(app._fx_labels() == {0: "freeze · sample"}, "the set map labels the transition FX")
        check(open(fx_tracks[0], "rb").read() == original, "the original file is untouched")
        stops_before = player.stops
        win.close()
        check(player.stops > stops_before, "closing the window stops the preview")

        # --- checks added by later tasks go above this line ---


app = None
failure = [None]


def run():
    try:
        scenario()
    except Exception as e:
        failure[0] = e
    finally:
        root.quit()


root = tk.Tk()
root.withdraw()
root.report_callback_exception = lambda t, e, tb: app_log.log_exception(t, e, tb, "Error in the interface")
errors = []
try:
    root.after(0, run)
    root.mainloop()
    if failure[0] is not None:
        raise failure[0]
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
