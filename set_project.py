#!/usr/bin/env python3
"""
Set project: one folder per set, with the audio brought into it.

    <projects root>/<name>/
        project.json     options, tracks, set list, step states, results
        source/          the audio files imported for this set (copies)
        premaster/       corrected copies written by the pre-master pass
        exports/         M3U playlists, transition sheets, JSON, charts

The music folder you started from is never written to. The GUI and the
command-line tools read and update project.json, so you always know where
you are and never redo a step.
"""

import datetime as _dt
import json
import os
import shutil
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.aiff', '.aif'}

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
    "analyze": "Click 'Analyze' to measure BPM, key and energy of every imported track (cached: only new files take time).",
    "setlist": "Click 'Propose' for an automatic order, then adjust it with Add / Remove / Up / Down in the Tracks tab.",
    "transitions": "Click 'Plan Transitions' to compute intro/outro sections and the transition sheet.",
    "premaster": "Optional: 'Pre-master Set' writes level-matched, phase-repaired copies into the project's premaster folder; later steps then use those copies.",
    "playlist": "Optional: 'Create Playlist' writes the set order as an M3U file into the project's exports folder.",
    "mixxx": "Close Mixxx, then 'Export to Mixxx'. Then load the playlist in Auto DJ.",
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


def safe_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_.()" else "_" for c in name.strip())
    return keep.strip(" .") or "set"


def list_projects(root: str) -> List[str]:
    """Project folders (containing project.json) under the projects root, newest first."""
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(root):
        return []
    found = []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if os.path.isfile(os.path.join(path, SetProject.FILENAME)):
            found.append(path)
    found.sort(key=lambda p: os.path.getmtime(os.path.join(p, SetProject.FILENAME)), reverse=True)
    return found


def audio_files_in(folder: str, recursive: bool = True) -> List[str]:
    files = []
    if recursive:
        for root, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for name in names:
                if os.path.splitext(name)[1].lower() in AUDIO_EXTENSIONS:
                    files.append(os.path.join(root, name))
    else:
        for name in os.listdir(folder):
            if os.path.splitext(name)[1].lower() in AUDIO_EXTENSIONS:
                files.append(os.path.join(folder, name))
    return sorted(files, key=lambda p: os.path.basename(p).lower())


