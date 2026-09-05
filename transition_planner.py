#!/usr/bin/env python3
"""
Transition planner for DynaMix.

Given an ordered list of tracks (a set list, an analyzed playlist or a plain
directory listing), it loads each track once and derives:

- an INTRO section: where the track should start playing under the previous
  one, until the point where its energy kicks in;
- an OUTRO section: where the previous track should start fading out, until
  the point where it must be gone.

Both sections are snapped to the beat grid. From those per-track sections it
builds a transition sheet for every consecutive pair (compatibility score,
tempo adjustment, exit and entry times), which can be printed, saved as text
or pushed to Mixxx (see mixxx_export.py) so that Auto DJ follows them.
"""

import os
from typing import Callable, Dict, List, Optional

import numpy as np

from audio_utils import AudioAnalyzer


def compatibility_from_features(f1: Dict, f2: Dict) -> Dict:
    """Same scoring as audio_utils.analyze_track_compatibility, without reloading audio."""
    bpm1 = float(f1.get('bpm') or 0)
    bpm2 = float(f2.get('bpm') or 0)
    bpm_diff = abs(bpm1 - bpm2)
    result = {
        'bpm_difference': bpm_diff,
        'bpm_compatibility': max(0.0, 100.0 - bpm_diff * 2),
    }

    key1 = str(f1.get('key') or '')
    key2 = str(f2.get('key') or '')
    if key1 and key1 == key2:
        result['key_compatibility'] = 100.0
    elif key1 and key2 and key1.split()[0] == key2.split()[0]:
        result['key_compatibility'] = 80.0
    else:
        result['key_compatibility'] = 50.0

    e1 = float(f1.get('avg_energy') or 0)
    e2 = float(f2.get('avg_energy') or 0)
    max_energy = max(e1, e2)
    result['energy_compatibility'] = max(0.0, 100.0 - abs(e1 - e2) / max_energy * 100.0) if max_energy > 0 else 100.0

    result['overall_score'] = (
        result['bpm_compatibility'] * 0.4
        + result['key_compatibility'] * 0.3
        + result['energy_compatibility'] * 0.3
    )
    return result


