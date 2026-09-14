#!/usr/bin/env python3
"""
"Transition FX" window of the Set Builder: per transition, a stack of effects
(freeze / roll, filter sweep, echo, FX sample) with their settings, a looped
preview while tweaking, and "Apply all FX" which renders the copies into fx/.
"""

import copy
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import soundfile as sf

import library
import transition_fx as tfx
from analysis_store import dynamix_home
from fx_render import render_preview, render_set

log = logging.getLogger("dynamix.fx")
MUTED = "#52514e"

FX_NAMES = {"freeze": "Freeze", "filter": "Filter", "echo": "Echo", "sample": "Sample"}

# (key, label, kind, choices or (min, max))
FIELDS = {
    "freeze": [("capture_offset_beats", "Capture point (beats)", "int", (-16, 0)),
               ("fade_db", "Fade to (dB)", "float", (-60, 0)),
               ("tail_beats", "Tail (beats)", "int", (0, 8)),
               ("gain_db", "Gain (dB)", "float", (-24, 6))],
    "filter": [("side", "Side", "choice", ("outgoing", "incoming")),
               ("kind", "Type", "choice", ("highpass", "lowpass", "bandpass")),
               ("start_hz", "From (Hz)", "float", (20, 20000)),
               ("end_hz", "To (Hz)", "float", (20, 20000)),
               ("width_octaves", "Band width (octaves)", "float", (0.3, 4)),
               ("resonance", "Resonance (Q)", "float", (0.7, 12)),
               ("beats", "Length (beats)", "choice", (2, 4, 8, 16)),
               ("curve", "Curve", "choice", ("exponential", "linear"))],
    "echo": [("start_offset_beats", "Start (beats)", "int", (-16, 0)),
             ("delay_beats", "Delay (beats)", "choice", (0.25, 0.5, 0.75, 1)),
             ("feedback", "Feedback", "float", (0, 0.85)),
             ("mix", "Mix", "float", (0, 1)),
             ("damping_hz", "Damping (Hz)", "float", (1000, 20000))],
    "sample": [("anchor", "Anchor", "choice", ("end_at_junction", "start_at_junction", "center_on_junction")),
               ("offset_beats", "Offset (beats)", "float", (-16, 16)),
               ("gain_db", "Gain (dB)", "float", (-24, 6)),
               ("fade_in_ms", "Fade in (ms)", "int", (0, 2000)),
               ("fade_out_ms", "Fade out (ms)", "int", (0, 2000))],
}
LOOP_FILTER_FIELDS = [f for f in FIELDS["filter"] if f[0] not in ("side", "beats")]
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
        extra = (" +filter" if fx.get("loop_filter") else "") + (" +echo" if fx.get("loop_echo") else "")
        return f"Freeze {steps}{extra}"
    if t == "filter":
        return (f"Filter {fx.get('side')} {fx.get('kind')} {float(fx.get('start_hz', 0)):.0f}→"
                f"{float(fx.get('end_hz', 0)):.0f} Hz, {fx.get('beats')} beats")
    if t == "echo":
        return f"Echo {float(fx.get('delay_beats', 0)):g} beat, feedback {float(fx.get('feedback', 0)):.2f}"
    if t == "sample":
        name = os.path.basename(fx.get("file") or "") or "(choose a sample)"
        return f"Sample {name} ({fx.get('anchor')})"
    return str(t)


