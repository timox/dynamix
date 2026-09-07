#!/usr/bin/env python3
"""
DynaMix configuration: paths, defaults and the environment report.

Saved as <DynaMix home>/config.json (see analysis_store.dynamix_home()).
Everything the GUI's Configuration tab shows and edits goes through here.
"""

import json
import os
import shutil
import sys
from typing import Any, Dict, List, Tuple

from analysis_store import dynamix_home, get_store

DEFAULTS: Dict[str, Any] = {
    "projects_root": os.path.join(os.path.expanduser("~"), "DynaMix Projects"),
    "mixxx_db": "",                # empty = auto-detect
    "set_duration": 60,
    "energy_curve": "build",
    "mix_bars": 8,
    "target_lufs": -14.0,
    "tone_match": True,
    "fix_phase": True,
    "mono_bass_hz": 120.0,         # pre-master: force mono bass below this frequency (0 = off)
    "output_format": "same",       # same | wav | flac | mp3 | ogg
}


class Config:
    FILENAME = "config.json"

    def __init__(self, path: str = None):
        self.path = path or os.path.join(dynamix_home(), self.FILENAME)
        self.data: Dict[str, Any] = dict(DEFAULTS)
        if os.path.exists(self.path):
            self.load()

    def load(self) -> "Config":
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            for key in DEFAULTS:
                if key in loaded:
                    self.data[key] = loaded[key]
        except (OSError, ValueError):
            pass
        return self

    def save(self) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)
        return self.path

    def get(self, key: str, default=None):
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value) -> None:
        self.data[key] = value

    @property
    def projects_root(self) -> str:
        return os.path.abspath(os.path.expanduser(self.get("projects_root")))

    def mixxx_db_path(self) -> str:
        """Configured Mixxx database, else the auto-detected one, else ''."""
        configured = (self.get("mixxx_db") or "").strip()
        if configured and os.path.isfile(configured):
            return configured
        from mixxx_export import find_mixxx_db
        return find_mixxx_db() or ""

    def project_defaults(self) -> Dict[str, Any]:
        return {k: self.get(k) for k in ("set_duration", "energy_curve", "mix_bars", "target_lufs", "tone_match", "fix_phase", "mono_bass_hz")}


def environment_report() -> List[Tuple[str, bool, str]]:
    """[(label, ok, detail)] describing what DynaMix can rely on here."""
    rows: List[Tuple[str, bool, str]] = []
    rows.append(("Python", sys.version_info >= (3, 8), f"{sys.version.split()[0]} ({sys.executable})"))
    try:
        import tkinter
        rows.append(("Tkinter (GUI)", True, f"Tk {tkinter.TkVersion}"))
    except Exception as exc:
        rows.append(("Tkinter (GUI)", False, str(exc)))
    try:
        import soundfile as sf
        formats = sf.available_formats()
        rows.append(("soundfile / libsndfile", True, f"libsndfile {sf.__libsndfile_version__}"))
        rows.append(("MP3 read/write (libsndfile)", "MP3" in formats, "native, no FFmpeg needed" if "MP3" in formats else "missing: install FFmpeg for MP3"))
        rows.append(("FLAC / OGG (libsndfile)", "FLAC" in formats and "OGG" in formats, ""))
    except Exception as exc:
        rows.append(("soundfile / libsndfile", False, str(exc)))
    try:
        import librosa
        rows.append(("librosa", True, librosa.__version__))
    except Exception as exc:
        rows.append(("librosa", False, str(exc)))
    try:
        import numba
        rows.append(("numba (fast limiter)", True, numba.__version__))
    except Exception:
        rows.append(("numba (fast limiter)", False, "not installed: the limiter uses a slower pure-Python loop"))
    ffmpeg = shutil.which("ffmpeg")
    rows.append(("FFmpeg (optional, M4A/AAC only)", bool(ffmpeg), ffmpeg or "not on PATH"))
    try:
        from mixxx_export import find_mixxx_db
        detected = find_mixxx_db()
        rows.append(("Mixxx database (auto-detected)", bool(detected), detected or "not found: set it in the Configuration tab"))
    except Exception as exc:
        rows.append(("Mixxx database (auto-detected)", False, str(exc)))
    try:
        stats = get_store().stats()
        rows.append(("Analysis cache", True, f"{stats['files']} files, {stats['entries']} results, {stats['size_bytes'] / 1e6:.1f} MB at {stats['db_path']}"))
    except Exception as exc:
        rows.append(("Analysis cache", False, str(exc)))
    rows.append(("DynaMix home", True, dynamix_home()))
    return rows


def format_environment_report() -> str:
    lines = []
    for label, ok, detail in environment_report():
        lines.append(f"[{'OK  ' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    return "\n".join(lines)
