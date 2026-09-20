#!/usr/bin/env python3
"""
The music library: every track the user mixed, kept in one folder.

The folder is scanned in place (nothing is copied). Durations come from the
file headers; BPM, key and energy come from the analysis cache when the track
was already analysed, so a scan never decodes audio.
"""

import logging
import os
from typing import Callable, Dict, List, Optional

from analysis_store import get_store
from set_project import audio_files_in

log = logging.getLogger("dynamix.library")


def read_duration(path: str) -> Optional[float]:
    """Duration in seconds from the file header, None when the file cannot be read."""
    try:
        import soundfile as sf
        return float(sf.info(path).duration)
    except Exception:
        return None


def library_entry(path: str, store=None) -> Dict:
    """One row of the library table."""
    features = None
    if store is not None:
        try:
            features = store.get(path, "features")
        except Exception:
            features = None
    entry = {
        "file_path": os.path.abspath(path),
        "filename": os.path.basename(path),
        "duration": None,
        "bpm": None,
        "key": None,
        "energy_level": None,
        "analysed": features is not None,
    }
    if features:
        entry["duration"] = float(features.get("duration") or 0) or None
        entry["bpm"] = float(features.get("bpm") or 0) or None
        entry["key"] = features.get("key") or None
        entry["energy_level"] = float(features.get("energy_level") or 0) or None
    if entry["duration"] is None:
        entry["duration"] = read_duration(path)
    return entry


def scan(folder: str, progress: Optional[Callable[[int, int, str], None]] = None,
         use_cache: bool = True) -> List[Dict]:
    """All audio files under folder (recursive), sorted by file name."""
    if not folder or not os.path.isdir(folder):
        raise FileNotFoundError(f"Library folder not found: {folder or '(not set)'}")
    files = audio_files_in(folder, recursive=True)
    store = get_store() if use_cache else None
    entries = []
    for i, path in enumerate(files, 1):
        entries.append(library_entry(path, store))
        if progress:
            progress(i, len(files), os.path.basename(path))
    minutes = sum(e["duration"] or 0 for e in entries) / 60
    log.info("Library scanned: %d files (%d analysed, %.0f min) in %s",
             len(entries), sum(1 for e in entries if e["analysed"]), minutes, folder)
    return entries


def scan_many(folders: List[str], progress: Optional[Callable[[int, int, str], None]] = None,
              use_cache: bool = True) -> tuple:
    """
    The audio files of several folders as one list sorted by file name (the FX samples folders).

    Every entry carries the folder it came from ('root') and that folder's name ('root_name'), so two
    samples with the same file name stay apart. A folder that is gone is returned in the second list
    rather than raised: the others are still usable. Returns (entries, missing folders).
    """
    entries: List[Dict] = []
    missing: List[str] = []
    seen_roots, seen_files = set(), set()
    for folder in folders:
        folder = (folder or "").strip()
        if not folder:
            continue
        root = os.path.abspath(folder)
        if os.path.normcase(root) in seen_roots:
            continue  # the same folder given twice
        seen_roots.add(os.path.normcase(root))
        if not os.path.isdir(root):
            missing.append(folder)
            continue
        for entry in scan(root, use_cache=use_cache):
            key = os.path.normcase(entry["file_path"])
            if key in seen_files:  # reachable from two roots (one nested in the other)
                continue
            seen_files.add(key)
            entries.append(dict(entry, root=root, root_name=os.path.basename(root) or root))
    entries.sort(key=lambda e: (e["filename"].lower(), e["root_name"].lower()))
    if progress:
        progress(len(entries), len(entries), "")
    return entries, missing


def filter_entries(entries: List[Dict], text: str) -> List[Dict]:
    """Entries whose file name - or the folder they came from - contains text (case-insensitive)."""
    needle = (text or "").strip().lower()
    if not needle:
        return list(entries)
    return [e for e in entries
            if needle in e["filename"].lower() or needle in (e.get("root_name") or "").lower()]
