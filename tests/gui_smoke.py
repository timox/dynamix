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
os.environ["DYNAMIX_LANGUAGE"] = "en"  # the checks read English texts, whatever the machine's language

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
        from tkinter import font as tkfont, ttk as tkttk
        import charts
        rows_before = int(tkttk.Style(root).lookup("Treeview", "rowheight"))
        app.cfg_font_size_var.set("13")
        check(tkfont.nametofont("TkDefaultFont").cget("size") == 13 and app.config.get("font_size") == 13,
              "the font size is applied and saved")
        check(tkfont.nametofont("DynaMixMono").cget("size") == 13, "the Log and report texts follow the font size")
        check(int(tkttk.Style(root).lookup("Treeview", "rowheight")) > rows_before, "table rows grow with the font")
        check(abs(charts._SCALE - 13 / 9) < 1e-6, "the charts follow the font size")
        app.cfg_font_size_var.set("9")
        check(app.font_size == 9 and abs(charts._SCALE - 1.0) < 1e-6, "the font size can be set back")

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
        sf.write(os.path.join(fx_samples, "riser 120BPM.wav"), np.full(sr, 0.2, dtype="float32"), sr)
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
        root.deiconify()  # the FX tab must be mapped: Tk drops the events generated on unmapped widgets
        win = app.open_fx_window(player=player)
        pump(seconds=0.3)
        check(win is not None, "the Transition FX window opens once transitions are planned")
        check(pump(lambda: len(win.samples) == 1, 5.0), "the FX samples folder is scanned")
        win.trans_tree.selection_set("T0")
        check(pump(lambda: win.pair_index == 0, 2.0), "a transition can be selected")
        check(pump(lambda: win._chart_canvas is not None, 20.0), "the transition chart is drawn with the waveforms")
        win.add_effect("freeze")
        win.add_effect("sample")
        check(pump(lambda: hasattr(win, "sample_list") and win.sample_list.size() == 1, 5.0), "the sample list is shown")
        check(pump(lambda: win.last_layout is not None and [lane["type"] for lane in win.last_layout["lanes"]] == ["freeze", "sample"], 3.0),
              "the chart has one lane per effect")
        win.start_preview()  # the sample effect has no file yet
        check(pump(lambda: "Choose a file" in win.status_label.cget("text"), 3.0),
              "a preview with a sample effect without a file asks to choose one (no error)")
        win.stop_preview()
        sample_list = win.sample_list
        sample_list.selection_set(0)
        sample_list.event_generate("<<ListboxSelect>>")  # a single click
        check(pump(lambda: (win.effects()[1].get("file") or "").endswith("riser 120BPM.wav"), 3.0), "a single click picks the sample")
        check(win.sample_list is sample_list and win.sample_list.winfo_exists(), "picking a sample keeps the list (no rebuild)")
        check("riser 120BPM.wav" in win.sample_current_label.cget("text"), "the current sample is shown")
        check(win.effects()[1].get("sample_bpm") == 120.0, "picking a sample reads its BPM from the file name")
        check("120 → 120 BPM" in win.sample_current_label.cget("text"), "the sample's tempo fit is shown")
        check("repeats" in win._form_vars, "the sample effect has a Repeats field")
        win._form_vars["repeats"].set("3")
        check(win.effects()[1].get("repeats") == 3 and "×3" in win.fx_tree.item("F1", "values")[1],
              "Repeats is stored and shown in the FX stack")
        win._form_vars["repeats"].set("1")
        win.fx_tree.selection_set("F0")
        check(pump(lambda: win.fx_index == 0, 2.0), "an effect can be selected")
        win.update_effect({"steps": [{"beats": 2, "repeats": 2}]}, rebuild_settings=True)
        win.update_effect({"steps": [{"beats": 4, "repeats": 1}]})  # an edit saved without rebuilding the panel
        win.add_freeze_step()
        check(win.effects()[0]["steps"] == [{"beats": 4, "repeats": 1}, {"beats": 1, "repeats": 2}], "+ step keeps the edited steps")
        win.remove_freeze_step(1)
        check(win.effects()[0]["steps"] == [{"beats": 4, "repeats": 1}], "- removes the chosen step")
        check(win.settings.master is win._settings_canvas, "the Settings panel is inside a scrolling canvas")
        pump(seconds=0.3)
        region = win._settings_canvas.bbox("all")
        check(region is not None and region[3] - region[1] >= win.settings.winfo_reqheight() - 2,
              "the scroll region covers every setting (Loop echo included)")
        win.update_effect({"steps": [{"beats": 2, "repeats": 2}]}, rebuild_settings=True)
        win.start_preview()
        check(pump(lambda: player.loops and os.path.exists(player.loops[-1]), 20.0), "the preview is rendered and looped")
        check(pump(lambda: win._result_env is not None, 5.0), "the rendered result is added to the chart")
        check(pump(lambda: win._play is not None, 5.0), "the looping preview starts the playhead")
        check(pump(lambda: "/" in win.position_label.cget("text"), 2.0), "the position bar shows the time in the loop")
        check(pump(lambda: win._playhead_item is not None, 5.0), "the playhead is drawn on the transition chart")
        loops_before = len(player.loops)
        check(win.seek(1.0) and len(player.loops) == loops_before + 1 and "preview_seek" in player.loops[-1],
              "moving the position plays the loop from there")
        check(abs(win.playhead_position() - 1.0) < 0.5, "the playhead follows the new position")
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
        planned = app.project.data["transitions"]["tracks"][0]
        planned["outro_start"] += 0.5
        check(win._plan_changed(), "the FX window notices a changed transition plan")
        win.apply_all()
        check(not win._applying, "Apply all FX refuses to render with a changed plan")
        planned["outro_start"] -= 0.5
        check(not win._plan_changed(), "the restored plan matches the FX window again")
        import transition_fx as tfx_module
        check(not win.orphan_row.winfo_manager(), "no orphan FX line without orphan FX")
        app.project.set_fx_effects(fx_tracks[1], fx_tracks[0], [tfx_module.new_effect("echo"), tfx_module.new_effect("freeze")])
        win.refresh_transitions()
        check(win.orphan_row.winfo_manager() == "pack" and "1 orphan FX" in win.orphan_label.cget("text"),
              "an FX pair that is no longer next to each other shows the orphan FX line")
        orphans = win.open_orphans()
        check(len(win._orphan_tree.get_children()) == 1 and "2 · echo · freeze" in win._orphan_tree.item("O0", "values")[2],
              "the orphan FX window lists the pair and its effects")
        check(win.remove_orphans(list(win._inactive)) == 1 and app.project.inactive_fx_pairs() == [],
              "orphan FX can be removed")
        check(not win.orphan_row.winfo_manager() and not win._orphan_tree.get_children(), "the line and the list are updated")
        orphans.destroy()
        check(app.set_notebook.select() == str(app.fx_tab), "Transition FX opens the FX tab")
        win.start_preview()
        stops_before = player.stops
        app.set_notebook.select(0)
        check(pump(lambda: player.stops > stops_before and not win._previewing, 2.0), "leaving the FX tab stops the preview")
        planned["outro_start"] += 0.5
        app.set_notebook.select(app.fx_tab)
        check(pump(lambda: app.fx_panel is not None and app.fx_panel is not win, 2.0), "the FX tab is rebuilt for a changed plan")
        planned["outro_start"] -= 0.5
        app.set_notebook.select(0)

        app.show_project_summary()
        check(pump(lambda: len(app.reports_tree.get_children()) == 1, 2.0), "the project summary is listed in the Log reports")
        report_path = app.reports_tree.selection()[0]
        check(os.path.isfile(report_path) and os.path.dirname(report_path) == os.path.join(app.project.exports_dir, "reports"),
              "the report is saved in exports/reports")
        check(app.notebook.select() == str(app.log_frame), "a new report opens the Log tab")
        check("smoke" in app.report_text.get("1.0", tk.END), "the report text is shown")
        app.log_level_var.set("Reports")
        app._log_rebuild()
        check(not app.log_body.winfo_manager(), "the Reports filter hides the log stream")
        app.log_level_var.set("All")
        app._log_rebuild()
        check(app.log_body.winfo_manager() == "pack", "All shows the log stream again")
        app.notebook.select(0)

        check("Audio used:" in app.audio_used_label.cget("text"), "the workflow panel says which audio is used")
        app.use_premaster_var.set(False)
        app._use_premaster_changed()
        check(app.project.options["use_premaster"] is False and "originals 2" in app.audio_used_label.cget("text"),
              f"unchecking the option plays the originals, got {app.audio_used_label.cget('text')!r}")
        check(not app.project.data["fx"]["render"] and not app.project.is_done("fx"),
              "changing the option invalidates the FX render")
        check(SetProject.open(app.project.folder).options["use_premaster"] is False, "the option is saved with the project")
        app.use_premaster_var.set(True)
        app._use_premaster_changed()
        order = list(app.project.set_list)
        snapshot = app._do_save_snapshot("smoke state")
        check(os.path.isfile(snapshot), "a snapshot is saved in the project")
        app.project.set_order(list(reversed(order)))
        app._save_project()
        check(app._do_restore_snapshot(snapshot) is not None and app.project.set_list == order,
              "restoring a snapshot brings the set list back")
        check(sorted(s["label"] for s in app.project.list_snapshots()) == ["before restore", "smoke state"],
              "the state before the restore is kept as a snapshot")
        dialog = app.open_snapshots()
        check(dialog is not None and dialog.winfo_exists(), "the Snapshots window opens")
        dialog.destroy()

        premaster_copy = os.path.join(app.project.premaster_dir, os.path.basename(fx_tracks[0]))
        shutil.copy(fx_tracks[0], premaster_copy)
        app.project.data["premaster"] = {"results": [{"input": fx_tracks[0], "output": premaster_copy}]}
        app._track_source_choice = None
        app._refresh_tables()
        app.set_tree.selection_set("S1")
        app.on_track_selected(app.set_tree)
        check("pre-mastered copy" in app.track_source_label.cget("text"),
              "the Track tab analyses the pre-mastered copy the set plays, and says so")
        check(pump(lambda: not any(w.winfo_class() == "TLabel" and str(w.cget("text")).startswith("Analysing")
                                   for w in app.track_frame.winfo_children())
                   and any(w.winfo_class() == "Canvas" for w in app.track_frame.winfo_children()), 20.0),
              "the mastering and band charts of the copy are drawn")
        app._set_track_source("original")
        check("File analysed: original" in app.track_source_label.cget("text"), "the Track tab can analyse the original instead")
        app._track_source_choice = None
        app.config.set("editor_audacity", sys.executable)                    # any existing program stands for the editor
        labels = [label for label, _ in app._track_menu_entries(fx_tracks[0])]
        check({"Open in Audacity", "Show in Explorer", "Open pre-mastered copy in Audacity",
               "Show pre-mastered copy in Explorer"} <= set(labels), f"the track menu offers the editors, got {labels}")
        app.config.set("editor_audacity", "")
        check(app._track_menu_entries(fx_tracks[1])[0][1] is None, "without an editor the menu says where to set one")
        check(set(app.cfg_editor_vars) == {"audacity", "renoise", "ableton", "mixbus"} and hasattr(app, "cfg_ffmpeg_var"),
              "the Configuration tab has FFmpeg and the audio editors")
        update = app._refresh_transition_measurements()
        check(update is not None and pump(lambda: update.state == "done", 30.0), "the transition sheet is measured again")
        check(pump(lambda: app.project.data["transitions"]["tracks"][0].get("measured_file") == premaster_copy, 5.0),
              "the transition sheet measures the pre-mastered copy the set plays")
        check(app.project.data["transitions"]["tracks"][0]["intro_start"] == 1.0, "measuring again keeps the cue positions")

        import time as _time

        def slow(task):
            for i in range(300):
                task.progress(i, 300, f"step {i}")
                _time.sleep(0.02)

        app.notebook.select(0)
        task = app._start_task("Smoke task", slow)
        check(pump(lambda: app.notebook.tab(app.tasks_frame, "text") == "Tasks (1)", 2.0), "the Tasks tab counts the running tasks")
        check(pump(lambda: "Smoke task" in app.task_status.cget("text") and float(app.task_progress["value"]) > 0, 3.0),
              "the status bar shows the running task and its progress")
        check(app.tasks_tree.exists(str(task.id)), "the task is listed in the Tasks tab")
        check(app.stop_latest_task() is task, "Stop in the status bar stops the newest task")
        check(pump(lambda: task.state == "stopped", 3.0), "a stopped task ends after its current step")
        check(pump(lambda: app.notebook.tab(app.tasks_frame, "text") == "Tasks", 2.0), "the Tasks title goes back when nothing runs")
        check(pump(lambda: app.tasks_tree.item(str(task.id), "values")[4] == "stopped", 2.0), "the stopped task stays listed")
        app.notebook.select(app.log_frame)  # earlier background reports (the updated transition sheet) are seen
        pump(seconds=0.3)
        app.notebook.select(0)
        shown = app.notebook.select()
        app.add_report("Background report", "text", show=False)
        check(app.notebook.select() == shown, "a report finished in the background does not change the tab")
        check("1 new report" in app.notebook.tab(app.log_frame, "text"), "the Log title counts the new reports")
        app.notebook.select(app.log_frame)
        check(pump(lambda: "new report" not in app.notebook.tab(app.log_frame, "text"), 2.0), "opening the Log resets the count")
        app.notebook.select(0)

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
