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


def filter_entries(entries: List[Dict], text: str) -> List[Dict]:
    """Entries whose file name contains text (case-insensitive)."""
    needle = (text or "").strip().lower()
    if not needle:
        return list(entries)
    return [e for e in entries if needle in e["filename"].lower()]
