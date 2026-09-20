#!/usr/bin/env python3
"""
"FX" tab of the Set Builder: per transition, a stack of effects
(freeze / roll, filter sweep, echo, FX sample) with their settings, a looped
preview while tweaking, and "Apply all FX" which renders the copies into fx/.
"""

import copy
import json
import logging
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
import soundfile as sf
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import charts
import library
import transition_fx as tfx
from analysis_store import dynamix_home
from fx_render import render_preview, render_set, transition_beats, transition_layout_for
from i18n import tr, tr_text
from mastering import load_audio

log = logging.getLogger("dynamix.fx")
MUTED = "#52514e"
PLAN_CHANGED = "The transitions or the set list changed: plan the transitions again (step 3)"
NO_SAMPLE_FILE = "Choose a file for the Sample effect: click a sample in the list"

FX_NAMES = {"freeze": "Freeze", "filter": "Filter", "echo": "Echo", "sample": "Sample", "scratch": "Scratch"}
MAX_A_END_BEATS = 64  # how far after the junction the 'A ends' marker can be moved

# (key, label, kind, choices or (min, max))
FIELDS = {
    "freeze": [("capture_offset_beats", "Capture point (beats)", "int", (-16, 0)),
               ("fade_db", "Fade to (dB)", "float", (-60, 0)),
               ("tail_beats", "Tail (beats)", "int", (0, 8)),
               ("gain_db", "Gain (dB)", "float", (-24, 6))],
    "filter": [("side", "Side", "choice", ("outgoing", "incoming", "across")),
               ("kind", "Type", "choice", ("highpass", "lowpass", "bandpass")),
               ("start_hz", "From (Hz)", "float", (20, 20000)),
               ("end_hz", "To (Hz)", "float", (20, 20000)),
               ("width_octaves", "Band width (octaves)", "float", (0.3, 4)),
               ("resonance", "Resonance (Q)", "float", (0.7, 12)),
               ("beats", "Length (beats)", "choice", (2, 4, 8, 16)),
               ("curve", "Curve", "choice", ("exponential", "linear")),
               ("start_offset_beats", "Start (beats)", "int", (-16, 8)),
               ("release_beats", "Return to dry (beats)", "choice", (tfx.NO_RELEASE, 0, 0.5, 1, 2, 4, 8))],
    "echo": [("start_offset_beats", "Start (beats)", "int", (-16, 0)),
             ("delay_beats", "Delay (beats)", "choice", (0.25, 0.5, 0.75, 1)),
             ("feedback", "Feedback", "float", (0, 0.85)),
             ("mix", "Mix", "float", (0, 1)),
             ("damping_hz", "Damping (Hz)", "float", (1000, 20000))],
    "sample": [("anchor", "Anchor", "choice", ("end_at_junction", "start_at_junction", "center_on_junction")),
               ("offset_beats", "Offset (beats)", "float", (-16, 16)),
               ("gain_db", "Gain (dB)", "float", (-24, 6)),
               ("fade_in_ms", "Fade in (ms)", "int", (0, 2000)),
               ("fade_out_ms", "Fade out (ms)", "int", (0, 2000)),
               ("repeats", "Repeats", "int", (1, 16)),
               ("tempo", "Tempo", "choice", ("varispeed", "stretch", "off")),
               ("sample_bpm", "Sample BPM", "float", (40, 250))],
}
FIELDS["scratch"] = [("sequence", "Sequence", "text", None),
                     ("length_beats", "Length (beats)", "choice", (2, 4, 8, 16)),
                     ("start_offset_beats", "Start (beats)", "int", (-32, 16)),
                     ("side", "Side", "choice", ("outgoing", "incoming")),
                     ("ramp", "Ramp", "choice", ("exponential", "linear")),
                     ("gain_db", "Gain (dB)", "float", (-24, 6))]
# choices shown with a word instead of their stored value
CHOICE_LABELS = {"release_beats": {tfx.NO_RELEASE: "no return (stays filtered)"}}
# scopes of transition_fx.effect_scope that are a word rather than a track name (A, B and A+B read the same anywhere)
SCOPE_LABELS = {"layer": "layer"}


def choice_label(key, value):
    """What a choice field shows for a stored value (translated where the value is a word, e.g. 'no return')."""
    if value is None:
        return ""
    label = CHOICE_LABELS.get(key, {}).get(value)
    if label is not None:
        return tr(label)
    return f"{value:g}" if isinstance(value, float) else str(value)


LOOP_FILTER_KEYS_OFF = ("side", "beats", "start_offset_beats", "release_beats")  # a loop filter sweeps over the freeze
LOOP_FILTER_FIELDS = [f for f in FIELDS["filter"] if f[0] not in LOOP_FILTER_KEYS_OFF]
LOOP_ECHO_FIELDS = [f for f in FIELDS["echo"] if f[0] != "start_offset_beats"]


class Player:
    """WAV playback: looped with winsound on Windows, the default player elsewhere (no loop)."""

    def play_loop(self, path: str) -> bool:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
            return True
        self._open(path)
        return False

    def play_once(self, path: str) -> None:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            self._open(path)

    def stop(self) -> None:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(None, 0)

    @staticmethod
    def _open(path: str) -> None:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


def effect_summary(fx: dict) -> str:
    t = fx.get("type")
    if t == "freeze":
        steps = " → ".join(f"{float(s['beats']):g}×{int(s['repeats'])}" for s in fx.get("steps") or [])
        extra = (" " + tr("+filter") if fx.get("loop_filter") else "") + (" " + tr("+echo") if fx.get("loop_echo") else "")
        return tr("Freeze {steps}", steps=steps) + extra
    if t == "filter":
        return tr("Filter {side} {kind} {start}→{end} Hz, {beats} beats", side=fx.get("side"), kind=fx.get("kind"),
                  start=f"{float(fx.get('start_hz', 0)):.0f}", end=f"{float(fx.get('end_hz', 0)):.0f}",
                  beats=fx.get("beats"))
    if t == "echo":
        return tr("Echo {delay} beat, feedback {feedback}", delay=f"{float(fx.get('delay_beats', 0)):g}",
                  feedback=f"{float(fx.get('feedback', 0)):.2f}")
    if t == "sample":
        name = os.path.basename(fx.get("file") or "") or tr("(choose a sample)")
        repeats = int(fx.get("repeats", 1))
        return tr("Sample {name}{repeats} ({anchor}, tempo {tempo})", name=name,
                  repeats=f" ×{repeats}" if repeats > 1 else "", anchor=fx.get("anchor"),
                  tempo=fx.get("tempo", "varispeed"))
    if t == "scratch":
        return tr("Scratch {sequence} · {beats} beats ({side})", sequence=fx.get("sequence") or "",
                  beats=fx.get("length_beats", 8), side=fx.get("side", "outgoing"))
    return str(t)


def _scrollable(parent):
    """A frame that scrolls vertically inside `parent` (scrollbar and mouse wheel); returns (frame, canvas)."""
    background = ttk.Style(parent).lookup("TFrame", "background") or None
    canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0, background=background)
    bar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set)
    bar.pack(side=tk.RIGHT, fill=tk.Y)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0), pady=6)
    frame = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=frame, anchor="nw")
    frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))

    def wheel(event):
        if isinstance(event.widget, (tk.Listbox, tk.Text)):
            return  # lists and texts scroll themselves
        if canvas.yview() == (0.0, 1.0):
            return  # everything is visible
        steps = int(-event.delta / 120) if event.delta else (-1 if event.num == 4 else 1)
        canvas.yview_scroll(steps, "units")

    def enter(_event):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind_all(seq, wheel)

    def leave(_event):
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.unbind_all(seq)

    for widget in (canvas, frame):
        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", leave, add="+")
    return frame, canvas


