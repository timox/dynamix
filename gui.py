#!/usr/bin/env python3
"""
DynaMix GUI - Graphical User Interface for all DynaMix tools
A comprehensive GUI application for audio analysis and DJ tools
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
import os
import threading
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

# Import DynaMix modules
from audio_utils import AudioAnalyzer, analyze_track_compatibility, suggest_mix_points
from dj_tools import DJTools, batch_analyze_tracks
from playlist_manager import PlaylistManager
from audio_effects import AudioEffects, TrackComparer
from export_tools import ExportTools
from mix_enhanced import EnhancedMixAnalyzer
from transition_planner import TransitionPlanner
from mixxx_export import MixxxExporter, find_mixxx_db, format_report
from mastering import check_files, format_check_summary, premaster_files, format_premaster_summary, playlist_tone_target
from set_project import SetProject, STEPS
from playlist_manager import PREMASTER_DIRNAME
from analysis_store import get_store
import charts


class DynaMixGUI:
    """Main GUI application for DynaMix"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("DynaMix - DJ Audio Analysis Tool")
        self.root.geometry("1200x800")
        
        # Variables
        self.current_track1 = None
        self.current_track2 = None
        self.current_playlist_dir = None
        self.analysis_results = {}
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create tabs
        self.create_track_analysis_tab()
        self.create_two_track_tab()
        self.create_playlist_tab()
        self.create_dj_tools_tab()
        self.create_audio_effects_tab()
        self.create_export_tab()
        
        # Status bar
        self.status_bar = tk.Label(root, text="Ready", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    
    def update_status(self, message: str):
        """Update status bar"""
        self.status_bar.config(text=message)
        self.root.update_idletasks()
    
    def create_track_analysis_tab(self):
        """Create single track analysis tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Track Analysis")
        
        # Top frame for file selection
        top_frame = ttk.Frame(frame)
        top_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(top_frame, text="Audio File:").pack(side=tk.LEFT, padx=5)
        self.track1_path_var = tk.StringVar()
        ttk.Entry(top_frame, textvariable=self.track1_path_var, width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="Browse", command=self.browse_track1).pack(side=tk.LEFT, padx=5)
        ttk.Button(top_frame, text="Analyze", command=self.analyze_track1).pack(side=tk.LEFT, padx=5)
        
        # Results frame
        results_frame = ttk.Frame(frame)
        results_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left panel - Text results
        left_panel = ttk.Frame(results_frame)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        
        ttk.Label(left_panel, text="Analysis Results:").pack(anchor=tk.W)
        self.track1_results = scrolledtext.ScrolledText(left_panel, height=30, width=50)
        self.track1_results.pack(fill=tk.BOTH, expand=True)
        
        # Right panel - Visualization
        right_panel = ttk.Frame(results_frame)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
        
        ttk.Label(right_panel, text="Visualization:").pack(anchor=tk.W)
        self.track1_viz_frame = ttk.Frame(right_panel)
        self.track1_viz_frame.pack(fill=tk.BOTH, expand=True)
    
    def create_two_track_tab(self):
        """Create two-track compatibility analysis tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Two-Track Analysis")
        
        # Track selection
        selection_frame = ttk.Frame(frame)
        selection_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Track 1
        track1_frame = ttk.LabelFrame(selection_frame, text="Track 1")
        track1_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.track1_compat_var = tk.StringVar()
        ttk.Entry(track1_frame, textvariable=self.track1_compat_var, width=40).pack(side=tk.LEFT, padx=5)
        ttk.Button(track1_frame, text="Browse", command=self.browse_track1_compat).pack(side=tk.LEFT, padx=5)
        
        # Track 2
        track2_frame = ttk.LabelFrame(selection_frame, text="Track 2")
        track2_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.track2_compat_var = tk.StringVar()
        ttk.Entry(track2_frame, textvariable=self.track2_compat_var, width=40).pack(side=tk.LEFT, padx=5)
        ttk.Button(track2_frame, text="Browse", command=self.browse_track2_compat).pack(side=tk.LEFT, padx=5)
        
        # Analyze button
        ttk.Button(selection_frame, text="Analyze Compatibility", 
                  command=self.analyze_compatibility).pack(side=tk.LEFT, padx=10)
        
        # Results
        results_frame = ttk.Frame(frame)
        results_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Text results
        text_frame = ttk.Frame(results_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        self.compat_results = scrolledtext.ScrolledText(text_frame, height=20)
        self.compat_results.pack(fill=tk.BOTH, expand=True)
        
        # Visualization
        self.compat_viz_frame = ttk.Frame(results_frame)
        self.compat_viz_frame.pack(fill=tk.BOTH, expand=True)
    
    def create_playlist_tab(self):
        """Set Builder: guided workflow with persistent project, table and charts"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Set Builder")
        self.project = None
        self._chart_canvases = {}
        
        # Folder selection
        dir_frame = ttk.Frame(frame)
        dir_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        ttk.Label(dir_frame, text="Music folder:").pack(side=tk.LEFT, padx=5)
        self.playlist_dir_var = tk.StringVar()
        entry = ttk.Entry(dir_frame, textvariable=self.playlist_dir_var, width=60)
        entry.pack(side=tk.LEFT, padx=5)
        entry.bind("<Return>", lambda e: self.load_project(self.playlist_dir_var.get()))
        ttk.Button(dir_frame, text="Browse", command=self.browse_playlist_dir).pack(side=tk.LEFT, padx=5)
        ttk.Button(dir_frame, text="Project summary", command=self.show_project_summary).pack(side=tk.LEFT, padx=5)
        
        paned = ttk.PanedWindow(frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # ---- left: workflow steps + options
        left = ttk.Frame(paned, width=340)
        paned.add(left, weight=0)
        
        steps_frame = ttk.LabelFrame(left, text="Workflow")
        steps_frame.pack(fill=tk.X, padx=2, pady=2)
        self.step_widgets = {}
        actions = {
            "analyze": ("Analyze", self.analyze_playlist),
            "setlist": ("Create Set List", self.create_set_list),
            "transitions": ("Plan Transitions", self.plan_transitions),
            "premaster": ("Pre-master Set", self.premaster_set),
            "playlist": ("Create Playlist", self.create_playlist_from_directory),
            "mixxx": ("Export to Mixxx...", self.export_to_mixxx),
        }
        for i, (key, label, required) in enumerate(STEPS, 1):
            row = ttk.Frame(steps_frame)
            row.pack(fill=tk.X, padx=4, pady=2)
            status = ttk.Label(row, text="○", width=2)
            status.pack(side=tk.LEFT)
            text = ttk.Label(row, text=f"{i}. {label}", width=30, anchor="w")
            text.pack(side=tk.LEFT)
            btn_text, command = actions[key]
            ttk.Button(row, text=btn_text, command=command, width=18).pack(side=tk.RIGHT, padx=2)
            detail = ttk.Label(steps_frame, text="", foreground="#52514e", anchor="w", wraplength=320)
            detail.pack(fill=tk.X, padx=28)
            self.step_widgets[key] = {"status": status, "text": text, "detail": detail}
        self.next_step_label = ttk.Label(steps_frame, text="Next: choose a music folder.", wraplength=320,
                                         anchor="w", justify=tk.LEFT, font=("TkDefaultFont", 9, "bold"))
        self.next_step_label.pack(fill=tk.X, padx=6, pady=(6, 4))
        
        options_frame = ttk.LabelFrame(left, text="Options")
        options_frame.pack(fill=tk.X, padx=2, pady=6)
        grid = ttk.Frame(options_frame)
        grid.pack(fill=tk.X, padx=4, pady=4)
        ttk.Label(grid, text="Set duration (min):").grid(row=0, column=0, sticky="w", pady=2)
        self.set_duration_var = tk.IntVar(value=60)
        ttk.Spinbox(grid, from_=15, to=240, textvariable=self.set_duration_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(grid, text="Energy curve:").grid(row=1, column=0, sticky="w", pady=2)
        self.energy_curve_var = tk.StringVar(value="build")
        ttk.Combobox(grid, textvariable=self.energy_curve_var, values=["build", "wave", "peak_middle", "constant"],
                     width=12, state="readonly").grid(row=1, column=1, sticky="w")
        ttk.Label(grid, text="Target loudness (LUFS):").grid(row=2, column=0, sticky="w", pady=2)
        self.premaster_lufs_var = tk.DoubleVar(value=-14.0)
        ttk.Spinbox(grid, from_=-24.0, to=-6.0, increment=0.5, textvariable=self.premaster_lufs_var, width=8).grid(row=2, column=1, sticky="w")
        self.premaster_tone_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grid, text="Match tone to the set", variable=self.premaster_tone_var).grid(row=3, column=0, columnspan=2, sticky="w")
        self.premaster_phase_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(grid, text="Fix phase problems", variable=self.premaster_phase_var).grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Button(options_frame, text="Mastering Report", command=self.mastering_report).pack(anchor="w", padx=4, pady=(0, 4))
        
        cache_frame = ttk.Frame(left)
        cache_frame.pack(fill=tk.X, padx=2, pady=2)
        self.cache_label = ttk.Label(cache_frame, text="", foreground="#52514e", wraplength=320, anchor="w", justify=tk.LEFT)
        self.cache_label.pack(fill=tk.X)
        
        # ---- right: tracks table + charts
        right = ttk.Frame(paned)
        paned.add(right, weight=1)
        self.set_notebook = ttk.Notebook(right)
        self.set_notebook.pack(fill=tk.BOTH, expand=True)
        
        table_frame = ttk.Frame(self.set_notebook)
        self.set_notebook.add(table_frame, text="Tracks")
        self.table_caption = ttk.Label(table_frame, text="", foreground="#52514e", anchor="w")
        self.table_caption.pack(fill=tk.X, padx=4, pady=(4, 0))
        columns = ("#", "Filename", "BPM", "Key", "Duration", "Energy (1-10)", "Master", "Flags")
        self.playlist_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=15)
        widths = {"#": 35, "Filename": 260, "BPM": 60, "Key": 80, "Duration": 65, "Energy (1-10)": 90, "Master": 60, "Flags": 260}
        for col in columns:
            self.playlist_tree.heading(col, text=col)
            self.playlist_tree.column(col, width=widths[col], anchor="w" if col in ("Filename", "Flags", "Key") else "center")
        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.playlist_tree.yview)
        self.playlist_tree.configure(yscrollcommand=scrollbar.set)
        self.playlist_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.playlist_tree.bind("<<TreeviewSelect>>", self.on_track_selected)
        
        self.overview_frame = ttk.Frame(self.set_notebook)
        self.set_notebook.add(self.overview_frame, text="Overview")
        self.track_frame = ttk.Frame(self.set_notebook)
        self.set_notebook.add(self.track_frame, text="Track")
        self.premaster_frame = ttk.Frame(self.set_notebook)
        self.set_notebook.add(self.premaster_frame, text="Pre-master")
        for f, msg in ((self.overview_frame, "Analyze the folder and create a set list to see the energy curve and the set map."),
                       (self.track_frame, "Select a track in the Tracks tab to see its energy envelope, intro/outro and tone balance."),
                       (self.premaster_frame, "Run 'Pre-master Set...' to see what was changed on every track.")):
            ttk.Label(f, text=msg, foreground="#52514e", wraplength=600).pack(padx=20, pady=20, anchor="w")
    
    # ------------------------------------------------------------------ project / workflow helpers
    def load_project(self, directory):
        """Open (or create in memory) the set project of a folder and restore its state"""
        if not directory or not os.path.isdir(directory):
            return
        self.playlist_dir_var.set(directory)
        self.current_playlist_dir = directory
        self.project = SetProject(directory)
        opts = self.project.options
        self.set_duration_var.set(int(opts.get("set_duration", 60)))
        self.energy_curve_var.set(opts.get("energy_curve", "build"))
        self.premaster_lufs_var.set(float(opts.get("target_lufs", -14.0)))
        self.premaster_tone_var.set(bool(opts.get("tone_match", True)))
        self.premaster_phase_var.set(bool(opts.get("fix_phase", True)))
        
        manager = PlaylistManager(directory)
        manager.tracks = list(self.project.tracks)
        self.playlist_manager = manager
        self.current_set_list = self.project.set_list_tracks() or None
        self.transition_planner = self._planner_from_project()
        self.transition_source_dir = directory
        
        if self.current_set_list:
            self._populate_playlist_tree(self.current_set_list, "Set list (proposed order)")
        elif manager.tracks:
            self._populate_playlist_tree(manager.tracks, "Analyzed tracks (folder order)")
        else:
            self._populate_playlist_tree([], "No analysis yet")
        self._refresh_workflow()
        self._render_overview()
        self._render_premaster()
        if SetProject.exists(directory):
            self.update_status(f"Project loaded: {self.project.path}")
        else:
            self.update_status(f"New set project for {directory} (saved after the first step)")
    
    def _save_project(self):
        if self.project is None:
            return
        self.project.options.update({
            "set_duration": int(self.set_duration_var.get()),
            "energy_curve": self.energy_curve_var.get(),
            "target_lufs": float(self.premaster_lufs_var.get()),
            "tone_match": bool(self.premaster_tone_var.get()),
            "fix_phase": bool(self.premaster_phase_var.get()),
        })
        self.project.save()
        self._refresh_workflow()
    
    def _planner_from_project(self):
        """Rebuild a TransitionPlanner from the saved plan (no audio work)"""
        data = self.project.data.get("transitions") if self.project else None
        if not data or not data.get("tracks"):
            return None
        planner = TransitionPlanner(self.project.set_list_tracks() or self.project.tracks)
        planner.profiles = list(data["tracks"])
        planner.transitions = list(data.get("transitions") or [])
        return planner
    
    def _refresh_workflow(self):
        """Update the step panel from the project"""
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
            for k in ("count", "cached", "analyzed", "duration", "curve", "out_dir", "file", "playlist", "db", "cues"):
                if k in details:
                    parts.append(f"{k} {details[k]}")
            w["detail"].config(text=" · ".join(parts))
        key, hint = self.project.next_step()
        self.next_step_label.config(text=f"Next: {hint}")
        try:
            stats = get_store().stats()
            self.cache_label.config(text=f"Analysis cache: {stats['files']} files, {stats['entries']} results ({stats['db_path']})")
        except Exception:
            pass
    
    def show_project_summary(self):
        if self.project is None:
            messagebox.showinfo("Project", "Choose a music folder first")
            return
        self._show_text_window("Set project", "\n".join(self.project.summary_lines()), "set_summary.txt")
    
    def _show_figure(self, container, fig):
        """Embed a matplotlib figure in a frame (replacing its content)"""
        for child in container.winfo_children():
            child.destroy()
        canvas = FigureCanvasTkAgg(fig, container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self._chart_canvases[str(container)] = canvas
        return canvas
    
    def _render_overview(self):
        """Overview tab: energy curve + BPM, and the set map when transitions exist"""
        tracks = self.current_set_list or (self.playlist_manager.tracks if getattr(self, "playlist_manager", None) else [])
        if not tracks:
            return
        for child in self.overview_frame.winfo_children():
            child.destroy()
        targets = None
        if self.current_set_list:
            values = [PlaylistManager._energy_value(t) for t in tracks]
            targets = PlaylistManager._target_curve(values, self.energy_curve_var.get())
        top = ttk.Frame(self.overview_frame)
        top.pack(fill=tk.BOTH, expand=True)
        self._show_figure(top, charts.set_overview(tracks, targets))
        planner = getattr(self, "transition_planner", None)
        if planner and planner.profiles:
            bottom = ttk.Frame(self.overview_frame)
            bottom.pack(fill=tk.BOTH, expand=True)
            self._show_figure(bottom, charts.set_timeline(planner.profiles, planner.transitions))
    
    def _render_premaster(self):
        pm = self.project.data.get("premaster") if self.project else None
        if not pm or not pm.get("results"):
            return
        for child in self.premaster_frame.winfo_children():
            child.destroy()
        fig_frame = ttk.Frame(self.premaster_frame)
        fig_frame.pack(fill=tk.BOTH, expand=True)
        self._show_figure(fig_frame, charts.premaster_before_after(pm["results"], float(pm.get("target_lufs", -14.0))))
        text = scrolledtext.ScrolledText(self.premaster_frame, height=8, font=("Consolas", 9))
        text.pack(fill=tk.X)
        text.insert(tk.END, pm.get("summary", ""))
    
    def on_track_selected(self, event=None):
        """Track tab: envelope + intro/outro + tone balance for the selected row"""
        selection = self.playlist_tree.selection()
        if not selection:
            return
        values = self.playlist_tree.item(selection[0], "values")
        if not values or len(values) < 2:
            return
        filename = values[1]
        planner = getattr(self, "transition_planner", None)
        profile = None
        if planner:
            for p in planner.profiles:
                if p.get("filename") == filename:
                    profile = p
                    break
        if profile is None:
            source = self.current_set_list or (self.playlist_manager.tracks if getattr(self, "playlist_manager", None) else [])
            for t in source:
                if t.get("filename") == filename:
                    profile = dict(t)
                    break
        if profile is None:
            return
        median = None
        if planner:
            reports = [p.get("mastering") for p in planner.profiles if p.get("mastering") and p["mastering"].get("lufs") is not None]
            if reports:
                median = playlist_tone_target(reports)
        self._show_figure(self.track_frame, charts.track_detail(profile, median))
        self.set_notebook.select(self.track_frame)
    
    def create_dj_tools_tab(self):
        """Create DJ tools tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="DJ Tools")
        
        # File selection
        file_frame = ttk.Frame(frame)
        file_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(file_frame, text="Audio File:").pack(side=tk.LEFT, padx=5)
        self.dj_tools_file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.dj_tools_file_var, width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_frame, text="Browse", command=self.browse_dj_tools_file).pack(side=tk.LEFT, padx=5)
        
        # Buttons
        buttons_frame = ttk.Frame(frame)
        buttons_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Button(buttons_frame, text="Detect Cue Points", 
                  command=self.detect_cue_points).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Suggest Loops", 
                  command=self.suggest_loops).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Analyze Zones", 
                  command=self.analyze_zones).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Generate DJ Notes", 
                  command=self.generate_dj_notes).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons_frame, text="Batch Analyze", 
                  command=self.batch_analyze).pack(side=tk.LEFT, padx=5)
        
        # Results
        results_frame = ttk.Frame(frame)
        results_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.dj_tools_results = scrolledtext.ScrolledText(results_frame, height=30)
        self.dj_tools_results.pack(fill=tk.BOTH, expand=True)
    
    def create_audio_effects_tab(self):
        """Create audio effects analysis tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Audio Effects")
        
        # File selection
        file_frame = ttk.Frame(frame)
        file_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(file_frame, text="Audio File:").pack(side=tk.LEFT, padx=5)
        self.effects_file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.effects_file_var, width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_frame, text="Browse", command=self.browse_effects_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_frame, text="Analyze Effects", 
                  command=self.analyze_effects).pack(side=tk.LEFT, padx=5)
        
        # Results
        results_frame = ttk.Frame(frame)
        results_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.effects_results = scrolledtext.ScrolledText(results_frame, height=30)
        self.effects_results.pack(fill=tk.BOTH, expand=True)
    
    def create_export_tab(self):
        """Create export tools tab"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Export Tools")
        
        # Export options
        options_frame = ttk.LabelFrame(frame, text="Export Options")
        options_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Label(options_frame, text="Format:").pack(side=tk.LEFT, padx=5)
        self.export_format_var = tk.StringVar(value="JSON")
        format_combo = ttk.Combobox(options_frame, textvariable=self.export_format_var,
                                   values=["JSON", "CSV", "M3U", "Rekordbox XML", "Traktor NML", "TXT"],
                                   width=15, state="readonly")
        format_combo.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(options_frame, text="Export Analysis", 
                  command=self.export_analysis).pack(side=tk.LEFT, padx=5)
        ttk.Button(options_frame, text="Export Playlist", 
                  command=self.export_playlist).pack(side=tk.LEFT, padx=5)
        
        # Export log
        log_frame = ttk.LabelFrame(frame, text="Export Log")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.export_log = scrolledtext.ScrolledText(log_frame, height=20)
        self.export_log.pack(fill=tk.BOTH, expand=True)
    
    # File browsing methods
    def browse_track1(self):
        filename = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("Audio files", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg"), ("All files", "*.*")]
        )
        if filename:
            self.track1_path_var.set(filename)
            self.current_track1 = filename
    
    def browse_track1_compat(self):
        filename = filedialog.askopenfilename(
            title="Select Track 1",
            filetypes=[("Audio files", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg"), ("All files", "*.*")]
        )
        if filename:
            self.track1_compat_var.set(filename)
            self.current_track1 = filename
    
    def browse_track2_compat(self):
        filename = filedialog.askopenfilename(
            title="Select Track 2",
            filetypes=[("Audio files", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg"), ("All files", "*.*")]
        )
        if filename:
            self.track2_compat_var.set(filename)
            self.current_track2 = filename
    
    def browse_playlist_dir(self):
        directory = filedialog.askdirectory(title="Select music folder")
        if directory:
            self.load_project(directory)
    
    def browse_dj_tools_file(self):
        filename = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("Audio files", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg"), ("All files", "*.*")]
        )
        if filename:
            self.dj_tools_file_var.set(filename)
    
    def browse_effects_file(self):
        filename = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("Audio files", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg"), ("All files", "*.*")]
        )
        if filename:
            self.effects_file_var.set(filename)
    
    # Analysis methods
    def analyze_track1(self):
        """Analyze single track"""
        file_path = self.track1_path_var.get()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "Please select a valid audio file")
            return
        
        def analyze():
            try:
                self.update_status("Analyzing track...")
                analyzer = AudioAnalyzer(file_path)
                features = analyzer.get_audio_features()
                
                # Format results
                result_text = f"Track Analysis: {os.path.basename(file_path)}\n"
                result_text += "=" * 50 + "\n\n"
                result_text += f"Duration: {features['duration']:.1f} seconds\n"
                result_text += f"BPM: {features['bpm']:.1f} (confidence: {features['bpm_confidence']:.2f})\n"
                result_text += f"Key: {features['key']} (confidence: {features['key_confidence']:.2f})\n"
                result_text += f"Energy Level: {features.get('energy_level', 0):.1f}/10\n"
                result_text += f"Average Energy: {features['avg_energy']:.4f}\n"
                result_text += f"Max Energy: {features['max_energy']:.4f}\n"
                result_text += f"Energy Std Dev: {features['energy_std']:.4f}\n"
                result_text += f"Beat Count: {features['beat_count']}\n"
                result_text += f"Section Count: {features['section_count']}\n"
                result_text += f"Drop Count: {features['drop_count']}\n"
                
                # Sections
                if features.get('sections'):
                    result_text += "\nSections:\n"
                    for section_name, start, end in features['sections']:
                        result_text += f"  {section_name}: {start:.1f}s - {end:.1f}s\n"
                
                self.track1_results.delete(1.0, tk.END)
                self.track1_results.insert(1.0, result_text)
                
                # Create visualization
                self.create_track_visualization(analyzer)
                
                self.update_status("Analysis complete")
            except Exception as e:
                messagebox.showerror("Error", f"Analysis failed: {str(e)}")
                self.update_status("Error during analysis")
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def create_track_visualization(self, analyzer: AudioAnalyzer):
        """Create visualization for track analysis"""
        # Clear existing plots
        for widget in self.track1_viz_frame.winfo_children():
            widget.destroy()
        
        try:
            fig, axes = plt.subplots(2, 1, figsize=(8, 6))
            
            # Energy profile
            times, rms = analyzer.analyze_energy_profile()
            axes[0].plot(times, rms, label='Energy', color='blue', alpha=0.7)
            axes[0].set_title('Energy Profile')
            axes[0].set_ylabel('RMS Energy')
            axes[0].legend()
            axes[0].grid(True, alpha=0.3)
            
            # Beat grid
            beat_times, beat_strengths = analyzer.analyze_beat_grid()
            axes[1].vlines(beat_times[:100], 0, beat_strengths[:100], alpha=0.6, color='red', label='Beats')
            axes[1].set_title('Beat Grid (first 100 beats)')
            axes[1].set_xlabel('Time (s)')
            axes[1].set_ylabel('Beat Strength')
            axes[1].legend()
            axes[1].grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            canvas = FigureCanvasTkAgg(fig, self.track1_viz_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        except Exception as e:
            print(f"Visualization error: {e}")
    
    def analyze_compatibility(self):
        """Analyze compatibility between two tracks"""
        track1 = self.track1_compat_var.get()
        track2 = self.track2_compat_var.get()
        
        if not track1 or not track2:
            messagebox.showerror("Error", "Please select both tracks")
            return
        
        if not os.path.exists(track1) or not os.path.exists(track2):
            messagebox.showerror("Error", "One or both files not found")
            return
        
        def analyze():
            try:
                self.update_status("Analyzing compatibility...")
                analyzer = EnhancedMixAnalyzer()
                results = analyzer.analyze_tracks(track1, track2)
                
                # Format results
                result_text = "Two-Track Compatibility Analysis\n"
                result_text += "=" * 50 + "\n\n"
                
                compat = results['compatibility']
                result_text += f"BPM Compatibility: {compat['bpm_compatibility']:.1f}%\n"
                result_text += f"Key Compatibility: {compat['key_compatibility']:.1f}%\n"
                result_text += f"Energy Compatibility: {compat['energy_compatibility']:.1f}%\n"
                result_text += f"Overall Score: {compat['overall_score']:.1f}%\n\n"
                
                mix_sugg = results['mix_suggestions']
                result_text += "Mix Suggestions:\n"
                result_text += f"  Recommended Duration: {mix_sugg['recommended_mix_duration']:.1f}s\n"
                result_text += f"  BPM Sync Required: {mix_sugg['bpm_sync_required']}\n"
                
                if mix_sugg.get('track1_exit_points'):
                    result_text += f"  Track 1 Exit Points: {[f'{t:.1f}s' for t in mix_sugg['track1_exit_points'][:3]]}\n"
                if mix_sugg.get('track2_entry_points'):
                    result_text += f"  Track 2 Entry Points: {[f'{t:.1f}s' for t in mix_sugg['track2_entry_points'][:3]]}\n"
                
                self.compat_results.delete(1.0, tk.END)
                self.compat_results.insert(1.0, result_text)
                
                self.analysis_results = results
                self.update_status("Compatibility analysis complete")
            except Exception as e:
                messagebox.showerror("Error", f"Analysis failed: {str(e)}")
                self.update_status("Error during analysis")
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def analyze_playlist(self):
        """Analyze the folder (cached per file) and record it in the project"""
        directory = self.playlist_dir_var.get()
        if not directory or not os.path.exists(directory):
            messagebox.showerror("Error", "Please select a valid directory")
            return
        if self.project is None or os.path.normcase(os.path.abspath(self.project.folder)) != os.path.normcase(os.path.abspath(directory)):
            self.load_project(directory)
        
        def analyze():
            try:
                manager = PlaylistManager(directory)
                audio_files = manager.scan_directory()
                if not audio_files:
                    self.root.after(0, messagebox.showwarning, "Warning", "No audio files found in directory")
                    return
                
                def progress(i, n, name, status):
                    self.root.after(0, self.update_status, f"Analyzing {i}/{n} ({status}): {name}")
                
                manager.analyze_playlist(audio_files, progress_callback=progress)
                run = manager.last_run
                
                def done():
                    before = {t["file_path"] for t in self.project.tracks}
                    after = {t["file_path"] for t in manager.tracks}
                    self.playlist_manager = manager
                    self.project.set_tracks(manager.tracks)
                    if before and before != after:
                        self.project.invalidate_from("analyze")
                        self.current_set_list = None
                        self.transition_planner = None
                    else:
                        self.current_set_list = self.project.set_list_tracks() or None
                    self.project.mark("analyze", count=len(manager.tracks), cached=run["cached"], analyzed=run["analyzed"])
                    self._save_project()
                    self._populate_playlist_tree(self.current_set_list or manager.tracks,
                                                 "Set list (proposed order)" if self.current_set_list else "Analyzed tracks (folder order)")
                    self._render_overview()
                    self.update_status(f"Analyzed {len(manager.tracks)} tracks ({run['cached']} from cache, {run['analyzed']} new, {run['failed']} failed)")
                
                self.root.after(0, done)
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Error", f"Playlist analysis failed: {str(e)}")
                self.root.after(0, self.update_status, "Error during analysis")
        
        self.update_status("Analyzing playlist...")
        threading.Thread(target=analyze, daemon=True).start()
    
    def _populate_playlist_tree(self, tracks, caption=None):
        """Fill the playlist table with a list of track dictionaries"""
        for item in self.playlist_tree.get_children():
            self.playlist_tree.delete(item)
        
        planner = getattr(self, "transition_planner", None)
        mastering_by_name = {}
        if planner:
            for p in planner.profiles:
                if p.get("mastering"):
                    mastering_by_name[p.get("filename")] = p["mastering"]
        
        for idx, track in enumerate(tracks):
            bpm = track.get('bpm', 0) or 0
            duration = track.get('duration', 0) or 0
            energy = track.get('energy_level', 0) or 0
            m = mastering_by_name.get(track.get('filename', ''), {})
            score = m.get('score')
            flags = m.get('flags') or []
            self.playlist_tree.insert("", tk.END, values=(
                idx + 1,
                track.get('filename', ''),
                f"{bpm:.1f}" if bpm else "-",
                track.get('key') or "-",
                f"{duration / 60:.1f}" if duration else "-",
                f"{energy:.1f}" if energy else "-",
                f"{score:.0f}" if score is not None else "-",
                ("; ".join(flags)[:80] + ("…" if len("; ".join(flags)) > 80 else "")) if flags else ("OK" if m else "-"),
            ))
        if caption is not None:
            self.table_caption.config(text=f"{caption} — {len(tracks)} tracks")
    
    def create_playlist_from_directory(self):
        """
        Create a playlist file from the selected directory.
        Uses the current set list or analyzed tracks when they belong to this
        directory, otherwise simply lists the audio files found in it.
        """
        directory = self.playlist_dir_var.get()
        if not directory or not os.path.isdir(directory):
            messagebox.showerror("Error", "Please select a valid directory")
            return
        
        tracks = None
        source = "directory scan"
        manager = getattr(self, 'playlist_manager', None)
        same_dir = manager is not None and os.path.normcase(os.path.abspath(manager.playlist_directory)) == \
            os.path.normcase(os.path.abspath(directory))
        if same_dir and getattr(self, 'current_set_list', None):
            tracks = self.current_set_list
            source = "set list"
        elif same_dir and manager.tracks:
            tracks = manager.tracks
            source = "analyzed tracks"
        
        if not tracks:
            tracks = PlaylistManager(directory).quick_playlist()
        
        if not tracks:
            messagebox.showwarning("Warning", "No audio files found in directory")
            return
        
        tracks, premastered = self._with_premastered(tracks)
        if premastered:
            source += f", {premastered} pre-mastered copies"
        default_name = os.path.basename(os.path.normpath(directory)) or "playlist"
        filename = filedialog.asksaveasfilename(
            title="Save Playlist",
            initialdir=directory,
            initialfile=f"{default_name}.m3u",
            defaultextension=".m3u",
            filetypes=[("M3U playlist", "*.m3u"), ("M3U8 playlist (UTF-8)", "*.m3u8"), ("All files", "*.*")]
        )
        if not filename:
            return
        
        try:
            ExportTools.export_to_m3u(tracks, filename)
        except Exception as e:
            messagebox.showerror("Error", f"Playlist creation failed: {str(e)}")
            return
        
        if self.project is not None:
            self.project.mark("playlist", file=os.path.basename(filename), count=len(tracks))
            self._save_project()
        self.update_status(f"Playlist saved: {len(tracks)} tracks ({source}) -> {filename}")
        messagebox.showinfo("Playlist created", f"{len(tracks)} tracks written to:\n{filename}")
    
    def _tracks_for_directory(self, directory):
        """Tracks to work on, in order: set list, analyzed tracks, or a plain directory scan."""
        if self.project is None or os.path.normcase(os.path.abspath(self.project.folder)) != os.path.normcase(os.path.abspath(directory)):
            self.load_project(directory)
        manager = getattr(self, 'playlist_manager', None)
        if getattr(self, 'current_set_list', None):
            return list(self.current_set_list), "set list"
        if manager is not None and manager.tracks:
            return list(manager.tracks), "analyzed tracks"
        return PlaylistManager(directory).quick_playlist(), "directory scan"
    
    def plan_transitions(self):
        """Compute intro/outro sections and the transition sheet for the current set"""
        directory = self.playlist_dir_var.get()
        if not directory or not os.path.isdir(directory):
            messagebox.showerror("Error", "Please select a valid directory")
            return
        
        tracks, source = self._tracks_for_directory(directory)
        if len(tracks) < 2:
            messagebox.showwarning("Warning", "At least two audio files are needed to plan transitions")
            return
        
        def work():
            try:
                planner = TransitionPlanner(tracks)
                planner.plan(progress_callback=lambda i, n, name: self.root.after(
                    0, self.update_status, f"Planning transitions {i}/{n}: {name}"))
                self.transition_planner = planner
                self.transition_source_dir = directory
                
                def done():
                    if self.project is not None:
                        self.project.data["transitions"] = planner.to_dict()
                        self.project.mark("transitions", count=len(planner.transitions))
                        self._save_project()
                    self._populate_playlist_tree(tracks, "Set list (proposed order)" if self.current_set_list else "Analyzed tracks (folder order)")
                    self._render_overview()
                    self._show_transition_window(source)
                
                self.root.after(0, done)
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Error", f"Transition planning failed: {str(e)}")
                self.root.after(0, self.update_status, "Error during transition planning")
        
        self.update_status(f"Planning transitions for {len(tracks)} tracks ({source})...")
        threading.Thread(target=work, daemon=True).start()
    
    def _show_text_window(self, title: str, text_content: str, save_name: str = "report.txt"):
        """Simple scrollable text window with a save button"""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("900x600")
        toolbar = ttk.Frame(win)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        text = scrolledtext.ScrolledText(win, wrap=tk.NONE, font=("Consolas", 10))
        
        def save():
            filename = filedialog.asksaveasfilename(title="Save", initialfile=save_name, defaultextension=".txt",
                                                    filetypes=[("Text", "*.txt"), ("All files", "*.*")])
            if filename:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(text.get("1.0", tk.END))
                self.update_status(f"Saved: {filename}")
        
        ttk.Button(toolbar, text="Save...", command=save).pack(side=tk.RIGHT, padx=5)
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        text.insert(tk.END, text_content)
        return text
    
    def mastering_report(self):
        """Measure loudness, peaks, clipping, tone and phase for the selected directory"""
        directory = self.playlist_dir_var.get()
        if not directory or not os.path.isdir(directory):
            messagebox.showerror("Error", "Please select a valid directory")
            return
        tracks, source = self._tracks_for_directory(directory)
        files = [t['file_path'] for t in tracks]
        if not files:
            messagebox.showwarning("Warning", "No audio files found in directory")
            return
        
        def work():
            try:
                reports = check_files(files, progress=lambda i, n, name: self.root.after(
                    0, self.update_status, f"Mastering check {i}/{n}: {name}"))
                self.mastering_reports = reports
                summary = format_check_summary(reports)
                self.root.after(0, self._show_text_window, "Mastering Report", summary, "mastering_report.txt")
                flagged = sum(1 for r in reports if r.get('flags'))
                self.root.after(0, self.update_status, f"Mastering check done: {flagged}/{len(reports)} tracks with issues")
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Error", f"Mastering check failed: {str(e)}")
        
        self.update_status(f"Checking mastering of {len(files)} tracks ({source})...")
        threading.Thread(target=work, daemon=True).start()
    
    def premaster_set(self):
        """Write loudness-normalised, phase-repaired copies of the tracks into another folder"""
        directory = self.playlist_dir_var.get()
        if not directory or not os.path.isdir(directory):
            messagebox.showerror("Error", "Please select a valid directory")
            return
        tracks, source = self._tracks_for_directory(directory)
        files = [t['file_path'] for t in tracks]
        if not files:
            messagebox.showwarning("Warning", "No audio files found in directory")
            return
        
        # corrected copies always go to <folder>/premaster (never scanned as tracks)
        out_dir = os.path.join(os.path.abspath(directory), PREMASTER_DIRNAME)
        target_lufs = float(self.premaster_lufs_var.get())
        tone = bool(self.premaster_tone_var.get())
        phase = bool(self.premaster_phase_var.get())
        
        def work():
            try:
                results = premaster_files(files, out_dir, target_lufs=target_lufs, tone_match=tone, repair_phase=phase,
                                          progress=lambda i, n, name: self.root.after(
                                              0, self.update_status, f"Pre-mastering {i}/{n}: {name}"))
                summary = format_premaster_summary(results, out_dir)
                done_count = sum(1 for r in results if 'error' not in r)
                
                def done():
                    if self.project is not None:
                        slim = []
                        for r in results:
                            if 'error' in r:
                                slim.append({'input': r['input'], 'error': r['error']})
                                continue
                            keep = ('lufs', 'true_peak_db', 'plr', 'score', 'clip_runs', 'flags')
                            slim.append({'input': r['input'], 'output': r['output'], 'actions': r['actions'],
                                         'before': {k: r['before'].get(k) for k in keep},
                                         'after': {k: r['after'].get(k) for k in keep}})
                        self.project.data["premaster"] = {"out_dir": out_dir, "target_lufs": target_lufs, "tone_match": tone,
                                                          "fix_phase": phase, "results": slim, "summary": summary}
                        self.project.mark("premaster", out_dir=out_dir, count=done_count)
                        self._save_project()
                    self._render_premaster()
                    self.set_notebook.select(self.premaster_frame)
                    self.update_status(f"Pre-master done: {done_count}/{len(results)} tracks written to {out_dir}")
                
                self.root.after(0, done)
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Error", f"Pre-master failed: {str(e)}")
        
        self.update_status(f"Pre-mastering {len(files)} tracks ({source}) into {out_dir} ...")
        self.set_notebook.select(self.premaster_frame)
        threading.Thread(target=work, daemon=True).start()
    
    def _with_premastered(self, tracks):
        """Same track dicts, pointing at the pre-mastered copies when they exist. Returns (tracks, count)."""
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
    
    def _show_transition_window(self, source: str):
        """Display the transition sheet with save / Mixxx export actions"""
        planner = self.transition_planner
        title = f"DynaMix Transition Sheet - {os.path.basename(os.path.normpath(self.transition_source_dir))}"
        
        win = tk.Toplevel(self.root)
        win.title("Transition Plan")
        win.geometry("900x600")
        
        toolbar = ttk.Frame(win)
        toolbar.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(toolbar, text=f"{len(planner.profiles)} tracks, {len(planner.transitions)} transitions ({source})").pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Save Sheet...", command=lambda: self.save_transition_sheet(title)).pack(side=tk.RIGHT, padx=5)
        ttk.Button(toolbar, text="Save JSON...", command=self.save_transition_json).pack(side=tk.RIGHT, padx=5)
        ttk.Button(toolbar, text="Export to Mixxx...", command=lambda: self.export_to_mixxx(text)).pack(side=tk.RIGHT, padx=5)
        
        text = scrolledtext.ScrolledText(win, wrap=tk.NONE, font=("Consolas", 10))
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        text.insert(tk.END, planner.to_text(title))
        self.update_status(f"Transitions planned: {len(planner.transitions)} ({source})")
    
    def save_transition_sheet(self, title: str):
        """Save the transition sheet as a text file"""
        filename = filedialog.asksaveasfilename(
            title="Save Transition Sheet",
            initialdir=self.transition_source_dir,
            initialfile="transitions.txt",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")]
        )
        if filename:
            self.transition_planner.save_text(filename, title)
            self.update_status(f"Transition sheet saved: {filename}")
    
    def save_transition_json(self):
        """Save the per-track analysis and transitions as JSON"""
        filename = filedialog.asksaveasfilename(
            title="Save Transition Data", initialdir=self.transition_source_dir, initialfile="transitions.json",
            defaultextension=".json", filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if filename:
            self.transition_planner.save_json(filename)
            self.update_status(f"Transition data saved: {filename}")
    
    def export_to_mixxx(self, log_widget=None):
        """Write intro/outro cues and a playlist into the Mixxx database"""
        planner = getattr(self, 'transition_planner', None)
        if planner is None or not planner.profiles:
            messagebox.showwarning("Warning", "Plan transitions first")
            return
        
        detected = find_mixxx_db()
        db_path = filedialog.askopenfilename(
            title="Select the Mixxx database (mixxxdb.sqlite) - close Mixxx first",
            initialdir=os.path.dirname(detected) if detected else None,
            initialfile=os.path.basename(detected) if detected else "mixxxdb.sqlite",
            filetypes=[("Mixxx database", "mixxxdb.sqlite"), ("SQLite", "*.sqlite"), ("All files", "*.*")]
        )
        if not db_path:
            return
        
        default_name = f"DynaMix - {os.path.basename(os.path.normpath(self.transition_source_dir))}"
        playlist_name = simpledialog.askstring("Mixxx playlist", "Name of the Mixxx playlist to create:",
                                               initialvalue=default_name, parent=self.root)
        if playlist_name is None:
            return
        
        if not messagebox.askyesno("Export to Mixxx",
                                   "Mixxx must be closed while exporting.\n"
                                   "A backup of the database will be created first.\n\nContinue?"):
            return
        
        profiles, premastered = self._with_premastered(planner.profiles)
        try:
            exporter = MixxxExporter(db_path)
            report = exporter.export(profiles, playlist_name=playlist_name.strip() or None)
        except Exception as e:
            messagebox.showerror("Error", f"Mixxx export failed: {str(e)}")
            return
        
        summary = format_report(report)
        if premastered:
            summary = f"Using the pre-mastered copies for {premastered} tracks ({PREMASTER_DIRNAME} subfolder).\n" + summary
        if self.project is not None:
            self.project.mark("mixxx", db=os.path.basename(os.path.dirname(db_path)) or db_path, playlist=playlist_name,
                              cues=report['cues_written'])
            self._save_project()
        if log_widget is not None:
            log_widget.insert(tk.END, "\n\nMIXXX EXPORT\n" + "-" * 60 + "\n" + summary + "\n")
            log_widget.see(tk.END)
        self.update_status(f"Mixxx export: {report['cues_written']} cues written, {len(report['missing'])} tracks missing")
        messagebox.showinfo("Export to Mixxx", summary)
    
    def create_set_list(self):
        """Create the set list proposal from the analyzed tracks and record it in the project"""
        manager = getattr(self, 'playlist_manager', None)
        if manager is None or not manager.tracks:
            messagebox.showwarning("Warning", "Please analyze the folder first (step 1)")
            return
        
        try:
            duration = int(self.set_duration_var.get())
            energy_curve = self.energy_curve_var.get()
            set_list = manager.create_set_list(duration_minutes=duration, energy_curve=energy_curve)
            self.current_set_list = set_list
            self.transition_planner = None
            if self.project is not None:
                self.project.set_set_list(set_list)
                self.project.invalidate_from("setlist")
                self.project.mark("setlist", count=len(set_list), duration=duration, curve=energy_curve)
                self._save_project()
            self._populate_playlist_tree(set_list, "Set list (proposed order)")
            self._render_overview()
            self.set_notebook.select(self.overview_frame)
            total = sum(float(t.get('duration') or 0) for t in set_list) / 60
            self.update_status(f"Set list created: {len(set_list)} tracks, {total:.0f} min, curve '{energy_curve}'")
        except Exception as e:
            messagebox.showerror("Error", f"Set list creation failed: {str(e)}")
    
    def detect_cue_points(self):
        """Detect cue points"""
        file_path = self.dj_tools_file_var.get()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "Please select a valid audio file")
            return
        
        def analyze():
            try:
                self.update_status("Detecting cue points...")
                dj_tools = DJTools(file_path)
                cue_points = dj_tools.detect_cue_points()
                
                result_text = f"Cue Points: {os.path.basename(file_path)}\n"
                result_text += "=" * 50 + "\n\n"
                
                for i, cue in enumerate(cue_points[:10], 1):
                    result_text += f"{i}. {cue['time']:.1f}s - {cue['type']} (Strength: {cue['strength']:.2f})\n"
                
                self.dj_tools_results.delete(1.0, tk.END)
                self.dj_tools_results.insert(1.0, result_text)
                self.update_status("Cue points detected")
            except Exception as e:
                messagebox.showerror("Error", f"Cue point detection failed: {str(e)}")
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def suggest_loops(self):
        """Suggest loops"""
        file_path = self.dj_tools_file_var.get()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "Please select a valid audio file")
            return
        
        def analyze():
            try:
                self.update_status("Suggesting loops...")
                dj_tools = DJTools(file_path)
                loops = dj_tools.suggest_loops()
                
                result_text = f"Loop Suggestions: {os.path.basename(file_path)}\n"
                result_text += "=" * 50 + "\n\n"
                
                for i, loop in enumerate(loops[:10], 1):
                    result_text += f"{i}. {loop['start_time']:.1f}s - {loop['end_time']:.1f}s "
                    result_text += f"({loop['duration']:.1f}s)\n"
                    result_text += f"   Type: {loop['type']}\n"
                    result_text += f"   Energy Stability: {loop['energy_stability']:.2f}\n\n"
                
                self.dj_tools_results.delete(1.0, tk.END)
                self.dj_tools_results.insert(1.0, result_text)
                self.update_status("Loops suggested")
            except Exception as e:
                messagebox.showerror("Error", f"Loop suggestion failed: {str(e)}")
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def analyze_zones(self):
        """Analyze performance zones"""
        file_path = self.dj_tools_file_var.get()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "Please select a valid audio file")
            return
        
        def analyze():
            try:
                self.update_status("Analyzing zones...")
                dj_tools = DJTools(file_path)
                zones = dj_tools.analyze_performance_zones()
                
                result_text = f"Performance Zones: {os.path.basename(file_path)}\n"
                result_text += "=" * 50 + "\n\n"
                
                for zone_name, zone_data in zones.items():
                    if zone_data['start'] > 0:
                        result_text += f"{zone_name.title()}:\n"
                        result_text += f"  Start: {zone_data['start']:.1f}s\n"
                        result_text += f"  End: {zone_data['end']:.1f}s\n"
                        result_text += f"  Energy: {zone_data['energy']:.4f}\n"
                        result_text += f"  Complexity: {zone_data['complexity']:.4f}\n\n"
                
                self.dj_tools_results.delete(1.0, tk.END)
                self.dj_tools_results.insert(1.0, result_text)
                self.update_status("Zones analyzed")
            except Exception as e:
                messagebox.showerror("Error", f"Zone analysis failed: {str(e)}")
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def generate_dj_notes(self):
        """Generate DJ notes"""
        file_path = self.dj_tools_file_var.get()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "Please select a valid audio file")
            return
        
        def analyze():
            try:
                self.update_status("Generating DJ notes...")
                dj_tools = DJTools(file_path)
                notes = dj_tools.generate_dj_notes()
                
                self.dj_tools_results.delete(1.0, tk.END)
                self.dj_tools_results.insert(1.0, notes)
                self.update_status("DJ notes generated")
            except Exception as e:
                messagebox.showerror("Error", f"DJ notes generation failed: {str(e)}")
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def batch_analyze(self):
        """Batch analyze directory"""
        directory = filedialog.askdirectory(title="Select Directory for Batch Analysis")
        if not directory:
            return
        
        output_dir = filedialog.askdirectory(title="Select Output Directory")
        if not output_dir:
            return
        
        def analyze():
            try:
                self.update_status("Batch analyzing...")
                batch_analyze_tracks(directory, output_dir)
                self.update_status("Batch analysis complete")
                messagebox.showinfo("Success", f"Batch analysis complete!\nResults saved to: {output_dir}")
            except Exception as e:
                messagebox.showerror("Error", f"Batch analysis failed: {str(e)}")
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def analyze_effects(self):
        """Analyze audio effects"""
        file_path = self.effects_file_var.get()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "Please select a valid audio file")
            return
        
        def analyze():
            try:
                self.update_status("Analyzing audio effects...")
                effects = AudioEffects(file_path)
                analysis = effects.get_comprehensive_effects_analysis()
                
                result_text = f"Audio Effects Analysis: {os.path.basename(file_path)}\n"
                result_text += "=" * 50 + "\n\n"
                
                # Dynamics
                result_text += "Dynamics:\n"
                dynamics = analysis['dynamics']
                result_text += f"  Peak Level: {dynamics['peak_level']:.4f}\n"
                result_text += f"  RMS Level: {dynamics['rms_level']:.4f}\n"
                result_text += f"  Dynamic Range: {dynamics['dynamic_range_db']:.2f} dB\n"
                result_text += f"  Compression Ratio: {dynamics['compression_ratio']:.2f}\n"
                result_text += f"  Crest Factor: {dynamics['crest_factor']:.2f}\n"
                result_text += f"  Is Compressed: {dynamics['is_compressed']}\n\n"
                
                # Frequency spectrum
                result_text += "Frequency Spectrum:\n"
                freq = analysis['frequency_spectrum']
                result_text += f"  Spectral Centroid: {freq['spectral_centroid']:.2f} Hz\n"
                result_text += f"  Spectral Rolloff: {freq['spectral_rolloff']:.2f} Hz\n"
                result_text += f"  Zero Crossing Rate: {freq['zero_crossing_rate']:.4f}\n"
                result_text += f"  Bass: {freq['bass_percentage']:.1f}%\n"
                result_text += f"  Mid: {freq['mid_percentage']:.1f}%\n"
                result_text += f"  Treble: {freq['treble_percentage']:.1f}%\n\n"
                
                # Transient response
                result_text += "Transient Response:\n"
                transient = analysis['transient_response']
                result_text += f"  Onset Count: {transient['onset_count']}\n"
                result_text += f"  Avg Attack Time: {transient['avg_attack_time']:.3f}s\n"
                result_text += f"  Max Attack Time: {transient['max_attack_time']:.3f}s\n"
                result_text += f"  Min Attack Time: {transient['min_attack_time']:.3f}s\n"
                
                if analysis['clipping_points']:
                    result_text += f"\n⚠️  Clipping detected at: {analysis['clipping_points'][:5]}\n"
                
                self.effects_results.delete(1.0, tk.END)
                self.effects_results.insert(1.0, result_text)
                self.update_status("Effects analysis complete")
            except Exception as e:
                messagebox.showerror("Error", f"Effects analysis failed: {str(e)}")
        
        threading.Thread(target=analyze, daemon=True).start()
    
    def export_analysis(self):
        """Export analysis results"""
        if not self.analysis_results:
            messagebox.showwarning("Warning", "No analysis results to export")
            return
        
        filename = filedialog.asksaveasfilename(
            title="Export Analysis",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("CSV", "*.csv"), ("Text", "*.txt"), ("All", "*.*")]
        )
        
        if not filename:
            return
        
        try:
            format_type = self.export_format_var.get().lower()
            
            if format_type == "json":
                ExportTools.export_to_json(self.analysis_results, filename)
            elif format_type == "csv":
                # Convert to list format for CSV
                if isinstance(self.analysis_results, dict):
                    ExportTools.export_to_csv([self.analysis_results], filename)
            elif format_type == "txt":
                ExportTools.export_analysis_report(self.analysis_results, filename, format='txt')
            
            self.export_log.insert(tk.END, f"Exported analysis to: {filename}\n")
            self.update_status("Export complete")
        except Exception as e:
            messagebox.showerror("Error", f"Export failed: {str(e)}")
    
    def export_playlist(self):
        """Export playlist"""
        if not hasattr(self, 'current_set_list') and not hasattr(self, 'playlist_manager'):
            messagebox.showwarning("Warning", "No playlist to export")
            return
        
        playlist = getattr(self, 'current_set_list', None)
        if not playlist and hasattr(self, 'playlist_manager'):
            playlist = self.playlist_manager.tracks
        
        if not playlist:
            messagebox.showwarning("Warning", "No playlist data available")
            return
        
        format_type = self.export_format_var.get().lower()
        
        if format_type == "m3u":
            filename = filedialog.asksaveasfilename(
                title="Export Playlist",
                defaultextension=".m3u",
                filetypes=[("M3U", "*.m3u"), ("All", "*.*")]
            )
            if filename:
                ExportTools.export_to_m3u(playlist, filename)
        elif format_type == "rekordbox xml":
            filename = filedialog.asksaveasfilename(
                title="Export Playlist",
                defaultextension=".xml",
                filetypes=[("XML", "*.xml"), ("All", "*.*")]
            )
            if filename:
                ExportTools.export_to_rekordbox_xml(playlist, filename)
        elif format_type == "traktor nml":
            filename = filedialog.asksaveasfilename(
                title="Export Playlist",
                defaultextension=".nml",
                filetypes=[("NML", "*.nml"), ("All", "*.*")]
            )
            if filename:
                ExportTools.export_to_traktor_nml(playlist, filename)
        elif format_type == "json":
            filename = filedialog.asksaveasfilename(
                title="Export Playlist",
                defaultextension=".json",
                filetypes=[("JSON", "*.json"), ("All", "*.*")]
            )
            if filename:
                ExportTools.export_to_json(playlist, filename)
        elif format_type == "csv":
            filename = filedialog.asksaveasfilename(
                title="Export Playlist",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv"), ("All", "*.*")]
            )
            if filename:
                ExportTools.export_to_csv(playlist, filename)
        
        if filename:
            self.export_log.insert(tk.END, f"Exported playlist to: {filename}\n")
            self.update_status("Playlist export complete")


def main():
    """Main entry point for GUI"""
    root = tk.Tk()
    app = DynaMixGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

