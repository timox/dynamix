#!/usr/bin/env python3
"""
Set project: the persistent record of one set being built from a music folder.

Saved as `.dynamix-set.json` inside the folder, it keeps the options, the
analysed tracks, the proposed order, what has been done on it (and when), the
transition plan and the pre-master results. The GUI and the command-line tools
read and update it, so you always know where you are and never redo a step.
"""

import datetime as _dt
import json
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

STEPS: List[Tuple[str, str, bool]] = [
    # key, label, required
    ("analyze", "Analyze the tracks", True),
    ("setlist", "Create the set list", True),
    ("transitions", "Plan the transitions", True),
    ("premaster", "Pre-master the set (optional)", False),
    ("playlist", "Write the playlist file (M3U)", False),
    ("mixxx", "Export intro/outro cues to Mixxx", True),
]

HINTS: Dict[str, str] = {
    "analyze": "Click 'Analyze' to measure BPM, key and energy of every track (cached, only new files take time).",
    "setlist": "Choose the duration and energy curve, then 'Create Set List'.",
    "transitions": "Click 'Plan Transitions' to compute intro/outro sections and the transition sheet.",
    "premaster": "Optional: 'Pre-master Set' writes level-matched, phase-repaired copies into the 'premaster' subfolder; later steps then use those copies.",
    "playlist": "Optional: 'Create Playlist' writes the set order as an M3U file.",
    "mixxx": "Close Mixxx, then 'Export to Mixxx' from the transition window. Then load the playlist in Auto DJ.",
    "done": "All steps done. In Mixxx: add the playlist to Auto DJ, mode 'Full Intro + Outro'.",
}


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _json_default(obj):
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


class SetProject:
    FILENAME = ".dynamix-set.json"

    def __init__(self, folder: str, autoload: bool = True):
        self.folder = os.path.abspath(folder)
        self.path = os.path.join(self.folder, self.FILENAME)
        self.data: Dict = {
            "version": 1,
            "folder": self.folder,
            "created": _now(),
            "updated": _now(),
            "options": {
                "set_duration": 60,
                "energy_curve": "build",
                "mix_bars": 8,
                "target_lufs": -14.0,
                "tone_match": True,
                "fix_phase": True,
            },
            "tracks": [],          # analysed track records (one per file)
            "set_list": [],        # ordered file paths of the proposal
            "steps": {key: {"done": False, "at": None, "details": {}} for key, _, _ in STEPS},
            "transitions": None,   # TransitionPlanner.to_dict()
            "premaster": None,     # {'out_dir', 'results': [...]} summary
            "notes": "",
        }
        if autoload and os.path.exists(self.path):
            self.load()

    # ------------------------------------------------------------- persistence
    @classmethod
    def exists(cls, folder: str) -> bool:
        return os.path.exists(os.path.join(os.path.abspath(folder), cls.FILENAME))

    def load(self) -> "SetProject":
        with open(self.path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        # keep defaults for keys added by newer versions
        for key, value in loaded.items():
            if key == "steps":
                for step_key, state in value.items():
                    self.data["steps"].setdefault(step_key, {"done": False, "at": None, "details": {}})
                    self.data["steps"][step_key].update(state)
            elif key == "options":
                self.data["options"].update(value)
            else:
                self.data[key] = value
        self.data["folder"] = self.folder
        return self

    def save(self) -> str:
        self.data["updated"] = _now()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, default=_json_default)
        os.replace(tmp, self.path)
        return self.path

    # ------------------------------------------------------------- content
    @property
    def options(self) -> Dict:
        return self.data["options"]

    @property
    def tracks(self) -> List[Dict]:
        return self.data["tracks"]

    def set_tracks(self, tracks: List[Dict]) -> None:
        self.data["tracks"] = [dict(t) for t in tracks]
        # drop set-list entries whose file disappeared from the analysis
        known = {t["file_path"] for t in self.data["tracks"]}
        self.data["set_list"] = [p for p in self.data["set_list"] if p in known]

    def set_set_list(self, tracks: List[Dict]) -> None:
        self.data["set_list"] = [t["file_path"] for t in tracks]

    def set_list_tracks(self) -> List[Dict]:
        """The proposal as full track records, in order."""
        by_path = {t["file_path"]: t for t in self.data["tracks"]}
        return [by_path[p] for p in self.data["set_list"] if p in by_path]

    def track(self, file_path: str) -> Optional[Dict]:
        for t in self.data["tracks"]:
            if t["file_path"] == file_path:
                return t
        return None

    def premaster_map(self) -> Dict[str, str]:
        """original file path -> pre-mastered copy, for copies that exist on disk."""
        pm = self.data.get("premaster") or {}
        mapping = {}
        for r in pm.get("results") or []:
            if "error" in r or not r.get("output"):
                continue
            if os.path.exists(r["output"]):
                mapping[r["input"]] = r["output"]
        return mapping

    # ------------------------------------------------------------- steps
    def mark(self, step: str, done: bool = True, **details) -> None:
        state = self.data["steps"].setdefault(step, {"done": False, "at": None, "details": {}})
        state["done"] = done
        state["at"] = _now() if done else None
        state["details"] = {k: v for k, v in details.items()} if done else {}

    def invalidate_from(self, step: str) -> None:
        """A step was redone: everything after it is no longer valid."""
        keys = [k for k, _, _ in STEPS]
        if step not in keys:
            return
        for later in keys[keys.index(step) + 1:]:
            self.mark(later, done=False)
        if step in ("analyze", "setlist"):
            self.data["transitions"] = None
        if step in ("analyze", "setlist", "transitions"):
            self.data["premaster"] = None

    def step_state(self, step: str) -> Dict:
        return self.data["steps"].get(step, {"done": False, "at": None, "details": {}})

    def is_done(self, step: str) -> bool:
        return bool(self.step_state(step).get("done"))

    def next_step(self) -> Tuple[str, str]:
        """(key, hint) of the first required step not done; ('done', hint) when complete."""
        for key, _, required in STEPS:
            if required and not self.is_done(key):
                return key, HINTS[key]
        return "done", HINTS["done"]

    def summary_lines(self) -> List[str]:
        lines = [f"Set project: {self.folder}", f"Updated: {self.data['updated']}",
                 f"Tracks analysed: {len(self.tracks)} | in set list: {len(self.data['set_list'])}"]
        for key, label, required in STEPS:
            state = self.step_state(key)
            mark = "[x]" if state["done"] else ("[ ]" if required else "[ ] (optional)")
            when = f" - {state['at']}" if state.get("at") else ""
            details = state.get("details") or {}
            extra = ", ".join(f"{k}={v}" for k, v in details.items() if k in ("count", "out_dir", "playlist", "db", "file"))
            lines.append(f"  {mark} {label}{when}{(' | ' + extra) if extra else ''}")
        key, hint = self.next_step()
        lines.append(f"Next: {hint}")
        return lines
