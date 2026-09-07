#!/usr/bin/env python3
"""
Set Builder and Configuration tabs of the DynaMix GUI (mixins for DynaMixGUI).

A set is a project folder (see set_project.py): audio is imported into it,
analysed once (cached), ordered into a set list you can edit, planned into
transitions, optionally pre-mastered, and exported to Mixxx. Every step is
recorded in the project so the panel always shows where you are.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import charts
from analysis_store import get_store, dynamix_home
from config import Config, format_environment_report
from mastering import check_files, format_check_summary, premaster_files, format_premaster_summary, playlist_tone_target
from band_analysis import analyze_bands_cached, format_band_summary, mix_recommendation
from mixxx_export import MixxxExporter, find_mixxx_db, format_report
from playlist_manager import PlaylistManager
from set_project import SetProject, STEPS, list_projects, audio_files_in
from transition_planner import TransitionPlanner

MUTED = "#52514e"


class SetBuilderMixin:
    """The Set Builder tab: project, workflow steps, editable set list, charts."""

    # ------------------------------------------------------------------ tab
    def create_playlist_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Set Builder")
        self.project = None
        self.playlist_manager = None
        self.current_set_list = None
        self.transition_planner = None
        self._chart_canvases = {}
        self._library_rows = []
        self._set_rows = []
        
        # ---- header: project selection
        head = ttk.Frame(frame)
        head.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(head, text="Project:").pack(side=tk.LEFT, padx=(0, 4))
        self.project_var = tk.StringVar()
        self.project_combo = ttk.Combobox(head, textvariable=self.project_var, width=34, state="readonly")
        self.project_combo.pack(side=tk.LEFT, padx=4)
        self.project_combo.bind("<<ComboboxSelected>>", lambda e: self.open_selected_project())
        ttk.Button(head, text="New project...", command=self.new_project).pack(side=tk.LEFT, padx=4)
        ttk.Button(head, text="Import audio...", command=self.import_audio).pack(side=tk.LEFT, padx=4)
        ttk.Button(head, text="Project summary", command=self.show_project_summary).pack(side=tk.LEFT, padx=4)
        self.project_path_label = ttk.Label(frame, text="No project open. Create one with 'New project...' (the Configuration tab sets where projects live).",
                                            foreground=MUTED, anchor="w")
        self.project_path_label.pack(fill=tk.X, padx=14)
        
        paned = ttk.PanedWindow(frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # ---- left: workflow + options
        left = ttk.Frame(paned, width=350)
        paned.add(left, weight=0)
        steps_frame = ttk.LabelFrame(left, text="Workflow")
        steps_frame.pack(fill=tk.X, padx=2, pady=2)
        self.step_widgets = {}
        actions = {
            "analyze": ("Analyze", self.analyze_playlist),
            "setlist": ("Propose", self.create_set_list),
            "transitions": ("Plan Transitions", self.plan_transitions),
            "premaster": ("Pre-master Set", self.premaster_set),
            "playlist": ("Create Playlist", self.create_playlist_from_directory),
            "mixxx": ("Export to Mixxx", self.export_to_mixxx),
        }
        for i, (key, label, required) in enumerate(STEPS, 1):
            row = ttk.Frame(steps_frame)
            row.pack(fill=tk.X, padx=4, pady=2)
            status = ttk.Label(row, text="○", width=2)
            status.pack(side=tk.LEFT)
            ttk.Label(row, text=f"{i}. {label}", width=30, anchor="w").pack(side=tk.LEFT)
            btn_text, command = actions[key]
            ttk.Button(row, text=btn_text, command=command, width=16).pack(side=tk.RIGHT, padx=2)
            detail = ttk.Label(steps_frame, text="", foreground=MUTED, anchor="w", wraplength=330)
            detail.pack(fill=tk.X, padx=28)
            self.step_widgets[key] = {"status": status, "detail": detail}
        self.next_step_label = ttk.Label(steps_frame, text="Next: open or create a project.", wraplength=330,
                                         anchor="w", justify=tk.LEFT, font=("TkDefaultFont", 9, "bold"))
        self.next_step_label.pack(fill=tk.X, padx=6, pady=(6, 4))
        
        options_frame = ttk.LabelFrame(left, text="Options for this set")
        options_frame.pack(fill=tk.X, padx=2, pady=6)
        grid = ttk.Frame(options_frame)
        grid.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(grid, text="Set duration (min):").grid(row=0, column=0, sticky="w", pady=2)
        self.set_duration_var = tk.IntVar(value=int(self.config.get("set_duration")))
        ttk.Spinbox(grid, from_=15, to=240, textvariable=self.set_duration_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(grid, text="Energy curve:").grid(row=1, column=0, sticky="w", pady=2)
        self.energy_curve_var = tk.StringVar(value=self.config.get("energy_curve"))
        ttk.Combobox(grid, textvariable=self.energy_curve_var, values=["build", "wave", "peak_middle", "constant"],
                     width=12, state="readonly").grid(row=1, column=1, sticky="w")
        ttk.Label(grid, text="Target loudness (LUFS):").grid(row=2, column=0, sticky="w", pady=2)
        self.premaster_lufs_var = tk.DoubleVar(value=float(self.config.get("target_lufs")))
        ttk.Spinbox(grid, from_=-24.0, to=-6.0, increment=0.5, textvariable=self.premaster_lufs_var, width=8).grid(row=2, column=1, sticky="w")
        self.premaster_tone_var = tk.BooleanVar(value=bool(self.config.get("tone_match")))
        ttk.Checkbutton(grid, text="Match tone to the set", variable=self.premaster_tone_var).grid(row=3, column=0, columnspan=2, sticky="w")
        self.premaster_phase_var = tk.BooleanVar(value=bool(self.config.get("fix_phase")))
        ttk.Checkbutton(grid, text="Fix phase problems", variable=self.premaster_phase_var).grid(row=4, column=0, columnspan=2, sticky="w")
        mono_row = ttk.Frame(grid)
        mono_row.grid(row=5, column=0, columnspan=2, sticky="w")
        self.mono_bass_var = tk.BooleanVar(value=float(self.config.get("mono_bass_hz") or 0) > 0)
        ttk.Checkbutton(mono_row, text="Mono bass below", variable=self.mono_bass_var).pack(side=tk.LEFT)
        self.mono_bass_hz_var = tk.DoubleVar(value=float(self.config.get("mono_bass_hz") or 120.0) or 120.0)
        ttk.Spinbox(mono_row, from_=40, to=300, increment=10, textvariable=self.mono_bass_hz_var, width=5).pack(side=tk.LEFT, padx=3)
        ttk.Label(mono_row, text="Hz").pack(side=tk.LEFT)
        report_row = ttk.Frame(options_frame)
        report_row.pack(anchor="w", padx=4, pady=(0, 4))
        ttk.Button(report_row, text="Mastering Report", command=self.mastering_report).pack(side=tk.LEFT)
        ttk.Button(report_row, text="Band Analysis", command=self.band_report).pack(side=tk.LEFT, padx=4)
        self.cache_label = ttk.Label(left, text="", foreground=MUTED, wraplength=330, anchor="w", justify=tk.LEFT)
        self.cache_label.pack(fill=tk.X, padx=2, pady=2)
        
        # ---- right: notebook
        right = ttk.Frame(paned)
        paned.add(right, weight=1)
        self.set_notebook = ttk.Notebook(right)
        self.set_notebook.pack(fill=tk.BOTH, expand=True)
        
        tracks_tab = ttk.Frame(self.set_notebook)
        self.set_notebook.add(tracks_tab, text="Tracks")
        lists = ttk.PanedWindow(tracks_tab, orient=tk.HORIZONTAL)
        lists.pack(fill=tk.BOTH, expand=True)
        
        lib_frame = ttk.Frame(lists)
        lists.add(lib_frame, weight=1)
        self.library_caption = ttk.Label(lib_frame, text="Library (all analysed tracks)", foreground=MUTED, anchor="w")
        self.library_caption.pack(fill=tk.X, padx=4, pady=(4, 0))
        self.library_tree = self._make_tree(lib_frame, ("#", "Filename", "BPM", "Key", "Dur", "Energy", "Master", "Set", "Flags"),
                                            {"#": 35, "Filename": 200, "BPM": 55, "Key": 75, "Dur": 50, "Energy": 55, "Master": 55, "Set": 40, "Flags": 240})
        self.library_tree.bind("<<TreeviewSelect>>", lambda e: self.on_track_selected(self.library_tree))
        self.library_tree.bind("<Double-1>", lambda e: self.set_add())
        
        mid = ttk.Frame(lists)
        lists.add(mid, weight=0)
        ttk.Label(mid, text="").pack(pady=14)
        for text, cmd in (("Add ▶", self.set_add), ("◀ Remove", self.set_remove), ("▲ Up", lambda: self.set_move(-1)),
                          ("▼ Down", lambda: self.set_move(1)), ("Propose", self.create_set_list)):
            ttk.Button(mid, text=text, command=cmd, width=10).pack(pady=3, padx=4)
        
        set_frame = ttk.Frame(lists)
        lists.add(set_frame, weight=1)
        self.set_caption = ttk.Label(set_frame, text="Set list (playing order)", foreground=MUTED, anchor="w")
        self.set_caption.pack(fill=tk.X, padx=4, pady=(4, 0))
        self.set_tree = self._make_tree(set_frame, ("#", "Filename", "BPM", "Key", "Dur", "Energy", "Master", "Flags"),
                                        {"#": 35, "Filename": 200, "BPM": 55, "Key": 75, "Dur": 50, "Energy": 55, "Master": 55, "Flags": 240})
        self.set_tree.bind("<<TreeviewSelect>>", lambda e: self.on_track_selected(self.set_tree))
        self.set_tree.bind("<Double-1>", lambda e: self.set_remove())
        self.playlist_tree = self.set_tree  # older code paths
        
        self.overview_frame = self._scrollable_tab("Overview")
        self.track_frame = self._scrollable_tab("Track")
        self.premaster_frame = self._scrollable_tab("Pre-master")
        for f, msg in ((self.overview_frame, "Analyze the tracks and build a set list to see the energy curve and the set map."),
                       (self.track_frame, "Select a track in the Tracks tab to see its energy envelope, intro/outro and tone balance."),
                       (self.premaster_frame, "Run 'Pre-master Set' to see what was changed on every track.")):
            ttk.Label(f, text=msg, foreground=MUTED, wraplength=600).pack(padx=20, pady=20, anchor="w")
        
        self.refresh_project_list()
        projects = list_projects(self.config.projects_root)
        if projects:
            self.load_project(projects[0])
    
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
        return inner
    
    def _make_tree(self, parent, columns, widths):
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=14, selectmode="browse")
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=widths.get(col, 80), anchor="w" if col in ("Filename", "Key", "Flags") else "center",
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
        name = simpledialog.askstring("New set project", "Name of the set (a folder with this name is created in the projects folder):",
                                      parent=self.root)
        if not name:
            return
        try:
            project = SetProject.create(self.config.projects_root, name, options=self.config.project_defaults())
        except FileExistsError as e:
            messagebox.showerror("Error", str(e))
            return
        self.load_project(project.folder)
        self.refresh_project_list()
        if messagebox.askyesno("Import audio", "Import the audio files of a music folder into this project now?"):
            self.import_audio()
    
    def import_audio(self):
        if self.project is None:
            messagebox.showinfo("Project", "Create or open a project first")
            return
        folder = filedialog.askdirectory(title="Music folder to import (files are COPIED into the project, originals untouched)")
        if not folder:
            return
        files = audio_files_in(folder)
        if not files:
            messagebox.showwarning("Warning", "No audio files found in that folder")
            return
        project = self.project
        
        def work():
            counts = project.import_folder(folder, progress=lambda i, n, name, status: self.root.after(
                0, self.update_status, f"Importing {i}/{n} ({status}): {name}"))
            
            def done():
                if counts["copied"]:
                    project.mark("analyze", done=False)
                    project.invalidate_from("analyze")
                    project.save()
                self.load_project(project.folder)
                self.update_status(f"Import done: {counts['copied']} copied, {counts['skipped']} already there, {counts['failed']} failed")
                if counts["copied"] and messagebox.askyesno("Analyze", "Analyze the imported tracks now?"):
                    self.analyze_playlist()
            self.root.after(0, done)
        
        self.update_status(f"Importing {len(files)} files from {folder} ...")
        threading.Thread(target=work, daemon=True).start()
    
    def load_project(self, folder):
        """Open a project folder and restore its state (no audio work)."""
        try:
            self.project = SetProject.open(folder)
        except FileNotFoundError as e:
            messagebox.showerror("Error", str(e))
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
        
        manager = PlaylistManager(project.source_dir)
        manager.tracks = list(project.tracks)
        self.playlist_manager = manager
        self.current_set_list = project.set_list_tracks() or None
        self.transition_planner = self._planner_from_project()
        self.transition_source_dir = project.exports_dir
        self.current_playlist_dir = project.source_dir
        
        n_files = len(project.source_files())
        self.project_path_label.config(text=f"{project.folder}   ·   {n_files} audio files in source/   ·   from {project.data.get('source_folder') or '-'}")
        self.refresh_project_list()
        self._refresh_tables()
        self._refresh_workflow()
        self._clear_frame(self.overview_frame, "Analyze the tracks and build a set list to see the energy curve and the set map.")
        self._render_overview()
        self._render_premaster()
        self.update_status(f"Project '{project.name}' loaded")
    
    def _save_project(self):
        if self.project is None:
            return
        self.project.options.update({
            "set_duration": int(self.set_duration_var.get()),
            "energy_curve": self.energy_curve_var.get(),
            "target_lufs": float(self.premaster_lufs_var.get()),
            "tone_match": bool(self.premaster_tone_var.get()),
            "fix_phase": bool(self.premaster_phase_var.get()),
            "mono_bass_hz": float(self.mono_bass_hz_var.get()) if bool(self.mono_bass_var.get()) else 0.0,
        })
        self.project.save()
        self._refresh_workflow()
    
    def _require_project(self):
        if self.project is None:
            messagebox.showinfo("Project", "Create or open a project first ('New project...')")
            return False
        return True
    
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
            for k in ("count", "cached", "analyzed", "manual", "duration", "curve", "file", "playlist", "cues"):
                if k in details:
                    parts.append(f"{k} {details[k]}" if k != "manual" else "edited by hand")
            w["detail"].config(text=" · ".join(parts))
        key, hint = self.project.next_step()
        self.next_step_label.config(text=f"Next: {hint}")
        try:
            stats = get_store().stats()
            self.cache_label.config(text=f"Analysis cache: {stats['files']} files, {stats['entries']} results")
        except Exception:
            pass
    
    def show_project_summary(self):
        if not self._require_project():
            return
        self._show_text_window("Set project", "\n".join(self.project.summary_lines()), "set_summary.txt")
    
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
    
    def _refresh_tables(self):
        for tree in (self.library_tree, self.set_tree):
            for item in tree.get_children():
                tree.delete(item)
        self._library_rows, self._set_rows = [], []
        if self.project is None:
            return
        mastering = self._mastering_by_path()
        for i, t in enumerate(self.project.library_tracks(), 1):
            self.library_tree.insert("", tk.END, iid=f"L{i}", values=self._row_values(t, i, mastering.get(t["file_path"]), with_set=True))
            self._library_rows.append(t)
        for i, t in enumerate(self.project.set_list_tracks(), 1):
            self.set_tree.insert("", tk.END, iid=f"S{i}", values=self._row_values(t, i, mastering.get(t["file_path"])))
            self._set_rows.append(t)
        total = sum(float(t.get("duration") or 0) for t in self._set_rows) / 60
        self.library_caption.config(text=f"Library: {len(self._library_rows)} analysed tracks ({len(self.project.source_files())} files in source/)")
        self.set_caption.config(text=f"Set list: {len(self._set_rows)} tracks, {total:.0f} min — playing order (Add/Remove/Up/Down to edit)")
    
    def _populate_playlist_tree(self, tracks, caption=None):
        """Compatibility with older code paths: refresh both tables."""
        self._refresh_tables()
    
    def _selected(self, tree, rows):
        sel = tree.selection()
        if not sel:
            return None
        try:
            idx = int(sel[0][1:]) - 1
        except ValueError:
            return None
        return rows[idx] if 0 <= idx < len(rows) else None
    
    def _after_manual_edit(self):
        self.project.mark("setlist", count=len(self.project.set_list), manual=True)
        self.current_set_list = self.project.set_list_tracks() or None
        self.transition_planner = None
        self._save_project()
        self._refresh_tables()
        self._render_overview()
    
    def set_add(self):
        if not self._require_project():
            return
        track = self._selected(self.library_tree, self._library_rows)
        if track is None:
            return
        # insert after the selected set-list row, else at the end
        current = self._selected(self.set_tree, self._set_rows)
        position = (self.project.set_list.index(current["file_path"]) + 1) if current else None
        self.project.add_to_set(track["file_path"], position)
        self._after_manual_edit()
    
    def set_remove(self):
        if not self._require_project():
            return
        track = self._selected(self.set_tree, self._set_rows)
        if track is None:
            return
        self.project.remove_from_set(track["file_path"])
        self._after_manual_edit()
    
    def set_move(self, delta):
        if not self._require_project():
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
        files = project.source_files()
        if not files:
            messagebox.showwarning("Warning", "No audio files in the project. Use 'Import audio...' first.")
            return
        
        def work():
            try:
                manager = PlaylistManager(project.source_dir)
                manager.analyze_playlist(files, progress_callback=lambda i, n, name, status: self.root.after(
                    0, self.update_status, f"Analyzing {i}/{n} ({status}): {name}"))
                run = manager.last_run
                
                def done():
                    before = {t["file_path"] for t in project.tracks}
                    after = {t["file_path"] for t in manager.tracks}
                    self.playlist_manager = manager
                    project.set_tracks(manager.tracks)
                    if before and before != after:
                        project.invalidate_from("analyze")
                    self.current_set_list = project.set_list_tracks() or None
                    if not self.current_set_list:
                        self.transition_planner = None
                    project.mark("analyze", count=len(manager.tracks), cached=run["cached"], analyzed=run["analyzed"])
                    self._save_project()
                    self._refresh_tables()
                    self._render_overview()
                    self.update_status(f"Analyzed {len(manager.tracks)} tracks ({run['cached']} from cache, {run['analyzed']} new, {run['failed']} failed)")
                self.root.after(0, done)
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Error", f"Analysis failed: {str(e)}")
        
        self.update_status(f"Analyzing {len(files)} tracks ...")
        threading.Thread(target=work, daemon=True).start()
    
    def create_set_list(self):
        """Propose an order (the library stays; edit the proposal afterwards)."""
        if not self._require_project():
            return
        manager = self.playlist_manager
        if manager is None or not manager.tracks:
            messagebox.showwarning("Warning", "Analyze the tracks first (step 1)")
            return
        try:
            duration = int(self.set_duration_var.get())
            curve = self.energy_curve_var.get()
            set_list = manager.create_set_list(duration_minutes=duration, energy_curve=curve)
            self.project.set_set_list(set_list)
            self.project.invalidate_from("setlist")
            self.project.mark("setlist", count=len(set_list), duration=duration, curve=curve)
            self.current_set_list = list(set_list)
            self.transition_planner = None
            self._save_project()
            self._refresh_tables()
            self._render_overview()
            total = sum(float(t.get("duration") or 0) for t in set_list) / 60
            self.update_status(f"Proposed set list: {len(set_list)} tracks, {total:.0f} min, curve '{curve}'. Adjust it in the Tracks tab if needed.")
        except Exception as e:
            messagebox.showerror("Error", f"Set list creation failed: {str(e)}")
    
    def _set_tracks_or_warn(self):
        tracks = self.project.set_list_tracks() if self.project else []
        if len(tracks) < 2:
            messagebox.showwarning("Warning", "The set list needs at least two tracks: click 'Propose' or add tracks in the Tracks tab")
            return None
        return tracks
    
    def plan_transitions(self):
        if not self._require_project():
            return
        tracks = self._set_tracks_or_warn()
        if tracks is None:
            return
        project = self.project
        
        def work():
            try:
                planner = TransitionPlanner(tracks, mix_bars=int(project.options.get("mix_bars", 8)))
                planner.plan(progress_callback=lambda i, n, name: self.root.after(
                    0, self.update_status, f"Planning transitions {i}/{n}: {name}"))
                
                def done():
                    self.transition_planner = planner
                    project.data["transitions"] = planner.to_dict()
                    project.mark("transitions", count=len(planner.transitions))
                    self._save_project()
                    self._refresh_tables()
                    self._render_overview()
                    self._show_transition_window("set list")
                self.root.after(0, done)
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Error", f"Transition planning failed: {str(e)}")
        
        self.update_status(f"Planning transitions for {len(tracks)} tracks ...")
        threading.Thread(target=work, daemon=True).start()
    
    def mastering_report(self):
        if not self._require_project():
            return
        tracks = self.project.set_list_tracks() or self.project.tracks
        files = [t["file_path"] for t in tracks] or self.project.source_files()
        if not files:
            messagebox.showwarning("Warning", "No audio files in the project")
            return
        
        def work():
            try:
                reports = check_files(files, progress=lambda i, n, name: self.root.after(
                    0, self.update_status, f"Mastering check {i}/{n}: {name}"))
                summary = format_check_summary(reports)
                self.root.after(0, self._show_text_window, "Mastering Report", summary, "mastering_report.txt")
                flagged = sum(1 for r in reports if r.get("flags"))
                self.root.after(0, self.update_status, f"Mastering check done: {flagged}/{len(reports)} tracks with issues")
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Error", f"Mastering check failed: {str(e)}")
        
        self.update_status(f"Checking mastering of {len(files)} tracks ...")
        threading.Thread(target=work, daemon=True).start()
    
    def band_report(self):
        """Band tracking, low-mid masking and resonances for the set list (or the library)."""
        if not self._require_project():
            return
        tracks = self.project.set_list_tracks() or self.project.tracks
        if not tracks:
            messagebox.showwarning("Warning", "Analyze the tracks first")
            return
        
        def work():
            try:
                reports = []
                for i, t in enumerate(tracks, 1):
                    self.root.after(0, self.update_status, f"Band analysis {i}/{len(tracks)}: {t.get('filename', '')}")
                    try:
                        reports.append(analyze_bands_cached(t["file_path"], bpm=float(t.get("bpm") or 0) or None))
                    except Exception as exc:
                        reports.append({"filename": t.get("filename", ""), "error": str(exc)})
                summary = format_band_summary(reports)
                needs_mix = [r["filename"] for r in reports if r.get("verdict") == "mix"]
                if needs_mix:
                    summary = (f"MIX REVISION RECOMMENDED for {len(needs_mix)}/{len(reports)} tracks: " + ", ".join(needs_mix)
                               + "\n\n" + summary)
                self.root.after(0, self._show_text_window, "Band Analysis", summary, "band_analysis.txt")
                self.root.after(0, self.update_status, f"Band analysis done: {len(needs_mix)}/{len(reports)} tracks need a mix revision")
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Error", f"Band analysis failed: {str(e)}")
        
        self.update_status(f"Band analysis of {len(tracks)} tracks ...")
        threading.Thread(target=work, daemon=True).start()
    
    def premaster_set(self):
        if not self._require_project():
            return
        tracks = self.project.set_list_tracks() or self.project.tracks
        files = [t["file_path"] for t in tracks]
        if not files:
            messagebox.showwarning("Warning", "Analyze the tracks first")
            return
        project = self.project
        out_dir = project.premaster_dir
        target_lufs = float(self.premaster_lufs_var.get())
        tone = bool(self.premaster_tone_var.get())
        phase = bool(self.premaster_phase_var.get())
        mono_hz = float(self.mono_bass_hz_var.get()) if bool(self.mono_bass_var.get()) else 0.0
        fmt = self.config.get("output_format", "same")
        
        def work():
            try:
                results = premaster_files(files, out_dir, target_lufs=target_lufs, tone_match=tone, repair_phase=phase, fmt=fmt,
                                          mono_bass_hz=mono_hz,
                                          progress=lambda i, n, name: self.root.after(
                                              0, self.update_status, f"Pre-mastering {i}/{n}: {name}"))
                summary = format_premaster_summary(results, out_dir)
                done_count = sum(1 for r in results if "error" not in r)
                
                def done():
                    keep = ("lufs", "true_peak_db", "plr", "score", "clip_runs", "flags")
                    slim = [({"input": r["input"], "error": r["error"]} if "error" in r else
                             {"input": r["input"], "output": r["output"], "actions": r["actions"],
                              "before": {k: r["before"].get(k) for k in keep}, "after": {k: r["after"].get(k) for k in keep}})
                            for r in results]
                    project.data["premaster"] = {"out_dir": out_dir, "target_lufs": target_lufs, "tone_match": tone,
                                                 "fix_phase": phase, "mono_bass_hz": mono_hz, "results": slim, "summary": summary}
                    project.mark("premaster", count=done_count)
                    self._save_project()
                    self._render_premaster()
                    self.set_notebook.select(self.premaster_frame)
                    self.update_status(f"Pre-master done: {done_count}/{len(results)} tracks written to {out_dir}")
                self.root.after(0, done)
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Error", f"Pre-master failed: {str(e)}")
        
        self.update_status(f"Pre-mastering {len(files)} tracks into {out_dir} ...")
        self.set_notebook.select(self.premaster_frame)
        threading.Thread(target=work, daemon=True).start()
    
    def _with_premastered(self, tracks):
        mapping = self.project.premaster_map() if self.project else {}
        if not mapping:
            return list(tracks), 0
        swapped, count = [], 0
        for t in tracks:
            out = mapping.get(t.get("file_path"))
            if out:
                t = dict(t, file_path=out, filename=os.path.basename(out))
                count += 1
            swapped.append(t)
        return swapped, count
    
    def create_playlist_from_directory(self):
        """Write the set list (or the library order) as an M3U into exports/."""
        if not self._require_project():
            return
        from export_tools import ExportTools
        tracks = self.project.set_list_tracks() or self.project.tracks
        if not tracks:
            messagebox.showwarning("Warning", "Nothing to write: analyze the tracks and build a set list first")
            return
        tracks, premastered = self._with_premastered(tracks)
        filename = filedialog.asksaveasfilename(
            title="Save Playlist", initialdir=self.project.exports_dir, initialfile=f"{self.project.name}.m3u",
            defaultextension=".m3u", filetypes=[("M3U playlist", "*.m3u"), ("M3U8 playlist (UTF-8)", "*.m3u8"), ("All files", "*.*")])
        if not filename:
            return
        try:
            ExportTools.export_to_m3u(tracks, filename)
        except Exception as e:
            messagebox.showerror("Error", f"Playlist creation failed: {str(e)}")
            return
        self.project.mark("playlist", file=os.path.basename(filename), count=len(tracks))
        self._save_project()
        note = f" ({premastered} pre-mastered copies)" if premastered else ""
        self.update_status(f"Playlist saved: {len(tracks)} tracks{note} -> {filename}")
        messagebox.showinfo("Playlist created", f"{len(tracks)} tracks written to:\n{filename}")
    
    def export_to_mixxx(self, log_widget=None):
        if not self._require_project():
            return
        planner = self.transition_planner
        if planner is None or not planner.profiles:
            messagebox.showwarning("Warning", "Plan the transitions first (step 3)")
            return
        db_path = self.config.mixxx_db_path()
        if not db_path:
            db_path = filedialog.askopenfilename(
                title="Select the Mixxx database (mixxxdb.sqlite) - close Mixxx first",
                filetypes=[("Mixxx database", "mixxxdb.sqlite"), ("SQLite", "*.sqlite"), ("All files", "*.*")])
            if not db_path:
                return
        default_name = f"DynaMix - {self.project.name}"
        playlist_name = simpledialog.askstring("Mixxx playlist", "Name of the Mixxx playlist to create:",
                                               initialvalue=default_name, parent=self.root)
        if playlist_name is None:
            return
        if not messagebox.askyesno("Export to Mixxx", f"Database: {db_path}\n\nMixxx must be closed while exporting.\n"
                                   "A backup of the database is created first.\n\nContinue?"):
            return
        profiles, premastered = self._with_premastered(planner.profiles)
        try:
            report = MixxxExporter(db_path).export(profiles, playlist_name=playlist_name.strip() or None)
        except Exception as e:
            messagebox.showerror("Error", f"Mixxx export failed: {str(e)}")
            return
        summary = format_report(report)
        if premastered:
            summary = f"Using the pre-mastered copies for {premastered} tracks.\n" + summary
        self.project.mark("mixxx", playlist=playlist_name, cues=report["cues_written"], db=os.path.basename(os.path.dirname(db_path)))
        self._save_project()
        if log_widget is not None:
            log_widget.insert(tk.END, "\n\nMIXXX EXPORT\n" + "-" * 60 + "\n" + summary + "\n")
            log_widget.see(tk.END)
        self.update_status(f"Mixxx export: {report['cues_written']} cues written, {len(report['missing'])} tracks missing")
        messagebox.showinfo("Export to Mixxx", summary)
    
    # ------------------------------------------------------------------ windows & charts
    def _show_text_window(self, title, text_content, save_name="report.txt"):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("900x600")
        toolbar = ttk.Frame(win)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        text = scrolledtext.ScrolledText(win, wrap=tk.NONE, font=("Consolas", 10))
        
        def save():
            filename = filedialog.asksaveasfilename(title="Save", initialdir=self.project.exports_dir if self.project else None,
                                                    initialfile=save_name, defaultextension=".txt",
                                                    filetypes=[("Text", "*.txt"), ("All files", "*.*")])
            if filename:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(text.get("1.0", tk.END))
                self.update_status(f"Saved: {filename}")
        ttk.Button(toolbar, text="Save...", command=save).pack(side=tk.RIGHT, padx=5)
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        text.insert(tk.END, text_content)
        return text
    
    def _show_transition_window(self, source):
        planner = self.transition_planner
        title = f"DynaMix Transition Sheet - {self.project.name}"
        win = tk.Toplevel(self.root)
        win.title("Transition Plan")
        win.geometry("900x600")
        toolbar = ttk.Frame(win)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(toolbar, text=f"{len(planner.profiles)} tracks, {len(planner.transitions)} transitions ({source})").pack(side=tk.LEFT, padx=5)
        text = scrolledtext.ScrolledText(win, wrap=tk.NONE, font=("Consolas", 10))
        ttk.Button(toolbar, text="Export to Mixxx...", command=lambda: self.export_to_mixxx(text)).pack(side=tk.RIGHT, padx=5)
        ttk.Button(toolbar, text="Save JSON...", command=self.save_transition_json).pack(side=tk.RIGHT, padx=5)
        ttk.Button(toolbar, text="Save Sheet...", command=lambda: self.save_transition_sheet(title)).pack(side=tk.RIGHT, padx=5)
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        text.insert(tk.END, planner.to_text(title))
        self.update_status(f"Transitions planned: {len(planner.transitions)}")
    
    def save_transition_sheet(self, title):
        filename = filedialog.asksaveasfilename(title="Save Transition Sheet", initialdir=self.project.exports_dir,
                                                initialfile="transitions.txt", defaultextension=".txt",
                                                filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if filename:
            self.transition_planner.save_text(filename, title)
            self.update_status(f"Transition sheet saved: {filename}")
    
    def save_transition_json(self):
        filename = filedialog.asksaveasfilename(title="Save Transition Data", initialdir=self.project.exports_dir,
                                                initialfile="transitions.json", defaultextension=".json",
                                                filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if filename:
            self.transition_planner.save_json(filename)
            self.update_status(f"Transition data saved: {filename}")
    
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
            return
        self._clear_frame(self.overview_frame)
        targets = None
        if self.current_set_list:
            values = [PlaylistManager._energy_value(t) for t in tracks]
            targets = PlaylistManager._target_curve(values, self.energy_curve_var.get())
        self._show_figure(self.overview_frame, charts.set_overview(tracks, targets))
        planner = self.transition_planner
        if planner and planner.profiles:
            self._show_figure(self.overview_frame, charts.set_timeline(planner.profiles, planner.transitions), replace=False)
    
    def _render_premaster(self):
        pm = self.project.data.get("premaster") if self.project else None
        if not pm or not pm.get("results"):
            self._clear_frame(self.premaster_frame, "Run 'Pre-master Set' to see what was changed on every track.")
            return
        self._clear_frame(self.premaster_frame)
        self._show_figure(self.premaster_frame, charts.premaster_before_after(pm["results"], float(pm.get("target_lufs", -14.0))))
        text = scrolledtext.ScrolledText(self.premaster_frame, height=10, font=("Consolas", 9), wrap=tk.NONE)
        text.pack(fill=tk.X, padx=2, pady=(0, 8))
        text.insert(tk.END, pm.get("summary", ""))
    
    def on_track_selected(self, tree=None):
        tree = tree or self.set_tree
        rows = self._set_rows if tree is self.set_tree else self._library_rows
        track = self._selected(tree, rows)
        if track is None:
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
        self._show_figure(self.track_frame, charts.track_detail(profile, median))
        # band tracking chart, computed in the background (cached afterwards)
        path = track.get("file_path")
        bpm = float(track.get("bpm") or 0) or None
        placeholder = ttk.Label(self.track_frame, text="Computing band tracking, low-mid masking and resonances ...", foreground=MUTED)
        placeholder.pack(anchor="w", padx=20, pady=8)
        self._band_request = path
        
        def work():
            try:
                report = analyze_bands_cached(path, bpm=bpm)
            except Exception as exc:
                self.root.after(0, lambda: placeholder.config(text=f"Band analysis failed: {exc}"))
                return
            
            def show():
                if self._band_request != path:
                    return  # another track was selected meanwhile
                placeholder.destroy()
                self._show_figure(self.track_frame, charts.band_dynamics(report), replace=False)
            self.root.after(0, show)
        threading.Thread(target=work, daemon=True).start()


class ConfigTabMixin:
    """The Configuration tab: paths, Mixxx database, defaults, environment."""

    def create_config_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Configuration")
        cfg = self.config
        
        paths = ttk.LabelFrame(frame, text="Paths")
        paths.pack(fill=tk.X, padx=10, pady=(10, 5))
        grid = ttk.Frame(paths)
        grid.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(grid, text="Projects folder:").grid(row=0, column=0, sticky="w", pady=3)
        self.cfg_projects_var = tk.StringVar(value=cfg.get("projects_root"))
        ttk.Entry(grid, textvariable=self.cfg_projects_var, width=70).grid(row=0, column=1, sticky="we", padx=4)
        ttk.Button(grid, text="Browse", command=lambda: self._cfg_pick_dir(self.cfg_projects_var)).grid(row=0, column=2)
        ttk.Label(grid, text="Each set is a subfolder: project.json, source/, premaster/, exports/", foreground=MUTED).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(grid, text="Mixxx database:").grid(row=2, column=0, sticky="w", pady=3)
        self.cfg_mixxx_var = tk.StringVar(value=cfg.get("mixxx_db") or "")
        ttk.Entry(grid, textvariable=self.cfg_mixxx_var, width=70).grid(row=2, column=1, sticky="we", padx=4)
        ttk.Button(grid, text="Browse", command=lambda: self._cfg_pick_file(self.cfg_mixxx_var)).grid(row=2, column=2)
        ttk.Button(grid, text="Detect", command=self._cfg_detect_mixxx).grid(row=2, column=3, padx=2)
        ttk.Label(grid, text="Leave empty to auto-detect (%LOCALAPPDATA%\\Mixxx\\mixxxdb.sqlite on Windows)", foreground=MUTED).grid(row=3, column=1, sticky="w", padx=4)
        ttk.Label(grid, text="DynaMix data (cache, config):").grid(row=4, column=0, sticky="w", pady=3)
        ttk.Label(grid, text=dynamix_home()).grid(row=4, column=1, sticky="w", padx=4)
        grid.columnconfigure(1, weight=1)
        
        defaults = ttk.LabelFrame(frame, text="Defaults for new projects")
        defaults.pack(fill=tk.X, padx=10, pady=5)
        dg = ttk.Frame(defaults)
        dg.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(dg, text="Set duration (min):").grid(row=0, column=0, sticky="w", pady=2)
        self.cfg_duration_var = tk.IntVar(value=int(cfg.get("set_duration")))
        ttk.Spinbox(dg, from_=15, to=240, textvariable=self.cfg_duration_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(dg, text="Energy curve:").grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.cfg_curve_var = tk.StringVar(value=cfg.get("energy_curve"))
        ttk.Combobox(dg, textvariable=self.cfg_curve_var, values=["build", "wave", "peak_middle", "constant"], width=12, state="readonly").grid(row=0, column=3, sticky="w")
        ttk.Label(dg, text="Crossfade length (bars):").grid(row=1, column=0, sticky="w", pady=2)
        self.cfg_bars_var = tk.IntVar(value=int(cfg.get("mix_bars")))
        ttk.Spinbox(dg, from_=2, to=32, textvariable=self.cfg_bars_var, width=8).grid(row=1, column=1, sticky="w")
        ttk.Label(dg, text="Target loudness (LUFS):").grid(row=1, column=2, sticky="w", padx=(16, 0))
        self.cfg_lufs_var = tk.DoubleVar(value=float(cfg.get("target_lufs")))
        ttk.Spinbox(dg, from_=-24.0, to=-6.0, increment=0.5, textvariable=self.cfg_lufs_var, width=8).grid(row=1, column=3, sticky="w")
        self.cfg_tone_var = tk.BooleanVar(value=bool(cfg.get("tone_match")))
        ttk.Checkbutton(dg, text="Match tone to the set", variable=self.cfg_tone_var).grid(row=2, column=0, columnspan=2, sticky="w")
        self.cfg_phase_var = tk.BooleanVar(value=bool(cfg.get("fix_phase")))
        ttk.Checkbutton(dg, text="Fix phase problems", variable=self.cfg_phase_var).grid(row=2, column=2, columnspan=2, sticky="w")
        ttk.Label(dg, text="Pre-master output format:").grid(row=3, column=0, sticky="w", pady=2)
        self.cfg_format_var = tk.StringVar(value=cfg.get("output_format"))
        ttk.Combobox(dg, textvariable=self.cfg_format_var, values=["same", "wav", "flac", "mp3", "ogg"], width=8, state="readonly").grid(row=3, column=1, sticky="w")
        ttk.Label(dg, text="Mono bass below (Hz, 0 = off):").grid(row=3, column=2, sticky="w", padx=(16, 0))
        self.cfg_mono_var = tk.DoubleVar(value=float(cfg.get("mono_bass_hz")))
        ttk.Spinbox(dg, from_=0, to=300, increment=10, textvariable=self.cfg_mono_var, width=8).grid(row=3, column=3, sticky="w")
        
        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(btns, text="Save configuration", command=self.save_config).pack(side=tk.LEFT)
        self.cfg_status = ttk.Label(btns, text="", foreground=MUTED)
        self.cfg_status.pack(side=tk.LEFT, padx=10)
        
        env = ttk.LabelFrame(frame, text="Environment (what DynaMix found on this machine)")
        env.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        ttk.Button(env, text="Refresh", command=self.refresh_environment).pack(anchor="w", padx=6, pady=4)
        self.env_text = scrolledtext.ScrolledText(env, height=12, font=("Consolas", 9))
        self.env_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.refresh_environment()
    
    def _cfg_pick_dir(self, var):
        d = filedialog.askdirectory(title="Choose folder", initialdir=var.get() or None)
        if d:
            var.set(d)
    
    def _cfg_pick_file(self, var):
        f = filedialog.askopenfilename(title="Select mixxxdb.sqlite", filetypes=[("Mixxx database", "mixxxdb.sqlite"), ("SQLite", "*.sqlite"), ("All files", "*.*")])
        if f:
            var.set(f)
    
    def _cfg_detect_mixxx(self):
        found = find_mixxx_db()
        if found:
            self.cfg_mixxx_var.set(found)
            self.cfg_status.config(text=f"Mixxx database found: {found}")
        else:
            self.cfg_status.config(text="Mixxx database not found: is Mixxx installed and started once?")
    
    def save_config(self):
        cfg = self.config
        cfg.set("projects_root", self.cfg_projects_var.get().strip() or cfg.get("projects_root"))
        cfg.set("mixxx_db", self.cfg_mixxx_var.get().strip())
        cfg.set("set_duration", int(self.cfg_duration_var.get()))
        cfg.set("energy_curve", self.cfg_curve_var.get())
        cfg.set("mix_bars", int(self.cfg_bars_var.get()))
        cfg.set("target_lufs", float(self.cfg_lufs_var.get()))
        cfg.set("tone_match", bool(self.cfg_tone_var.get()))
        cfg.set("fix_phase", bool(self.cfg_phase_var.get()))
        cfg.set("output_format", self.cfg_format_var.get())
        cfg.set("mono_bass_hz", float(self.cfg_mono_var.get()))
        os.makedirs(cfg.projects_root, exist_ok=True)
        path = cfg.save()
        self.cfg_status.config(text=f"Saved to {path}")
        self.update_status("Configuration saved")
        if hasattr(self, "refresh_project_list"):
            self.refresh_project_list()
    
    def refresh_environment(self):
        self.env_text.delete("1.0", tk.END)
        self.env_text.insert(tk.END, format_environment_report())