class SetProject:
    FILENAME = "project.json"
    SOURCE_DIR = "source"
    PREMASTER_DIR = "premaster"
    EXPORTS_DIR = "exports"

    def __init__(self, folder: str, autoload: bool = True):
        self.folder = os.path.abspath(folder)
        self.path = os.path.join(self.folder, self.FILENAME)
        self.data: Dict = {
            "version": 2,
            "name": os.path.basename(self.folder),
            "created": _now(),
            "updated": _now(),
            "source_folder": "",   # where the audio came from (informative)
            "imported": [],        # [{original, path, size}]
            "options": {
                "set_duration": 60,
                "energy_curve": "build",
                "mix_bars": 8,
                "target_lufs": -14.0,
                "tone_match": True,
                "fix_phase": True,
                "mono_bass_hz": 120.0,
            },
            "tracks": [],          # analysed track records (one per source file)
            "set_list": [],        # ordered file paths of the proposal / edited set
            "steps": {key: {"done": False, "at": None, "details": {}} for key, _, _ in STEPS},
            "transitions": None,
            "premaster": None,
            "notes": "",
        }
        if autoload and os.path.exists(self.path):
            self.load()

    # ------------------------------------------------------------- creation / discovery
    @classmethod
    def create(cls, root: str, name: str, source_folder: str = "", options: Optional[Dict] = None) -> "SetProject":
        folder = os.path.join(os.path.abspath(os.path.expanduser(root)), safe_name(name))
        if os.path.exists(os.path.join(folder, cls.FILENAME)):
            raise FileExistsError(f"A project already exists at {folder}")
        project = cls(folder, autoload=False)
        project.data["name"] = name.strip() or os.path.basename(folder)
        project.data["source_folder"] = os.path.abspath(source_folder) if source_folder else ""
        if options:
            project.data["options"].update(options)
        for sub in (cls.SOURCE_DIR, cls.PREMASTER_DIR, cls.EXPORTS_DIR):
            os.makedirs(os.path.join(folder, sub), exist_ok=True)
        project.save()
        return project

    @classmethod
    def open(cls, path: str) -> "SetProject":
        """Open a project by its folder or its project.json path."""
        folder = os.path.dirname(path) if os.path.isfile(path) else path
        if not os.path.isfile(os.path.join(folder, cls.FILENAME)):
            raise FileNotFoundError(f"No {cls.FILENAME} in {folder}")
        return cls(folder)

    @classmethod
    def exists(cls, folder: str) -> bool:
        return os.path.exists(os.path.join(os.path.abspath(folder), cls.FILENAME))

    @property
    def name(self) -> str:
        return self.data.get("name") or os.path.basename(self.folder)

    @property
    def source_dir(self) -> str:
        return os.path.join(self.folder, self.SOURCE_DIR)

    @property
    def premaster_dir(self) -> str:
        return os.path.join(self.folder, self.PREMASTER_DIR)

    @property
    def exports_dir(self) -> str:
        return os.path.join(self.folder, self.EXPORTS_DIR)

    def ensure_dirs(self) -> None:
        for d in (self.source_dir, self.premaster_dir, self.exports_dir):
            os.makedirs(d, exist_ok=True)

    # ------------------------------------------------------------- persistence
    def load(self) -> "SetProject":
        with open(self.path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        for key, value in loaded.items():
            if key == "steps":
                for step_key, state in value.items():
                    self.data["steps"].setdefault(step_key, {"done": False, "at": None, "details": {}})
                    self.data["steps"][step_key].update(state)
            elif key == "options":
                self.data["options"].update(value)
            else:
                self.data[key] = value
        return self

    def save(self) -> str:
        self.data["updated"] = _now()
        os.makedirs(self.folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, default=_json_default)
        os.replace(tmp, self.path)
        return self.path

    # ------------------------------------------------------------- audio import
    def import_audio(self, files: List[str], progress: Optional[Callable[[int, int, str, str], None]] = None) -> Dict[str, int]:
        """
        Copy audio files into source/ (skipping identical existing copies).
        Returns counts {'copied', 'skipped', 'failed'}.
        """
        self.ensure_dirs()
        counts = {"copied": 0, "skipped": 0, "failed": 0}
        known = {entry["original"]: entry for entry in self.data["imported"]}
        for i, src in enumerate(files):
            src = os.path.abspath(src)
            name = os.path.basename(src)
            dest = os.path.join(self.source_dir, name)
            status = "copied"
            try:
                size = os.path.getsize(src)
                # same name from another folder: keep both by suffixing
                if os.path.exists(dest) and known.get(src, {}).get("path") != dest:
                    base, ext = os.path.splitext(name)
                    n = 2
                    while os.path.exists(os.path.join(self.source_dir, f"{base} ({n}){ext}")):
                        n += 1
                    if src not in known:
                        dest = os.path.join(self.source_dir, f"{base} ({n}){ext}")
                if os.path.exists(dest) and os.path.getsize(dest) == size:
                    status = "skipped"
                else:
                    shutil.copy2(src, dest)
                if src not in known:
                    entry = {"original": src, "path": dest, "size": size}
                    self.data["imported"].append(entry)
                    known[src] = entry
            except OSError as exc:
                status = "failed"
                print(f"Import failed for {src}: {exc}")
            counts[status] += 1
            if progress:
                progress(i + 1, len(files), name, status)
        self.save()
        return counts

    def import_folder(self, folder: str, recursive: bool = True, progress=None) -> Dict[str, int]:
        if not self.data.get("source_folder"):
            self.data["source_folder"] = os.path.abspath(folder)
        return self.import_audio(audio_files_in(folder, recursive), progress)

    def source_files(self) -> List[str]:
        """Audio files currently in source/ (what gets analysed)."""
        if not os.path.isdir(self.source_dir):
            return []
        return audio_files_in(self.source_dir, recursive=False)

    # ------------------------------------------------------------- content
    @property
    def options(self) -> Dict:
        return self.data["options"]

    @property
    def tracks(self) -> List[Dict]:
        return self.data["tracks"]

    def set_tracks(self, tracks: List[Dict]) -> None:
        self.data["tracks"] = [dict(t) for t in tracks]
        known = {t["file_path"] for t in self.data["tracks"]}
        self.data["set_list"] = [p for p in self.data["set_list"] if p in known]

    def track(self, file_path: str) -> Optional[Dict]:
        for t in self.data["tracks"]:
            if t["file_path"] == file_path:
                return t
        return None

    # ------------------------------------------------------------- set list (editable)
    @property
    def set_list(self) -> List[str]:
        return self.data["set_list"]

    def set_set_list(self, tracks: List[Dict]) -> None:
        self.data["set_list"] = [t["file_path"] for t in tracks]

    def set_order(self, file_paths: List[str]) -> None:
        known = {t["file_path"] for t in self.data["tracks"]}
        self.data["set_list"] = [p for p in file_paths if p in known]
        self.invalidate_from("setlist")

    def add_to_set(self, file_path: str, position: Optional[int] = None) -> None:
        if file_path in self.data["set_list"] or self.track(file_path) is None:
            return
        if position is None or position >= len(self.data["set_list"]):
            self.data["set_list"].append(file_path)
        else:
            self.data["set_list"].insert(max(0, position), file_path)
        self.invalidate_from("setlist")

    def remove_from_set(self, file_path: str) -> None:
        if file_path in self.data["set_list"]:
            self.data["set_list"].remove(file_path)
            self.invalidate_from("setlist")

    def move_in_set(self, file_path: str, delta: int) -> int:
        """Move a track up (delta < 0) or down (delta > 0). Returns its new index."""
        lst = self.data["set_list"]
        if file_path not in lst:
            return -1
        i = lst.index(file_path)
        j = max(0, min(len(lst) - 1, i + delta))
        if i != j:
            lst.insert(j, lst.pop(i))
            self.invalidate_from("setlist")
        return j

    def set_list_tracks(self) -> List[Dict]:
        by_path = {t["file_path"]: t for t in self.data["tracks"]}
        return [by_path[p] for p in self.data["set_list"] if p in by_path]

    def library_tracks(self) -> List[Dict]:
        """All analysed tracks, with an 'in_set' flag and 'set_position' (1-based or None)."""
        order = {p: i + 1 for i, p in enumerate(self.data["set_list"])}
        out = []
        for t in self.data["tracks"]:
            row = dict(t)
            row["set_position"] = order.get(t["file_path"])
            row["in_set"] = row["set_position"] is not None
            out.append(row)
        return out

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
        """A step was redone: everything after it is no longer valid (the step itself stays)."""
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
        for key, _, required in STEPS:
            if required and not self.is_done(key):
                return key, HINTS[key]
        return "done", HINTS["done"]

    def summary_lines(self) -> List[str]:
        lines = [f"Set project: {self.name}", f"Folder: {self.folder}",
                 f"Source music folder: {self.data.get('source_folder') or '-'}",
                 f"Updated: {self.data['updated']}",
                 f"Imported files: {len(self.data['imported'])} | analysed: {len(self.tracks)} | in set list: {len(self.data['set_list'])}"]
        for key, label, required in STEPS:
            state = self.step_state(key)
            mark = "[x]" if state["done"] else ("[ ]" if required else "[ ] (optional)")
            when = f" - {state['at']}" if state.get("at") else ""
            details = state.get("details") or {}
            extra = ", ".join(f"{k}={v}" for k, v in details.items() if k in ("count", "out_dir", "playlist", "db", "file", "cues"))
            lines.append(f"  {mark} {label}{when}{(' | ' + extra) if extra else ''}")
        key, hint = self.next_step()
        lines.append(f"Next: {hint}")
        return lines
