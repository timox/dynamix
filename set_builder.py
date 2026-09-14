#!/usr/bin/env python3
"""
Set Builder and Configuration tabs of the DynaMix GUI (mixins for DynaMixGUI).

A set is a project folder (see set_project.py): audio is imported into it,
analysed once (cached), ordered into a set list you can edit, planned into
transitions, optionally pre-mastered, and exported to Mixxx. Every step is
recorded in the project so the panel always shows where you are.
"""

import collections
import logging
import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import audio_tools
import charts
import i18n
from i18n import tr
import library
import ui_fonts
import set_proposer
from analysis_store import get_store, dynamix_home
from config import format_environment_report
from mastering import (analyze_mastering_cached, check_files, format_check_summary, premaster_files, format_premaster_summary,
                       playlist_tone_target)
from band_analysis import analyze_bands_cached, format_band_summary, mix_recommendation
from mixxx_export import MixxxExporter, find_mixxx_db, format_report
from playlist_manager import PlaylistManager
from set_project import SetProject, STEPS, list_projects
from fx_window import TransitionFxPanel
from transition_planner import TransitionPlanner

MUTED = "#52514e"
log = logging.getLogger("dynamix.gui")
# details of a workflow step: key -> English text (translated when shown)
STEP_DETAILS = {"count": "count {value}", "cached": "cached {value}", "analyzed": "analyzed {value}",
                "duration": "duration {value}", "curve": "curve {value}", "score": "score {value}", "file": "file {value}",
                "playlist": "playlist {value}", "cues": "cues {value}"}
# state of a selected track (code compared by the program) -> English text shown
TRACK_STATES = {"analysed": "analysed", "pending": "pending", "failed": "failed", "missing": "missing"}


