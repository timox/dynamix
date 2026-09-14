#!/usr/bin/env python3
"""
Rendering of transition FX into copies (fx/ folder of a set project).

For every set-list track touched by an active transition FX, the base (the
pre-mastered copy when there is one, else the original, read only) gets the
incoming-side FX of the previous transition and the outgoing-side FX of the next
one, then a true-peak limiter pass, and is written to out_dir with its new
intro/outro positions. Also renders the looped preview clip of one transition.
"""

import logging
import os
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

import transition_fx as tfx
from mastering import load_audio, output_path_for, true_peak_limiter, write_audio

log = logging.getLogger("dynamix.fx")


def _active(effects: Sequence[Dict]) -> List[Dict]:
    return [fx for fx in effects or [] if fx.get("enabled", True)]


def _beats_for(profile: Dict, grids: Optional[Dict[str, Dict]], duration: float) -> Tuple[List[float], Optional[str]]:
    path = profile["file_path"]
    grid = (grids or {}).get(path) or tfx.beat_grid(path)
    if profile.get("has_beat") is False:
        grid = dict(grid, has_beat=False)  # the analysis found no rhythm: use a regular grid
    return tfx.usable_beats(grid, float(profile.get("bpm") or 0), duration)


def _cues(profile: Dict) -> Dict[str, float]:
    duration = float(profile.get("duration") or 0.0)
    return {"intro_start": float(profile.get("intro_start", 0.0)), "intro_end": float(profile.get("intro_end", 0.0)),
            "outro_start": float(profile.get("outro_start", duration)), "outro_end": float(profile.get("outro_end", duration))}


def render_set(profiles: Sequence[Dict], fx_for_pair: Callable[[str, str], Optional[Dict]], bases: Dict[str, str],
               out_dir: str, fmt: str = "same", grids: Optional[Dict[str, Dict]] = None,
               progress: Optional[Callable[[int, int, str], None]] = None) -> Tuple[List[Dict], List[str]]:
    """
    profiles: planner profiles in set order (original file_path, intro/outro, bpm, duration).
    fx_for_pair(a_path, b_path) -> {"effects": [...], "nudge_ms": n} or None.
    bases: original path -> file to read (pre-mastered copy); missing = the original.
    Returns (results, problems): one result per written copy, readable problems per skipped transition.
    """
    n = len(profiles)
    active = []
    for i in range(n - 1):
        entry = fx_for_pair(profiles[i]["file_path"], profiles[i + 1]["file_path"]) or {}
        if _active(entry.get("effects")):
            active.append((i, entry))
    involved = sorted({i for i, _ in active} | {i + 1 for i, _ in active})
    audio, rates, beats, cues, problems = {}, {}, {}, {}, []
    for i in involved:
        prof = profiles[i]
        base = bases.get(prof["file_path"], prof["file_path"])
        data, rates[i] = load_audio(base)
        audio[i] = tfx.to_stereo(data)
        beats[i], warning = _beats_for(prof, grids, len(audio[i]) / rates[i])
        if warning:
            problems.append(f"{prof.get('filename') or os.path.basename(prof['file_path'])}: {warning}")
        cues[i] = _cues(prof)
    steps = len(active) + len(involved)
    done = 0
    for i, entry in active:
        a, b = i, i + 1
        done += 1
        if progress:
            progress(done, steps, f"{profiles[a].get('filename', '')} -> {profiles[b].get('filename', '')}")
        ctx = tfx.make_context(audio[a], rates[a], beats[a], cues[a]["outro_start"], cues[a]["outro_end"],
                               audio[b], rates[b], beats[b], cues[b]["intro_start"], entry.get("nudge_ms", 0.0))
        b_start = int(round(ctx.b_offset * rates[b]))
        b_len = len(ctx.b)
        try:
            tfx.apply_effects(ctx, _active(entry["effects"]))
        except (ValueError, OSError) as exc:
            problems.append(f"transition {a + 1}: {exc}")
            continue
        a_start = int(round(ctx.a_offset * rates[a]))
        audio[a] = np.concatenate([audio[a][:a_start], ctx.a]).astype(np.float32)
        audio[b] = np.concatenate([audio[b][:b_start], ctx.b, audio[b][b_start + b_len:]]).astype(np.float32)
        cues[a]["outro_start"], cues[a]["outro_end"] = ctx.outro_start, ctx.a_end
        cues[b]["intro_start"] = ctx.junction_b
        cues[b]["intro_end"] = max(cues[b]["intro_end"], ctx.junction_b)
        problems.extend(ctx.warnings)
    results = []
    os.makedirs(out_dir, exist_ok=True)
    for i in involved:
        prof = profiles[i]
        done += 1
        if progress:
            progress(done, steps, prof.get("filename", ""))
        x = audio[i]
        before = float(np.max(np.abs(x))) if len(x) else 0.0
        limited = true_peak_limiter(x, rates[i], ceiling_db=-1.0)
        after = float(np.max(np.abs(limited))) if len(limited) else 0.0
        reduction = max(0.0, 20 * np.log10(max(before, 1e-9) / max(after, 1e-9))) if before > 0 else 0.0
        if reduction > 3.0:
            log.warning("FX render: the limiter reduced %s by %.1f dB", prof.get("filename", ""), reduction)
        base = bases.get(prof["file_path"], prof["file_path"])
        output = output_path_for(base, out_dir, fmt)
        write_audio(output, limited, rates[i])
        duration = len(limited) / rates[i]
        result = {"source": prof["file_path"], "input": base, "output": output,
                  "limiter_reduction_db": round(reduction, 2), "duration": duration}
        result.update({k: round(min(v, duration), 4) for k, v in cues[i].items()})
        results.append(result)
    return results, problems


def render_preview(profile_a: Dict, profile_b: Dict, entry: Dict, bases: Dict[str, str], length: str = "short",
                   grids: Optional[Dict[str, Dict]] = None) -> Tuple[np.ndarray, int, List[str]]:
    """The looped preview clip of one transition (only its own FX)."""
    a_path = bases.get(profile_a["file_path"], profile_a["file_path"])
    b_path = bases.get(profile_b["file_path"], profile_b["file_path"])
    a_audio, a_sr = load_audio(a_path)
    b_audio, b_sr = load_audio(b_path)
    a_audio, b_audio = tfx.to_stereo(a_audio), tfx.to_stereo(b_audio)
    a_beats, wa = _beats_for(profile_a, grids, len(a_audio) / a_sr)
    b_beats, wb = _beats_for(profile_b, grids, len(b_audio) / b_sr)
    ca, cb = _cues(profile_a), _cues(profile_b)
    ctx = tfx.make_context(a_audio, a_sr, a_beats, ca["outro_start"], ca["outro_end"], b_audio, b_sr, b_beats,
                           cb["intro_start"], entry.get("nudge_ms", 0.0))
    tfx.apply_effects(ctx, _active(entry.get("effects")))
    clip, sr = tfx.preview_mix(ctx, cb["intro_end"], length)
    return clip, sr, [w for w in (wa, wb) if w] + ctx.warnings