def _fmt(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


class TransitionFxWindow(tk.Toplevel):
    """Needs `app` with: root, project, config, update_status, _report_error, _save_project, _render_overview."""

    def __init__(self, app, player=None):
        super().__init__(app.root)
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
        self.title(f"Transition FX - {self.project.name}")
        self.geometry("1250x700")
        self._build()
        self.refresh_transitions()
        self.scan_samples()
        self.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------------ layout
    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=6)
        ttk.Button(bar, text="▶ Preview (loop)", command=self.start_preview).pack(side=tk.LEFT)
        ttk.Button(bar, text="■ Stop", command=self.stop_preview).pack(side=tk.LEFT, padx=4)
        ttk.Label(bar, text="Length:").pack(side=tk.LEFT, padx=(12, 2))
        self.length_var = tk.StringVar(value="short")
        length = ttk.Combobox(bar, textvariable=self.length_var, values=("short", "long"), width=7, state="readonly")
        length.pack(side=tk.LEFT)
        length.bind("<<ComboboxSelected>>", lambda e: self.schedule_preview())
        self.apply_button = ttk.Button(bar, text="Apply all FX", command=self.apply_all)
        self.apply_button.pack(side=tk.LEFT, padx=12)
        self.status_label = ttk.Label(bar, text="", foreground=MUTED)
        self.status_label.pack(side=tk.LEFT, padx=8)

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        left = ttk.Frame(panes)
        panes.add(left, weight=1)
        ttk.Label(left, text="Transitions", foreground=MUTED).pack(anchor="w")
        self.trans_tree = ttk.Treeview(left, columns=("#", "Transition", "Score", "FX", "State"), show="headings",
                                       height=12, selectmode="browse")
        for col, width in (("#", 30), ("Transition", 260), ("Score", 50), ("FX", 35), ("State", 45)):
            self.trans_tree.heading(col, text=col)
            self.trans_tree.column(col, width=width, anchor="w" if col == "Transition" else "center",
                                   stretch=(col == "Transition"))
        self.trans_tree.pack(fill=tk.BOTH, expand=True)
        self.trans_tree.bind("<<TreeviewSelect>>", lambda e: self.on_transition_selected())
        self.info_label = ttk.Label(left, text="", foreground=MUTED, justify=tk.LEFT, wraplength=380)
        self.info_label.pack(anchor="w", pady=4)
        nudge_row = ttk.Frame(left)
        nudge_row.pack(anchor="w")
        ttk.Label(nudge_row, text="Nudge (ms):").pack(side=tk.LEFT)
        self.nudge_var = tk.StringVar(value="0")
        ttk.Spinbox(nudge_row, from_=-50, to=50, increment=1, textvariable=self.nudge_var, width=6).pack(side=tk.LEFT, padx=4)
        self.nudge_var.trace_add("write", lambda *a: self.on_nudge())
        inactive = ttk.LabelFrame(left, text="Inactive FX (pairs no longer next to each other)")
        inactive.pack(fill=tk.X, pady=6)
        self.inactive_list = tk.Listbox(inactive, height=3)
        self.inactive_list.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(inactive, text="Remove", command=self.remove_inactive).pack(anchor="w", padx=4, pady=2)

        mid = ttk.Frame(panes)
        panes.add(mid, weight=1)
        ttk.Label(mid, text="FX stack (top to bottom)", foreground=MUTED).pack(anchor="w")
        self.fx_tree = ttk.Treeview(mid, columns=("On", "Effect"), show="headings", height=12, selectmode="browse")
        self.fx_tree.heading("On", text="On")
        self.fx_tree.heading("Effect", text="Effect")
        self.fx_tree.column("On", width=35, anchor="center", stretch=False)
        self.fx_tree.column("Effect", width=300, anchor="w")
        self.fx_tree.pack(fill=tk.BOTH, expand=True)
        self.fx_tree.bind("<<TreeviewSelect>>", lambda e: self.on_fx_selected())
        buttons = ttk.Frame(mid)
        buttons.pack(fill=tk.X, pady=4)
        add = ttk.Menubutton(buttons, text="Add ▾")
        menu = tk.Menu(add, tearoff=False)
        for fx_type in tfx.FX_TYPES:
            menu.add_command(label=FX_NAMES[fx_type], command=lambda t=fx_type: self.add_effect(t))
        add["menu"] = menu
        add.pack(side=tk.LEFT)
        for text, command in (("Remove", self.remove_effect), ("▲", lambda: self.move_effect(-1)),
                              ("▼", lambda: self.move_effect(1)), ("Duplicate", self.duplicate_effect),
                              ("On/Off", self.toggle_effect)):
            ttk.Button(buttons, text=text, command=command).pack(side=tk.LEFT, padx=2)

        right = ttk.LabelFrame(panes, text="Settings")
        panes.add(right, weight=2)
        self.settings = ttk.Frame(right)
        self.settings.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def status(self, text):
        if self.winfo_exists():
            self.status_label.config(text=text)

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
        self.inactive_list.delete(0, tk.END)
        self._inactive = self.project.inactive_fx_pairs()
        for a, b in self._inactive:
            self.inactive_list.insert(tk.END, f"{os.path.basename(a)} → {os.path.basename(b)}")
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
        self.info_label.config(text=(
            f"Junction A {_fmt(pa.get('outro_start', 0))} · B {_fmt(pb.get('intro_start', 0))}\n"
            f"{bpm_a:.1f} → {float(pb.get('bpm') or 0):.1f} BPM · {pa.get('key') or '-'} → {pb.get('key') or '-'} · "
            f"beat {beat} · score {float(t.get('score', 0)):.0f}"))
        self._setting_nudge = True
        self.nudge_var.set(str(int(round(float(self.entry().get("nudge_ms", 0))))))
        self._setting_nudge = False
        self.refresh_fx()
        self.show_settings()
        self.schedule_preview()

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

    def remove_inactive(self):
        sel = self.inactive_list.curselection()
        if not sel:
            return
        a, b = self._inactive[sel[0]]
        self.project.remove_fx(a, b)
        self._saved()

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
        self.schedule_preview()

    def refresh_fx(self):
        self.fx_tree.delete(*self.fx_tree.get_children())
        if self.pair_index is None:
            return
        for i, fx in enumerate(self.effects()):
            self.fx_tree.insert("", tk.END, iid=f"F{i}", values=("✓" if fx.get("enabled", True) else "", effect_summary(fx)))
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
            messagebox.showinfo("Transition FX", "Select a transition first", parent=self)
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

    # ------------------------------------------------------------------ settings panel
    def show_settings(self):
        for child in self.settings.winfo_children():
            child.destroy()
        if self.pair_index is None or self.fx_index is None:
            ttk.Label(self.settings, text="Select a transition, then add or select an effect.", foreground=MUTED).pack(anchor="w")
            return
        fx = self.effects()[self.fx_index]
        ttk.Label(self.settings, text=FX_NAMES[fx["type"]], font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        form = ttk.Frame(self.settings)
        form.pack(fill=tk.X, pady=4)
        self._fields(form, FIELDS[fx["type"]], fx, lambda key, value: self.update_effect({key: value}))
        if fx["type"] == "freeze":
            self._freeze_extras(fx)
        if fx["type"] == "sample":
            self._sample_extras(fx)

    def _fields(self, parent, fields, values, on_change):
        for row, (key, label, kind, spec) in enumerate(fields):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(values.get(key)))
            if kind == "choice":
                widget = ttk.Combobox(parent, textvariable=var, values=[str(c) for c in spec], width=18, state="readonly")
            else:
                lo, hi = spec
                step = 1 if kind == "int" else (0.05 if hi <= 1 else (0.1 if hi <= 20 else 10))
                widget = ttk.Spinbox(parent, from_=lo, to=hi, increment=step, textvariable=var, width=10)
            widget.grid(row=row, column=1, sticky="w", padx=6)
            var.trace_add("write", lambda *a, k=key, v=var, kd=kind, s=spec: self._field_changed(k, v, kd, s, on_change))

    @staticmethod
    def _field_changed(key, var, kind, spec, on_change):
        text = var.get()
        if kind == "choice":
            value = next((c for c in spec if str(c) == text), None)
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
        steps_box = ttk.LabelFrame(self.settings, text="Steps (a roll shortens the loop)")
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
            ttk.Label(row, text="beats ×").pack(side=tk.LEFT)
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
        ttk.Button(steps_box, text="+ step", command=self.add_freeze_step).pack(anchor="w", padx=4, pady=2)

        for key, label, fields, defaults in (
                ("loop_filter", "Loop filter", LOOP_FILTER_FIELDS,
                 {k: v for k, v in tfx.new_effect("filter").items() if k not in ("type", "enabled", "side", "beats")}),
                ("loop_echo", "Loop echo", LOOP_ECHO_FIELDS,
                 {k: v for k, v in tfx.new_effect("echo").items() if k not in ("type", "enabled", "start_offset_beats")})):
            box = ttk.LabelFrame(self.settings, text=label)
            box.pack(fill=tk.X, pady=4)
            on = tk.BooleanVar(value=bool(fx.get(key)))
            ttk.Checkbutton(box, text="On", variable=on,
                            command=lambda k=key, v=on, d=defaults: self.update_effect({k: dict(d) if v.get() else None},
                                                                                        rebuild_settings=True)).pack(anchor="w", padx=4)
            if fx.get(key):
                inner = ttk.Frame(box)
                inner.pack(fill=tk.X, padx=4)
                self._fields(inner, fields, fx[key],
                             lambda k2, value, k=key: self.update_effect({k: dict(self.effects()[self.fx_index][k], **{k2: value})}))

    def _sample_extras(self, fx):
        box = ttk.LabelFrame(self.settings, text="Sample")
        box.pack(fill=tk.BOTH, expand=True, pady=4)
        folder = self.app.config.get("fx_samples_folder") or ""
        if not folder:
            ttk.Label(box, text="Set the FX samples folder in the Configuration tab.", foreground=MUTED).pack(anchor="w", padx=4)
            return
        top = ttk.Frame(box)
        top.pack(fill=tk.X, padx=4)
        ttk.Label(top, text="Filter:").pack(side=tk.LEFT)
        filter_var = tk.StringVar()
        ttk.Entry(top, textvariable=filter_var, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="▶ Sample", command=self.audition_sample).pack(side=tk.LEFT, padx=4)
        ttk.Label(box, text=f"Current: {os.path.basename(fx.get('file') or '') or '-'}", foreground=MUTED).pack(anchor="w", padx=4)
        self.sample_list = tk.Listbox(box, height=8)
        self.sample_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self._shown_samples = []

        def fill(*a):
            self.sample_list.delete(0, tk.END)
            self._shown_samples = library.filter_entries(self.samples, filter_var.get())
            for entry in self._shown_samples:
                too_long = (entry.get("duration") or 0) > tfx.MAX_SAMPLE_SECONDS
                self.sample_list.insert(tk.END, f"{entry['filename']}  ({(entry.get('duration') or 0):.1f} s)"
                                        + ("  - too long" if too_long else ""))
                if too_long:
                    self.sample_list.itemconfig(tk.END, foreground="#9a9a9a")
        filter_var.trace_add("write", fill)
        fill()

        self.sample_list.bind("<Double-1>", lambda e: self.pick_sample())
        self.sample_list.bind("<Return>", lambda e: self.pick_sample())

    def pick_sample(self):
        """Use the sample selected in the list for the current sample effect."""
        sel = self.sample_list.curselection()
        if not sel:
            return
        entry = self._shown_samples[sel[0]]
        if (entry.get("duration") or 0) > tfx.MAX_SAMPLE_SECONDS:
            self.status(f"{entry['filename']} is longer than {tfx.MAX_SAMPLE_SECONDS:.0f} s")
            return
        self.update_effect({"file": entry["file_path"]}, rebuild_settings=True)

    def scan_samples(self):
        folder = (self.app.config.get("fx_samples_folder") or "").strip()
        if not folder:
            return

        def work():
            try:
                entries = library.scan(folder, use_cache=False)
            except Exception as e:
                self.app._report_error(f"FX samples scan failed: {e}", e)
                return

            def done():
                if not self.winfo_exists():
                    return
                self.samples = entries
                if self.fx_index is not None and self.effects()[self.fx_index]["type"] == "sample":
                    self.show_settings()
            self.after(0, done)
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
            self.app._report_error(f"Cannot play {os.path.basename(path)}: {e}", e)

    # ------------------------------------------------------------------ preview
    @staticmethod
    def _tmp_dir():
        folder = os.path.join(dynamix_home(), "tmp")
        os.makedirs(folder, exist_ok=True)
        return folder

    def start_preview(self):
        if self.pair_index is None:
            messagebox.showinfo("Transition FX", "Select a transition first", parent=self)
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
        self._preview_seq += 1
        seq = self._preview_seq
        index = self.pair_index
        entry = copy.deepcopy(self.entry())
        bases = self.project.premaster_map()
        length = self.length_var.get()
        path = os.path.join(self._tmp_dir(), f"preview_{'a' if seq % 2 else 'b'}.wav")
        self.status("Rendering the preview ...")

        def work():
            try:
                clip, sr, warnings = render_preview(self.profiles[index], self.profiles[index + 1], entry, bases, length)
                if seq != self._preview_seq:
                    return
                sf.write(path, clip, sr, subtype="PCM_16")
            except Exception as e:
                self.app._report_error(f"Preview failed: {e}", e)
                self.after(0, self.status, "Preview failed (see the Log)")
                return

            def done():
                if seq != self._preview_seq or not self._previewing or not self.winfo_exists():
                    return
                try:
                    looping = self.player.play_loop(path)
                except Exception as e:
                    self.app._report_error(f"Cannot play the preview: {e}", e)
                    self.status("Preview playback failed (see the Log)")
                    return
                for w in warnings:
                    log.warning("Preview: %s", w)
                self.status(("Looping the preview" if looping else "Preview opened in the default player")
                            + (f" - {warnings[0]}" if warnings else ""))
            self.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def stop_preview(self):
        self._previewing = False
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
            self._preview_job = None
        self._preview_seq += 1
        self.player.stop()
        self.status("Stopped")

    def close(self):
        self.stop_preview()
        self.destroy()

    # ------------------------------------------------------------------ render
    def apply_all(self):
        if self._applying:
            return
        pairs = self.project.active_fx_pairs()
        if not pairs:
            messagebox.showinfo("Transition FX", "No active FX on the transitions of the set list", parent=self)
            return
        self.stop_preview()
        self._applying = True
        self.apply_button.state(["disabled"])
        app, project = self.app, self.project
        profiles = list(self.profiles)
        lookup = {project.fx_key(a, b): copy.deepcopy(project.fx_for_pair(a, b)) for a, b in pairs}
        bases = project.premaster_map()
        fmt = app.config.get("output_format", "same")
        out_dir = project.fx_dir
        self.status(f"Rendering FX for {len(pairs)} transitions ...")

        def work():
            try:
                results, problems = render_set(
                    profiles, lambda a, b: lookup.get(project.fx_key(a, b)), bases, out_dir, fmt,
                    progress=lambda i, n, name: app.root.after(0, app.update_status, f"Rendering FX {i}/{n}: {name}"))
            except Exception as e:
                app._report_error(f"FX render failed: {e}", e)
                app.root.after(0, self._apply_finished, "FX render failed (see the Log)")
                return

            def done():
                self._apply_finished(None)
                current = {project.fx_key(a, b): copy.deepcopy(project.fx_for_pair(a, b)) for a, b in project.active_fx_pairs()}
                if current != lookup or project.premaster_map() != bases:
                    log.warning("FX render discarded: the FX settings or the pre-master changed during the render; "
                                "click 'Apply all FX' again")
                    if self.winfo_exists():
                        self.status("Settings changed during the render: click 'Apply all FX' again")
                    return
                project.set_fx_render(results)
                project.mark("fx", count=len(results))
                for problem in problems:
                    log.warning("FX: %s", problem)
                message = f"FX rendered: {len(results)} copies in {out_dir}" + (
                    f" ({len(problems)} problems, see the Log)" if problems else "")
                log.info(message)
                if app.project is not project:
                    project.save()
                    return
                app._save_project()
                app._render_overview()
                app.update_status(message)
                if self.winfo_exists():
                    self.refresh_transitions()
                    self.status(message)
            app.root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def _apply_finished(self, message):
        self._applying = False
        if self.winfo_exists():
            self.apply_button.state(["!disabled"])
            if message:
                self.status(message)