def _fmt(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def loop_position(started: float, now: float, length: float) -> float:
    """Where a looped clip of `length` seconds is, `now - started` seconds after its position 0."""
    return (now - started) % length if length > 0 else 0.0


def rotate_clip(clip: np.ndarray, sr: int, offset: float) -> np.ndarray:
    """The clip starting at `offset` seconds and wrapping around: looping it is looping the clip from there."""
    i = int(round(max(0.0, offset) * sr)) % max(1, len(clip))
    return np.concatenate([clip[i:], clip[:i]])


class TransitionFxPanel(ttk.Frame):
    """FX tab of the Set Builder, for the project and transition plan it was built with.
    Needs `app` with: root, project, config, update_status, _report_error, _save_project, _render_overview,
    _start_task and _task_failed (tasks_tab.TasksTabMixin)."""

    def __init__(self, parent, app, player=None):
        super().__init__(parent)
        self.app = app
        self.project = app.project
        self.player = player or Player()
        data = self.project.data.get("transitions") or {}
        self.profiles = list(data.get("tracks") or [])
        self.transitions = list(data.get("transitions") or [])
        self.pair_index = None
        self.fx_index = None
        self.samples = []
        self._previewing = False
        self._preview_job = None
        self._preview_seq = 0
        self._applying = False
        self._logged_warnings = set()  # a preview warning goes to the Log once, not at every render
        self._play = None               # the looping preview: {"clip", "sr", "length", "preview_start", "started"}
        self._playhead_job = None
        self._playhead_item = None
        self._playhead_widget = None
        self._seek_count = 0
        self._setting_position = False
        self._dragging_position = False
        self._waves = {}            # (A file, B file) -> {"a_env", "b_env", "beats"} for the chart
        self._waves_loading = set()
        self._result_env = None     # {"key": what was rendered, "env": peak envelope of the preview clip}
        self._chart_job = None
        self._chart_canvas = None
        self._sample_lengths = {}
        self.last_layout = None
        self._plan_at_open = self._plan_signature()
        self._build()
        self.refresh_transitions()
        self.scan_samples()

    # ------------------------------------------------------------------ layout
    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=6)
        ttk.Button(bar, text=tr("▶ Preview (loop)"), command=self.start_preview).pack(side=tk.LEFT)
        ttk.Button(bar, text=tr("■ Stop"), command=self.stop_preview).pack(side=tk.LEFT, padx=4)
        ttk.Label(bar, text=tr("Length:")).pack(side=tk.LEFT, padx=(12, 2))
        # the codes "short" / "long" go to the renderer; the combobox shows their translation
        self._length_labels = {"short": tr("short"), "long": tr("long")}
        self._length_display = tk.StringVar(value=self._length_labels["short"])
        self.length_var = tk.StringVar(value="short")
        length = ttk.Combobox(bar, textvariable=self._length_display, values=tuple(self._length_labels.values()),
                              width=10, state="readonly")
        length.pack(side=tk.LEFT)
        length.bind("<<ComboboxSelected>>", lambda e: self._length_selected())
        self.apply_button = ttk.Button(bar, text=tr("Apply all FX"), command=self.apply_all)
        self.apply_button.pack(side=tk.LEFT, padx=12)
        self.status_label = ttk.Label(bar, text="", foreground=MUTED)
        self.status_label.pack(side=tk.LEFT, padx=8)

        # position of the looping preview: follows the playback, click or drag to play from another point
        posbar = ttk.Frame(self)
        posbar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(4, 0))
        ttk.Label(posbar, text=tr("Position:")).pack(side=tk.LEFT)
        self.position_var = tk.DoubleVar(value=0.0)
        self.position_scale = ttk.Scale(posbar, from_=0.0, to=1.0, orient=tk.HORIZONTAL, variable=self.position_var)
        self.position_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.position_scale.bind("<ButtonPress-1>", lambda e: setattr(self, "_dragging_position", True))
        self.position_scale.bind("<ButtonRelease-1>", lambda e: self._position_released())
        self.position_label = ttk.Label(posbar, text=tr("(start the preview)"), foreground=MUTED, width=28)
        self.position_label.pack(side=tk.LEFT)

        rows = ttk.PanedWindow(self, orient=tk.VERTICAL)
        rows.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))
        self.chart_frame = ttk.Frame(rows, height=340)
        self.chart_frame.pack_propagate(False)
        rows.add(self.chart_frame, weight=1)
        self._chart_message(tr("Select a transition to see it: A and B, the fades and every effect on a beat axis."))
        panes = ttk.PanedWindow(rows, orient=tk.HORIZONTAL)
        rows.add(panes, weight=1)

        left = ttk.Frame(panes)
        panes.add(left, weight=1)
        ttk.Label(left, text=tr("Transitions"), foreground=MUTED).pack(anchor="w")
        self.trans_tree = ttk.Treeview(left, columns=("#", "Transition", "Score", "FX", "State"), show="headings",
                                       height=12, selectmode="browse")
        headings = {"#": "#", "Transition": tr("Transition"), "Score": tr("Score"), "FX": tr("FX"), "State": tr("State")}
        for col, width in (("#", 30), ("Transition", 260), ("Score", 50), ("FX", 35), ("State", 45)):
            self.trans_tree.heading(col, text=headings[col])
            self.trans_tree.column(col, width=width, anchor="w" if col == "Transition" else "center",
                                   stretch=(col == "Transition"))
        self.trans_tree.pack(fill=tk.BOTH, expand=True)
        self.trans_tree.bind("<<TreeviewSelect>>", lambda e: self.on_transition_selected())
        self.info_label = ttk.Label(left, text="", foreground=MUTED, justify=tk.LEFT, wraplength=380)
        self.info_label.pack(anchor="w", pady=(4, 0))
        self.source_label = ttk.Label(left, text="", foreground=MUTED, justify=tk.LEFT, wraplength=380)
        self.source_label.pack(anchor="w", pady=(0, 4))
        nudge_row = ttk.Frame(left)
        nudge_row.pack(anchor="w")
        ttk.Label(nudge_row, text=tr("Nudge (ms):")).pack(side=tk.LEFT)
        self.nudge_var = tk.StringVar(value="0")
        ttk.Spinbox(nudge_row, from_=-50, to=50, increment=1, textvariable=self.nudge_var, width=6).pack(side=tk.LEFT, padx=4)
        self.nudge_var.trace_add("write", lambda *a: self.on_nudge())
        # where A stops being heard: the plan ties it to the track's own outro, which often makes the
        # transition longer than wanted and forces the effects to stretch over it
        ttk.Label(nudge_row, text=tr("A ends (beats):")).pack(side=tk.LEFT, padx=(14, 0))
        self.a_end_var = tk.StringVar(value="")
        ttk.Spinbox(nudge_row, from_=0, to=MAX_A_END_BEATS, increment=1, textvariable=self.a_end_var,
                    width=6).pack(side=tk.LEFT, padx=4)
        self.a_end_var.trace_add("write", lambda *a: self.on_a_end())
        self.a_end_label = ttk.Label(nudge_row, text="", foreground=MUTED)
        self.a_end_label.pack(side=tk.LEFT)
        ttk.Button(nudge_row, text=tr("Planned"), command=self.reset_a_end).pack(side=tk.LEFT, padx=6)
        # orphan FX (the two tracks no longer follow each other): one line, shown only when there are some
        self.orphan_row = ttk.Frame(left)
        self.orphan_label = ttk.Label(self.orphan_row, text="", foreground=MUTED)
        self.orphan_label.pack(side=tk.LEFT)
        ttk.Button(self.orphan_row, text=tr("Manage…"), command=self.open_orphans).pack(side=tk.LEFT, padx=6)
        self._orphan_window = None
        self._inactive = []

        mid = ttk.Frame(panes)
        panes.add(mid, weight=1)
        ttk.Label(mid, text=tr("FX stack (top to bottom)"), foreground=MUTED).pack(anchor="w")
        # 8 rows asked for, not 12: the list grows with the pane, and a short one leaves room for the buttons below
        self.fx_tree = ttk.Treeview(mid, columns=("On", "Scope", "Effect"), show="headings", height=8, selectmode="browse")
        self.fx_tree.heading("On", text=tr("On"))
        self.fx_tree.heading("Scope", text=tr("On track"))
        self.fx_tree.heading("Effect", text=tr("Effect"))
        self.fx_tree.column("On", width=35, anchor="center", stretch=False)
        self.fx_tree.column("Scope", width=55, anchor="center", stretch=False)
        self.fx_tree.column("Effect", width=300, anchor="w")
        self.fx_tree.bind("<<TreeviewSelect>>", lambda e: self.on_fx_selected())
        # buttons and hint are packed to the bottom first: the list gives up the room, never the buttons
        buttons = ttk.Frame(mid)
        buttons.pack(side=tk.BOTTOM, fill=tk.X, pady=4)
        add = ttk.Menubutton(buttons, text=tr("Add ▾"))
        menu = tk.Menu(add, tearoff=False)
        for fx_type in tfx.FX_TYPES:
            menu.add_command(label=tr(FX_NAMES[fx_type]), command=lambda t=fx_type: self.add_effect(t))
        add["menu"] = menu
        add.pack(side=tk.LEFT)
        for text, command in ((tr("Remove"), self.remove_effect), ("▲", lambda: self.move_effect(-1)),
                              ("▼", lambda: self.move_effect(1)), (tr("Duplicate"), self.duplicate_effect),
                              (tr("On/Off"), self.toggle_effect)):
            ttk.Button(buttons, text=text, command=command).pack(side=tk.LEFT, padx=2)
        hint = ttk.Label(mid, text=tr("Applied from top to bottom, each effect on what the ones above it left (an echo "
                                      "under a filter echoes the filtered sound). 'On track': the side of the junction "
                                      "it writes to, 'layer' mixes over the result."),
                         foreground=MUTED, justify=tk.LEFT, wraplength=320)
        hint.pack(side=tk.BOTTOM, anchor="w", fill=tk.X, pady=(4, 0))
        # wrap on the pane's own width (the sash can be moved); binding on the pane, not the label, avoids a loop
        mid.bind("<Configure>", lambda e: hint.config(wraplength=max(160, e.width - 8)))
        self.fx_tree.pack(fill=tk.BOTH, expand=True)

        right = ttk.LabelFrame(panes, text=tr("Settings"))
        panes.add(right, weight=2)
        self.settings, self._settings_canvas = _scrollable(right)

    def status(self, text):
        if self.winfo_exists():
            self.status_label.config(text=text)

    def _length_selected(self):
        """The length chosen in the combobox (shown translated) becomes its code for the renderer."""
        shown = self._length_display.get()
        self.length_var.set(next((code for code, label in self._length_labels.items() if label == shown), "short"))
        self.schedule_preview()
        self.schedule_chart()

    def _plan_signature(self):
        """The set list and the cue positions of the planned tracks (None when there is no plan)."""
        data = self.project.data.get("transitions")
        tracks = None
        if data is not None:
            tracks = tuple((t.get("file_path"), t.get("intro_start"), t.get("intro_end"), t.get("outro_start"),
                            t.get("outro_end")) for t in data.get("tracks") or [])
        return tuple(self.project.set_list), tracks

    def _plan_changed(self):
        """True when the transitions or the set list changed since the window was opened."""
        return self._plan_signature() != self._plan_at_open

    # ------------------------------------------------------------------ transitions
    def pair(self, index=None):
        index = self.pair_index if index is None else index
        return self.profiles[index]["file_path"], self.profiles[index + 1]["file_path"]

    def entry(self):
        a, b = self.pair()
        return self.project.fx_for_pair(a, b) or {"nudge_ms": 0.0, "effects": []}

    def effects(self):
        return [dict(fx) for fx in self.entry().get("effects") or []]

    def refresh_transitions(self):
        selected = self.pair_index
        self.trans_tree.delete(*self.trans_tree.get_children())
        rendered = self.project.data["fx"].get("render") is not None
        for i in range(len(self.profiles) - 1):
            a, b = self.pair(i)
            entry = self.project.fx_for_pair(a, b) or {}
            count = sum(1 for fx in entry.get("effects") or [] if fx.get("enabled", True))
            state = ("✓" if rendered else "*") if count else ""
            score = self.transitions[i].get("score", "") if i < len(self.transitions) else ""
            name = f"{self.profiles[i].get('filename', os.path.basename(a))} → {self.profiles[i + 1].get('filename', os.path.basename(b))}"
            self.trans_tree.insert("", tk.END, iid=f"T{i}", values=(i + 1, name, f"{float(score):.0f}" if score != "" else "",
                                                                   count or "", state))
        self._inactive = self.project.inactive_fx_pairs()
        self._refresh_orphans()
        if selected is not None and f"T{selected}" in self.trans_tree.get_children():
            self.trans_tree.selection_set(f"T{selected}")

    def on_transition_selected(self):
        sel = self.trans_tree.selection()
        if not sel:
            return
        index = int(sel[0][1:])
        if index == self.pair_index:
            return
        self.pair_index = index
        self.fx_index = None
        pa, pb = self.profiles[index], self.profiles[index + 1]
        t = self.transitions[index] if index < len(self.transitions) else {}
        bpm_a = float(pa.get("bpm") or 0)
        beat = f"{60.0 / bpm_a:.3f} s" if bpm_a else "-"
        self.info_label.config(text=tr(
            "Junction A {a} · B {b}\n{bpm_a} → {bpm_b} BPM · {key_a} → {key_b} · beat {beat} · score {score}",
            a=_fmt(pa.get("outro_start", 0)), b=_fmt(pb.get("intro_start", 0)), bpm_a=f"{bpm_a:.1f}",
            bpm_b=f"{float(pb.get('bpm') or 0):.1f}", key_a=pa.get("key") or "-", key_b=pb.get("key") or "-",
            beat=beat, score=f"{float(t.get('score', 0)):.0f}"))
        self.refresh_sources()
        self._setting_nudge = True
        self.nudge_var.set(str(int(round(float(self.entry().get("nudge_ms", 0))))))
        self._setting_nudge = False
        self.refresh_a_end()
        self.refresh_fx()
        self.show_settings()
        self.load_waveforms()
        self.schedule_preview()

    def refresh_sources(self):
        """Which file the preview and the render read for A and B: the pre-mastered copy or the original."""
        if self.pair_index is None or not self.winfo_exists():
            return
        bases = self.project.premaster_map()
        a, b = self.pair()
        kind = {True: tr("pre-mastered copy"), False: tr("original")}
        if self.project.options.get("use_premaster", True):
            text = tr("Plays from: A {a} · B {b}", a=kind[a in bases], b=kind[b in bases])
        else:
            text = tr("Plays from: A {a} · B {b} (pre-mastered copies not used)", a=kind[a in bases], b=kind[b in bases])
        self.source_label.config(text=text)

    def on_nudge(self):
        if getattr(self, "_setting_nudge", False) or self.pair_index is None:
            return
        try:
            value = max(-50.0, min(50.0, float(self.nudge_var.get())))
        except ValueError:
            return
        a, b = self.pair()
        self.project.set_fx_nudge(a, b, value)
        self._saved()

    # ------------------------------------------------------------------ where A ends
    def _a_grid(self):
        """A's beat grid for the selected transition (loaded with the waveforms, else through the cache)."""
        wave = self._waves.get(self._wave_key())
        if wave is not None:
            return wave["beats"][0]
        return transition_beats(self.profiles[self.pair_index], self.profiles[self.pair_index + 1])[0]

    def _a_end_beats(self):
        """(marker, what the plan alone gives) as whole beats after the junction, for the selected transition."""
        pa = self.profiles[self.pair_index]
        beats = self._a_grid()
        junction = tfx.nearest_beat_index(beats, float(pa.get("outro_start", 0.0)))
        base, period = tfx.beat_time(beats, junction, 0), tfx.median_period(beats) or 0.5
        planned = int(round((float(pa.get("outro_end", 0.0)) - base) / period))
        marker = self.entry().get("a_end_s")
        current = planned if marker is None else int(round((float(marker) - base) / period))
        return max(0, current), max(0, planned)

    def _a_end_seconds(self, beats):
        """The exact time in A of the beat `beats` after the junction (the grid, not a regular tempo)."""
        pa = self.profiles[self.pair_index]
        grid = self._a_grid()
        return tfx.beat_time(grid, tfx.nearest_beat_index(grid, float(pa.get("outro_start", 0.0))), beats)

    def refresh_a_end(self):
        """Put the marker of the selected transition in its field, with what the plan would give beside it."""
        if self.pair_index is None or not self.winfo_exists():
            return
        current, planned = self._a_end_beats()
        self._setting_a_end = True
        self.a_end_var.set(str(current))
        self._setting_a_end = False
        self.a_end_label.config(text=tr("(planned: {beats})", beats=planned))

    def on_a_end(self):
        if getattr(self, "_setting_a_end", False) or self.pair_index is None:
            return
        try:
            beats = int(round(float(self.a_end_var.get())))
        except ValueError:
            return
        beats = max(0, min(MAX_A_END_BEATS, beats))
        _, planned = self._a_end_beats()
        a, b = self.pair()
        # back on the planned beat: drop the marker instead, so the transition follows the plan again
        seconds = None if beats == planned else self._a_end_seconds(beats)
        if self.project.set_fx_a_end(a, b, seconds):
            self._a_end_saved()

    def reset_a_end(self):
        if self.pair_index is None:
            return
        a, b = self.pair()
        if self.project.set_fx_a_end(a, b, None):
            self._a_end_saved()
        self.refresh_a_end()

    def _a_end_saved(self):
        """A moved marker changes the blend lengths: the sheet and the set map must say so too."""
        self._saved()
        if hasattr(self.app, "_write_sheet_files"):
            self.app._write_sheet_files()
        if hasattr(self.app, "_render_overview"):
            self.app._render_overview()

    # ------------------------------------------------------------------ orphan FX
    def _refresh_orphans(self):
        count = len(self._inactive)
        if count:
            self.orphan_label.config(text=tr("⚠ {count} orphan FX (tracks no longer next to each other)", count=count))
            if not self.orphan_row.winfo_manager():
                self.orphan_row.pack(anchor="w", pady=(2, 4))
        elif self.orphan_row.winfo_manager():
            self.orphan_row.pack_forget()
        if self._orphan_window is not None and self._orphan_window.winfo_exists():
            self._fill_orphans()

    def remove_orphans(self, pairs):
        """Delete the FX settings of these orphan pairs; returns how many were removed."""
        pairs = [pair for pair in pairs if pair in self._inactive]
        for a, b in pairs:
            self.project.remove_fx(a, b)
        if pairs:
            log.info("Orphan FX removed: %s", ", ".join(f"{os.path.basename(a)} → {os.path.basename(b)}" for a, b in pairs))
            self._saved()
        return len(pairs)

    def open_orphans(self):
        """A window listing the orphan FX, to remove some or all of them."""
        if self._orphan_window is not None and self._orphan_window.winfo_exists():
            self._orphan_window.lift()
            return self._orphan_window
        win = tk.Toplevel(self)
        win.title(tr("Orphan FX - {project}", project=self.project.name))
        win.geometry("720x320")
        win.transient(self.winfo_toplevel())
        ttk.Label(win, text=tr("FX set on two tracks that no longer follow each other in the set list. They come back if the "
                               "two tracks are next to each other again; remove the ones you do not need."),
                  foreground=MUTED, wraplength=680, justify=tk.LEFT).pack(anchor="w", padx=10, pady=(10, 4))
        tree = ttk.Treeview(win, columns=("From", "To", "FX"), show="headings", selectmode="extended")
        headings = {"From": tr("From"), "To": tr("To"), "FX": tr("FX")}
        for col, width in (("From", 250), ("To", 250), ("FX", 180)):
            tree.heading(col, text=headings[col], command=lambda c=col: self._sort_orphans(c))
            tree.column(col, width=width, anchor="w")
        tree.pack(fill=tk.BOTH, expand=True, padx=10)
        buttons = ttk.Frame(win)
        buttons.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(buttons, text=tr("Remove selected"), command=lambda: self._confirm_remove_orphans(selected=True)).pack(side=tk.LEFT)
        ttk.Button(buttons, text=tr("Remove all"), command=lambda: self._confirm_remove_orphans(selected=False)).pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text=tr("Close"), command=win.destroy).pack(side=tk.RIGHT)
        self._orphan_window, self._orphan_tree, self._orphan_sort = win, tree, None
        self._fill_orphans()
        return win

    def _orphan_rows(self):
        rows = []
        for a, b in self._inactive:
            effects = (self.project.fx_for_pair(a, b) or {}).get("effects") or []
            types = " · ".join(fx.get("type", "?") for fx in effects)
            rows.append(((a, b), (os.path.basename(a), os.path.basename(b), f"{len(effects)} · {types}")))
        if self._orphan_sort is not None:
            rows.sort(key=lambda row: row[1][self._orphan_sort].lower())
        return rows

    def _fill_orphans(self):
        tree = self._orphan_tree
        tree.delete(*tree.get_children())
        self._orphan_pairs = {}
        for i, (pair, values) in enumerate(self._orphan_rows()):
            tree.insert("", tk.END, iid=f"O{i}", values=values)
            self._orphan_pairs[f"O{i}"] = pair

    def _sort_orphans(self, column):
        self._orphan_sort = ("From", "To", "FX").index(column)
        self._fill_orphans()

    def _confirm_remove_orphans(self, selected):
        pairs = ([self._orphan_pairs[iid] for iid in self._orphan_tree.selection()] if selected
                 else list(self._inactive))
        if not pairs:
            return 0
        answer = messagebox.askyesnocancel(
            tr("Remove orphan FX"), tr("Remove the FX of {count} pair(s)?\n\n"
                                       "Yes: save a snapshot of the project first (Snapshots... to restore it), then remove.\n"
                                       "No: remove without a snapshot.", count=len(pairs)), parent=self._orphan_window)
        if answer is None:
            return 0
        if answer and hasattr(self.app, "_do_save_snapshot"):
            self.app._do_save_snapshot("before removing orphan FX")
        return self.remove_orphans(pairs)

    # ------------------------------------------------------------------ FX stack
    def _store(self, effects, rebuild_settings=False):
        a, b = self.pair()
        self.project.set_fx_effects(a, b, effects)
        self._saved()
        self.refresh_fx()
        if rebuild_settings:
            self.show_settings()

    def _saved(self):
        self.project.save()
        self.refresh_transitions()
        if hasattr(self.app, "_refresh_workflow"):
            self.app._refresh_workflow()
        self.schedule_chart()
        self.schedule_preview()

    def refresh_fx(self):
        self.fx_tree.delete(*self.fx_tree.get_children())
        if self.pair_index is None:
            return
        for i, fx in enumerate(self.effects()):
            scope = tfx.effect_scope(fx)
            self.fx_tree.insert("", tk.END, iid=f"F{i}",
                                values=("✓" if fx.get("enabled", True) else "",
                                        tr(SCOPE_LABELS[scope]) if scope in SCOPE_LABELS else scope,
                                        effect_summary(fx)))
        if self.fx_index is not None and f"F{self.fx_index}" in self.fx_tree.get_children():
            self.fx_tree.selection_set(f"F{self.fx_index}")

    def on_fx_selected(self):
        sel = self.fx_tree.selection()
        index = int(sel[0][1:]) if sel else None
        if index != self.fx_index:
            self.fx_index = index
            self.show_settings()

    def add_effect(self, fx_type):
        if self.pair_index is None:
            messagebox.showinfo(tr("Transition FX"), tr("Select a transition first"), parent=self)
            return
        effects = self.effects()
        effects.append(tfx.new_effect(fx_type))
        self.fx_index = len(effects) - 1
        self._store(effects, rebuild_settings=True)

    def remove_effect(self):
        if self.fx_index is None:
            return
        effects = self.effects()
        effects.pop(self.fx_index)
        self.fx_index = None
        self._store(effects, rebuild_settings=True)

    def move_effect(self, delta):
        if self.fx_index is None:
            return
        effects = self.effects()
        j = max(0, min(len(effects) - 1, self.fx_index + delta))
        effects.insert(j, effects.pop(self.fx_index))
        self.fx_index = j
        self._store(effects)

    def duplicate_effect(self):
        if self.fx_index is None:
            return
        effects = self.effects()
        effects.insert(self.fx_index + 1, copy.deepcopy(effects[self.fx_index]))
        self.fx_index += 1
        self._store(effects, rebuild_settings=True)

    def toggle_effect(self):
        if self.fx_index is None:
            return
        effects = self.effects()
        effects[self.fx_index]["enabled"] = not effects[self.fx_index].get("enabled", True)
        self._store(effects)

    def update_effect(self, changes, rebuild_settings=False):
        effects = self.effects()
        if self.fx_index is None or self.fx_index >= len(effects):
            return
        effects[self.fx_index].update(changes)
        self._store(effects, rebuild_settings)
        if not rebuild_settings:
            self._refresh_sample_label()
            self._refresh_scratch_info()
            self._refresh_filter_response()

    # ------------------------------------------------------------------ settings panel
    def show_settings(self):
        for child in self.settings.winfo_children():
            child.destroy()
        self._settings_canvas.yview_moveto(0.0)
        if self.pair_index is None or self.fx_index is None:
            ttk.Label(self.settings, text=tr("Select a transition, then add or select an effect."), foreground=MUTED).pack(anchor="w")
            return
        fx = self.effects()[self.fx_index]
        ttk.Label(self.settings, text=tr(FX_NAMES[fx["type"]]), font="DynaMixTitle").pack(anchor="w")
        form = ttk.Frame(self.settings)
        form.pack(fill=tk.X, pady=4)
        self._form_vars = self._fields(form, FIELDS[fx["type"]], fx, lambda key, value: self.update_effect({key: value}))
        if fx["type"] == "freeze":
            self._freeze_extras(fx)
        if fx["type"] == "sample":
            self._sample_extras(fx)
        if fx["type"] == "scratch":
            self._scratch_extras(fx)
        if fx["type"] == "filter":
            self._filter_extras(fx)

    def _filter_extras(self, fx):
        box = ttk.LabelFrame(self.settings, text=tr("Filter response"))
        box.pack(fill=tk.X, pady=6)
        ttk.Label(box, text=tr("Side: outgoing filters the end of A up to the junction, incoming the start of B from the "
                               "junction, across one sweep over both tracks from Start (beats from the junction). "
                               "Return to dry: how long B (and A with across) takes to sound normal again after the "
                               "sweep; 'no return' keeps the filter on the rest of the track, as outgoing already does "
                               "on A. Below, what the filter lets through at the start and at the end of the sweep: bass "
                               "on the left, treble on the right; the resonance is the bump at the cutoff, the band width "
                               "(band-pass only) is the width of the bell."),
                  foreground=MUTED, wraplength=380, justify=tk.LEFT).pack(anchor="w", padx=4, pady=2)
        self._filter_figure = charts.filter_response(fx)
        self._filter_canvas = FigureCanvasTkAgg(self._filter_figure, box)
        self._filter_canvas.get_tk_widget().config(height=charts.pixel_height(self._filter_figure))
        self._filter_canvas.get_tk_widget().pack(fill=tk.X, padx=4, pady=(0, 4))
        self._filter_canvas.draw()

    def _refresh_filter_response(self):
        canvas = getattr(self, "_filter_canvas", None)
        if canvas is None or not canvas.get_tk_widget().winfo_exists() or self.fx_index is None:
            return
        effects = self.effects()
        if self.fx_index >= len(effects) or effects[self.fx_index].get("type") != "filter":
            return
        charts.filter_response(dict(tfx.new_effect("filter"), **effects[self.fx_index]), fig=self._filter_figure)
        canvas.draw_idle()

    def _scratch_extras(self, fx):
        box = ttk.LabelFrame(self.settings, text=tr("Sequence"))
        box.pack(fill=tk.X, pady=6)
        ttk.Label(box, text=tr("Commands of 5 characters, hexadecimal values as in a tracker: d (slow down) or u (speed up), "
                               "factor 1-F (0 keeps the speed), seconds 1-F, b, 0 forwards or 1 backwards. "
                               "Example: d81b0 u42b1 dF3b1. The rest of the effect catches up so that the track ends "
                               "where it would be."),
                  foreground=MUTED, wraplength=380, justify=tk.LEFT).pack(anchor="w", padx=4, pady=2)
        ttk.Label(box, text=tr("In the field, as in a tracker: ↑ / ↓ change the character under the cursor (d/u, factor, "
                               "seconds, direction) and typing replaces the characters (Insert switches to inserting). "
                               "Wrong commands are underlined in red. The curve follows what you type and shows the "
                               "command under the cursor; click the curve to reach a command in the field. "
                               "Apply (or Enter) applies the sequence, then the transition chart and the preview follow."),
                  foreground=MUTED, wraplength=380, justify=tk.LEFT).pack(anchor="w", padx=4, pady=2)
        ttk.Button(box, text=tr("✓ Apply the sequence"), command=lambda: self._apply_text("sequence")).pack(anchor="w", padx=4, pady=2)
        self.scratch_info = ttk.Label(box, text="", justify=tk.LEFT, wraplength=380)
        self.scratch_info.pack(anchor="w", padx=4, pady=(2, 4))
        self._scratch_figure = charts.scratch_head({"steps": [], "catch_up_speed": None, "warnings": []},
                                                   {"t": [], "speed": [], "offset": []}, 1.0)
        self._scratch_canvas = FigureCanvasTkAgg(self._scratch_figure, box)
        self._scratch_canvas.get_tk_widget().config(height=charts.pixel_height(self._scratch_figure))
        self._scratch_canvas.get_tk_widget().pack(fill=tk.X, padx=4, pady=(0, 4))
        self._scratch_canvas.mpl_connect("button_press_event", self._scratch_curve_clicked)
        self._scratch_job, self._scratch_steps = None, []
        self._scratch_editor(self._text_fields["sequence"][0])
        self._refresh_scratch_info()

    # ------------------------------------------------------------------ scratch sequence editor
    SCRATCH_TAGS = (("kind", charts.BLUE_DARK), ("factor", charts.BLUE), ("seconds", charts.VIOLET), ("letter_b", MUTED),
                    ("direction", charts.TEXT))

    def _scratch_editor(self, widget):
        """Tracker-like keys on the sequence field: arrows step a character, typing overwrites (Insert toggles)."""
        for tag, color in self.SCRATCH_TAGS:
            widget.tag_configure(tag, foreground=color)
        widget.tag_configure("bad", foreground=charts.STATUS_CRITICAL, underline=True)
        widget.tag_configure("current", background="#dce9f9")
        widget.tag_raise("bad")
        self._scratch_overwrite = True
        widget.bind("<Up>", lambda e: self._scratch_nudge(1))
        widget.bind("<Down>", lambda e: self._scratch_nudge(-1))
        widget.bind("<Insert>", lambda e: self._scratch_toggle_overwrite())
        widget.bind("<KeyPress>", self._scratch_key, add="+")
        widget.bind("<ButtonRelease-1>", lambda e: self._scratch_editor_changed(), add="+")

    def _scratch_field(self):
        widget, _ = getattr(self, "_text_fields", {}).get("sequence", (None, None))
        return widget if widget is not None and widget.winfo_exists() else None

    @staticmethod
    def _offset(widget, index="insert"):
        if not widget.compare(index, ">", "1.0"):
            return 0
        count = widget.count("1.0", index, "chars")  # a tuple, or an int on recent Pythons
        return int(count[0] if isinstance(count, tuple) else count or 0)

    def _scratch_nudge(self, delta):
        widget = self._scratch_field()
        if widget is None:
            return None
        offset = self._offset(widget)
        changed = tfx.scratch_nudge(widget.get("1.0", "end-1c"), offset, delta)
        if changed is None:
            return None  # not a steppable character: the arrow moves the cursor as usual
        widget.delete(f"1.0 + {offset} chars")
        widget.insert(f"1.0 + {offset} chars", changed[offset])
        widget.mark_set("insert", f"1.0 + {offset} chars")
        self._typing("sequence")
        return "break"

    def _scratch_toggle_overwrite(self):
        self._scratch_overwrite = not self._scratch_overwrite
        self.status(tr("Sequence field: typing replaces the characters") if self._scratch_overwrite
                    else tr("Sequence field: typing inserts characters"))
        return "break"

    def _scratch_key(self, event):
        """In overwrite mode a typed character replaces the one under the cursor (never a space or the end of a line)."""
        widget = event.widget
        if not self._scratch_overwrite or not event.char or not event.char.isprintable() or event.char.isspace():
            return None
        if event.state & 0x4 or widget.tag_ranges("sel"):  # Ctrl shortcuts and selections work as usual
            return None
        under = widget.get("insert")
        if under and not under.isspace():
            widget.delete("insert")
        return None

    def _scratch_editor_changed(self):
        """Colours of the typed commands, the command under the cursor and, a moment later, the curve."""
        widget = self._scratch_field()
        if widget is None:
            return
        for tag, _ in self.SCRATCH_TAGS:
            widget.tag_remove(tag, "1.0", tk.END)
        widget.tag_remove("bad", "1.0", tk.END)
        commands = tfx.scratch_commands(widget.get("1.0", "end-1c"))
        for command in commands:
            start = command["start"]
            if command["error"]:
                widget.tag_add("bad", f"1.0 + {start} chars", f"1.0 + {command['end']} chars")
                continue
            for n, (tag, _) in enumerate(self.SCRATCH_TAGS):
                widget.tag_add(tag, f"1.0 + {start + n} chars", f"1.0 + {start + n + 1} chars")
        self._scratch_commands = commands
        if self._scratch_job is not None:
            self.after_cancel(self._scratch_job)
        self._scratch_job = self.after(200, self._draw_scratch_curve)

    def _scratch_cursor_command(self):
        """Index of the command under (or just after) the cursor, among the typed commands."""
        widget = self._scratch_field()
        if widget is None:
            return None
        offset = self._offset(widget)
        for n, command in enumerate(getattr(self, "_scratch_commands", [])):
            if command["start"] <= offset <= command["end"]:
                return n
        return None

    def _draw_scratch_curve(self):
        """The speed and read-position curve of the typed sequence (the applied one while the typed one is unreadable)."""
        self._scratch_job = None
        widget, canvas = self._scratch_field(), getattr(self, "_scratch_canvas", None)
        if widget is None or canvas is None or not canvas.get_tk_widget().winfo_exists():
            return
        context = self._scratch_context()
        if context is None:
            return
        fx, length = context
        typed = widget.get("1.0", "end-1c")
        highlight = self._scratch_cursor_command()
        try:
            plan = tfx.scratch_plan(typed, length, 200, fx.get("ramp", "exponential"))
        except ValueError:
            highlight = None
            try:
                plan = tfx.scratch_plan(fx["sequence"], length, 200, fx.get("ramp", "exponential"))
            except ValueError:
                plan = None
        widget.tag_remove("current", "1.0", tk.END)
        if plan is None:
            self._scratch_steps = []
            return
        if highlight is not None and highlight < len(self._scratch_commands):
            command = self._scratch_commands[highlight]
            widget.tag_add("current", f"1.0 + {command['start']} chars", f"1.0 + {command['end']} chars")
        self._scratch_steps = plan["steps"]
        charts.scratch_head(plan, tfx.scratch_head(plan, 200), length, highlight=highlight, fig=self._scratch_figure)
        canvas.draw_idle()

    def _scratch_curve_clicked(self, event):
        """A click on the curve puts the cursor on the command played at that moment."""
        widget = self._scratch_field()
        if widget is None or event.xdata is None:
            return
        for n, step in enumerate(self._scratch_steps):
            if step["start"] <= event.xdata < step["end"] and n < len(getattr(self, "_scratch_commands", [])):
                widget.mark_set("insert", f"1.0 + {self._scratch_commands[n]['start']} chars")
                widget.see("insert")
                widget.focus_set()
                self._scratch_editor_changed()
                return

    def _scratch_context(self):
        """(the selected scratch effect with its defaults, its length in seconds), or None."""
        if self.fx_index is None or self.pair_index is None:
            return None
        effects = self.effects()
        if self.fx_index >= len(effects) or effects[self.fx_index].get("type") != "scratch":
            return None
        fx = dict(tfx.new_effect("scratch"), **effects[self.fx_index])
        profile = self.profiles[self.pair_index if fx.get("side") == "outgoing" else self.pair_index + 1]
        period = 60.0 / float(profile.get("bpm") or tfx.DEFAULT_BPM)
        return fx, int(fx["length_beats"]) * period

    def _text_field(self, parent, key, var):
        """
        A multi-line text field applied only on request (the Apply button or Enter): typing stores nothing and redraws
        nothing (the field keeps the focus); the StringVar holds the applied text, and setting it updates the field.
        """
        widget = tk.Text(parent, height=3, width=34, wrap="word", font="DynaMixMono", undo=True)
        widget.insert("1.0", var.get())
        if not hasattr(self, "_text_fields"):
            self._text_fields = {}
        self._text_fields[key] = (widget, var)
        widget.bind("<Return>", lambda e, k=key: (self._apply_text(k), "break")[1])
        widget.bind("<KeyRelease>", lambda e, k=key: self._typing(k))

        def show_applied(*_):
            if widget.winfo_exists() and widget.get("1.0", "end-1c") != var.get():
                widget.delete("1.0", tk.END)
                widget.insert("1.0", var.get())
        var.trace_add("write", show_applied)
        return widget

    def _apply_text(self, key):
        """Apply what is typed in a text field (the StringVar trace stores the effect); an unreadable sequence is refused."""
        widget, var = getattr(self, "_text_fields", {}).get(key, (None, None))
        if widget is None or not widget.winfo_exists():
            return False
        text = " ".join(widget.get("1.0", "end-1c").split())
        if key == "sequence":
            try:
                tfx.parse_scratch(text)
            except ValueError as exc:
                self._refresh_scratch_info(sequence=text)
                self.status(tr("The sequence is not applied: {error}", error=tr_text(str(exc))))
                return False
        if text != var.get():
            var.set(text)
        if key == "sequence":
            self._refresh_scratch_info()
            self.status(tr("Sequence applied"))
        return True

    def _typing(self, key):
        widget, _ = getattr(self, "_text_fields", {}).get(key, (None, None))
        if key == "sequence" and widget is not None and widget.winfo_exists():
            self._refresh_scratch_info(sequence=widget.get("1.0", "end-1c"))

    def _refresh_scratch_info(self, sequence=None):
        """What the sequence does over the effect (the one being typed when given): length, catch-up, warnings."""
        label = getattr(self, "scratch_info", None)
        context = self._scratch_context()
        if label is None or not label.winfo_exists() or context is None:
            return
        fx, length = context
        self._scratch_editor_changed()
        try:
            plan = tfx.scratch_plan(fx["sequence"] if sequence is None else sequence, length, 200, fx.get("ramp", "exponential"))
        except ValueError as exc:
            label.config(text=tr("Sequence error: {error}", error=tr_text(str(exc))), foreground=charts.STATUS_CRITICAL)
            return
        lines = [tr("{steps} step(s): {seconds:.2f} s of the {length:.2f} s effect ({beats} beats)", steps=len(plan["steps"]),
                    seconds=plan["sequence_end"], length=length, beats=fx["length_beats"])]
        if plan["catch_up_speed"] is None:
            lines.append(tr("no time left to catch up"))
        else:
            lines.append(tr("catch-up ×{speed:.2f} during {seconds:.2f} s, then the track is back in place",
                            speed=plan["catch_up_speed"], seconds=length - plan["sequence_end"]))
        lines.extend("⚠ " + tr_text(w) for w in plan["warnings"])
        if sequence is not None and " ".join(sequence.split()) != fx["sequence"]:
            lines.append(tr("not applied yet: click Apply (or press Enter)"))
        label.config(text="\n".join(lines), foreground=charts.STATUS_CRITICAL if plan["warnings"] else "")

    def _fields(self, parent, fields, values, on_change):
        """Build one row per field; returns {key: StringVar} so a field can be updated without a rebuild."""
        variables = {}
        for row, (key, label, kind, spec) in enumerate(fields):
            ttk.Label(parent, text=tr(label)).grid(row=row, column=0, sticky="w", pady=2)
            value = values.get(key)
            if kind == "choice":
                var = tk.StringVar(value=choice_label(key, value))
                widget = ttk.Combobox(parent, textvariable=var, values=[choice_label(key, c) for c in spec],
                                      width=24, state="readonly")
            elif kind == "text":
                var = tk.StringVar(value="" if value is None else str(value))
                widget = self._text_field(parent, key, var)
            else:
                var = tk.StringVar(value="" if value is None else
                                   (f"{value:g}" if isinstance(value, float) else str(value)))
                lo, hi = spec
                step = 1 if kind == "int" else (0.05 if hi <= 1 else (0.1 if hi <= 20 else (1 if hi <= 300 else 10)))
                widget = ttk.Spinbox(parent, from_=lo, to=hi, increment=step, textvariable=var, width=10)
            widget.grid(row=row, column=1, sticky="we" if kind == "text" else "w", padx=6)
            var.trace_add("write", lambda *a, k=key, v=var, kd=kind, s=spec: self._field_changed(k, v, kd, s, on_change))
            variables[key] = var
        parent.columnconfigure(1, weight=1)
        return variables

    @staticmethod
    def _field_changed(key, var, kind, spec, on_change):
        text = var.get()
        if kind == "text":
            value = text  # stored as typed: an unreadable sequence is reported, never lost
        elif kind == "choice":
            value = next((c for c in spec if choice_label(key, c) == text), None)
            if value is None:
                return
        else:
            try:
                value = float(text)
            except ValueError:
                return
            lo, hi = spec
            if not lo <= value <= hi:
                return
            if kind == "int":
                value = int(round(value))
        on_change(key, value)

    def freeze_steps(self):
        """The steps saved on the selected freeze (read at click time, never from the built panel)."""
        return [dict(s) for s in self.effects()[self.fx_index].get("steps") or []]

    def add_freeze_step(self):
        self.update_effect({"steps": self.freeze_steps() + [{"beats": 1, "repeats": 2}]}, rebuild_settings=True)

    def remove_freeze_step(self, index):
        steps = self.freeze_steps()
        if len(steps) > 1 and 0 <= index < len(steps):
            steps.pop(index)
            self.update_effect({"steps": steps}, rebuild_settings=True)

    def _freeze_extras(self, fx):
        steps_box = ttk.LabelFrame(self.settings, text=tr("Steps (a roll shortens the loop)"))
        steps_box.pack(fill=tk.X, pady=4)
        steps = [dict(s) for s in fx.get("steps") or []]

        def set_steps(new_steps, rebuild=True):
            self.update_effect({"steps": new_steps}, rebuild_settings=rebuild)

        for i, step in enumerate(steps):
            row = ttk.Frame(steps_box)
            row.pack(anchor="w", padx=4, pady=1)
            ttk.Label(row, text=f"{i + 1}.").pack(side=tk.LEFT)
            beats_var = tk.StringVar(value=f"{float(step['beats']):g}")
            ttk.Combobox(row, textvariable=beats_var, values=("4", "2", "1", "0.5"), width=4, state="readonly").pack(side=tk.LEFT, padx=2)
            ttk.Label(row, text=tr("beats ×")).pack(side=tk.LEFT)
            rep_var = tk.StringVar(value=str(int(step["repeats"])))
            ttk.Spinbox(row, from_=1, to=32, increment=1, textvariable=rep_var, width=4).pack(side=tk.LEFT, padx=2)

            def changed(*a, i=i, bv=beats_var, rv=rep_var):
                try:
                    beats, repeats = float(bv.get()), int(float(rv.get()))
                except ValueError:
                    return
                if repeats < 1:
                    return
                new = [dict(s) for s in self.effects()[self.fx_index].get("steps") or []]
                new[i] = {"beats": int(beats) if beats >= 1 else beats, "repeats": repeats}
                set_steps(new, rebuild=False)
            beats_var.trace_add("write", changed)
            rep_var.trace_add("write", changed)
            ttk.Button(row, text="−", width=2,
                       command=lambda i=i: self.remove_freeze_step(i)).pack(side=tk.LEFT, padx=4)
        ttk.Button(steps_box, text=tr("+ step"), command=self.add_freeze_step).pack(anchor="w", padx=4, pady=2)

        for key, label, fields, defaults in (
                ("loop_filter", "Loop filter", LOOP_FILTER_FIELDS,
                 {k: v for k, v in tfx.new_effect("filter").items() if k not in ("type", "enabled") + LOOP_FILTER_KEYS_OFF}),
                ("loop_echo", "Loop echo", LOOP_ECHO_FIELDS,
                 {k: v for k, v in tfx.new_effect("echo").items() if k not in ("type", "enabled", "start_offset_beats")})):
            box = ttk.LabelFrame(self.settings, text=tr(label))
            box.pack(fill=tk.X, pady=4)
            on = tk.BooleanVar(value=bool(fx.get(key)))
            ttk.Checkbutton(box, text=tr("On"), variable=on,
                            command=lambda k=key, v=on, d=defaults: self.update_effect({k: dict(d) if v.get() else None},
                                                                                        rebuild_settings=True)).pack(anchor="w", padx=4)
            if fx.get(key):
                inner = ttk.Frame(box)
                inner.pack(fill=tk.X, padx=4)
                self._fields(inner, fields, fx[key],
                             lambda k2, value, k=key: self.update_effect({k: dict(self.effects()[self.fx_index][k], **{k2: value})}))

    def _sample_extras(self, fx):
        box = ttk.LabelFrame(self.settings, text=tr("Sample"))
        box.pack(fill=tk.BOTH, expand=True, pady=4)
        folder = self.app.config.get("fx_samples_folder") or ""
        if not folder:
            ttk.Label(box, text=tr("Set the FX samples folder in the Configuration tab."), foreground=MUTED).pack(anchor="w", padx=4)
            return
        top = ttk.Frame(box)
        top.pack(fill=tk.X, padx=4)
        ttk.Label(top, text=tr("Filter:")).pack(side=tk.LEFT)
        filter_var = tk.StringVar()
        ttk.Entry(top, textvariable=filter_var, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text=tr("▶ Sample"), command=self.audition_sample).pack(side=tk.LEFT, padx=4)
        ttk.Label(box, text=tr("Click a sample to use it, double-click to hear it."), foreground=MUTED).pack(anchor="w", padx=4)
        self.sample_current_label = ttk.Label(box, text="", wraplength=420, justify=tk.LEFT)
        self.sample_current_label.pack(anchor="w", padx=4)
        self._refresh_sample_label()
        self.sample_list = tk.Listbox(box, height=8, exportselection=False)
        self.sample_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self._shown_samples = []

        def fill(*a):
            self.sample_list.delete(0, tk.END)
            self._shown_samples = library.filter_entries(self.samples, filter_var.get())
            for entry in self._shown_samples:
                too_long = (entry.get("duration") or 0) > tfx.MAX_SAMPLE_SECONDS
                self.sample_list.insert(tk.END, f"{entry['filename']}  ({(entry.get('duration') or 0):.1f} s)"
                                        + ("  - " + tr("too long") if too_long else ""))
                if too_long:
                    self.sample_list.itemconfig(tk.END, foreground="#9a9a9a")
        filter_var.trace_add("write", fill)
        fill()

        self.sample_list.bind("<<ListboxSelect>>", lambda e: self.pick_sample())
        self.sample_list.bind("<Return>", lambda e: self.pick_sample())
        self.sample_list.bind("<Double-1>", lambda e: self.audition_sample())

    def pick_sample(self):
        """Use the sample selected in the list for the current sample effect (the list is kept as it is)."""
        sel = self.sample_list.curselection()
        if not sel or self.fx_index is None:
            return
        entry = self._shown_samples[sel[0]]
        if (entry.get("duration") or 0) > tfx.MAX_SAMPLE_SECONDS:
            self.status(tr("{name} is longer than {seconds} s", name=entry["filename"],
                           seconds=f"{tfx.MAX_SAMPLE_SECONDS:.0f}"))
            return
        if self.effects()[self.fx_index].get("file") != entry["file_path"]:
            bpm = tfx.bpm_from_name(entry["file_path"])
            self.update_effect({"file": entry["file_path"], "sample_bpm": bpm})
            var = (getattr(self, "_form_vars", None) or {}).get("sample_bpm")
            if var is not None:
                var.set("" if bpm is None else f"{bpm:g}")
        self._refresh_sample_label()
        self.status(tr("Sample: {name}", name=entry["filename"]))

    def _tempo_note(self, fx):
        """How the sample will be fitted to the outgoing track's tempo (for the 'Current' line)."""
        if self.pair_index is None or fx.get("tempo", "varispeed") == "off":
            return ""
        track_bpm = float(self.profiles[self.pair_index].get("bpm") or 0)
        if not track_bpm:
            return ""
        ratio, sample_bpm, problem = tfx.sample_tempo(fx, track_bpm)
        if problem:
            return f" · {tr_text(problem)}"
        if sample_bpm is None:
            return " · " + tr("no BPM in the name: played as it is (set Sample BPM)")
        detail = fx.get("tempo", "varispeed")
        if detail == "varispeed":
            detail += f", {12 * math.log2(ratio):+.1f} st"
        return f" · {sample_bpm:g} → {track_bpm:.0f} BPM ({detail})"

    def _refresh_sample_label(self):
        label = getattr(self, "sample_current_label", None)
        if label is None or not label.winfo_exists() or self.fx_index is None or self.pair_index is None:
            return
        effects = self.effects()
        if self.fx_index >= len(effects) or effects[self.fx_index].get("type") != "sample":
            return
        fx = effects[self.fx_index]
        label.config(text=tr("Current: {name}{note}", name=os.path.basename(fx.get("file") or "") or "-",
                             note=self._tempo_note(fx)))

    @staticmethod
    def _sample_missing(entry):
        """True when an enabled sample effect of the transition has no file yet."""
        return any(fx.get("type") == "sample" and fx.get("enabled", True) and not fx.get("file")
                   for fx in (entry or {}).get("effects") or [])

    def scan_samples(self):
        folder = (self.app.config.get("fx_samples_folder") or "").strip()
        if not folder:
            return

        def work():
            try:
                entries = library.scan(folder, use_cache=False)
            except Exception as e:
                self.app._report_error(tr("FX samples scan failed: {error}", error=e), e)
                return

            def done():
                if not self.winfo_exists():
                    return
                self.samples = entries
                if self.fx_index is not None and self.effects()[self.fx_index]["type"] == "sample":
                    self.show_settings()
            self.app.root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def audition_sample(self):
        sel = self.sample_list.curselection() if hasattr(self, "sample_list") else ()
        path = self._shown_samples[sel[0]]["file_path"] if sel else (self.effects()[self.fx_index].get("file") if self.fx_index is not None else "")
        if not path:
            return
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
            out = os.path.join(self._tmp_dir(), "sample_preview.wav")
            self.stop_preview()
            sf.write(out, data, sr, subtype="PCM_16")
            self.player.play_once(out)
        except Exception as e:
            self.app._report_error(tr("Cannot play {file}: {error}", file=os.path.basename(path), error=e), e)

    # ------------------------------------------------------------------ preview
    @staticmethod
    def _tmp_dir():
        folder = os.path.join(dynamix_home(), "tmp")
        os.makedirs(folder, exist_ok=True)
        return folder

    def start_preview(self):
        if self.pair_index is None:
            messagebox.showinfo(tr("Transition FX"), tr("Select a transition first"), parent=self)
            return
        if self._plan_changed():
            self.status(tr(PLAN_CHANGED))
            return
        self._previewing = True
        self.render_preview()

    def schedule_preview(self):
        if not self._previewing:
            return
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(400, self.render_preview)

    def render_preview(self):
        self._preview_job = None
        if self.pair_index is None:
            return
        if self._plan_changed():
            self.status(tr(PLAN_CHANGED))
            return
        if self._sample_missing(self.entry()):
            self.status(tr(NO_SAMPLE_FILE))
            return
        problems = [p for fx in self.entry().get("effects") or [] if fx.get("enabled", True) for p in tfx.validate_effect(fx)]
        if problems:  # e.g. a scratch sequence being typed: say it, no error dialog at every key
            self.status(tr("Cannot preview yet: {problem}", problem=tr_text(problems[0])))
            return
        self._preview_seq += 1
        seq = self._preview_seq
        index = self.pair_index
        entry = copy.deepcopy(self.entry())
        bases = self.project.premaster_map()
        length = self.length_var.get()
        result_key = self._result_key(index, entry, length)
        pa, pb = self.profiles[index], self.profiles[index + 1]
        path = os.path.join(self._tmp_dir(), f"preview_{'a' if seq % 2 else 'b'}.wav")
        self.status(tr("Rendering the preview ..."))

        def work():
            try:
                clip, sr, warnings = render_preview(pa, pb, entry, bases, length)
                if seq != self._preview_seq:
                    return
                sf.write(path, clip, sr, subtype="PCM_16")
                preview_start = transition_layout_for(pa, pb, entry, length)["preview_start"]
                result_env = tfx.peak_envelope(clip, sr, t0=preview_start)
            except Exception as e:
                self.app._report_error(tr("Preview failed: {error}", error=e), e)
                self.app.root.after(0, self.status, tr("Preview failed (see the Log)"))
                return

            def done():
                if seq != self._preview_seq or not self.winfo_exists():
                    return
                self._result_env = {"key": result_key, "env": result_env}
                self.schedule_chart()
                if not self._previewing:
                    return
                try:
                    looping = self.player.play_loop(path)
                except Exception as e:
                    self.app._report_error(tr("Cannot play the preview: {error}", error=e), e)
                    self.status(tr("Preview playback failed (see the Log)"))
                    return
                if looping:
                    self._start_playhead(clip, sr, preview_start)
                for w in warnings:
                    if w not in self._logged_warnings:
                        self._logged_warnings.add(w)
                        log.warning("Preview: %s", w)
                self.status((tr("Looping the preview") if looping else tr("Preview opened in the default player"))
                            + (f" - {tr_text(warnings[0])}" if warnings else ""))
            self.app.root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def stop_preview(self):
        self._previewing = False
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
            self._preview_job = None
        self._preview_seq += 1
        self.player.stop()
        self._stop_playhead()
        self.status(tr("Stopped"))

    # ------------------------------------------------------------------ playhead
    def _start_playhead(self, clip, sr, preview_start, offset=0.0):
        self._play = {"clip": clip, "sr": int(sr), "length": len(clip) / float(sr), "preview_start": float(preview_start),
                      "started": time.monotonic() - offset}
        if self._playhead_job is None:
            self._tick_playhead()

    def _stop_playhead(self):
        self._play = None
        if self._playhead_job is not None:
            self.after_cancel(self._playhead_job)
            self._playhead_job = None
        if self._playhead_item is not None and self._playhead_widget is not None and self._playhead_widget.winfo_exists():
            self._playhead_widget.delete(self._playhead_item)
        self._playhead_item = None
        self._setting_position = True
        self.position_var.set(0.0)
        self._setting_position = False
        self.position_label.config(text=tr("(start the preview)"))

    def playhead_position(self):
        """Seconds into the looping preview clip, or None when nothing loops."""
        play = self._play
        return loop_position(play["started"], time.monotonic(), play["length"]) if play else None

    def _tick_playhead(self):
        self._playhead_job = None
        play = self._play
        if play is None or not self.winfo_exists():
            return
        position = self.playhead_position()
        if not self._dragging_position:
            self._setting_position = True
            self.position_var.set(position / play["length"] if play["length"] else 0.0)
            self._setting_position = False
        t = play["preview_start"] + position
        layout = self.last_layout
        if layout and layout.get("period"):
            text = tr("{position} / {length} · J{offset} beats", position=_fmt(position), length=_fmt(play["length"]),
                      offset=f"{(t - layout['junction']) / layout['period']:+.0f}")
        else:
            text = f"{_fmt(position)} / {_fmt(play['length'])}"
        self.position_label.config(text=text)
        self._draw_playhead(t)
        self._playhead_job = self.after(50, self._tick_playhead)

    def _chart_geometry(self):
        """(figure, widget, pixel ratio) of the chart on screen, or None."""
        canvas = self._chart_canvas
        if canvas is None or not canvas.figure.axes:
            return None
        widget = canvas.get_tk_widget()
        return canvas.figure, widget, float(getattr(canvas, "device_pixel_ratio", 1.0) or 1.0)

    def _draw_playhead(self, t):
        geometry = self._chart_geometry()
        if geometry is None:
            return
        fig, widget, ratio = geometry
        axes = fig.axes
        x0, x1 = axes[0].get_xlim()
        height = fig.bbox.height
        if not x0 <= t <= x1:
            x = -10.0
        else:
            x = axes[-1].transData.transform((t, 0))[0] / ratio
        top = (height - axes[0].bbox.y1) / ratio
        bottom = (height - axes[-1].bbox.y0) / ratio
        if widget is not self._playhead_widget or self._playhead_item is None:
            self._playhead_widget = widget
            self._playhead_item = widget.create_line(x, top, x, bottom, fill=charts.STATUS_CRITICAL, width=2)
        else:
            widget.coords(self._playhead_item, x, top, x, bottom)
            widget.tag_raise(self._playhead_item)

    def seek(self, offset):
        """Play the looping preview from `offset` seconds (the loop goes on from there)."""
        play = self._play
        if play is None or not self._previewing:
            return False
        offset = min(max(0.0, float(offset)), max(0.0, play["length"] - 0.05))
        self._seek_count += 1
        path = os.path.join(self._tmp_dir(), f"preview_seek_{'a' if self._seek_count % 2 else 'b'}.wav")
        try:
            sf.write(path, rotate_clip(play["clip"], play["sr"], offset), play["sr"], subtype="PCM_16")
            self.player.play_loop(path)
        except Exception as e:
            self.app._report_error(tr("Cannot play the preview from {time}: {error}", time=_fmt(offset), error=e), e)
            return False
        play["started"] = time.monotonic() - offset
        return True

    def _position_released(self):
        self._dragging_position = False
        play = self._play
        if play is not None:
            self.seek(float(self.position_var.get()) * play["length"])

    def _on_chart_click(self, event):
        play, geometry = self._play, self._chart_geometry()
        if play is None or geometry is None:
            return
        fig, _, ratio = geometry
        ax = fig.axes[-1]
        t = ax.transData.inverted().transform((event.x * ratio, 0))[0]
        offset = t - play["preview_start"]
        if 0.0 <= offset <= play["length"]:
            self.seek(offset)

    def close(self):
        self.stop_preview()
        if self._chart_job is not None:
            self.after_cancel(self._chart_job)
            self._chart_job = None
        self.destroy()

    # ------------------------------------------------------------------ transition chart
    def _wave_key(self, index=None):
        a, b = self.pair(index)
        bases = self.project.premaster_map()
        return bases.get(a, a), bases.get(b, b)

    @staticmethod
    def _result_key(index, entry, length):
        return index, json.dumps(entry, sort_keys=True, default=str), length

    def _sample_seconds(self, path):
        if path not in self._sample_lengths:
            try:
                self._sample_lengths[path] = float(sf.info(path).duration)
            except Exception:
                self._sample_lengths[path] = None
        return self._sample_lengths[path]

    def load_waveforms(self):
        """Read A and B around the junction in the background (peak envelopes, kept per transition)."""
        index = self.pair_index
        key = self._wave_key(index)
        if key in self._waves or key in self._waves_loading:
            self.schedule_chart()
            return
        self._waves_loading.add(key)
        pa, pb = self.profiles[index], self.profiles[index + 1]
        self._chart_message(tr("Loading the waveforms ..."))

        def work():
            try:
                beats = transition_beats(pa, pb)
                envs = []
                for path, lo, hi in ((key[0], float(pa.get("outro_start", 0)) - 90.0, float(pa.get("outro_end", 0)) + 40.0),
                                     (key[1], float(pb.get("intro_start", 0)) - 10.0, float(pb.get("intro_start", 0)) + 110.0)):
                    audio, sr = load_audio(path)
                    i0, i1 = int(max(0.0, lo) * sr), min(len(audio), int(hi * sr))
                    envs.append(tfx.peak_envelope(tfx.to_stereo(audio[i0:i1]), sr, t0=i0 / sr))
            except Exception as e:
                log.warning("Transition chart: cannot read the audio: %s", e)
                reason = str(e)  # `e` is deleted at the end of the except block, before failed() runs

                def failed():
                    self._waves_loading.discard(key)
                    if self.winfo_exists() and self.pair_index == index:
                        self._chart_message(tr("Cannot read the audio of this transition: {reason}", reason=reason))
                self.app.root.after(0, failed)
                return

            def done():
                self._waves_loading.discard(key)
                self._waves[key] = {"a_env": envs[0], "b_env": envs[1], "beats": beats}
                if self.winfo_exists():
                    self.schedule_chart()
            self.app.root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def schedule_chart(self):
        if not self.winfo_exists():
            return
        if self._chart_job is not None:
            self.after_cancel(self._chart_job)
        self._chart_job = self.after(150, self.draw_chart)

    def draw_chart(self):
        self._chart_job = None
        if not self.winfo_exists() or self.pair_index is None:
            return
        waves = self._waves.get(self._wave_key())
        if waves is None:
            if self._wave_key() not in self._waves_loading:
                self.load_waveforms()
            return
        entry = self.entry()
        length = self.length_var.get()
        result = self._result_env
        result = result["env"] if result and result["key"] == self._result_key(self.pair_index, entry, length) else None
        try:
            layout = transition_layout_for(self.profiles[self.pair_index], self.profiles[self.pair_index + 1], entry, length,
                                           beats=waves["beats"], sample_seconds=self._sample_seconds)
            fig = charts.transition_detail(layout, waves["a_env"], waves["b_env"], result)
        except Exception as e:
            log.warning("Transition chart: %s", e)
            self._chart_message(tr("Cannot draw this transition: {error}", error=e))
            return
        self.last_layout = layout
        for child in self.chart_frame.winfo_children():
            child.destroy()
        canvas = FigureCanvasTkAgg(fig, self.chart_frame)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        canvas.get_tk_widget().bind("<Button-1>", self._on_chart_click)  # click: play the preview from there
        canvas.draw()
        self._chart_canvas = canvas
        self._playhead_item = None  # drawn again on the new chart at the next tick

    def _chart_message(self, text):
        for child in self.chart_frame.winfo_children():
            child.destroy()
        self._chart_canvas = None
        ttk.Label(self.chart_frame, text=text, foreground=MUTED, wraplength=900).pack(padx=20, pady=20, anchor="w")

    # ------------------------------------------------------------------ render
    def apply_all(self):
        if self._applying:
            return
        if self._plan_changed():
            self.status(tr(PLAN_CHANGED))
            return
        pairs = self.project.active_fx_pairs()
        if not pairs:
            messagebox.showinfo(tr("Transition FX"), tr("No active FX on the transitions of the set list"), parent=self)
            return
        if any(self._sample_missing(self.project.fx_for_pair(a, b)) for a, b in pairs):
            self.status(tr(NO_SAMPLE_FILE))
            messagebox.showinfo(tr("Transition FX"), tr(NO_SAMPLE_FILE), parent=self)
            return
        self.stop_preview()
        self._applying = True
        self.apply_button.state(["disabled"])
        app, project = self.app, self.project
        profiles = list(self.profiles)
        lookup = {project.fx_key(a, b): copy.deepcopy(project.fx_for_pair(a, b)) for a, b in pairs}
        bases = project.premaster_map()
        plan = self._plan_signature()
        fmt = app.config.get("output_format", "same")
        out_dir = project.fx_dir
        self.status(tr("Rendering FX for {count} transitions ...", count=len(pairs)))

        def work(task):
            try:
                results, problems = render_set(
                    profiles, lambda a, b: lookup.get(project.fx_key(a, b)), bases, out_dir, fmt,
                    progress=lambda i, n, name: task.progress(i, n, name))
            except Exception as e:
                app._task_failed(task, tr("FX render failed: {error}", error=e), e)
                app.root.after(0, self._apply_finished, tr("FX render failed (see the Log)"))
                return
            task.check()  # stopped: the project keeps its previous FX render

            def done():
                self._apply_finished(None)
                current = {project.fx_key(a, b): copy.deepcopy(project.fx_for_pair(a, b)) for a, b in project.active_fx_pairs()}
                if current != lookup or project.premaster_map() != bases or self._plan_signature() != plan:
                    log.warning("FX render discarded: the FX settings, the pre-master, the transitions or the set list "
                                "changed during the render; click 'Apply all FX' again")
                    if self.winfo_exists():
                        self.status(tr("Settings changed during the render: click 'Apply all FX' again"))
                    return
                project.set_fx_render(results)
                project.invalidate_from("fx")  # the playlist and the Mixxx export must use the new copies
                project.mark("fx", count=len(results))
                for problem in problems:
                    log.warning("FX: %s", problem)
                message = f"FX rendered: {len(results)} copies in {out_dir}" + (
                    f" ({len(problems)} problems, see the Log)" if problems else "")
                log.info(message)
                if problems:
                    shown = tr("FX rendered: {count} copies in {folder} ({problems} problems, see the Log)",
                               count=len(results), folder=out_dir, problems=len(problems))
                else:
                    shown = tr("FX rendered: {count} copies in {folder}", count=len(results), folder=out_dir)
                if app.project is not project:
                    project.save()
                    return
                app._save_project()
                app._render_overview()
                app.update_status(shown)
                if self.winfo_exists():
                    self.refresh_transitions()
                    self.status(shown)
            app.root.after(0, done)
        app._start_task(tr("Apply all FX"), work,
                        on_stopped=lambda: self._apply_finished(tr("FX render stopped: the project keeps its previous FX copies")))

    def _apply_finished(self, message):
        self._applying = False
        if self.winfo_exists():
            self.apply_button.state(["!disabled"])
            if message:
                self.status(message)