class TransitionPlanner:
    """Compute intro/outro sections and a transition sheet for an ordered track list."""

    def __init__(self, tracks: List[Dict], mix_bars: int = 8,
                 min_mix_seconds: float = 8.0, max_mix_seconds: float = 32.0):
        """
        Args:
            tracks: ordered list of dicts with at least 'file_path'
                    (analyzed tracks with bpm/key/duration are reused as-is)
            mix_bars: target crossfade length in bars of 4 beats
        """
        self.tracks = list(tracks)
        self.mix_bars = mix_bars
        self.min_mix_seconds = min_mix_seconds
        self.max_mix_seconds = max_mix_seconds
        self.profiles: List[Dict] = []
        self.transitions: List[Dict] = []

    # ------------------------------------------------------------------ analysis
    def _mix_duration(self, bpm: float) -> float:
        if not bpm or bpm <= 0:
            return 16.0
        seconds = self.mix_bars * 4 * 60.0 / bpm
        return float(np.clip(seconds, self.min_mix_seconds, self.max_mix_seconds))

    @staticmethod
    def _snap_to_beat(value: float, beat_times: np.ndarray, prefer_before: bool = True) -> float:
        """Snap to the beat grid. With prefer_before the result never moves later than value."""
        if beat_times is None or len(beat_times) == 0:
            return float(value)
        if prefer_before:
            earlier = beat_times[beat_times <= value + 1e-6]
            return float(earlier[-1]) if len(earlier) else float(value)
        idx = int(np.argmin(np.abs(beat_times - value)))
        return float(beat_times[idx])

    @staticmethod
    def _smooth(values: np.ndarray, times: np.ndarray, seconds: float) -> np.ndarray:
        """Moving average over roughly `seconds` of signal (centered)."""
        if len(times) < 2:
            return values.astype(float)
        step = float(times[1] - times[0]) or 1.0
        window = max(1, int(round(seconds / step)))
        kernel = np.ones(window) / window
        # Pad with edge values so the first/last seconds are not artificially quiet
        padded = np.pad(values.astype(float), (window // 2, window - 1 - window // 2), mode='edge')
        return np.convolve(padded, kernel, mode='valid')[:len(values)]

    @staticmethod
    def _sustained_index(mask: np.ndarray, min_run: int, from_start: bool = True) -> Optional[int]:
        """
        from_start=True : first index where `mask` stays True for min_run samples.
        from_start=False: start index of the final run of True values, if it is
                          at least min_run long (None otherwise).
        """
        n = len(mask)
        if n == 0:
            return None
        if from_start:
            run = 0
            for i in range(n):
                run = run + 1 if mask[i] else 0
                if run >= min_run:
                    return i - min_run + 1
            return None
        if not mask[-1]:
            return None
        i = n - 1
        while i > 0 and mask[i - 1]:
            i -= 1
        return i if (n - i) >= min_run else None

    def profile_track(self, track: Dict) -> Dict:
        """Load one track and compute its intro/outro sections."""
        path = track['file_path']
        analyzer = AudioAnalyzer(path)
        duration = float(analyzer.duration)

        # Reuse analysis results when the caller already has them
        bpm = float(track.get('bpm') or 0)
        key = track.get('key') or ''
        avg_energy = float(track.get('avg_energy') or 0)
        if bpm <= 0:
            bpm, _ = analyzer.detect_bpm()
        if not key:
            key, _ = analyzer.detect_key()

        times, rms = analyzer.analyze_energy_profile()
        if avg_energy <= 0:
            avg_energy = float(np.mean(rms))
        beat_times, _ = analyzer.analyze_beat_grid()
        beat_times = np.asarray(beat_times, dtype=float)

        mix_dur = self._mix_duration(bpm)
        beat_len = 60.0 / bpm if bpm > 0 else 0.5
        step = float(times[1] - times[0]) if len(times) > 1 else 0.25
        min_run = max(2, int(round(4 * beat_len / step)))  # a sustained change lasts >= 4 beats

        # Energy smoothed over ~4 seconds, compared with the loud "body" of the track
        smooth = self._smooth(rms, times, 4.0)
        body = smooth[int(len(smooth) * 0.25):max(int(len(smooth) * 0.75), int(len(smooth) * 0.25) + 1)]
        reference = float(np.median(body)) if len(body) else float(np.median(smooth))
        loud = smooth >= reference * 0.7

        # ---- intro: leading quiet part until the energy settles in
        head = times <= min(duration * 0.4, 90.0)
        first_loud = self._sustained_index(loud & head, min_run, from_start=True)
        if first_loud is not None and times[first_loud] >= 4 * beat_len:
            intro_end = self._snap_to_beat(float(times[first_loud]), beat_times)
            intro_start = self._snap_to_beat(max(0.0, intro_end - mix_dur), beat_times)
        else:
            # Track is loud from the start: begin on the first beat, blend for one mix length
            intro_start = float(beat_times[0]) if len(beat_times) and beat_times[0] <= 2 * beat_len else 0.0
            intro_end = self._snap_to_beat(min(duration, intro_start + mix_dur), beat_times, prefer_before=False)
        if intro_end - intro_start < 2 * beat_len:
            intro_end = min(duration, intro_start + mix_dur)

        # ---- outro: start of the trailing quiet part, else mix_dur before the end
        tail_start_idx = self._sustained_index(~loud, min_run, from_start=False)
        if tail_start_idx is not None and times[tail_start_idx] >= duration * 0.5:
            outro_start = self._snap_to_beat(float(times[tail_start_idx]), beat_times)
        else:
            outro_start = self._snap_to_beat(max(0.0, duration - mix_dur - 2 * beat_len), beat_times)
        outro_start = max(outro_start, intro_end)
        outro_end = min(duration, outro_start + mix_dur)
        if outro_end - outro_start < 2 * beat_len:  # keep a usable section on very short tracks
            outro_start = max(intro_end, duration - mix_dur)
            outro_end = duration

        return {
            'file_path': path,
            'filename': os.path.basename(path),
            'duration': duration,
            'bpm': float(bpm),
            'key': key,
            'avg_energy': avg_energy,
            'mix_duration': mix_dur,
            'intro_start': float(intro_start),
            'intro_end': float(intro_end),
            'outro_start': float(outro_start),
            'outro_end': float(outro_end),
        }

    def plan(self, progress_callback: Optional[Callable[[int, int, str], None]] = None) -> List[Dict]:
        """Profile every track and build the transition list."""
        self.profiles = []
        total = len(self.tracks)
        for i, track in enumerate(self.tracks):
            if progress_callback:
                progress_callback(i + 1, total, os.path.basename(track['file_path']))
            self.profiles.append(self.profile_track(track))

        self.transitions = []
        for i in range(len(self.profiles) - 1):
            a, b = self.profiles[i], self.profiles[i + 1]
            compat = compatibility_from_features(a, b)
            bpm_adjust = ((b['bpm'] - a['bpm']) / a['bpm'] * 100.0) if a['bpm'] > 0 else 0.0
            crossfade = min(a['outro_end'] - a['outro_start'], b['intro_end'] - b['intro_start'])

            notes = []
            if compat['bpm_difference'] > 5:
                notes.append(f"sync tempo ({bpm_adjust:+.1f}%)")
            if compat['key_compatibility'] < 80:
                notes.append("key clash: use EQ / short blend")
            if compat['energy_compatibility'] < 60:
                notes.append("energy jump")
            if not notes:
                notes.append("smooth")

            self.transitions.append({
                'index': i + 1,
                'from_file': a['file_path'],
                'to_file': b['file_path'],
                'from_name': a['filename'],
                'to_name': b['filename'],
                'exit_time': a['outro_start'],
                'exit_end': a['outro_end'],
                'entry_time': b['intro_start'],
                'entry_end': b['intro_end'],
                'crossfade_seconds': float(crossfade),
                'bpm_from': a['bpm'],
                'bpm_to': b['bpm'],
                'bpm_difference': compat['bpm_difference'],
                'bpm_adjust_pct': bpm_adjust,
                'key_from': a['key'],
                'key_to': b['key'],
                'score': compat['overall_score'],
                'notes': notes,
            })
        return self.transitions

    # ------------------------------------------------------------------ output
    @staticmethod
    def _fmt(seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        return f"{int(seconds // 60)}:{seconds % 60:05.2f}"

    def to_text(self, title: str = "DynaMix Transition Sheet") -> str:
        if not self.profiles:
            return "No tracks planned."
        lines = [title, "=" * len(title), ""]
        total = sum(p['duration'] for p in self.profiles)
        lines.append(f"{len(self.profiles)} tracks, {total / 60:.1f} minutes")
        lines.append("")
        lines.append("TRACKS (intro / outro sections, beat-aligned)")
        lines.append("-" * 60)
        for i, p in enumerate(self.profiles, 1):
            lines.append(f"{i:2d}. {p['filename']}")
            lines.append(f"    {p['bpm']:.1f} BPM | {p['key'] or '-'} | {self._fmt(p['duration'])}")
            lines.append(f"    intro {self._fmt(p['intro_start'])} -> {self._fmt(p['intro_end'])}"
                         f"   outro {self._fmt(p['outro_start'])} -> {self._fmt(p['outro_end'])}")
        lines.append("")
        lines.append("TRANSITIONS")
        lines.append("-" * 60)
        for t in self.transitions:
            lines.append(f"{t['index']:2d}. {t['from_name']}  ->  {t['to_name']}")
            lines.append(f"    score {t['score']:.0f}/100 | {t['bpm_from']:.1f} -> {t['bpm_to']:.1f} BPM "
                         f"({t['bpm_adjust_pct']:+.1f}%) | {t['key_from'] or '-'} -> {t['key_to'] or '-'}")
            lines.append(f"    start next track at {self._fmt(t['exit_time'])} of the current one, "
                         f"cue it at {self._fmt(t['entry_time'])}, blend ~{t['crossfade_seconds']:.0f}s")
            lines.append(f"    {'; '.join(t['notes'])}")
        return "\n".join(lines) + "\n"

    def save_text(self, output_path: str, title: str = "DynaMix Transition Sheet") -> str:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(self.to_text(title))
        return output_path


def tracks_from_m3u(path: str) -> List[Dict]:
    """Read an M3U/M3U8 file and return DynaMix track dictionaries in file order."""
    base_dir = os.path.dirname(os.path.abspath(path))
    tracks = []
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            file_path = line if os.path.isabs(line) else os.path.join(base_dir, line)
            if os.path.exists(file_path):
                tracks.append({'file_path': os.path.abspath(file_path), 'filename': os.path.basename(file_path)})
            else:
                print(f"Skipping missing file from playlist: {line}")
    return tracks
