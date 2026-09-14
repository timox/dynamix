#!/usr/bin/env python3
"""
Set project: one folder per set.

    <projects root>/<name>/
        project.json     selection, tracks, proposals, set list, step states, results
        premaster/       corrected copies written by the pre-master pass
        fx/              copies with transition FX (freeze, filters, echo, samples)
        exports/         M3U playlists, transition sheets, JSON, charts
        source/          (projects created before version 3 only) imported copies

The tracks of a set are picked in the music library (one folder holding every
track, see library.py) and referenced by absolute path: nothing is copied and
the library is never written to. The GUI and the command-line tools read and
update project.json, so you always know where you are and never redo a step.
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
    ("analyze", "Select and analyze the tracks", True),
    ("setlist", "Create the set list", True),
    ("transitions", "Plan the transitions", True),
    ("premaster", "Pre-master the set (optional)", False),
    ("fx", "Add transition FX (optional)", False),
    ("playlist", "Write the playlist file (M3U)", False),
    ("mixxx", "Export intro/outro cues to Mixxx", True),
]

HINTS: Dict[str, str] = {
    "analyze": "Pick tracks in the Library, add them to the Selection, then 'Analyze selection' (cached tracks are instant).",
    "setlist": "Click 'Propose', compare the variants, then 'Use this proposal' and adjust the order.",
    "transitions": "Click 'Plan Transitions' to compute intro/outro sections and the transition sheet.",
    "premaster": "Optional: 'Pre-master Set' writes level-matched, phase-repaired copies into the project's premaster folder; later steps then use those copies.",
    "fx": "Optional: 'Transition FX' adds freezes, filter sweeps, echoes and samples on chosen transitions, rendered into the project's fx folder.",
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
    FX_DIR = "fx"
    EXPORTS_DIR = "exports"

    def __init__(self, folder: str, autoload: bool = True):
        self.folder = os.path.abspath(folder)
        self.path = os.path.join(self.folder, self.FILENAME)
        self.data: Dict = {
            "version": 3,
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
            "selection": [],       # absolute paths of the tracks picked in the library
            "tracks": [],          # analysed track records (selected files only)
            "failed": [],          # selected files whose analysis failed
            "proposals": None,     # {params, created, variants[]} from set_proposer
            "set_list": [],        # ordered file paths of the chosen proposal / edited set
            "steps": {key: {"done": False, "at": None, "details": {}} for key, _, _ in STEPS},
            "transitions": None,
            "premaster": None,
            "fx": {"transitions": {}, "render": None},  # FX recipes per track pair, and the last render
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
        project.ensure_dirs()
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
    def fx_dir(self) -> str:
        return os.path.join(self.folder, self.FX_DIR)

    @property
    def exports_dir(self) -> str:
        return os.path.join(self.folder, self.EXPORTS_DIR)

    def ensure_dirs(self) -> None:
        for d in (self.premaster_dir, self.exports_dir):
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
            elif key == "fx":
                self.data["fx"] = {"transitions": dict((value or {}).get("transitions") or {}),
                                   "render": (value or {}).get("render")}
            else:
                self.data[key] = value
        self._migrate()
        return self

    def _migrate(self) -> None:
        """Version 2 projects: the imported copies in source/ become the selection."""
        if int(self.data.get("version") or 0) >= 3:
            return
        if not self.data.get("selection"):
            self.data["selection"] = self.source_files()
        self.data["version"] = 3

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
        os.makedirs(self.source_dir, exist_ok=True)
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

    def set_tracks(self, tracks: List[Dict], attempted: Optional[List[str]] = None) -> None:
        """Store the analysed records; `attempted` = the files the analysis ran on (default: the selection on disk).

        Only attempted files still in the selection and without a record are failed; files
        added to the selection after the attempt stay pending.
        """
        self.data["tracks"] = [dict(t) for t in tracks]
        known = {t["file_path"] for t in self.data["tracks"]}
        self.data["set_list"] = [p for p in self.data["set_list"] if p in known]
        candidates = attempted if attempted is not None else self.selection_files()
        selected = set(self.data["selection"])
        self.data["failed"] = [p for p in candidates if p not in known and p in selected]

    # ------------------------------------------------------------- selection (picked in the library)
    @property
    def selection(self) -> List[str]:
        return self.data["selection"]

    def selection_files(self) -> List[str]:
        """Selected files that exist on disk (what gets analysed)."""
        return [p for p in self.data["selection"] if os.path.isfile(p)]

    def add_to_selection(self, paths: List[str]) -> int:
        """Append new paths (in the given order). Returns how many were added."""
        added = 0
        for p in paths:
            if p not in self.data["selection"]:
                self.data["selection"].append(p)
                added += 1
        if added:
            self.data["proposals"] = None
            self.mark("analyze", done=False)
            self.invalidate_from("analyze")
        return added

    def remove_from_selection(self, paths: List[str]) -> int:
        """Drop paths from the selection, the analysed tracks and the set list."""
        gone = set(paths) & set(self.data["selection"])
        if not gone:
            return 0
        self.data["selection"] = [p for p in self.data["selection"] if p not in gone]
        self.data["tracks"] = [t for t in self.data["tracks"] if t["file_path"] not in gone]
        self.data["failed"] = [p for p in self.data.get("failed", []) if p not in gone]
        self.data["set_list"] = [p for p in self.data["set_list"] if p not in gone]
        self.data["proposals"] = None
        self.invalidate_from("analyze")
        return len(gone)

    def selection_rows(self) -> List[Dict]:
        """One row per selected file: its analysed record when there is one, plus a 'state'."""
        by_path = {t["file_path"]: t for t in self.data["tracks"]}
        failed = set(self.data.get("failed") or [])
        rows = []
        for p in self.data["selection"]:
            row = dict(by_path[p]) if p in by_path else {"file_path": p, "filename": os.path.basename(p)}
            if not os.path.isfile(p):
                row["state"] = "missing"
            elif p in by_path:
                row["state"] = "analysed"
            elif p in failed:
                row["state"] = "failed"
            else:
                row["state"] = "pending"
            rows.append(row)
        return rows

    def proposal_tracks(self) -> Tuple[List[Dict], List[str]]:
        """(analysed selected tracks whose file exists, file names of the selected tracks left out)."""
        usable, skipped = [], []
        for row in self.selection_rows():
            if row["state"] == "analysed":
                usable.append({k: v for k, v in row.items() if k != "state"})
            else:
                skipped.append(row["filename"])
        return usable, skipped

    def forget_analysis(self) -> None:
        """After clearing the analysis cache: the selection must be analysed again."""
        self.data["tracks"] = []
        self.data["failed"] = []
        self.data["proposals"] = None
        self.mark("analyze", done=False)
        self.invalidate_from("analyze")

    # ------------------------------------------------------------- proposals
    def set_proposals(self, params: Dict, variants: List[Dict]) -> None:
        """Keep the variants returned by set_proposer.propose (without their track records)."""
        self.data["proposals"] = {
            "params": dict(params),
            "created": _now(),
            "variants": [{k: v for k, v in variant.items() if k != "tracks"} for variant in variants],
        }

    def proposal_variants(self) -> List[Dict]:
        return (self.data.get("proposals") or {}).get("variants") or []

    def use_proposal(self, index: int) -> List[str]:
        """Copy a proposal into the set list (later steps are invalidated). Returns the set list."""
        variants = self.proposal_variants()
        if not 0 <= index < len(variants):
            raise IndexError(f"No proposal #{index + 1}")
        variant = variants[index]
        self.set_order(variant["order"])
        self.mark("setlist", count=len(self.data["set_list"]), curve=variant["curve"], score=variant["score"])
        return self.data["set_list"]

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

    # ------------------------------------------------------------- transition FX
    @staticmethod
    def fx_key(a: str, b: str) -> str:
        return f"{a}|{b}"

    def fx_for_pair(self, a: str, b: str) -> Optional[Dict]:
        """The FX entry {nudge_ms, effects} of the transition a -> b, or None."""
        return self.data["fx"]["transitions"].get(self.fx_key(a, b))

    def fx_transition(self, a: str, b: str) -> Dict:
        """The FX entry of a -> b, created empty when missing."""
        entry = self.data["fx"]["transitions"].setdefault(self.fx_key(a, b), {"a": a, "b": b, "nudge_ms": 0.0, "effects": []})
        entry.setdefault("a", a)
        entry.setdefault("b", b)
        return entry

    @staticmethod
    def _plan_cues(data: Optional[Dict]) -> Optional[List[Tuple]]:
        """What a plan decides for the rendered audio: the tracks and their intro/outro positions."""
        if not data:
            return None
        return [(t.get("file_path"), t.get("intro_start"), t.get("intro_end"), t.get("outro_start"), t.get("outro_end"))
                for t in data.get("tracks") or []]

    def set_transitions(self, data: Dict) -> None:
        """
        Store a transition plan. A different plan (tracks or cue positions) invalidates the FX render and the
        later steps (recipes kept); the same plan again, as mixxx_export.py --project re-plans on every run,
        keeps them.
        """
        if self._plan_cues(self.data.get("transitions")) != self._plan_cues(data):
            self.invalidate_from("transitions")
        self.data["transitions"] = data
        self.mark("transitions", count=len(data.get("transitions") or []))

    def _fx_changed(self) -> None:
        self.data["fx"]["render"] = None
        self.mark("fx", done=False)
        self.invalidate_from("fx")

    def set_fx_effects(self, a: str, b: str, effects: List[Dict]) -> None:
        self.fx_transition(a, b)["effects"] = [dict(fx) for fx in effects]
        self._fx_changed()

    def set_fx_nudge(self, a: str, b: str, nudge_ms: float) -> None:
        self.fx_transition(a, b)["nudge_ms"] = float(nudge_ms)
        self._fx_changed()

    def remove_fx(self, a: str, b: str) -> None:
        if self.data["fx"]["transitions"].pop(self.fx_key(a, b), None) is not None:
            self._fx_changed()

    def set_list_pairs(self) -> List[Tuple[str, str]]:
        lst = self.data["set_list"]
        return list(zip(lst, lst[1:]))

    def active_fx_pairs(self) -> List[Tuple[str, str]]:
        """Neighbouring set-list pairs with at least one enabled effect, in set order."""
        active = []
        for a, b in self.set_list_pairs():
            entry = self.fx_for_pair(a, b)
            if entry and any(fx.get("enabled", True) for fx in entry.get("effects") or []):
                active.append((a, b))
        return active

    def inactive_fx_pairs(self) -> List[Tuple[str, str]]:
        """Pairs that have effects but are no longer neighbours in the set list."""
        neighbours = set(self.set_list_pairs())
        out = []
        for key, entry in self.data["fx"]["transitions"].items():
            if "a" in entry and "b" in entry:
                a, b = entry["a"], entry["b"]
            else:  # entries saved before the pair was stored
                a, _, b = key.partition("|")
            if entry.get("effects") and (a, b) not in neighbours:
                out.append((a, b))
        return out

    def set_fx_render(self, results: List[Dict]) -> None:
        self.data["fx"]["render"] = {"at": _now(), "results": [dict(r) for r in results]}

    def fx_map(self) -> Dict[str, Dict]:
        """original file path -> FX render result, for copies that exist on disk."""
        render = self.data["fx"].get("render") or {}
        return {r["source"]: r for r in render.get("results") or [] if r.get("output") and "error" not in r and os.path.exists(r["output"])}

    def rendered_profiles(self, profiles: List[Dict]) -> Tuple[List[Dict], Dict[str, int]]:
        """
        Profiles pointing at the file to play: the FX copy (with its rendered intro/outro positions),
        else the pre-mastered copy, else the original. Returns (profiles, {'fx': n, 'premaster': n}).
        """
        fx, premaster = self.fx_map(), self.premaster_map()
        out, counts = [], {"fx": 0, "premaster": 0}
        for p in profiles:
            src = p.get("file_path")
            if src in fx:
                r = fx[src]
                q = dict(p, file_path=r["output"], filename=os.path.basename(r["output"]))
                for key in ("intro_start", "intro_end", "outro_start", "outro_end", "duration"):
                    if key in r:
                        q[key] = r[key]
                counts["fx"] += 1
            elif src in premaster:
                q = dict(p, file_path=premaster[src], filename=os.path.basename(premaster[src]))
                counts["premaster"] += 1
            else:
                q = dict(p)
            out.append(q)
        return out, counts

    # ------------------------------------------------------------- reset
    @staticmethod
    def _files_under(path: str) -> List[str]:
        if os.path.isfile(path):
            return [path]
        found = []
        for root, _dirs, names in os.walk(path):
            found.extend(os.path.join(root, n) for n in names)
        return found

    def _count(self, folders: List[str]) -> Dict[str, int]:
        files = [f for d in folders if os.path.isdir(d) for f in self._files_under(d)]
        return {"files": len(files), "bytes": sum(os.path.getsize(f) for f in files)}

    def reset_preview(self) -> Dict[str, Dict[str, int]]:
        """What reset() would delete: {'outputs': premaster/ + fx/ + exports/, 'imported': source/}."""
        return {"outputs": self._count([self.premaster_dir, self.fx_dir, self.exports_dir]),
                "imported": self._count([self.source_dir])}

    def reset(self, delete_imported: bool = False) -> Dict[str, int]:
        """
        Start the set again from an empty selection. Keeps the name, options, notes
        and the analysis cache; empties premaster/ and exports/ (and source/ when
        delete_imported). Returns {'files_deleted', 'bytes_deleted'}.
        """
        folders = [self.premaster_dir, self.fx_dir, self.exports_dir] + ([self.source_dir] if delete_imported else [])
        result = {"files_deleted": 0, "bytes_deleted": 0}
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                files = self._files_under(path)
                size = sum(os.path.getsize(f) for f in files)
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                result["files_deleted"] += len(files)
                result["bytes_deleted"] += size
        self.data.update(selection=[], tracks=[], failed=[], proposals=None, set_list=[],
                         transitions=None, premaster=None, fx={"transitions": {}, "render": None})
        if delete_imported:
            self.data["imported"] = []
        for key, _, _ in STEPS:
            self.mark(key, done=False)
        self.save()
        return result

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
            if step == "transitions" and later == "premaster":
                continue  # the pre-mastered copies do not depend on the transitions
            self.mark(later, done=False)
        if step in ("analyze", "setlist"):
            self.data["transitions"] = None
            self.data["premaster"] = None
        if step in ("analyze", "setlist", "transitions", "premaster"):
            self.data["fx"]["render"] = None  # the recipes are kept

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
                 f"Selected: {len(self.data['selection'])} | analysed: {len(self.tracks)} | failed: {len(self.data.get('failed') or [])}"
                 f" | proposals: {len(self.proposal_variants())} | in set list: {len(self.data['set_list'])}"]
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