class SetBuilderMixin:
    """The Set Builder tab: project, workflow steps, editable set list, charts."""

    # ------------------------------------------------------------------ tab
    def create_playlist_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=tr("Set Builder"))
        self.set_builder_frame = frame
        self.project = None
        self.playlist_manager = None
        self.current_set_list = None
        self.transition_planner = None
        self._chart_canvases = {}
        self._library_rows = []
        self._set_rows = []
        self._selection_rows = []
        self._library_entries = []
        self._library_scanning = False
        self._library_rescan_pending = False
        self._previewing = False
        
        # ---- header: project selection
        head = ttk.Frame(frame)
        head.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(head, text=tr("Project:")).pack(side=tk.LEFT, padx=(0, 4))
        self.project_var = tk.StringVar()
        self.project_combo = ttk.Combobox(head, textvariable=self.project_var, width=34, state="readonly")
        self.project_combo.pack(side=tk.LEFT, padx=4)
        self.project_combo.bind("<<ComboboxSelected>>", lambda e: self.open_selected_project())
        ttk.Button(head, text=tr("New project..."), command=self.new_project).pack(side=tk.LEFT, padx=4)
        ttk.Button(head, text=tr("Project summary"), command=self.show_project_summary).pack(side=tk.LEFT, padx=4)
        ttk.Button(head, text=tr("Snapshots..."), command=self.open_snapshots).pack(side=tk.LEFT, padx=4)
        ttk.Button(head, text=tr("Reset project..."), command=self.reset_project).pack(side=tk.LEFT, padx=(16, 4))
        ttk.Button(head, text=tr("Clear analysis cache..."), command=self.clear_analysis_cache).pack(side=tk.LEFT, padx=4)
        self.project_path_label = ttk.Label(frame, text=tr("No project open. Create one with 'New project...' (the Configuration tab sets where projects live)."),
                                            foreground=MUTED, anchor="w")
        self.project_path_label.pack(fill=tk.X, padx=14)
        
        paned = ttk.PanedWindow(frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # ---- left: workflow + options
        left = ttk.Frame(paned, width=350)
        paned.add(left, weight=0)
        steps_frame = ttk.LabelFrame(left, text=tr("Workflow"))
        steps_frame.pack(fill=tk.X, padx=2, pady=2)
        self.step_widgets = {}
        actions = {
            "analyze": (tr("Analyze"), self.analyze_playlist),
            "setlist": (tr("Propose"), self.create_set_list),
            "transitions": (tr("Plan Transitions"), self.plan_transitions),
            "premaster": (tr("Pre-master Set"), self.premaster_set),
            "fx": (tr("Transition FX"), self.open_fx_window),
            "playlist": (tr("Create Playlist"), self.create_playlist_from_directory),
            "mixxx": (tr("Export to Mixxx"), self.export_to_mixxx),
        }
        for i, (key, label, required) in enumerate(STEPS, 1):
            row = ttk.Frame(steps_frame)
            row.pack(fill=tk.X, padx=4, pady=2)
            status = ttk.Label(row, text="○", width=2)
            status.pack(side=tk.LEFT)
            btn_text, command = actions[key]
            # natural sizes: the button keeps its whole text, the step label wraps (longer texts in French)
            ttk.Button(row, text=btn_text, command=command).pack(side=tk.RIGHT, padx=2)
            ttk.Label(row, text=f"{i}. {tr(label)}", anchor="w", justify=tk.LEFT,
                      wraplength=190).pack(side=tk.LEFT, fill=tk.X, expand=True)
            detail = ttk.Label(steps_frame, text="", foreground=MUTED, anchor="w", wraplength=330)
            detail.pack(fill=tk.X, padx=28)
            self.step_widgets[key] = {"status": status, "detail": detail}
        self.next_step_label = ttk.Label(steps_frame, text=tr("Next: open or create a project."), wraplength=330,
                                         anchor="w", justify=tk.LEFT, font=ui_fonts.BOLD)
        self.next_step_label.pack(fill=tk.X, padx=6, pady=(6, 4))
        self.audio_used_label = ttk.Label(steps_frame, text="", foreground=MUTED, wraplength=330, anchor="w", justify=tk.LEFT)
        self.audio_used_label.pack(fill=tk.X, padx=6, pady=(0, 4))
        
        options_frame = ttk.LabelFrame(left, text=tr("Options for this set"))
        options_frame.pack(fill=tk.X, padx=2, pady=6)
        grid = ttk.Frame(options_frame)
        grid.pack(fill=tk.X, padx=4, pady=4)
        # set duration and energy curve are edited in the Proposals panel of the Tracks tab
        self.set_duration_var = tk.IntVar(value=int(self.config.get("set_duration")))
        self.energy_curve_var = tk.StringVar(value=self.config.get("energy_curve"))
        ttk.Label(grid, text=tr("Target loudness (LUFS):")).grid(row=2, column=0, sticky="w", pady=2)
        self.premaster_lufs_var = tk.DoubleVar(value=float(self.config.get("target_lufs")))
        ttk.Spinbox(grid, from_=-24.0, to=-6.0, increment=0.5, textvariable=self.premaster_lufs_var, width=8).grid(row=2, column=1, sticky="w")
        self.premaster_tone_var = tk.BooleanVar(value=bool(self.config.get("tone_match")))
        ttk.Checkbutton(grid, text=tr("Match tone to the set"), variable=self.premaster_tone_var).grid(row=3, column=0, columnspan=2, sticky="w")
        self.premaster_phase_var = tk.BooleanVar(value=bool(self.config.get("fix_phase")))
        ttk.Checkbutton(grid, text=tr("Fix phase problems"), variable=self.premaster_phase_var).grid(row=4, column=0, columnspan=2, sticky="w")
        mono_row = ttk.Frame(grid)
        mono_row.grid(row=5, column=0, columnspan=2, sticky="w")
        self.mono_bass_var = tk.BooleanVar(value=float(self.config.get("mono_bass_hz") or 0) > 0)
        ttk.Checkbutton(mono_row, text=tr("Mono bass below"), variable=self.mono_bass_var).pack(side=tk.LEFT)
        self.mono_bass_hz_var = tk.DoubleVar(value=float(self.config.get("mono_bass_hz") or 120.0) or 120.0)
        ttk.Spinbox(mono_row, from_=40, to=300, increment=10, textvariable=self.mono_bass_hz_var, width=5).pack(side=tk.LEFT, padx=3)
        ttk.Label(mono_row, text="Hz").pack(side=tk.LEFT)
        self.use_premaster_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grid, text=tr("Use pre-mastered copies (FX, playlist, Mixxx)"), variable=self.use_premaster_var,
                        command=self._use_premaster_changed).grid(row=6, column=0, columnspan=2, sticky="w")
        report_row = ttk.Frame(options_frame)
        report_row.pack(anchor="w", padx=4, pady=(0, 4))
        ttk.Button(report_row, text=tr("Mastering Report"), command=self.mastering_report).pack(side=tk.LEFT)
        ttk.Button(report_row, text=tr("Band Analysis"), command=self.band_report).pack(side=tk.LEFT, padx=4)
        self.cache_label = ttk.Label(left, text="", foreground=MUTED, wraplength=330, anchor="w", justify=tk.LEFT)
        self.cache_label.pack(fill=tk.X, padx=2, pady=2)
        
        # ---- right: notebook
        right = ttk.Frame(paned)
        paned.add(right, weight=1)
        self.set_notebook = ttk.Notebook(right)
        self.set_notebook.pack(fill=tk.BOTH, expand=True)
        
        tracks_tab = ttk.Frame(self.set_notebook)
        self.set_notebook.add(tracks_tab, text=tr("Tracks"))
        lists = ttk.PanedWindow(tracks_tab, orient=tk.HORIZONTAL)
        lists.pack(fill=tk.BOTH, expand=True)

        # column 1: every track of the library folder
        lib_frame = ttk.Frame(lists)
        lists.add(lib_frame, weight=1)
        self.library_caption = ttk.Label(lib_frame, text=tr("Library"), foreground=MUTED, anchor="w")
        self.library_caption.pack(fill=tk.X, padx=4, pady=(4, 0))
        lib_bar = ttk.Frame(lib_frame)
        lib_bar.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(lib_bar, text=tr("Filter:")).pack(side=tk.LEFT)
        self.library_filter_var = tk.StringVar()
        ttk.Entry(lib_bar, textvariable=self.library_filter_var, width=16).pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(lib_bar, text=tr("Rescan"), command=self.rescan_library).pack(side=tk.LEFT, padx=2)
        ttk.Button(lib_bar, text=tr("Add to selection →"), command=self.selection_add).pack(side=tk.LEFT, padx=2)
        self.library_tree = self._make_tree(lib_frame, ("Filename", "Dur", "BPM", "Key", "Energy", "Sel"),
                                            {"Filename": 220, "Dur": 55, "BPM": 50, "Key": 75, "Energy": 50, "Sel": 35},
                                            selectmode="extended")
        self.library_tree.bind("<Double-1>", lambda e: self.selection_add())
        self.library_tree.bind("<Button-3>", lambda e: self._track_menu(e, self.library_tree, self._library_rows))
        self.library_filter_var.trace_add("write", lambda *args: self._refresh_library_table())

        # column 2: the tracks picked for this set
        sel_frame = ttk.Frame(lists)
        lists.add(sel_frame, weight=1)
        self.selection_caption = ttk.Label(sel_frame, text=tr("Selection"), foreground=MUTED, anchor="w")
        self.selection_caption.pack(fill=tk.X, padx=4, pady=(4, 0))
        sel_bar = ttk.Frame(sel_frame)
        sel_bar.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(sel_bar, text=tr("← Remove"), command=self.selection_remove).pack(side=tk.LEFT, padx=2)
        ttk.Button(sel_bar, text=tr("Analyze selection"), command=self.analyze_playlist).pack(side=tk.LEFT, padx=2)
        ttk.Button(sel_bar, text=tr("Add to set list ▶"), command=self.set_add).pack(side=tk.LEFT, padx=2)
        self.selection_tree = self._make_tree(sel_frame, ("Filename", "Dur", "BPM", "Key", "Energy", "State"),
                                              {"Filename": 220, "Dur": 55, "BPM": 50, "Key": 75, "Energy": 50, "State": 70},
                                              selectmode="extended")
        self.selection_tree.bind("<<TreeviewSelect>>", lambda e: self.on_track_selected(self.selection_tree))
        self.selection_tree.bind("<Double-1>", lambda e: self.selection_remove())
        self.selection_tree.bind("<Button-3>", lambda e: self._track_menu(e, self.selection_tree, self._selection_rows))

        # column 3: proposals and the set list
        right_col = ttk.Frame(lists)
        lists.add(right_col, weight=1)
        prop_frame = ttk.LabelFrame(right_col, text=tr("Proposals (from the analysed selection)"))
        prop_frame.pack(fill=tk.X, padx=4, pady=(4, 2))
        prop_bar = ttk.Frame(prop_frame)
        prop_bar.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(prop_bar, text=tr("Duration (min):")).pack(side=tk.LEFT)
        ttk.Spinbox(prop_bar, from_=15, to=240, textvariable=self.set_duration_var, width=5).pack(side=tk.LEFT, padx=3)
        ttk.Label(prop_bar, text=tr("Curve:")).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Combobox(prop_bar, textvariable=self.energy_curve_var, values=list(set_proposer.CURVES) + ["all"],
                     width=11, state="readonly").pack(side=tk.LEFT, padx=3)
        ttk.Button(prop_bar, text=tr("Propose"), command=self.create_set_list).pack(side=tk.LEFT, padx=3)
        prop_body = ttk.Frame(prop_frame)
        prop_body.pack(fill=tk.X, padx=4)
        self.proposal_tree = self._make_tree(prop_body, ("#", "Curve", "Tracks", "Duration", "Score", "Worst"),
                                             {"#": 30, "Curve": 90, "Tracks": 50, "Duration": 120, "Score": 50, "Worst": 90},
                                             height=4)
        self.proposal_tree.bind("<<TreeviewSelect>>", lambda e: self.preview_proposal())
        self.proposal_tree.bind("<Double-1>", lambda e: self.use_selected_proposal())
        ttk.Button(prop_frame, text=tr("Use this proposal"), command=self.use_selected_proposal).pack(anchor="w", padx=4, pady=4)
        set_frame = ttk.Frame(right_col)
        set_frame.pack(fill=tk.BOTH, expand=True)
        self.set_caption = ttk.Label(set_frame, text=tr("Set list (playing order)"), foreground=MUTED, anchor="w")
        self.set_caption.pack(fill=tk.X, padx=4, pady=(4, 0))
        set_bar = ttk.Frame(set_frame)
        set_bar.pack(fill=tk.X, padx=4, pady=2)
        for text, cmd in ((tr("▲ Up"), lambda: self.set_move(-1)), (tr("▼ Down"), lambda: self.set_move(1)), (tr("Remove"), self.set_remove)):
            ttk.Button(set_bar, text=text, command=cmd).pack(side=tk.LEFT, padx=2)
        self.set_tree = self._make_tree(set_frame, ("#", "Filename", "BPM", "Key", "Dur", "Energy", "Master", "Flags"),
                                        {"#": 35, "Filename": 200, "BPM": 55, "Key": 75, "Dur": 50, "Energy": 55, "Master": 55, "Flags": 240})
        self.set_tree.tag_configure("preview", foreground=MUTED)
        self.set_tree.bind("<<TreeviewSelect>>", lambda e: self.on_track_selected(self.set_tree))
        self.set_tree.bind("<Double-1>", lambda e: self.set_remove())
        self.set_tree.bind("<Button-3>", lambda e: self._track_menu(e, self.set_tree, self._set_rows))
        
        self.overview_frame = self._scrollable_tab(tr("Overview"))
        self.track_frame = self._scrollable_tab(tr("Track"))
        self.premaster_frame = self._scrollable_tab(tr("Pre-master"))
        for f, msg in ((self.overview_frame, tr("Analyze the tracks and build a set list to see the energy curve and the set map.")),
                       (self.track_frame, tr("Select a track in the Tracks tab to see its energy envelope, intro/outro and tone balance.")),
                       (self.premaster_frame, tr("Run 'Pre-master Set' to see what was changed on every track."))):
            ttk.Label(f, text=msg, foreground=MUTED, wraplength=600).pack(padx=20, pady=20, anchor="w")
        self.fx_tab = ttk.Frame(self.set_notebook)
        self.set_notebook.add(self.fx_tab, text="FX")
        self.fx_panel = None
        self._fx_player = None
        self.set_notebook.bind("<<NotebookTabChanged>>", lambda e: self._fx_tab_changed(), add="+")
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._fx_tab_changed(), add="+")

        self.refresh_project_list()
        projects = list_projects(self.config.projects_root)
        if projects:
            self.load_project(projects[0])
        self.rescan_library()
    
    def _scrollable_tab(self, title):
        """A notebook tab whose content scrolls vertically; returns the inner frame to fill."""
        outer = ttk.Frame(self.set_notebook)
        self.set_notebook.add(outer, text=title)
        canvas = tk.Canvas(outer, highlightthickness=0, background="#fcfcfb")
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        
        def on_inner_configure(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        def on_canvas_configure(event):
            canvas.itemconfigure(window, width=event.width)  # charts follow the width, keep their height
        
        def on_wheel(event):
            if event.delta:  # Windows / macOS
                canvas.yview_scroll(int(-event.delta / 120), "units")
            elif event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
        
        inner.bind("<Configure>", on_inner_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind(seq, on_wheel)
            inner.bind(seq, on_wheel)
        inner._scroll_canvas = canvas
        inner._notebook_tab = outer  # what set_notebook.select() needs: the inner frame is not a tab
        return inner
    
    # ------------------------------------------------------------------ open a track in an audio editor
    def _track_menu_entries(self, path):
        """[(label, command)] of the right-click menu of a track: open it (and its pre-mastered copy) in the editors."""
        copy_path = self.project._premaster_outputs().get(path) if self.project is not None else None
        versions = [(False, path)] + ([(True, copy_path)] if copy_path else [])
        editors = [spec for spec in audio_tools.EDITORS if os.path.isfile((self.config.get(f"editor_{spec['key']}") or "").strip())]
        entries = []
        for is_copy, file in versions:
            for spec in editors:
                label = (tr("Open pre-mastered copy in {editor}", editor=spec["label"]) if is_copy
                         else tr("Open in {editor}", editor=spec["label"]))
                entries.append((label, lambda k=spec["key"], f=file: self.open_in_editor(k, f)))
            entries.append((tr("Show pre-mastered copy in Explorer") if is_copy else tr("Show in Explorer"),
                            lambda f=file: self._reveal(f)))
        if not editors:
            entries.insert(0, (tr("No audio editor set: Configuration tab, 'Detect editors'"), None))
        return entries

    def _track_menu(self, event, tree, rows):
        iid = tree.identify_row(event.y)
        if not iid:
            return None
        index = tree.index(iid)
        if not 0 <= index < len(rows) or not rows[index].get("file_path"):
            return None
        menu = tk.Menu(tree, tearoff=False)
        for label, command in self._track_menu_entries(rows[index]["file_path"]):
            if command is None:
                menu.add_command(label=label, state="disabled")
                menu.add_separator()
            else:
                menu.add_command(label=label, command=command)
        menu.tk_popup(event.x_root, event.y_root)
        return menu

    def open_in_editor(self, key, file):
        spec = audio_tools.editor(key)
        exe = (self.config.get(f"editor_{key}") or "").strip()
        args = self.config.get(f"editor_{key}_args") or ""
        try:
            result = audio_tools.open_in_editor(exe, args, file)
        except Exception as e:
            self._report_error(tr("Cannot open {file} in {editor}: {error}", file=os.path.basename(file), editor=spec["label"],
                                  error=e), e)
            return None
        name = os.path.basename(file)
        log.info("%s opened in %s%s (%s)", name, spec["label"],
                 f" - drag the file shown in Explorer into {spec['label']}" if result["revealed"] else "", " ".join(result["command"]))
        if result["revealed"]:
            self.update_status(tr("{file} opened in {editor} - drag the file shown in Explorer into {editor}",
                                  file=name, editor=spec["label"]))
        else:
            self.update_status(tr("{file} opened in {editor}", file=name, editor=spec["label"]))
        return result

    def _reveal(self, file):
        try:
            audio_tools.reveal(file)
        except Exception as e:
            self._report_error(tr("Cannot show {file}: {error}", file=file, error=e), e)

    def _make_tree(self, parent, columns, widths, selectmode="browse", height=14):
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=height, selectmode=selectmode)
        for col in columns:
            tree.heading(col, text=tr(col))
            tree.column(col, width=widths.get(col, 80), anchor="w" if col in ("Filename", "Key", "Flags", "Curve", "Worst") else "center",
                        stretch=(col in ("Filename", "Flags")))
        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        return tree
    
    # ------------------------------------------------------------------ projects
    def refresh_project_list(self):
        self._project_paths = list_projects(self.config.projects_root)
        names = [f"{SetProject(p).name}  ({os.path.basename(p)})" for p in self._project_paths]
        self.project_combo["values"] = names
        if self.project is not None and self.project.folder in self._project_paths:
            self.project_var.set(names[self._project_paths.index(self.project.folder)])
    
    def open_selected_project(self):
        idx = self.project_combo.current()
        if 0 <= idx < len(self._project_paths):
            self.load_project(self._project_paths[idx])
    
    def new_project(self):
        name = simpledialog.askstring(tr("New set project"), tr("Name of the set (a folder with this name is created in the projects folder):"),
                                      parent=self.root)
        if not name:
            return
        try:
            project = SetProject.create(self.config.projects_root, name, options=self.config.project_defaults())
        except FileExistsError as e:
            messagebox.showerror(tr("Error"), str(e))
            return
        self.load_project(project.folder)
        self.refresh_project_list()
        if not (self.config.get("library_folder") or "").strip():
            messagebox.showinfo(tr("Music library"), tr("Set your music library folder in the Configuration tab, "
                                                       "then pick the tracks of this set in the Library."))

    def reset_project(self):
        if not self._require_project():
            return
        project = self.project
        preview = project.reset_preview()
        outputs, imported = preview["outputs"], preview["imported"]
        win = tk.Toplevel(self.root)
        win.title(tr("Reset project"))
        win.transient(self.root)
        win.resizable(False, False)
        text = (tr("Reset '{name}' to an empty set?", name=project.name) + "\n\n"
                + tr("Deleted: the selection ({count} tracks), the analysed track list, the proposals, "
                     "the set list, the transitions and pre-master results, and {files} files "
                     "({mb:.1f} MB) in premaster/, fx/ and exports/.",
                     count=len(project.selection), files=outputs['files'], mb=outputs['bytes'] / 1e6) + "\n\n"
                + tr("Kept: the project name, its options and notes, the analysis cache and your library."))
        ttk.Label(win, text=text, justify=tk.LEFT, wraplength=520).pack(padx=16, pady=(16, 8), anchor="w")
        delete_imported = tk.BooleanVar(value=False)
        if imported["files"]:
            ttk.Checkbutton(win, text=tr("Also delete the imported copies in source/ ({files} files, {mb:.1f} MB)",
                                         files=imported['files'], mb=imported['bytes'] / 1e6), variable=delete_imported).pack(padx=16, anchor="w")
        buttons = ttk.Frame(win)
        buttons.pack(fill=tk.X, padx=16, pady=16)

        def confirm():
            choice = bool(delete_imported.get())
            win.destroy()
            self._do_reset(choice)
        ttk.Button(buttons, text=tr("Reset project"), command=confirm).pack(side=tk.RIGHT)
        ttk.Button(buttons, text=tr("Cancel"), command=win.destroy).pack(side=tk.RIGHT, padx=6)
        win.grab_set()

    def _do_reset(self, delete_imported=False):
        project = self.project
        try:
            result = project.reset(delete_imported=delete_imported)
        except OSError as e:
            self._report_error(tr("Reset failed (is a file open in another program?): {error}", error=e), e)
            self.load_project(project.folder)
            return None
        log.info("Project '%s' reset: %s files deleted (%.1f MB)", project.name, result['files_deleted'], result['bytes_deleted'] / 1e6)
        self.load_project(project.folder)
        self.update_status(tr("Project '{name}' reset: {files} files deleted ({mb:.1f} MB)", name=project.name,
                              files=result['files_deleted'], mb=result['bytes_deleted'] / 1e6))
        return result

    def clear_analysis_cache(self):
        if not self._require_project():
            return
        paths = list(self.project.selection)
        if not paths:
            messagebox.showinfo(tr("Clear analysis cache"), tr("The selection is empty: nothing to clear.\n"
                                                                "(The Configuration tab can clear the whole cache.)"))
            return
        if not messagebox.askyesno(tr("Clear analysis cache"),
                                   tr("Forget the analysis results (features, intro/outro, mastering, bands) of the "
                                      "{count} selected tracks?\n\nThey will be analysed again. The selection is kept; "
                                      "the set list comes back after 'Analyze selection'.", count=len(paths)), icon="warning"):
            return
        self._do_clear_analysis_cache(paths)

    def _do_clear_analysis_cache(self, paths):
        removed = get_store().clear_paths(paths)
        log.info("Analysis cache: %s results removed for %d selected tracks", removed, len(paths))
        self._after_cache_cleared()
        self.update_status(tr("Analysis cache: {removed} results removed for {count} selected tracks", removed=removed, count=len(paths)))
        return removed

    def _after_cache_cleared(self):
        """Cached analyses are gone: the project must analyse its selection again."""
        if self.project is not None:
            self.project.forget_analysis()
            self.playlist_manager.tracks = []
            self.current_set_list = None
            self.transition_planner = None
            self._save_project()
            self._refresh_tables()
            self._render_overview()
            self._refresh_fx_tab()
        self.rescan_library()

    def load_project(self, folder):
        """Open a project folder and restore its state (no audio work)."""
        try:
            self.project = SetProject.open(folder)
        except FileNotFoundError as e:
            messagebox.showerror(tr("Error"), str(e))
            return
        project = self.project
        project.ensure_dirs()
        opts = project.options
        self.set_duration_var.set(int(opts.get("set_duration", 60)))
        self.energy_curve_var.set(opts.get("energy_curve", "build"))
        self.premaster_lufs_var.set(float(opts.get("target_lufs", -14.0)))
        self.premaster_tone_var.set(bool(opts.get("tone_match", True)))
        self.premaster_phase_var.set(bool(opts.get("fix_phase", True)))
        mono_hz = float(opts.get("mono_bass_hz", 120.0) or 0)
        self.mono_bass_var.set(mono_hz > 0)
        if mono_hz > 0:
            self.mono_bass_hz_var.set(mono_hz)
        self.use_premaster_var.set(bool(opts.get("use_premaster", True)))
        self._track_source_choice = None  # the Track tab analyses the file the set plays again
        
        manager = PlaylistManager(project.folder)
        manager.tracks = list(project.tracks)
        self.playlist_manager = manager
        self.current_set_list = project.set_list_tracks() or None
        self.transition_planner = self._planner_from_project()

        self.project_path_label.config(text=tr("{folder}   ·   {count} selected tracks   ·   library: {library}", folder=project.folder,
                                               count=len(project.selection),
                                               library=self.config.get('library_folder') or tr("not set (Configuration tab)")))
        self.refresh_project_list()
        self._refresh_tables()
        self._refresh_library_table()
        self._refresh_workflow()
        self._clear_frame(self.overview_frame, tr("Analyze the tracks and build a set list to see the energy curve and the set map."))
        self._render_overview()
        self._render_premaster()
        self._refresh_fx_tab()
        self._reports_refresh()
        self.update_status(tr("Project '{name}' loaded", name=project.name))
    
    def _save_project(self):
        if self.project is None:
            return
        self.project.options.update({
            "set_duration": int(self.set_duration_var.get()),
            "energy_curve": (self.energy_curve_var.get() if self.energy_curve_var.get() in set_proposer.CURVES
                             else self.project.options.get("energy_curve", "build")),
            "target_lufs": float(self.premaster_lufs_var.get()),
            "tone_match": bool(self.premaster_tone_var.get()),
            "fix_phase": bool(self.premaster_phase_var.get()),
            "mono_bass_hz": float(self.mono_bass_hz_var.get()) if bool(self.mono_bass_var.get()) else 0.0,
            "use_premaster": bool(self.use_premaster_var.get()),
        })
        self.project.save()
        self._refresh_workflow()
    
    def _require_project(self):
        if self.project is None:
            messagebox.showinfo(tr("Project"), tr("Create or open a project first ('New project...')"))
            return False
        return True

    def _report_error(self, message, exc=None):
        """Log an error (with its traceback) and show it; safe to call from a worker thread."""
        log.error(message, exc_info=exc)
        self.root.after(0, messagebox.showerror, tr("Error"), message)

    def _planner_from_project(self):
        data = self.project.data.get("transitions") if self.project else None
        if not data or not data.get("tracks"):
            return None
        planner = TransitionPlanner(self.project.set_list_tracks() or self.project.tracks)
        planner.profiles = list(data["tracks"])
        planner.transitions = list(data.get("transitions") or [])
        return planner
    
    def _refresh_workflow(self):
        if self.project is None:
            return
        for key, label, required in STEPS:
            state = self.project.step_state(key)
            w = self.step_widgets[key]
            w["status"].config(text="✓" if state.get("done") else "○")
            details = state.get("details") or {}
            parts = []
            if state.get("at"):
                parts.append(state["at"].replace("T", " ")[:16])
            for k in ("count", "cached", "analyzed", "manual", "duration", "curve", "score", "file", "playlist", "cues"):
                if k in details:
                    parts.append(tr(STEP_DETAILS[k], value=details[k]) if k != "manual" else tr("edited by hand"))
            w["detail"].config(text=" · ".join(parts))
        key, hint = self.project.next_step()
        self.next_step_label.config(text=tr("Next: {hint}", hint=tr(hint)))
        self.audio_used_label.config(text=self.project.audio_used_text(translate=tr))
        try:
            stats = get_store().stats()
            self.cache_label.config(text=tr("Analysis cache: {files} files, {entries} results", files=stats['files'], entries=stats['entries']))
        except Exception:
            pass
    
    def show_project_summary(self):
        if not self._require_project():
            return
        self.add_report(tr("Project summary"), "\n".join(self.project.summary_lines()))

    def _use_premaster_changed(self):
        if self.project is None:
            return
        use = bool(self.use_premaster_var.get())
        if not self.project.set_use_premaster(use):
            return
        self._save_project()
        self._refresh_tables()
        self._render_overview()
        self._refresh_transition_measurements()
        if self.fx_panel is not None:
            self.fx_panel.refresh_sources()
            self.fx_panel.schedule_chart()
        log.info("%s: apply the FX, write the playlist and export to Mixxx again",
                 "The pre-mastered copies are used" if use else "The originals are used, not the pre-mastered copies")
        self.update_status(tr("The pre-mastered copies are used: apply the FX, write the playlist and export to Mixxx again") if use
                           else tr("The originals are used, not the pre-mastered copies: apply the FX, write the playlist and "
                                   "export to Mixxx again"))

    # ------------------------------------------------------------------ snapshots
    def open_snapshots(self):
        """Save the project's settings as a snapshot, restore or delete one."""
        if not self._require_project():
            return
        project = self.project
        win = tk.Toplevel(self.root)
        win.title(tr("Snapshots - {name}", name=project.name))
        win.geometry("700x380")
        win.transient(self.root)
        ttk.Label(win, text=tr("A snapshot keeps the project's settings (selection, set list, transitions, FX settings, options), "
                               "not the audio copies. Restoring saves the current state first ('before restore')."),
                  foreground=MUTED, wraplength=660, justify=tk.LEFT).pack(anchor="w", padx=10, pady=(10, 4))
        tree = ttk.Treeview(win, columns=("Saved", "Name", "Set list", "FX"), show="headings", selectmode="browse")
        for col, width in (("Saved", 150), ("Name", 300), ("Set list", 70), ("FX", 60)):
            tree.heading(col, text=tr(col))
            tree.column(col, width=width, anchor="w" if col in ("Saved", "Name") else "center", stretch=(col == "Name"))
        tree.pack(fill=tk.BOTH, expand=True, padx=10)

        def fill():
            tree.delete(*tree.get_children())
            for s in project.list_snapshots():
                tree.insert("", tk.END, iid=s["path"], values=(s["at"].replace("T", " "), s["label"], s["set_list"], s["fx"]))

        def chosen():
            sel = tree.selection()
            return sel[0] if sel else None

        def save():
            label = simpledialog.askstring(tr("Save snapshot"), tr("Name of this snapshot:"), parent=win)
            if label is not None:
                self._do_save_snapshot(label)
                fill()

        def restore():
            path = chosen()
            if path and messagebox.askyesno(tr("Restore snapshot"), tr("Replace the project's current settings with this snapshot?\n\n"
                                                  "The current state is saved first as 'before restore'."), parent=win):
                self._do_restore_snapshot(path)
                fill()

        def delete():
            path = chosen()
            if path and messagebox.askyesno(tr("Delete snapshot"), tr("Delete the snapshot '{name}'?", name=tree.item(path, 'values')[1]),
                                            parent=win):
                self._do_delete_snapshot(path)
                fill()

        buttons = ttk.Frame(win)
        buttons.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(buttons, text=tr("Save current state..."), command=save).pack(side=tk.LEFT)
        ttk.Button(buttons, text=tr("Restore"), command=restore).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text=tr("Delete"), command=delete).pack(side=tk.LEFT)
        ttk.Button(buttons, text=tr("Close"), command=win.destroy).pack(side=tk.RIGHT)
        fill()
        return win

    def _do_save_snapshot(self, label):
        self._save_project()
        path = self.project.save_snapshot(label)
        log.info("Snapshot saved: %s", path)
        self.update_status(tr("Snapshot saved: {file}", file=os.path.basename(path)))
        return path

    def _do_restore_snapshot(self, path):
        project = self.project
        try:
            result = project.restore_snapshot(path)
        except (OSError, ValueError, KeyError) as e:
            self._report_error(tr("Cannot restore the snapshot: {error}", error=e), e)
            return None
        self.load_project(project.folder)
        stale = result["stale"]
        name = os.path.basename(path)
        log.info("Snapshot restored: %s%s; write the playlist and export to Mixxx again", name,
                 f"; to redo because the audio copies changed since: {', '.join(stale)}" if stale else "")
        if stale:
            self.update_status(tr("Snapshot restored: {file}; to redo because the audio copies changed since: {stale}; "
                                  "write the playlist and export to Mixxx again", file=name, stale=", ".join(stale)))
        else:
            self.update_status(tr("Snapshot restored: {file}; write the playlist and export to Mixxx again", file=name))
        return result

    def _do_delete_snapshot(self, path):
        try:
            os.remove(path)
        except OSError as e:
            self._report_error(tr("Cannot delete the snapshot: {error}", error=e), e)
            return False
        log.info("Snapshot deleted: %s", path)
        return True
    
    # ------------------------------------------------------------------ tables
    def _mastering_by_path(self):
        """file path -> mastering report, with the mix-revision verdict folded into its flags."""
        out = {}
        planner = self.transition_planner
        if planner:
            for p in planner.profiles:
                if p.get("mastering") or p.get("bands"):
                    m = dict(p.get("mastering") or {"flags": [], "score": None})
                    kind, reasons = mix_recommendation(p.get("bands"), p.get("mastering"))
                    if kind == "mix":
                        m = dict(m, flags=["MIX REVISION: " + "; ".join(reasons)])
                    out[p.get("file_path")] = m
        return out
    
    def _row_values(self, track, index, mastering, with_set=False):
        bpm = track.get("bpm", 0) or 0
        duration = track.get("duration", 0) or 0
        energy = track.get("energy_level", 0) or 0
        score = mastering.get("score") if mastering else None
        values = [index, track.get("filename", ""), f"{bpm:.1f}" if bpm else "-", track.get("key") or "-",
                  f"{duration / 60:.1f}" if duration else "-", f"{energy:.1f}" if energy else "-",
                  f"{score:.0f}" if score is not None else "-"]
        if with_set:
            values.append(track.get("set_position") or "")
        flags = (mastering or {}).get("flags") or []
        if mastering and not flags:
            values.append("OK")
        elif flags:
            text = "; ".join(flags)
            values.append(text if len(text) <= 90 else text[:89] + "…")
        else:
            values.append("")
        return values
    
    @staticmethod
    def _fmt_time(seconds):
        """h:mm:ss or m:ss, '-' when unknown."""
        if not seconds:
            return "-"
        total = int(round(float(seconds)))
        hours, rest = divmod(total, 3600)
        minutes, secs = divmod(rest, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    @staticmethod
    def _short_values(row, duration, last):
        """Filename, Dur, BPM, Key, Energy, <last> (library and selection tables)."""
        bpm = row.get("bpm") or 0
        energy = row.get("energy_level") or 0
        return [row.get("filename", ""), SetBuilderMixin._fmt_time(duration), f"{bpm:.1f}" if bpm else "-",
                row.get("key") or "-", f"{energy:.1f}" if energy else "-", last]

    def _refresh_library_table(self, caption=None):
        tree = self.library_tree
        for item in tree.get_children():
            tree.delete(item)
        selected = set(self.project.selection) if self.project else set()
        rows = library.filter_entries(self._library_entries, self.library_filter_var.get())
        self._library_rows = rows
        for i, entry in enumerate(rows, 1):
            tree.insert("", tk.END, iid=f"L{i}",
                        values=self._short_values(entry, entry.get("duration"), "✓" if entry["file_path"] in selected else ""))
        folder = self.config.get("library_folder") or ""
        if caption is None:
            if not folder:
                caption = tr("Library: set the library folder in the Configuration tab")
            elif self._library_scanning:
                caption = tr("Library: scanning {folder} ...", folder=folder)
            else:
                total = len(self._library_entries)
                hours = sum(e.get("duration") or 0 for e in self._library_entries) / 3600
                if len(rows) != total:
                    caption = tr("Library: {shown} shown of {total} tracks, {hours:.1f} h ({folder})", shown=len(rows), total=total,
                                 hours=hours, folder=folder)
                else:
                    caption = tr("Library: {total} tracks, {hours:.1f} h ({folder})", total=total, hours=hours, folder=folder)
        self.library_caption.config(text=caption)

    def rescan_library(self):
        """Scan the library folder in the background (headers and cache only, no audio decoding)."""
        folder = (self.config.get("library_folder") or "").strip()
        if not folder:
            self._library_entries = []
            self._refresh_library_table()
            return
        if self._library_scanning:
            self._library_rescan_pending = True  # scan again when the running scan ends
            return
        self._library_scanning = True
        self._refresh_library_table()

        def work(task):
            try:
                entries = library.scan(folder, progress=lambda i, n, name: task.progress(i, n, name))
            except Exception as e:
                entries = []
                self._report_error(tr("Library scan failed: {error}", error=e), e)

            def done():
                self._library_scanning = False
                self._library_entries = entries
                self._refresh_library_table()
                self.update_status(tr("Library: {count} tracks in {folder}", count=len(entries), folder=folder))
                if self._library_rescan_pending:
                    self._library_rescan_pending = False
                    self.rescan_library()
            self.root.after(0, done)
        self._start_task(tr("Scan library"), work, cancellable=False)

    def _merge_into_library(self, tracks):
        """Show freshly analysed values in the library table without rescanning."""
        by_path = {t["file_path"]: t for t in tracks}
        for entry in self._library_entries:
            t = by_path.get(entry["file_path"])
            if t:
                entry.update(analysed=True, duration=t.get("duration") or entry.get("duration"),
                             bpm=t.get("bpm") or None, key=t.get("key") or None, energy_level=t.get("energy_level") or None)

    def _refresh_tables(self):
        self._previewing = False
        for tree in (self.selection_tree, self.set_tree, self.proposal_tree):
            for item in tree.get_children():
                tree.delete(item)
        self._selection_rows, self._set_rows = [], []
        if self.project is None:
            return
        mastering = self._mastering_by_path()
        lib_by_path = {e["file_path"]: e for e in self._library_entries}
        for i, row in enumerate(self.project.selection_rows(), 1):
            row["duration"] = row.get("duration") or lib_by_path.get(row["file_path"], {}).get("duration")
            self.selection_tree.insert("", tk.END, iid=f"C{i}", values=self._short_values(row, row["duration"], tr(TRACK_STATES.get(row["state"], row["state"]))))
            self._selection_rows.append(row)
        for i, t in enumerate(self.project.set_list_tracks(), 1):
            self.set_tree.insert("", tk.END, iid=f"S{i}", values=self._row_values(t, i, mastering.get(t["file_path"])))
            self._set_rows.append(t)
        for i, variant in enumerate(self.project.proposal_variants(), 1):
            self.proposal_tree.insert("", tk.END, iid=f"P{i}", values=self._proposal_values(i, variant))
        counts = collections.Counter(r["state"] for r in self._selection_rows)
        others = ", ".join(f"{n} {tr(TRACK_STATES.get(state, state))}" for state, n in sorted(counts.items()) if state != "analysed")
        sel_seconds = sum(float(r.get("duration") or 0) for r in self._selection_rows)
        self.selection_caption.config(text=tr("Selection: {count} tracks · {duration}", count=len(self._selection_rows),
                                              duration=self._fmt_time(sel_seconds))
                                           + (f" ({others})" if others else ""))
        set_seconds = sum(float(t.get("duration") or 0) for t in self._set_rows)
        self.set_caption.config(text=tr("Set list: {count} tracks, {duration} — playing order", count=len(self._set_rows),
                                        duration=self._fmt_time(set_seconds)))
    
    def _selected(self, tree, rows):
        sel = tree.selection()
        if not sel:
            return None
        try:
            idx = int(sel[0][1:]) - 1
        except ValueError:
            return None
        return rows[idx] if 0 <= idx < len(rows) else None

    def _selected_many(self, tree, rows):
        out = []
        for iid in tree.selection():
            try:
                idx = int(iid[1:]) - 1
            except ValueError:
                continue
            if 0 <= idx < len(rows):
                out.append(rows[idx])
        return out

    def _after_manual_edit(self):
        curve = (self.project.step_state("setlist").get("details") or {}).get("curve")
        extra = {"curve": curve} if curve else {}
        self.project.mark("setlist", count=len(self.project.set_list), manual=True, **extra)
        self.current_set_list = self.project.set_list_tracks() or None
        self.transition_planner = None
        self._save_project()
        self._refresh_tables()
        self._render_overview()
    
    def selection_add(self):
        if not self._require_project():
            return
        entries = self._selected_many(self.library_tree, self._library_rows)
        if not entries:
            return
        added = self.project.add_to_selection([e["file_path"] for e in entries])
        log.info("Selection: %s tracks added (%d selected)", added, len(self.project.selection))
        self._after_selection_change(tr("Selection: {count} tracks added ({selected} selected)", count=added,
                                        selected=len(self.project.selection)))

    def selection_remove(self):
        if not self._require_project():
            return
        rows = self._selected_many(self.selection_tree, self._selection_rows)
        if not rows:
            return
        removed = self.project.remove_from_selection([r["file_path"] for r in rows])
        log.info("Selection: %s tracks removed (%d selected)", removed, len(self.project.selection))
        self._after_selection_change(tr("Selection: {count} tracks removed ({selected} selected)", count=removed,
                                        selected=len(self.project.selection)))

    def _after_selection_change(self, message):
        self.playlist_manager.tracks = list(self.project.tracks)
        self.current_set_list = self.project.set_list_tracks() or None
        self.transition_planner = None
        self._save_project()
        self._refresh_tables()
        self._refresh_library_table()
        self._render_overview()
        self.update_status(message)

    def set_add(self):
        if not self._require_project() or self._end_preview():
            return
        rows = [r for r in self._selected_many(self.selection_tree, self._selection_rows) if r["state"] == "analysed"]
        if not rows:
            messagebox.showinfo(tr("Set list"), tr("Select analysed tracks in the Selection first"))
            return
        # insert after the selected set-list row, else at the end
        current = self._selected(self.set_tree, self._set_rows)
        position = (self.project.set_list.index(current["file_path"]) + 1) if current else None
        for offset, row in enumerate(rows):
            self.project.add_to_set(row["file_path"], None if position is None else position + offset)
        self._after_manual_edit()
    
    def set_remove(self):
        if not self._require_project() or self._end_preview():
            return
        track = self._selected(self.set_tree, self._set_rows)
        if track is None:
            return
        self.project.remove_from_set(track["file_path"])
        self._after_manual_edit()
    
    def set_move(self, delta):
        if not self._require_project() or self._end_preview():
            return
        track = self._selected(self.set_tree, self._set_rows)
        if track is None:
            return
        j = self.project.move_in_set(track["file_path"], delta)
        self._after_manual_edit()
        if j >= 0:
            self.set_tree.selection_set(f"S{j + 1}")
            self.set_tree.see(f"S{j + 1}")
    
    # ------------------------------------------------------------------ steps
    def analyze_playlist(self):
        if not self._require_project():
            return
        project = self.project
        files = project.selection_files()
        if not files:
            messagebox.showwarning(tr("Warning"), tr("No selected tracks on disk: pick tracks in the Library and click 'Add to selection →'."))
            return
        
        def work(task):
            try:
                task.progress(0, len(files))
                manager = PlaylistManager(project.folder)
                manager.analyze_playlist(files, progress_callback=lambda i, n, name, status: task.progress(i, n, name))
                run = manager.last_run
                task.check()  # stopped: the project is left unchanged (the analysed tracks stay in the cache)
                
                def done():
                    # the selection may have changed while the worker ran: keep selected records only
                    selected = set(project.selection)
                    records = [t for t in manager.tracks if t["file_path"] in selected]
                    before = {t["file_path"] for t in project.tracks}
                    after = {t["file_path"] for t in records}
                    project.set_tracks(records, attempted=files)
                    if before and before != after:
                        project.invalidate_from("analyze")
                    added = sum(1 for r in project.selection_rows() if r["state"] == "pending")
                    if added:
                        project.mark("analyze", done=False)
                        log.info("%d tracks were added during the analysis: click 'Analyze selection' again", added)
                    else:
                        project.mark("analyze", count=len(records), cached=run["cached"], analyzed=run["analyzed"])
                    if self.project is not project:
                        project.save()
                        log.info("Analysis of project '%s' saved (another project was opened meanwhile)", project.name)
                        return
                    manager.tracks = records
                    self.playlist_manager = manager
                    self.current_set_list = project.set_list_tracks() or None
                    if not self.current_set_list:
                        self.transition_planner = None
                    self._save_project()
                    self._merge_into_library(records)
                    self._refresh_tables()
                    self._refresh_library_table()
                    self._render_overview()
                    log.info("Analysis: %d tracks (%s from cache, %s new, %s failed)", len(records), run['cached'], run['analyzed'],
                             run['failed'])
                    failed = [os.path.basename(p) for p in project.data.get("failed") or []]
                    if failed:
                        log.warning("Analysis failed for %d tracks: %s", len(failed), ", ".join(failed))
                    self.update_status(tr("Analysis: {count} tracks ({cached} from cache, {analyzed} new, {failed} failed)",
                                          count=len(records), cached=run['cached'], analyzed=run['analyzed'], failed=run['failed']))
                self.root.after(0, done)
            except Exception as e:
                self._task_failed(task, tr("Analysis failed: {error}", error=e), e)

        self.update_status(tr("Analyzing {count} tracks ...", count=len(files)))
        self._start_task(tr("Analyze selection"), work)
    
    def create_set_list(self):
        """Compute proposals from the analysed selection (worker thread); the set list changes on 'Use this proposal'."""
        if not self._require_project():
            return
        project = self.project
        tracks, skipped = project.proposal_tracks()
        if not tracks:
            messagebox.showwarning(tr("Warning"), tr("No analysed tracks in the selection: add tracks, then click 'Analyze selection'"))
            return
        if skipped:
            log.warning("Proposals: %d selected tracks left out (not analysed or missing): %s", len(skipped), ", ".join(skipped))
        duration = int(self.set_duration_var.get())
        curve = self.energy_curve_var.get()
        mix_bars = self._mix_bars()

        def work(task):
            try:
                if curve == "all":
                    variants = []
                    for n, c in enumerate(set_proposer.CURVES):
                        task.progress(n, len(set_proposer.CURVES), c)
                        variants.append(set_proposer.propose(tracks, duration * 60, curve=c, mix_bars=mix_bars, variants=1)[0])
                    variants.sort(key=lambda v: (-v["score"], v["cost"]))
                else:
                    variants = set_proposer.propose(tracks, duration * 60, curve=curve, mix_bars=mix_bars, variants=3)
            except Exception as e:
                self._task_failed(task, tr("Proposal failed: {error}", error=e), e)
                return
            task.check()

            def done():
                if self.project is not project:
                    return  # another project was opened meanwhile
                project.set_proposals({"duration_min": duration, "curve": curve, "mix_bars": mix_bars}, variants)
                self._save_project()
                self._refresh_tables()
                best = max(v['score'] for v in variants)
                log.info("Proposals: %d variants for %s min (%s) from %d tracks, best score %s", len(variants), duration, curve,
                         len(tracks), best)
                self.update_status(tr("Proposals: {count} variants for {duration} min ({curve}) from {tracks} tracks, best score {score}"
                                      " - select one to preview it, then 'Use this proposal'", count=len(variants), duration=duration,
                                      curve=curve, tracks=len(tracks), score=best))
                self.proposal_tree.selection_set("P1")
            self.root.after(0, done)

        self.update_status(tr("Computing proposals from {count} tracks ...", count=len(tracks)))
        self._start_task(tr("Propose"), work)

    @staticmethod
    def _proposal_values(number, variant):
        worst = variant.get("worst")
        duration = f"{SetBuilderMixin._fmt_time(variant['effective_seconds'])} / {SetBuilderMixin._fmt_time(variant['target_seconds'])}"
        return [number, variant["curve"], len(variant["order"]), duration, variant["score"],
                f"{worst['index'] + 1}→{worst['index'] + 2} · {worst['score']}" if worst else "-"]

    def _selected_proposal(self):
        """(variant, index) of the selected row of the Proposals table, else (None, None)."""
        sel = self.proposal_tree.selection()
        if not sel or self.project is None:
            return None, None
        index = int(sel[0][1:]) - 1
        variants = self.project.proposal_variants()
        return (variants[index], index) if 0 <= index < len(variants) else (None, None)

    def preview_proposal(self):
        """Show the selected proposal in the set list table (greyed) and the Overview, without saving."""
        variant, index = self._selected_proposal()
        if variant is None:
            return
        by_path = {t["file_path"]: t for t in self.project.tracks}
        tracks = [by_path[p] for p in variant["order"] if p in by_path]
        for item in self.set_tree.get_children():
            self.set_tree.delete(item)
        mastering = self._mastering_by_path()
        for i, t in enumerate(tracks, 1):
            self.set_tree.insert("", tk.END, iid=f"S{i}", values=self._row_values(t, i, mastering.get(t["file_path"])),
                                 tags=("preview",))
        self._set_rows = tracks
        self._previewing = True
        self.set_caption.config(text=tr("Preview of proposal {number} ({curve}, score {score}): {count} tracks, {duration} — "
                                        "'Use this proposal' to keep it", number=index + 1, curve=variant['curve'],
                                        score=variant['score'], count=len(tracks), duration=self._fmt_time(variant['effective_seconds'])))
        self._clear_frame(self.overview_frame)
        self._show_figure(self.overview_frame,
                          charts.set_overview(tracks, set_proposer.curve_targets(tracks, variant["curve"], self._mix_bars())))

    def use_selected_proposal(self):
        if not self._require_project():
            return
        variant, index = self._selected_proposal()
        if variant is None:
            messagebox.showinfo(tr("Proposals"), tr("Select a proposal first (click 'Propose' when the list is empty)"))
            return
        self.project.use_proposal(index)
        self.current_set_list = self.project.set_list_tracks() or None
        self.transition_planner = None
        self._save_project()
        self._refresh_tables()
        self._render_overview()
        log.info("Proposal %d (%s, score %s) is now the set list: %d tracks", index + 1, variant['curve'], variant['score'],
                 len(self.project.set_list))
        self.update_status(tr("Proposal {number} ({curve}, score {score}) is now the set list: {count} tracks", number=index + 1,
                              curve=variant['curve'], score=variant['score'], count=len(self.project.set_list)))

    def _end_preview(self):
        """If a proposal preview is showing, show the set list again and return True (the edit is skipped)."""
        if not self._previewing:
            return False
        self._refresh_tables()
        self._render_overview()
        self.update_status(tr("Preview closed: the set list is shown again (click again to edit it)"))
        return True

    def _mix_bars(self):
        return int(self.project.options.get("mix_bars", 8)) if self.project else 8

    def _set_curve(self):
        """Curve of the current set list: the one of the proposal it came from, else the chosen curve."""
        details = {}
        if self.project is not None:
            details = self.project.step_state("setlist").get("details") or {}
        return details.get("curve") or self.energy_curve_var.get()
    
    def _set_tracks_or_warn(self):
        tracks = self.project.set_list_tracks() if self.project else []
        if len(tracks) < 2:
            messagebox.showwarning(tr("Warning"), tr("The set list needs at least two tracks: click 'Propose' or add tracks in the Tracks tab"))
            return None
        return tracks
    
    def plan_transitions(self):
        if not self._require_project():
            return
        tracks = self._set_tracks_or_warn()
        if tracks is None:
            return
        project = self.project
        measure = project.premaster_map()  # measured on the files the set plays; the cues come from the tracks

        def work(task):
            try:
                planner = TransitionPlanner(tracks, mix_bars=int(project.options.get("mix_bars", 8)))
                planner.plan(progress_callback=lambda i, n, name: task.progress(i - 1, n, name), measure=measure)
                task.check()
                
                def done():
                    project.set_transitions(planner.to_dict())
                    if self.project is not project:
                        project.save()
                        log.info("Transitions of project '%s' saved (another project was opened meanwhile)", project.name)
                        return
                    self.transition_planner = planner
                    self._save_project()
                    self._refresh_tables()
                    self._render_overview()
                    self._refresh_fx_tab()
                    self._transition_report()
                self.root.after(0, done)
            except Exception as e:
                self._task_failed(task, tr("Transition planning failed: {error}", error=e), e)

        self.update_status(tr("Planning transitions for {count} tracks ...", count=len(tracks)))
        self._start_task(tr("Plan transitions"), work)
    
    def mastering_report(self):
        if not self._require_project():
            return
        tracks = self.project.set_list_tracks() or self.project.tracks
        originals = [t["file_path"] for t in tracks] or self.project.selection_files()
        if not originals:
            messagebox.showwarning(tr("Warning"), tr("No audio files in the project"))
            return
        files, note = self._played_files(originals)

        def work(task):
            try:
                reports = check_files(files, progress=lambda i, n, name: task.progress(i, n, name))
                task.check()
                for report, original, path in zip(reports, originals, files):
                    if path != original:
                        report["filename"] = f"{report.get('filename', '')} [pre-mastered copy]"
                summary = note + "\n\n" + format_check_summary(reports)
                self.root.after(0, self.add_report, tr("Mastering Report"), summary, False)
                flagged = sum(1 for r in reports if r.get("flags"))
                self.root.after(0, self.update_status, tr("Mastering check done: {flagged}/{count} tracks with issues "
                                                         "(report in the Log tab)", flagged=flagged, count=len(reports)))
            except Exception as e:
                self._task_failed(task, tr("Mastering check failed: {error}", error=e), e)

        self.update_status(tr("Checking mastering of {count} tracks ...", count=len(files)))
        self._start_task(tr("Mastering Report"), work)
    
    def band_report(self):
        """Band tracking, low-mid masking and resonances for the set list (or the library)."""
        if not self._require_project():
            return
        tracks = self.project.set_list_tracks() or self.project.tracks
        if not tracks:
            messagebox.showwarning(tr("Warning"), tr("Analyze the tracks first"))
            return
        
        files, note = self._played_files([t["file_path"] for t in tracks])

        def work(task):
            try:
                reports = []
                for i, (t, path) in enumerate(zip(tracks, files), 1):
                    task.progress(i - 1, len(tracks), t.get("filename", ""))
                    label = os.path.basename(path) + (" [pre-mastered copy]" if path != t["file_path"] else "")
                    try:
                        report = analyze_bands_cached(path, bpm=float(t.get("bpm") or 0) or None)
                        reports.append(dict(report, key=t.get("key"), filename=label))  # the key names the resonances' notes
                    except Exception as exc:
                        reports.append({"filename": label, "error": str(exc)})
                task.progress(len(tracks), len(tracks))
                summary = note + "\n\n" + format_band_summary(reports)
                needs_mix = [r["filename"] for r in reports if r.get("verdict") == "mix"]
                if needs_mix:
                    summary = (f"MIX REVISION RECOMMENDED for {len(needs_mix)}/{len(reports)} tracks: " + ", ".join(needs_mix)
                               + "\n\n" + summary)
                self.root.after(0, self.add_report, tr("Band Analysis"), summary, False)
                self.root.after(0, self.update_status, tr("Band analysis done: {count}/{total} tracks need a mix "
                                                         "revision (report in the Log tab)", count=len(needs_mix), total=len(reports)))
            except Exception as e:
                self._task_failed(task, tr("Band analysis failed: {error}", error=e), e)

        self.update_status(tr("Band analysis of {count} tracks ...", count=len(tracks)))
        self._start_task(tr("Band Analysis"), work)
    
    def premaster_set(self):
        if not self._require_project():
            return
        tracks = self.project.set_list_tracks() or self.project.tracks
        files = [t["file_path"] for t in tracks]
        if not files:
            messagebox.showwarning(tr("Warning"), tr("Analyze the tracks first"))
            return
        project = self.project
        out_dir = project.premaster_dir
        target_lufs = float(self.premaster_lufs_var.get())
        tone = bool(self.premaster_tone_var.get())
        phase = bool(self.premaster_phase_var.get())
        mono_hz = float(self.mono_bass_hz_var.get()) if bool(self.mono_bass_var.get()) else 0.0
        fmt = self.config.get("output_format", "same")
        
        def work(task):
            try:
                results = premaster_files(files, out_dir, target_lufs=target_lufs, tone_match=tone, repair_phase=phase, fmt=fmt,
                                          mono_bass_hz=mono_hz,
                                          progress=lambda i, n, name: task.progress(i, n, name))
                task.check()  # stopped: the copies already written are overwritten next time, the project is unchanged
                summary = format_premaster_summary(results, out_dir)
                done_count = sum(1 for r in results if "error" not in r)
                
                def done():
                    keep = ("lufs", "true_peak_db", "plr", "score", "clip_runs", "flags")
                    slim = [({"input": r["input"], "error": r["error"]} if "error" in r else
                             {"input": r["input"], "output": r["output"], "actions": r["actions"],
                              "before": {k: r["before"].get(k) for k in keep}, "after": {k: r["after"].get(k) for k in keep}})
                            for r in results]
                    project.invalidate_from("premaster")  # FX renders were made from the previous copies
                    project.data["premaster"] = {"out_dir": out_dir, "target_lufs": target_lufs, "tone_match": tone,
                                                 "fix_phase": phase, "mono_bass_hz": mono_hz, "results": slim, "summary": summary}
                    project.mark("premaster", count=done_count)
                    if self.project is not project:
                        project.save()
                        log.info("Pre-master of project '%s' saved (another project was opened meanwhile)", project.name)
                        return
                    self._save_project()
                    self._render_premaster()
                    self._refresh_fx_tab()
                    self._refresh_transition_measurements()
                    self.add_report(tr("Pre-master"), summary, show=False)
                    self.update_status(tr("Pre-master done: {done}/{count} tracks written to {folder} (report in the Log tab)",
                                          done=done_count, count=len(results), folder=out_dir))
                self.root.after(0, done)
            except Exception as e:
                self._task_failed(task, tr("Pre-master failed: {error}", error=e), e)

        self.update_status(tr("Pre-mastering {count} tracks into {folder} ...", count=len(files), folder=out_dir))
        self._start_task(tr("Pre-master Set"), work)
    
    def _with_rendered(self, tracks):
        """Tracks pointing at the file to play: FX copy (with its cue positions), else pre-master, else original."""
        if self.project is None:
            return list(tracks), {"fx": 0, "premaster": 0}
        return self.project.rendered_profiles(list(tracks))

    @staticmethod
    def _copies_note(counts, translate=False):
        """'2 FX copies, 3 pre-mastered copies'; English for the reports, translated for the status bar."""
        if translate:
            parts = ([tr("{count} FX copies", count=counts["fx"])] if counts["fx"] else []) + \
                    ([tr("{count} pre-mastered copies", count=counts["premaster"])] if counts["premaster"] else [])
        else:
            parts = [f"{counts[k]} {label}" for k, label in (("fx", "FX copies"), ("premaster", "pre-mastered copies")) if counts[k]]
        return ", ".join(parts)

    def _fx_labels(self):
        """Transition index -> its enabled FX types (for the set map)."""
        if self.project is None:
            return {}
        labels = {}
        lst = self.project.set_list
        for i, (a, b) in enumerate(zip(lst, lst[1:])):
            entry = self.project.fx_for_pair(a, b) or {}
            types = [fx["type"] for fx in entry.get("effects") or [] if fx.get("enabled", True)]
            if types:
                labels[i] = " · ".join(types)
        return labels

    def open_fx_window(self, player=None):
        """Workflow step 5: show the FX tab (returns its panel, None without a transition plan)."""
        if not self._require_project():
            return None
        if player is not None:
            self._fx_player = player
            if self.fx_panel is not None:
                self.fx_panel.player = player
        panel = self._refresh_fx_tab()
        self.set_notebook.select(self.fx_tab)
        if panel is None:
            messagebox.showwarning(tr("Warning"), tr("Plan the transitions first (step 3)"))
        return panel

    def _refresh_fx_tab(self):
        """Keep the FX tab in step with the open project and its transition plan; returns the panel or None."""
        panel = self.fx_panel
        if panel is not None and panel.winfo_exists():
            if panel.project is self.project and not panel._plan_changed():
                return panel
            if panel._applying:
                return panel  # its render finishes and is discarded if it is stale
            panel.close()
        self.fx_panel = None
        for child in self.fx_tab.winfo_children():
            child.destroy()
        data = self.project.data.get("transitions") if self.project else None
        if not data or len(data.get("tracks") or []) < 2:
            ttk.Label(self.fx_tab, text=tr("Plan the transitions first (step 3): the FX are set per transition of the set list."),
                      foreground=MUTED, wraplength=600).pack(padx=20, pady=20, anchor="w")
            return None
        self.fx_panel = TransitionFxPanel(self.fx_tab, self, player=self._fx_player)
        self.fx_panel.pack(fill=tk.BOTH, expand=True)
        return self.fx_panel

    def _fx_tab_visible(self):
        try:
            return (self.notebook.select() == str(self.set_builder_frame)
                    and self.set_notebook.select() == str(self.fx_tab))
        except tk.TclError:
            return False

    def _fx_tab_changed(self):
        if self._fx_tab_visible():
            if self.project is not None:
                self._refresh_fx_tab()
        elif self.fx_panel is not None and self.fx_panel._previewing:
            self.fx_panel.stop_preview()
    
    def create_playlist_from_directory(self):
        """Write the set list (or the library order) as an M3U into exports/."""
        if not self._require_project():
            return
        from export_tools import ExportTools
        tracks = self.project.set_list_tracks() or self.project.tracks
        if not tracks:
            messagebox.showwarning(tr("Warning"), tr("Nothing to write: analyze the tracks and build a set list first"))
            return
        tracks, counts = self._with_rendered(tracks)
        filename = filedialog.asksaveasfilename(
            title=tr("Save Playlist"), initialdir=self.project.exports_dir, initialfile=f"{self.project.name}.m3u",
            defaultextension=".m3u", filetypes=[(tr("M3U playlist"), "*.m3u"), (tr("M3U8 playlist (UTF-8)"), "*.m3u8"),
                                                (tr("All files"), "*.*")])
        if not filename:
            return
        try:
            ExportTools.export_to_m3u(tracks, filename)
        except Exception as e:
            self._report_error(tr("Playlist creation failed: {error}", error=e), e)
            return
        self.project.mark("playlist", file=os.path.basename(filename), count=len(tracks))
        self._save_project()
        note = f" ({self._copies_note(counts, translate=True)})" if counts["fx"] or counts["premaster"] else ""
        self.add_report(tr("Playlist"), f"{len(tracks)} tracks written to {filename}\n{self.project.audio_used_text()}\n\n"
                        + "\n".join(f"{i:2d}. {t.get('filename', '')}" for i, t in enumerate(tracks, 1)))
        self.update_status(tr("Playlist saved: {count} tracks{note} -> {file}", count=len(tracks), note=note, file=filename))
    
    def export_to_mixxx(self):
        if not self._require_project():
            return
        planner = self.transition_planner
        if planner is None or not planner.profiles:
            messagebox.showwarning(tr("Warning"), tr("Plan the transitions first (step 3)"))
            return
        db_path = self.config.mixxx_db_path()
        if not db_path:
            db_path = filedialog.askopenfilename(
                title=tr("Select the Mixxx database (mixxxdb.sqlite) - close Mixxx first"),
                filetypes=[(tr("Mixxx database"), "mixxxdb.sqlite"), ("SQLite", "*.sqlite"), (tr("All files"), "*.*")])
            if not db_path:
                return
        default_name = f"DynaMix - {self.project.name}"
        playlist_name = simpledialog.askstring(tr("Mixxx playlist"), tr("Name of the Mixxx playlist to create:"),
                                               initialvalue=default_name, parent=self.root)
        if playlist_name is None:
            return
        if not messagebox.askyesno(tr("Export to Mixxx"), tr("Database: {path}\n\nMixxx must be closed while exporting.\n"
                                                             "A backup of the database is created first.\n\nContinue?", path=db_path)):
            return
        profiles, counts = self._with_rendered(planner.profiles)
        try:
            report = MixxxExporter(db_path).export(profiles, playlist_name=playlist_name.strip() or None)
        except Exception as e:
            self._report_error(tr("Mixxx export failed: {error}", error=e), e)
            return
        summary = format_report(report)
        if counts["fx"] or counts["premaster"]:
            summary = f"Using {self._copies_note(counts)}.\n" + summary
        self.project.mark("mixxx", playlist=playlist_name, cues=report["cues_written"], db=os.path.basename(os.path.dirname(db_path)))
        self._save_project()
        self.add_report(tr("Mixxx Export"), summary)
        self.update_status(tr("Mixxx export: {cues} cues written, {missing} tracks missing", cues=report['cues_written'],
                              missing=len(report['missing'])))
    
    # ------------------------------------------------------------------ windows & charts
    def _refresh_transition_measurements(self):
        """Measure the planned tracks again on the files the set plays (after a pre-master or a change of the option)."""
        project = self.project
        data = project.data.get("transitions") if project is not None else None
        if not data or not data.get("tracks"):
            return None
        planner = TransitionPlanner(project.set_list_tracks() or project.tracks)
        planner.profiles = [dict(p) for p in data["tracks"]]  # the project's plan is replaced only if nothing changed meanwhile
        planner.transitions = list(data.get("transitions") or [])
        measure = project.premaster_map()
        cues = project._plan_cues(data)

        def work(task):
            changed = planner.refresh_measurements(measure, progress_callback=lambda i, n, name: task.progress(i, n, name))
            task.check()

            def done():
                if not changed or self.project is not project or project._plan_cues(project.data.get("transitions")) != cues:
                    return  # nothing new, or re-planned / another project meanwhile
                project.set_transitions(planner.to_dict())
                self.transition_planner = planner
                self._save_project()
                self._refresh_tables()
                self._render_overview()
                self._transition_report(updated=True)
            self.root.after(0, done)
        return self._start_task(tr("Update transition sheet"), work)

    def _transition_report(self, updated=False):
        """The transition sheet as a report in the Log tab, and its data as exports/transitions.json."""
        planner = self.transition_planner
        path = None
        try:
            path = planner.save_json(os.path.join(self.project.exports_dir, "transitions.json"))
        except Exception as e:
            self._report_error(tr("Cannot save transitions.json: {error}", error=e), e)
        self.add_report(tr("Transition Sheet"), planner.to_text(f"DynaMix Transition Sheet - {self.project.name}"), show=False)
        if updated:
            self.update_status(tr("Transition sheet updated with the measurements of the files the set plays (Log tab)"))
        elif path:
            self.update_status(tr("Transitions planned: {count} (data: {path}) - transition sheet in the Log tab",
                                  count=len(planner.transitions), path=path))
        else:
            self.update_status(tr("Transitions planned: {count} - transition sheet in the Log tab", count=len(planner.transitions)))
    
    def _clear_frame(self, container, placeholder=None):
        for child in container.winfo_children():
            child.destroy()
        if placeholder:
            ttk.Label(container, text=placeholder, foreground=MUTED, wraplength=600).pack(padx=20, pady=20, anchor="w")
    
    def _show_figure(self, container, fig, replace=True):
        """Embed a figure: it follows the container's width and keeps its designed height."""
        if replace:
            for child in container.winfo_children():
                child.destroy()
        canvas = FigureCanvasTkAgg(fig, container)
        widget = canvas.get_tk_widget()
        widget.configure(height=charts.pixel_height(fig), highlightthickness=0)
        widget.pack(fill=tk.X, expand=False, padx=2, pady=(2, 8))
        scroll_canvas = getattr(container, "_scroll_canvas", None)
        if scroll_canvas is not None:
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                widget.bind(seq, lambda e, c=scroll_canvas: c.yview_scroll(
                    int(-e.delta / 120) if e.delta else (-1 if e.num == 4 else 1), "units"))
        canvas.draw()
        self._chart_canvases[f"{container}:{len(container.winfo_children())}"] = canvas
        return canvas
    
    def _render_overview(self):
        tracks = self.current_set_list or (self.playlist_manager.tracks if self.playlist_manager else [])
        if not tracks:
            self._clear_frame(self.overview_frame, tr("Analyze the selection and build a set list to see the energy curve and the set map."))
            return
        self._clear_frame(self.overview_frame)
        targets = None
        if self.current_set_list:
            targets = set_proposer.curve_targets(tracks, self._set_curve(), self._mix_bars())
        self._show_figure(self.overview_frame, charts.set_overview(tracks, targets))
        planner = self.transition_planner
        if planner and planner.profiles:
            self._show_figure(self.overview_frame, charts.set_timeline(planner.profiles, planner.transitions,
                                                                       fx_labels=self._fx_labels()), replace=False)
    
    def _render_premaster(self):
        pm = self.project.data.get("premaster") if self.project else None
        if not pm or not pm.get("results"):
            self._clear_frame(self.premaster_frame, tr("Run 'Pre-master Set' to see what was changed on every track."))
            return
        self._clear_frame(self.premaster_frame)
        self._show_figure(self.premaster_frame, charts.premaster_before_after(pm["results"], float(pm.get("target_lufs", -14.0))))
        ttk.Label(self.premaster_frame, text=tr("The detailed pre-master report is in the Log tab."),
                  foreground=MUTED).pack(anchor="w", padx=4, pady=(0, 8))
    
    def on_track_selected(self, tree=None):
        tree = tree or self.set_tree
        self._track_tree_shown = tree  # redrawn after a font size change
        rows = self._set_rows if tree is self.set_tree else self._selection_rows
        track = self._selected(tree, rows)
        if track is None or track.get("state", "analysed") != "analysed":
            return
        profile = None
        planner = self.transition_planner
        if planner:
            for p in planner.profiles:
                if p.get("file_path") == track.get("file_path"):
                    profile = p
                    break
        if profile is None:
            profile = dict(track)
        median = None
        if planner:
            reports = [p.get("mastering") for p in planner.profiles if p.get("mastering") and p["mastering"].get("lufs") is not None]
            if reports:
                median = playlist_tone_target(reports)
        # which file to analyse: by default the one the set plays (the pre-mastered copy when it is used)
        original = track.get("file_path")
        copy_path = self.project._premaster_outputs().get(original) if self.project else None
        plays_copy = bool(copy_path) and self.project.premaster_map().get(original) == copy_path
        choice = getattr(self, "_track_source_choice", None)
        source = choice if copy_path and choice in ("original", "premaster") else ("premaster" if plays_copy else "original")
        path = copy_path if source == "premaster" else original
        self._clear_frame(self.track_frame)
        self._track_source_header(original, copy_path, source, plays_copy)
        bpm = float(track.get("bpm") or 0) or None
        key = profile.get("key")
        need_mastering = source == "premaster" or (profile.get("mastering") or {}).get("lufs") is None
        if not need_mastering:
            self._track_section(tr("Mastering: loudness, stereo phase, tone balance"))
            self._show_figure(self.track_frame, charts.track_detail(profile, median), replace=False)
        placeholder = ttk.Label(self.track_frame, text=(
            tr("Analysing {file}: mastering, bands, low-mid masking and resonances ...", file=os.path.basename(path)) if need_mastering
            else tr("Analysing {file}: bands, low-mid masking and resonances ...", file=os.path.basename(path))),
                                foreground=MUTED)
        placeholder.pack(anchor="w", padx=20, pady=8)
        request = self._band_request = (original, source)

        def work():
            try:
                mastering = analyze_mastering_cached(path) if need_mastering else None
                report = analyze_bands_cached(path, bpm=bpm)
            except Exception as exc:
                message = tr("Analysis of {file} failed: {error}", file=os.path.basename(path), error=exc)  # `exc` is deleted before the callback runs
                self.root.after(0, lambda: placeholder.winfo_exists() and placeholder.config(text=message))
                return

            def show():
                if self._band_request != request or not placeholder.winfo_exists():
                    return  # another track or version was selected meanwhile
                placeholder.destroy()
                if mastering is not None:
                    self._track_section(tr("Mastering: loudness, stereo phase, tone balance"))
                    shown = dict(profile, mastering=mastering, filename=os.path.basename(path))
                    self._show_figure(self.track_frame, charts.track_detail(shown, median), replace=False)
                self._track_section(tr("Band analysis: band tracking, low-mid masking, resonances"))
                self._show_figure(self.track_frame, charts.band_dynamics(dict(report, key=key)), replace=False)
            self.root.after(0, show)
        threading.Thread(target=work, daemon=True).start()

    def _track_section(self, text):
        ttk.Label(self.track_frame, text=text, font=ui_fonts.BOLD).pack(anchor="w", padx=8, pady=(10, 0))

    def _track_source_header(self, original, copy_path, source, plays_copy):
        """Which file the Track tab analyses, and the choice between the original and the pre-mastered copy."""
        row = ttk.Frame(self.track_frame)
        row.pack(fill=tk.X, padx=8, pady=(8, 2))
        shown = copy_path if source == "premaster" else original
        self.track_source_label = ttk.Label(
            row, text=(tr("File analysed: pre-mastered copy — {file}", file=shown) if source == "premaster"
                       else tr("File analysed: original — {file}", file=shown)),
            font=ui_fonts.BOLD, wraplength=900, justify=tk.LEFT)
        self.track_source_label.pack(anchor="w")
        if not copy_path:
            ttk.Label(row, text=tr("No pre-mastered copy of this track: 'Pre-master Set' makes one to compare with."),
                      foreground=MUTED).pack(anchor="w")
            return
        choice = ttk.Frame(row)
        choice.pack(anchor="w", pady=(2, 0))
        ttk.Label(choice, text=tr("Analyse:")).pack(side=tk.LEFT)
        self.track_source_var = tk.StringVar(value=source)
        for value, text in (("original", tr("original")), ("premaster", tr("pre-mastered copy"))):
            ttk.Radiobutton(choice, text=text, value=value, variable=self.track_source_var,
                            command=lambda: self._set_track_source(self.track_source_var.get())).pack(side=tk.LEFT, padx=4)
        ttk.Label(choice, text=(tr("(the set plays the pre-mastered copy; judge the mix on the original)") if plays_copy
                                else tr("(the set plays the original; judge the mix on the original)")), foreground=MUTED).pack(side=tk.LEFT, padx=8)

    def _set_track_source(self, source):
        self._track_source_choice = source
        tree = getattr(self, "_track_tree_shown", None)
        if tree is not None:
            self.on_track_selected(tree)

    def _played_files(self, originals):
        """(files the set plays, header line saying how many are pre-mastered copies) for a report."""
        played = self.project.premaster_map()
        files = [played.get(p, p) for p in originals]
        copies = sum(1 for o, f in zip(originals, files) if f != o)
        note = (f"Files analysed: the ones the set plays - {copies} pre-mastered copies, {len(files) - copies} originals "
                "(the Track tab can show the other version)")
        return files, note


class ConfigTabMixin:
    """The Configuration tab: paths, Mixxx database, defaults, environment."""

    def create_config_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=tr("Configuration"))
        cfg = self.config

        display = ttk.LabelFrame(frame, text=tr("Display"))
        display.pack(fill=tk.X, padx=10, pady=(10, 5))
        drow = ttk.Frame(display)
        drow.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(drow, text=tr("Font size:")).pack(side=tk.LEFT)
        self.cfg_font_size_var = tk.StringVar(value=str(self.font_size))
        ttk.Spinbox(drow, from_=ui_fonts.MIN_SIZE, to=ui_fonts.MAX_SIZE, increment=1, textvariable=self.cfg_font_size_var,
                    width=5).pack(side=tk.LEFT, padx=4)
        ttk.Label(drow, text=tr("points ({min} to {max}): the whole window, the tables and the charts, applied and saved at once",
                                min=ui_fonts.MIN_SIZE, max=ui_fonts.MAX_SIZE), foreground=MUTED).pack(side=tk.LEFT, padx=6)
        self.cfg_font_size_var.trace_add("write", lambda *a: self._font_size_changed())
        ttk.Label(drow, text=tr("Language:")).pack(side=tk.LEFT, padx=(24, 0))
        self._language_choices = [("auto", tr("Auto (Windows language)"))] + list(i18n.LANGUAGES.items())
        current = cfg.get("language") or "auto"
        self.cfg_language_var = tk.StringVar(value=next((label for code, label in self._language_choices if code == current),
                                                        self._language_choices[0][1]))
        language_box = ttk.Combobox(drow, textvariable=self.cfg_language_var, state="readonly", width=24,
                                    values=[label for _, label in self._language_choices])
        language_box.pack(side=tk.LEFT, padx=4)
        language_box.bind("<<ComboboxSelected>>", lambda e: self._language_changed())

        paths = ttk.LabelFrame(frame, text=tr("Paths"))
        paths.pack(fill=tk.X, padx=10, pady=5)
        grid = ttk.Frame(paths)
        grid.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(grid, text=tr("Projects folder:")).grid(row=0, column=0, sticky="w", pady=3)
        self.cfg_projects_var = tk.StringVar(value=cfg.get("projects_root"))
        ttk.Entry(grid, textvariable=self.cfg_projects_var, width=70).grid(row=0, column=1, sticky="we", padx=4)
        ttk.Button(grid, text=tr("Browse"), command=lambda: self._cfg_pick_dir(self.cfg_projects_var)).grid(row=0, column=2)
        ttk.Label(grid, text=tr("Each set is a subfolder: project.json, premaster/, exports/"), foreground=MUTED).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(grid, text=tr("Mixxx database:")).grid(row=2, column=0, sticky="w", pady=3)
        self.cfg_mixxx_var = tk.StringVar(value=cfg.get("mixxx_db") or "")
        ttk.Entry(grid, textvariable=self.cfg_mixxx_var, width=70).grid(row=2, column=1, sticky="we", padx=4)
        ttk.Button(grid, text=tr("Browse"), command=lambda: self._cfg_pick_file(self.cfg_mixxx_var)).grid(row=2, column=2)
        ttk.Button(grid, text=tr("Detect"), command=self._cfg_detect_mixxx).grid(row=2, column=3, padx=2)
        ttk.Label(grid, text=tr("Leave empty to auto-detect (%LOCALAPPDATA%\\Mixxx\\mixxxdb.sqlite on Windows)"), foreground=MUTED).grid(row=3, column=1, sticky="w", padx=4)
        ttk.Label(grid, text=tr("DynaMix data (cache, config):")).grid(row=4, column=0, sticky="w", pady=3)
        ttk.Label(grid, text=dynamix_home()).grid(row=4, column=1, sticky="w", padx=4)
        ttk.Label(grid, text=tr("Music library folder:")).grid(row=5, column=0, sticky="w", pady=3)
        self.cfg_library_var = tk.StringVar(value=cfg.get("library_folder") or "")
        ttk.Entry(grid, textvariable=self.cfg_library_var, width=70).grid(row=5, column=1, sticky="we", padx=4)
        ttk.Button(grid, text=tr("Browse"), command=lambda: self._cfg_pick_dir(self.cfg_library_var)).grid(row=5, column=2)
        ttk.Label(grid, text=tr("Every track you mixed, in one folder (subfolders included). Scanned in place, never copied."),
                  foreground=MUTED).grid(row=6, column=1, sticky="w", padx=4)
        ttk.Label(grid, text=tr("FX samples folder:")).grid(row=7, column=0, sticky="w", pady=3)
        self.cfg_fx_samples_var = tk.StringVar(value=cfg.get("fx_samples_folder") or "")
        ttk.Entry(grid, textvariable=self.cfg_fx_samples_var, width=70).grid(row=7, column=1, sticky="we", padx=4)
        ttk.Button(grid, text=tr("Browse"), command=lambda: self._cfg_pick_dir(self.cfg_fx_samples_var)).grid(row=7, column=2)
        ttk.Label(grid, text=tr("Risers, impacts, sweeps... used by Transition FX (30 s max per sample)."),
                  foreground=MUTED).grid(row=8, column=1, sticky="w", padx=4)
        ttk.Label(grid, text=tr("FFmpeg (optional):")).grid(row=9, column=0, sticky="w", pady=3)
        self.cfg_ffmpeg_var = tk.StringVar(value=cfg.get("ffmpeg_path") or "")
        ttk.Entry(grid, textvariable=self.cfg_ffmpeg_var, width=70).grid(row=9, column=1, sticky="we", padx=4)
        ttk.Button(grid, text=tr("Browse"), command=lambda: self._cfg_pick_exe(self.cfg_ffmpeg_var, "ffmpeg.exe")).grid(row=9, column=2)
        ttk.Button(grid, text=tr("Detect"), command=self._cfg_detect_ffmpeg).grid(row=9, column=3, padx=2)
        ttk.Label(grid, text=tr("Only needed for M4A/AAC files (MP3, WAV, FLAC and OGG need nothing). Empty = the one on the PATH."),
                  foreground=MUTED).grid(row=10, column=1, sticky="w", padx=4)
        grid.columnconfigure(1, weight=1)

        editors = ttk.LabelFrame(frame, text=tr("Audio editors (right-click a track: Open in...)"))
        editors.pack(fill=tk.X, padx=10, pady=5)
        eg = ttk.Frame(editors)
        eg.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(eg, text=tr("Arguments: {file} is the audio file; empty = start the editor and show the file in Explorer "
                              "(Ableton Live and Mixbus do not open an audio file given on their command line).", file="{file}"),
                  foreground=MUTED, wraplength=900, justify=tk.LEFT).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 4))
        self.cfg_editor_vars = {}
        for row, spec in enumerate(audio_tools.EDITORS, 1):
            key = spec["key"]
            path_var = tk.StringVar(value=cfg.get(f"editor_{key}") or "")
            args_var = tk.StringVar(value=cfg.get(f"editor_{key}_args") if cfg.get(f"editor_{key}_args") is not None else spec["args"])
            self.cfg_editor_vars[key] = (path_var, args_var)
            ttk.Label(eg, text=f"{spec['label']}:").grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(eg, textvariable=path_var, width=44).grid(row=row, column=1, sticky="we", padx=4)
            ttk.Button(eg, text=tr("Browse"), command=lambda v=path_var, s=spec: self._cfg_pick_exe(v, s["exe"])).grid(row=row, column=2)
            ttk.Label(eg, text=tr("Arguments:")).grid(row=row, column=3, sticky="e", padx=(8, 2))
            ttk.Entry(eg, textvariable=args_var, width=14).grid(row=row, column=4, sticky="w")
        ttk.Button(eg, text=tr("Detect editors"), command=self._cfg_detect_editors).grid(row=len(audio_tools.EDITORS) + 1, column=1,
                                                                                   sticky="w", padx=4, pady=(4, 0))
        eg.columnconfigure(1, weight=1)
        
        defaults = ttk.LabelFrame(frame, text=tr("Defaults for new projects"))
        defaults.pack(fill=tk.X, padx=10, pady=5)
        dg = ttk.Frame(defaults)
        dg.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(dg, text=tr("Set duration (min):")).grid(row=0, column=0, sticky="w", pady=2)
        self.cfg_duration_var = tk.IntVar(value=int(cfg.get("set_duration")))
        ttk.Spinbox(dg, from_=15, to=240, textvariable=self.cfg_duration_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(dg, text=tr("Energy curve:")).grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.cfg_curve_var = tk.StringVar(value=cfg.get("energy_curve"))
        ttk.Combobox(dg, textvariable=self.cfg_curve_var, values=["build", "wave", "peak_middle", "constant"], width=12, state="readonly").grid(row=0, column=3, sticky="w")
        ttk.Label(dg, text=tr("Crossfade length (bars):")).grid(row=1, column=0, sticky="w", pady=2)
        self.cfg_bars_var = tk.IntVar(value=int(cfg.get("mix_bars")))
        ttk.Spinbox(dg, from_=2, to=32, textvariable=self.cfg_bars_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(dg, text=tr("Target loudness (LUFS):")).grid(row=1, column=2, sticky="w", padx=(16, 0))
        self.cfg_lufs_var = tk.DoubleVar(value=float(cfg.get("target_lufs")))
        ttk.Spinbox(dg, from_=-24.0, to=-6.0, increment=0.5, textvariable=self.cfg_lufs_var, width=8).grid(row=1, column=3, sticky="w")
        self.cfg_tone_var = tk.BooleanVar(value=bool(cfg.get("tone_match")))
        ttk.Checkbutton(dg, text=tr("Match tone to the set"), variable=self.cfg_tone_var).grid(row=2, column=0, columnspan=2, sticky="w")
        self.cfg_phase_var = tk.BooleanVar(value=bool(cfg.get("fix_phase")))
        ttk.Checkbutton(dg, text=tr("Fix phase problems"), variable=self.cfg_phase_var).grid(row=2, column=2, columnspan=2, sticky="w")
        ttk.Label(dg, text=tr("Pre-master output format:")).grid(row=3, column=0, sticky="w", pady=2)
        self.cfg_format_var = tk.StringVar(value=cfg.get("output_format"))
        ttk.Combobox(dg, textvariable=self.cfg_format_var, values=["same", "wav", "flac", "mp3", "ogg"], width=8, state="readonly").grid(row=3, column=1, sticky="w")
        ttk.Label(dg, text=tr("Mono bass below (Hz, 0 = off):")).grid(row=3, column=2, sticky="w", padx=(16, 0))
        self.cfg_mono_var = tk.DoubleVar(value=float(cfg.get("mono_bass_hz")))
        ttk.Spinbox(dg, from_=0, to=300, increment=10, textvariable=self.cfg_mono_var, width=8).grid(row=3, column=3, sticky="w")
        
        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btns, text=tr("Save configuration"), command=self.save_config).pack(side=tk.LEFT)
        self.cfg_status = ttk.Label(btns, text="", foreground=MUTED)
        self.cfg_status.pack(side=tk.LEFT, padx=10)
        
        env = ttk.LabelFrame(frame, text=tr("Environment (what DynaMix found on this machine)"))
        env.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        env_bar = ttk.Frame(env)
        env_bar.pack(anchor="w", padx=6, pady=4)
        ttk.Button(env_bar, text=tr("Refresh"), command=self.refresh_environment).pack(side=tk.LEFT)
        ttk.Button(env_bar, text=tr("Clear whole cache..."), command=self.clear_whole_cache).pack(side=tk.LEFT, padx=6)
        self.env_text = scrolledtext.ScrolledText(env, height=12, font=ui_fonts.MONO)
        self.env_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.refresh_environment()

    def apply_font_size(self, size, redraw=True):
        """Apply a font size to the whole GUI and the charts; with `redraw`, draw the shown charts again."""
        self.font_size = ui_fonts.apply(self.root, size)
        charts.set_scale(ui_fonts.chart_scale(self.font_size))
        if redraw and getattr(self, "project", None) is not None:
            self._render_overview()
            self._render_premaster()
            tree = getattr(self, "_track_tree_shown", None)
            if tree is not None:
                self.on_track_selected(tree)
            if getattr(self, "fx_panel", None) is not None:
                self.fx_panel.schedule_chart()
        return self.font_size

    def _language_changed(self):
        code = next((code for code, label in self._language_choices if label == self.cfg_language_var.get()), "auto")
        if code == (self.config.get("language") or "auto"):
            return
        self.config.set("language", code)
        self.config.save()
        message = tr("The language is applied at the next start of DynaMix")
        self.update_status(message)
        messagebox.showinfo(tr("Language"), message)

    def _font_size_changed(self):
        try:
            size = int(self.cfg_font_size_var.get())
        except ValueError:
            return  # being typed
        if not ui_fonts.MIN_SIZE <= size <= ui_fonts.MAX_SIZE or size == self.font_size:
            return
        self.apply_font_size(size)
        self.config.set("font_size", self.font_size)
        self.config.save()
        self.update_status(tr("Font size: {size} pt", size=self.font_size))

    def _cfg_pick_dir(self, var):
        d = filedialog.askdirectory(title=tr("Choose folder"), initialdir=var.get() or None)
        if d:
            var.set(d)
    
    def _cfg_pick_file(self, var):
        f = filedialog.askopenfilename(title=tr("Select mixxxdb.sqlite"), filetypes=[(tr("Mixxx database"), "mixxxdb.sqlite"), ("SQLite", "*.sqlite"),
                                                                            (tr("All files"), "*.*")])
        if f:
            var.set(f)
    
    def _cfg_pick_exe(self, var, name):
        f = filedialog.askopenfilename(title=tr("Select {name}", name=name), filetypes=[(tr("Programs"), "*.exe"), (tr("All files"), "*.*")],
                                       initialdir=os.path.dirname(var.get()) if var.get() else None)
        if f:
            var.set(f)

    def _cfg_detect_ffmpeg(self):
        found = audio_tools.detect_ffmpeg()
        if found:
            self.cfg_ffmpeg_var.set(found)
        self.cfg_status.config(text=tr("FFmpeg found: {path}", path=found) if found else tr("FFmpeg not found (only needed for M4A/AAC files)"))

    def _cfg_detect_editors(self):
        """Fill the empty editor paths with the installed editors ('Save configuration' keeps them)."""
        programs = audio_tools._registry_programs()
        found = []
        for spec in audio_tools.EDITORS:
            path_var, _ = self.cfg_editor_vars[spec["key"]]
            if path_var.get().strip() and os.path.isfile(path_var.get().strip()):
                found.append(spec["label"])
                continue
            path = audio_tools.detect_editor(spec["key"], programs=programs)
            if path:
                path_var.set(path)
                found.append(spec["label"])
        self.cfg_status.config(text=tr("Audio editors found: {names} - click 'Save configuration' to keep them", names=", ".join(found))
                               if found else tr("No audio editor found - click 'Save configuration' to keep them"))
        return found

    def _cfg_detect_mixxx(self):
        found = find_mixxx_db()
        if found:
            self.cfg_mixxx_var.set(found)
            self.cfg_status.config(text=tr("Mixxx database found: {path}", path=found))
        else:
            self.cfg_status.config(text=tr("Mixxx database not found: is Mixxx installed and started once?"))
    
    def save_config(self):
        cfg = self.config
        cfg.set("projects_root", self.cfg_projects_var.get().strip() or cfg.get("projects_root"))
        cfg.set("mixxx_db", self.cfg_mixxx_var.get().strip())
        cfg.set("library_folder", self.cfg_library_var.get().strip())
        cfg.set("fx_samples_folder", self.cfg_fx_samples_var.get().strip())
        cfg.set("set_duration", int(self.cfg_duration_var.get()))
        cfg.set("energy_curve", self.cfg_curve_var.get())
        cfg.set("mix_bars", int(self.cfg_bars_var.get()))
        cfg.set("target_lufs", float(self.cfg_lufs_var.get()))
        cfg.set("tone_match", bool(self.cfg_tone_var.get()))
        cfg.set("fix_phase", bool(self.cfg_phase_var.get()))
        cfg.set("output_format", self.cfg_format_var.get())
        cfg.set("mono_bass_hz", float(self.cfg_mono_var.get()))
        cfg.set("font_size", self.font_size)
        cfg.set("ffmpeg_path", self.cfg_ffmpeg_var.get().strip())
        for key, (path_var, args_var) in self.cfg_editor_vars.items():
            cfg.set(f"editor_{key}", path_var.get().strip())
            cfg.set(f"editor_{key}_args", args_var.get().strip())
        audio_tools.apply_ffmpeg_path(cfg.get("ffmpeg_path"))
        os.makedirs(cfg.projects_root, exist_ok=True)
        path = cfg.save()
        self.cfg_status.config(text=tr("Saved to {path}", path=path))
        self.update_status(tr("Configuration saved"))
        if hasattr(self, "refresh_project_list"):
            self.refresh_project_list()
        if hasattr(self, "rescan_library"):
            self.rescan_library()
    
    def refresh_environment(self):
        self.env_text.delete("1.0", tk.END)
        self.env_text.insert(tk.END, format_environment_report())

    def clear_whole_cache(self):
        store = get_store()
        stats = store.stats()
        if not messagebox.askyesno(tr("Clear whole cache"),
                                   tr("Forget every analysis result ({files} files, {entries} results, {mb:.1f} MB)?\n\n"
                                      "Every track will be analysed again when needed. "
                                      "Your library and the projects' selections are not changed.",
                                      files=stats['files'], entries=stats['entries'], mb=stats['size_bytes'] / 1e6), icon="warning"):
            return
        removed = store.clear()
        log.info("Analysis cache cleared: %s results removed", removed)
        message = tr("Analysis cache cleared: {removed} results removed", removed=removed)
        self.refresh_environment()
        if hasattr(self, "rescan_library"):
            self.rescan_library()  # the projects keep their analysed tracks (spec): only the library's badges change
        self.update_status(message)
