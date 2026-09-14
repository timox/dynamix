#!/usr/bin/env python3
"""
Rendering of transition FX into copies (fx/ folder of a set project).

For every set-list track touched by an active transition FX, the base (the
pre-mastered copy when there is one, else the original, read only) gets the
incoming-side FX of the previous transition and the outgoing-side FX of the next
one, then a true-peak limiter pass over the modified spans, and is written to
out_dir with its new intro/outro positions. Tracks are streamed in set order: at
most the two tracks of the current transition are in memory. Also renders the
looped preview clip of one transition.
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
    # tracks are loaded when a transition first needs them and written as soon as no later transition can touch them
    audio, rates, beats, cues, spans, problems = {}, {}, {}, {}, {}, []
    unusable, rendered, results = set(), set(), []
    steps = len(active) + len(involved)
    counter = [0]
    os.makedirs(out_dir, exist_ok=True)

    def load(i: int) -> bool:
        if i in audio:
            return True
        if i in unusable:
            return False
        prof = profiles[i]
        name = prof.get("filename") or os.path.basename(prof["file_path"])
        base = bases.get(prof["file_path"], prof["file_path"])
        try:
            data, sr = load_audio(base)
            data = tfx.to_stereo(data)
            grid, warning = _beats_for(prof, grids, len(data) / sr)
        except Exception as exc:  # missing or unreadable file, beat analysis failure
            unusable.add(i)
            problems.append(f"{name}: cannot be read ({exc})")
            return False
        if warning:
            problems.append(f"{name}: {warning}")
        audio[i], rates[i], beats[i], cues[i], spans[i] = data, sr, grid, _cues(prof), []
        return True

    def finish(i: int) -> None:
        x, sr, track_spans, track_cues = audio.pop(i), rates.pop(i), spans.pop(i), cues.pop(i)
        beats.pop(i, None)
        if i not in rendered:
            return
        prof = profiles[i]
        counter[0] += 1
        if progress:
            progress(counter[0], steps, prof.get("filename", ""))
        reduction = _limit_spans(x, sr, track_spans)
        if reduction > 3.0:
            log.warning("FX render: the limiter reduced %s by %.1f dB", prof.get("filename", ""), reduction)
        base = bases.get(prof["file_path"], prof["file_path"])
        output = output_path_for(base, out_dir, fmt)
        write_audio(output, x, sr)
        duration = len(x) / sr
        result = {"source": prof["file_path"], "input": base, "output": output,
                  "limiter_reduction_db": round(reduction, 2), "duration": duration}
        result.update({k: round(min(v, duration), 4) for k, v in track_cues.items()})
        results.append(result)

    for i, entry in active:
        a, b = i, i + 1
        for k in sorted(audio):
            if k < a:
                finish(k)  # no later transition can touch it
        counter[0] += 1
        if progress:
            progress(counter[0], steps, f"{profiles[a].get('filename', '')} -> {profiles[b].get('filename', '')}")
        usable_a, usable_b = load(a), load(b)
        if not (usable_a and usable_b):
            problems.append(f"transition {a + 1}: skipped (a track cannot be read)")
            continue
        ctx = tfx.make_context(audio[a], rates[a], beats[a], cues[a]["outro_start"], cues[a]["outro_end"],
                               audio[b], rates[b], beats[b], cues[b]["intro_start"], entry.get("nudge_ms", 0.0))
        b_start = int(round(ctx.b_offset * rates[b]))
        b_len = len(ctx.b)
        try:
            tfx.apply_effects(ctx, _active(entry["effects"]))
        except Exception as exc:
            problems.append(f"transition {a + 1}: {exc}")
            continue
        a_start = int(round(ctx.a_offset * rates[a]))
        audio[a] = np.concatenate([audio[a][:a_start], ctx.a]).astype(np.float32)
        spans[a].append((a_start, len(audio[a])))
        audio[b] = np.concatenate([audio[b][:b_start], ctx.b, audio[b][b_start + b_len:]]).astype(np.float32)
        spans[b].append((b_start, b_start + len(ctx.b)))
        cues[a]["outro_start"], cues[a]["outro_end"] = ctx.outro_start, ctx.a_end
        cues[b]["intro_start"] = ctx.junction_b
        # Mixxx ends the transition at A's outro end: B's intro must last at least as long for B to enter on the junction
        cues[b]["intro_end"] = max(cues[b]["intro_end"], ctx.junction_b + (ctx.a_end - ctx.junction_a))
        problems.extend(ctx.warnings)
        rendered.update((a, b))
        del ctx
    for k in sorted(audio):
        finish(k)
    return results, problems


LIMIT_EDGE_FADE_S = 0.010


def _merge_spans(spans: Sequence[Tuple[int, int]], length: int) -> List[Tuple[int, int]]:
    merged: List[List[int]] = []
    for s, e in sorted((max(0, s), min(length, e)) for s, e in spans):
        if e <= s:
            continue
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def _limit_spans(x: np.ndarray, sr: int, spans: Sequence[Tuple[int, int]]) -> float:
    """
    True-peak limit only the modified spans of x (in place), with a short linear crossfade back to the
    untouched audio at span edges inside the file. Returns the largest reduction in dB.
    """
    reduction = 0.0
    for s, e in _merge_spans(spans, len(x)):
        seg = x[s:e]
        limited = true_peak_limiter(seg, sr, ceiling_db=-1.0)
        if limited is seg:
            continue  # nothing above the ceiling
        limited = np.asarray(limited, dtype=np.float32)
        before = float(np.max(np.abs(seg)))
        after = float(np.max(np.abs(limited)))
        if before > 0:
            reduction = max(reduction, 20 * float(np.log10(max(before, 1e-9) / max(after, 1e-9))))
        weight = np.ones(e - s, dtype=np.float32)
        fade = min(int(round(LIMIT_EDGE_FADE_S * sr)), (e - s) // 2)
        if fade > 0:
            if s > 0:
                weight[:fade] = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            if e < len(x):
                weight[e - s - fade:] = np.linspace(1.0, 0.0, fade, dtype=np.float32)
        x[s:e] = seg + (limited - seg) * weight[:, None]
    return max(0.0, reduction)


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
    # same rule as render_set: B's intro lasts at least as long as A's outro
    clip, sr = tfx.preview_mix(ctx, max(cb["intro_end"], ctx.junction_b + (ctx.a_end - ctx.junction_a)), length)
    return clip, sr, [w for w in (wa, wb) if w] + ctx.warnings
