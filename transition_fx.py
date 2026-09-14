#!/usr/bin/env python3
"""
Transition FX for DynaMix: freeze / roll, filter sweeps, tempo-synced echo and
FX samples, placed in musical beats around the junction of two tracks.

A transition goes from track A (outgoing) to track B (incoming). The junction is
where B enters: A.outro_start in A's time, B.intro_start in B's time, both snapped
to a beat. Every effect is positioned in beats relative to the junction.

Overflow rule: what an effect writes while A is audible (until a_end) goes into
A; what lasts past a_end goes into B at the same musical instant, so nothing is
played twice during the crossfade.

Pure numpy / scipy: arrays in, arrays out (float32, shape (n, 2)).
"""

import math
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import signal

from i18n import N_

FX_TYPES = ("freeze", "filter", "echo", "sample", "scratch")
BLOCK = 256
EDGE_FADE_S = 0.005
MAX_FREEZE_BEATS = 64
MAX_SAMPLE_SECONDS = 30.0
MAX_REPEATED_SAMPLE_SECONDS = 64.0
MAX_ECHO_TAIL_BEATS = 16
DEFAULT_BPM = 120.0
MIN_GRID_BEATS = 8


# ------------------------------------------------------------------ beat grid
def median_period(beats: Sequence[float]) -> float:
    """Median beat duration in seconds (120 BPM when the grid is too short)."""
    if len(beats) >= 2:
        return float(np.median(np.diff(np.asarray(beats, dtype=float))))
    return 60.0 / DEFAULT_BPM


def regular_grid(bpm: float, duration: float) -> List[float]:
    period = 60.0 / (bpm or DEFAULT_BPM)
    return [i * period for i in range(int(max(duration, 0.0) / period) + 2)]


def nearest_beat_index(beats: Sequence[float], t: float) -> int:
    return int(np.argmin(np.abs(np.asarray(beats, dtype=float) - t)))


def beat_time(beats: Sequence[float], anchor_index: int, offset_beats: float) -> float:
    """Seconds of the beat `offset_beats` away from beats[anchor_index] (fractions interpolate, edges extrapolate)."""
    arr = np.asarray(beats, dtype=float)
    period = median_period(arr)
    pos = anchor_index + offset_beats
    last = len(arr) - 1
    if pos <= 0:
        return float(arr[0] + pos * period)
    if pos >= last:
        return float(arr[last] + (pos - last) * period)
    i = int(math.floor(pos))
    return float(arr[i] + (pos - i) * (arr[i + 1] - arr[i]))


def beat_grid(path: str, use_cache: bool = True) -> Dict:
    """{'beats': [s...], 'bpm', 'has_beat', 'duration'} for a file, through the analysis cache (kind 'beats')."""
    from analysis_store import get_store
    store = get_store() if use_cache else None
    cached = store.get(path, "beats") if store else None
    if cached is not None:
        return cached
    from audio_utils import AudioAnalyzer
    analyzer = AudioAnalyzer(path)
    times, _ = analyzer.analyze_beat_grid()
    beats = [float(t) for t in np.atleast_1d(times)]
    grid = {"beats": beats, "bpm": 60.0 / median_period(beats) if len(beats) >= 2 else 0.0,
            "has_beat": len(beats) >= MIN_GRID_BEATS, "duration": float(analyzer.duration)}
    if store:
        store.put(path, "beats", grid)
    return grid


def grid_is_regular(beats: Sequence[float], tolerance: float = 0.10, share: float = 0.8) -> bool:
    """True when most beat intervals stay within `tolerance` of the median period (audio_utils.grid_is_regular)."""
    from audio_utils import grid_is_regular as regular
    return regular(beats, MIN_GRID_BEATS, tolerance, share)


def usable_beats(grid: Dict, fallback_bpm: float, duration: float, name: str = "") -> Tuple[List[float], Optional[str]]:
    """The detected grid, or a steady one at the track's tempo (with a warning) when the track has no usable beat."""
    beats = list(grid.get("beats") or [])
    if grid.get("has_beat", True) and len(beats) >= MIN_GRID_BEATS:
        return beats, None
    bpm = float(fallback_bpm or grid.get("bpm") or DEFAULT_BPM)
    if name:
        warning = N_("{name}: no steady beat found, the effects follow a regular {bpm:.0f} BPM grid").format(name=name, bpm=bpm)
    else:
        warning = N_("no steady beat found, the effects follow a regular {bpm:.0f} BPM grid").format(bpm=bpm)
    return regular_grid(bpm, duration), warning


# ------------------------------------------------------------------ validation
_RANGES = {
    "freeze": {"capture_offset_beats": (-16, 0), "fade_db": (-60, 0), "tail_beats": (0, 8), "gain_db": (-24, 6)},
    "filter": {"start_hz": (20, 20000), "end_hz": (20, 20000), "width_octaves": (0.3, 4), "resonance": (0.7, 12),
               "beats": (2, 16), "start_offset_beats": (-16, 8)},
    "echo": {"start_offset_beats": (-16, 0), "delay_beats": (0.25, 1), "feedback": (0, 0.85), "mix": (0, 1),
             "damping_hz": (1000, 20000)},
    "sample": {"offset_beats": (-16, 16), "gain_db": (-24, 6), "fade_in_ms": (0, 2000), "fade_out_ms": (0, 2000),
               "sample_bpm": (40, 250), "repeats": (1, 16)},
    "scratch": {"start_offset_beats": (-32, 16), "gain_db": (-24, 6)},
}
_CHOICES = {
    "filter": {"side": ("outgoing", "incoming", "across"), "kind": ("highpass", "lowpass", "bandpass"),
               "curve": ("exponential", "linear"), "beats": (2, 4, 8, 16), "release_beats": (0, 0.5, 1, 2, 4, 8)},
    "echo": {"delay_beats": (0.25, 0.5, 0.75, 1)},
    "sample": {"anchor": ("end_at_junction", "start_at_junction", "center_on_junction"),
               "tempo": ("varispeed", "stretch", "off")},
    "scratch": {"length_beats": (2, 4, 8, 16), "side": ("outgoing", "incoming"), "ramp": ("exponential", "linear")},
}
DEFAULTS = {
    "freeze": {"enabled": True, "capture_offset_beats": 0, "steps": [{"beats": 1, "repeats": 4}], "loop_filter": None,
               "loop_echo": None, "fade_db": 0.0, "tail_beats": 0, "gain_db": 0.0},
    "filter": {"enabled": True, "side": "outgoing", "kind": "highpass", "start_hz": 20.0, "end_hz": 1000.0,
               "width_octaves": 1.0, "resonance": 0.707, "beats": 8, "curve": "exponential", "start_offset_beats": -4,
               "release_beats": 1},
    "echo": {"enabled": True, "start_offset_beats": -4, "delay_beats": 0.5, "feedback": 0.5, "mix": 0.5,
             "damping_hz": 6000.0},
    "sample": {"enabled": True, "file": "", "anchor": "end_at_junction", "offset_beats": 0.0, "gain_db": -3.0,
               "fade_in_ms": 5, "fade_out_ms": 5, "tempo": "varispeed", "sample_bpm": None, "repeats": 1},
    "scratch": {"enabled": True, "sequence": "d81b0 u81b0", "length_beats": 8, "start_offset_beats": -8,
                "side": "outgoing", "ramp": "exponential", "gain_db": 0.0},
}


def new_effect(fx_type: str) -> Dict:
    """A fresh effect of that type with its default settings."""
    if fx_type not in DEFAULTS:
        raise ValueError(f"Unknown FX type: {fx_type}")
    import copy
    return dict(copy.deepcopy(DEFAULTS[fx_type]), type=fx_type)


def _check_ranges(fx_type: str, fx: Dict, label: str = "") -> List[str]:
    errors = []
    for key, (lo, hi) in _RANGES.get(fx_type, {}).items():
        if key in fx and fx[key] is not None and not (lo <= float(fx[key]) <= hi):
            errors.append(f"{label}{fx_type}: {key}={fx[key]} is outside {lo}..{hi}")
    for key, allowed in _CHOICES.get(fx_type, {}).items():
        if key in fx and fx[key] not in allowed:
            errors.append(f"{label}{fx_type}: {key}={fx[key]!r} must be one of {', '.join(map(str, allowed))}")
    return errors


def validate_effect(fx: Dict) -> List[str]:
    """Readable problems with an effect's settings ([] when it can be rendered)."""
    fx_type = fx.get("type")
    if fx_type not in FX_TYPES:
        return [f"Unknown FX type: {fx_type!r}"]
    known = set(DEFAULTS[fx_type]) | {"type"}
    errors = [f"{fx_type}: unknown setting {key!r}" for key in fx if key not in known]
    errors += _check_ranges(fx_type, fx)
    if fx_type == "freeze":
        steps = fx.get("steps") or []
        if not steps:
            errors.append("freeze: at least one step is needed")
        total = 0.0
        for step in steps:
            if step.get("beats") not in (4, 2, 1, 0.5) or int(step.get("repeats", 0)) < 1:
                errors.append(f"freeze: invalid step {step} (beats 4/2/1/0.5, repeats >= 1)")
            else:
                total += float(step["beats"]) * int(step["repeats"])
        if total > MAX_FREEZE_BEATS:
            errors.append(f"freeze: {total:g} beats is longer than {MAX_FREEZE_BEATS}")
        if fx.get("loop_filter"):
            errors += _check_ranges("filter", dict(fx["loop_filter"], side="outgoing"), "loop ")
        if fx.get("loop_echo"):
            errors += _check_ranges("echo", dict(fx["loop_echo"], start_offset_beats=0), "loop ")
    if fx_type == "scratch":
        try:
            parse_scratch(fx.get("sequence") or "")
        except ValueError as exc:
            errors.append(f"scratch: {exc}")
    if fx_type == "sample":
        import os
        if not fx.get("file") or not os.path.isfile(fx["file"]):
            errors.append(f"sample: file not found: {fx.get('file') or '(none)'}")
    return errors


# ------------------------------------------------------------------ DSP building blocks
def to_stereo(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    return np.ascontiguousarray(x[:, :2])


def _fade(x: np.ndarray, sr: int, fade_in_s: float = EDGE_FADE_S, fade_out_s: float = EDGE_FADE_S) -> np.ndarray:
    y = np.array(x, dtype=np.float32, copy=True)
    n = len(y)
    fi = min(n, int(round(fade_in_s * sr)))
    fo = min(n, int(round(fade_out_s * sr)))
    if fi > 0:
        y[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)[:, None]
    if fo > 0:
        y[n - fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)[:, None]
    return y


def _db(value: float) -> float:
    return float(10 ** (value / 20.0))


def biquad_coefficients(kind: str, freq: float, q: float, sr: int) -> Tuple[np.ndarray, np.ndarray]:
    """RBJ cookbook biquad (b, a), normalised; bandpass has a 0 dB peak."""
    freq = float(np.clip(freq, 10.0, 0.45 * sr))
    w0 = 2.0 * math.pi * freq / sr
    cos_w, sin_w = math.cos(w0), math.sin(w0)
    alpha = sin_w / (2.0 * max(q, 0.1))
    if kind == "lowpass":
        b = [(1 - cos_w) / 2, 1 - cos_w, (1 - cos_w) / 2]
    elif kind == "highpass":
        b = [(1 + cos_w) / 2, -(1 + cos_w), (1 + cos_w) / 2]
    elif kind == "bandpass":
        b = [alpha, 0.0, -alpha]
    else:
        raise ValueError(f"Unknown filter kind: {kind}")
    a = [1 + alpha, -2 * cos_w, 1 - alpha]
    return np.asarray(b) / a[0], np.asarray(a) / a[0]


def filter_q(kind: str, resonance: float, width_octaves: float) -> float:
    """Q for a filter: the resonance for highpass/lowpass; width-derived Q scaled by resonance for bandpass."""
    if kind != "bandpass":
        return float(resonance)
    bw = 2.0 ** float(width_octaves)
    return float(math.sqrt(bw) / (bw - 1.0) * (float(resonance) / 0.707))


def sweep_filter(x: np.ndarray, sr: int, kind: str, start_hz: float, end_hz: float, q: float,
                 sweep_samples: int, curve: str = "exponential", hold_start: int = 0) -> np.ndarray:
    """
    Time-varying biquad: start_hz during the first `hold_start` samples, then a sweep to end_hz
    over `sweep_samples`, then end_hz. Coefficients change every BLOCK samples; the state is kept.
    """
    x = to_stereo(x)
    y = np.empty_like(x)
    n = len(x)
    if n == 0:
        return y
    zi = None
    for start in range(0, n, BLOCK):
        end = min(n, start + BLOCK)
        centre = (start + end) / 2.0 - hold_start
        t = 0.0 if centre <= 0 else min(1.0, centre / max(1, sweep_samples))
        if curve == "linear":
            freq = start_hz + (end_hz - start_hz) * t
        else:
            freq = start_hz * (end_hz / start_hz) ** t
        b, a = biquad_coefficients(kind, freq, q, sr)
        if zi is None:
            zi = signal.lfilter_zi(b, a)[:, None] * x[0][None, :]
        y[start:end], zi = signal.lfilter(b, a, x[start:end], axis=0, zi=zi)
    return y.astype(np.float32)


def tempo_echo(x: np.ndarray, sr: int, delay_s: float, feedback: float, mix: float, damping_hz: float,
               max_tail_s: float) -> np.ndarray:
    """Dry signal plus feedback echo (one-pole low-pass in the loop); the tail is trimmed below -60 dB."""
    x = to_stereo(x)
    d = max(1, int(round(delay_s * sr)))
    n_in = len(x)
    n_out = n_in + int(round(max_tail_s * sr))
    inp = np.zeros((n_out, 2), dtype=np.float32)
    inp[:n_in] = x
    wet = np.zeros_like(inp)
    coef = math.exp(-2.0 * math.pi * float(damping_hz) / sr)
    b, a = [1.0 - coef], [1.0, -coef]
    zi = np.zeros((1, 2))
    for start in range(d, n_out, d):
        end = min(n_out, start + d)
        src = wet[start - d:end - d]
        damped, zi = signal.lfilter(b, a, src, axis=0, zi=zi)
        wet[start:end] = inp[start - d:end - d] + feedback * damped
    out = inp + mix * wet
    peak = float(np.max(np.abs(out))) if n_out else 0.0
    if n_out > n_in and peak > 0:
        loud = np.nonzero(np.max(np.abs(out[n_in:]), axis=1) > peak * 1e-3)[0]
        keep = n_in + (int(loud[-1]) + 1 if len(loud) else 0)
        out = out[:keep]
    return out


def load_sample(path: str, sr: int) -> np.ndarray:
    """An FX sample as stereo float32 at sr (not time-stretched); refuses files longer than 30 s."""
    import soundfile as sf
    info = sf.info(path)
    if info.duration > MAX_SAMPLE_SECONDS:
        raise ValueError(f"{path}: {info.duration:.1f} s is longer than {MAX_SAMPLE_SECONDS:.0f} s")
    data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    data = to_stereo(data)
    if int(file_sr) != int(sr):
        g = math.gcd(int(sr), int(file_sr))
        data = signal.resample_poly(data, int(sr) // g, int(file_sr) // g, axis=0).astype(np.float32)
    return data


MIN_TEMPO_RATIO, MAX_TEMPO_RATIO = 0.5, 2.0


def bpm_from_name(path: str) -> Optional[float]:
    """The tempo written in a sample's file name ('... 143BPM.wav', 'riser 128.5 bpm.flac'), or None."""
    match = re.search(r"(\d{2,3}(?:[.,]\d+)?)\s*bpm", os.path.basename(path or ""), re.IGNORECASE)
    return float(match.group(1).replace(",", ".")) if match else None


def sample_tempo(fx: Dict, target_bpm: float) -> Tuple[float, Optional[float], Optional[str]]:
    """
    (ratio, sample_bpm, problem) to fit a sample effect to target_bpm: ratio = target / sample BPM.
    The sample BPM is the one set on the effect, else the one in the file name. A sample played as it is
    (tempo "off", no BPM known, or a ratio outside 0.5..2) gets ratio 1.0; only the last case is a problem.
    """
    if fx.get("tempo", "varispeed") == "off" or not target_bpm:
        return 1.0, None, None
    sample_bpm = fx.get("sample_bpm") or bpm_from_name(fx.get("file") or "")
    if not sample_bpm:
        return 1.0, None, None
    ratio = float(target_bpm) / float(sample_bpm)
    if not MIN_TEMPO_RATIO <= ratio <= MAX_TEMPO_RATIO:
        return 1.0, float(sample_bpm), N_("sample {sample_bpm:g} BPM vs track {track_bpm:.0f} BPM: out of range (x{ratio:.2f}), "
                                          "played as it is").format(sample_bpm=float(sample_bpm), track_bpm=float(target_bpm), ratio=ratio)
    return ratio, float(sample_bpm), None


def fit_tempo(data: np.ndarray, sr: int, ratio: float, mode: str) -> np.ndarray:
    """Play a (n, 2) sample `ratio` times faster: varispeed (resampled, the pitch follows) or stretch (pitch kept)."""
    if mode == "off" or abs(ratio - 1.0) < 1e-6:
        return data
    if mode == "stretch":
        import librosa
        channels = [librosa.effects.time_stretch(np.ascontiguousarray(data[:, c]), rate=float(ratio))
                    for c in range(data.shape[1])]
        n = min(len(c) for c in channels)
        return np.stack([c[:n] for c in channels], axis=1).astype(np.float32)
    from fractions import Fraction
    step = Fraction(1.0 / float(ratio)).limit_denominator(1000)
    # edge padding: zero padding would dip the first and last samples (an audible gap between repeats)
    return signal.resample_poly(data, step.numerator, step.denominator, axis=0, padtype="edge").astype(np.float32)


# ------------------------------------------------------------------ transition context
@dataclass
class TransitionContext:
    a: np.ndarray            # outgoing region (n, 2), starting at a_offset seconds in track A
    a_sr: int
    a_offset: float
    a_beats: List[float]     # beat times of track A (absolute seconds)
    junction_a: float        # absolute seconds in A (snapped + nudge)
    a_end: float             # where A stops being audible (outro_end, or the end of a freeze)
    b: np.ndarray            # incoming region (n, 2), starting at b_offset seconds in track B
    b_sr: int
    b_offset: float
    b_beats: List[float]
    junction_b: float
    outro_start: float = 0.0  # A's outro start in the rendered copy (the junction, or the freeze capture point)
    overflow: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), dtype=np.float32))
    warnings: List[str] = field(default_factory=list)

    def a_index(self, t: float) -> int:
        return int(round((t - self.a_offset) * self.a_sr))

    def b_index(self, t: float) -> int:
        return int(round((t - self.b_offset) * self.b_sr))

    @property
    def a_junction_index(self) -> int:
        return nearest_beat_index(self.a_beats, self.junction_a)

    @property
    def b_junction_index(self) -> int:
        return nearest_beat_index(self.b_beats, self.junction_b)

    @property
    def a_period(self) -> float:
        return median_period(self.a_beats)

    def a_local_bpm(self) -> float:
        """Tempo of A around the junction (median of the 8 beats before it)."""
        j = self.a_junction_index
        near = self.a_beats[max(0, j - 8):j + 1]
        return 60.0 / (median_period(near) if len(near) >= 3 else self.a_period)

    def a_beat(self, offset_beats: float) -> float:
        """Seconds in A of the beat offset_beats away from the junction (the nudge included)."""
        j = self.a_junction_index
        return beat_time(self.a_beats, j, offset_beats) + (self.junction_a - float(self.a_beats[j]))

    def b_beat(self, offset_beats: float) -> float:
        """Seconds in B of the beat offset_beats away from the junction (the nudge included)."""
        j = self.b_junction_index
        return beat_time(self.b_beats, j, offset_beats) + (self.junction_b - float(self.b_beats[j]))


def make_context(a_audio: np.ndarray, a_sr: int, a_beats: Sequence[float], a_outro_start: float, a_outro_end: float,
                 b_audio: np.ndarray, b_sr: int, b_beats: Sequence[float], b_intro_start: float,
                 nudge_ms: float = 0.0, a_region_s: float = 45.0, b_region_s: float = 120.0) -> TransitionContext:
    """Snap the junction to the beat grids and cut the working regions out of the two tracks."""
    nudge = float(nudge_ms) / 1000.0
    junction_a = float(a_beats[nearest_beat_index(a_beats, a_outro_start)]) + nudge
    junction_b = float(b_beats[nearest_beat_index(b_beats, b_intro_start)]) + nudge
    a_audio, b_audio = to_stereo(a_audio), to_stereo(b_audio)
    a_offset = max(0.0, junction_a - a_region_s)
    b_offset = max(0.0, junction_b - 2.0)
    a_start = int(round(a_offset * a_sr))
    b_start = int(round(b_offset * b_sr))
    b_stop = min(len(b_audio), int(round((junction_b + b_region_s) * b_sr)))
    a_end = max(junction_a, float(a_outro_end) + nudge)
    return TransitionContext(a=np.array(a_audio[a_start:], copy=True), a_sr=int(a_sr), a_offset=a_start / a_sr,
                             a_beats=list(a_beats), junction_a=junction_a, a_end=a_end,
                             b=np.array(b_audio[b_start:b_stop], copy=True), b_sr=int(b_sr), b_offset=b_start / b_sr,
                             b_beats=list(b_beats), junction_b=junction_b, outro_start=junction_a)


def _add_layer(ctx: TransitionContext, layer: np.ndarray, start_t: float) -> None:
    """Mix a layer that starts at absolute A time start_t: into A until a_end, into the overflow after."""
    layer = to_stereo(layer)
    begin = ctx.a_index(start_t)
    if begin < 0:
        layer = layer[-begin:]
        begin = 0
    end_idx = ctx.a_index(ctx.a_end)
    in_a = max(0, min(len(layer), end_idx - begin))
    if in_a:
        stop = begin + in_a
        if stop > len(ctx.a):
            ctx.a = np.concatenate([ctx.a, np.zeros((stop - len(ctx.a), 2), dtype=np.float32)])
        ctx.a[begin:stop] += layer[:in_a]
    rest = layer[in_a:]
    if len(rest):
        at = max(0, begin + in_a - end_idx)
        need = at + len(rest)
        if need > len(ctx.overflow):
            ctx.overflow = np.concatenate([ctx.overflow, np.zeros((need - len(ctx.overflow), 2), dtype=np.float32)])
        ctx.overflow[at:need] += rest


# ------------------------------------------------------------------ effects
def _apply_freeze(ctx: TransitionContext, fx: Dict) -> None:
    capture_offset = int(fx.get("capture_offset_beats", 0))
    capture_t = ctx.a_beat(capture_offset)
    capture_i = ctx.a_index(capture_t)
    pieces = []
    for step in fx.get("steps") or []:
        seg_start = ctx.a_index(ctx.a_beat(capture_offset - float(step["beats"])))
        segment = _fade(ctx.a[max(0, seg_start):capture_i], ctx.a_sr)
        pieces.extend([segment] * int(step["repeats"]))
    freeze = np.concatenate(pieces) if pieces else np.zeros((0, 2), dtype=np.float32)
    n_freeze = len(freeze)
    tail = np.zeros((int(round(float(fx.get("tail_beats", 0)) * ctx.a_period * ctx.a_sr)), 2), dtype=np.float32)
    body = np.concatenate([freeze, tail])
    if fx.get("loop_filter"):
        lf = dict(new_effect("filter"), **fx["loop_filter"])
        q = filter_q(lf["kind"], lf["resonance"], lf["width_octaves"])
        body = sweep_filter(body, ctx.a_sr, lf["kind"], lf["start_hz"], lf["end_hz"], q, n_freeze, lf["curve"])
    if fx.get("loop_echo"):
        le = dict(new_effect("echo"), **fx["loop_echo"])
        body = tempo_echo(body, ctx.a_sr, le["delay_beats"] * ctx.a_period, le["feedback"], le["mix"],
                          le["damping_hz"], 0.0)
    gain = np.ones(len(body), dtype=np.float32) * _db(float(fx.get("gain_db", 0.0)))
    fade_db = float(fx.get("fade_db", 0.0))
    if fade_db and n_freeze:
        ramp = np.concatenate([np.linspace(0.0, fade_db, n_freeze), np.full(len(body) - n_freeze, fade_db)])
        gain *= (10 ** (ramp / 20.0)).astype(np.float32)
    body = _fade(body * gain[:, None], ctx.a_sr, fade_in_s=EDGE_FADE_S, fade_out_s=EDGE_FADE_S)
    head = _fade(ctx.a[:capture_i], ctx.a_sr, fade_in_s=0.0)
    ctx.a = np.concatenate([head, body]).astype(np.float32)
    ctx.outro_start = capture_t
    ctx.junction_a = capture_t  # B now enters on the capture point
    ctx.a_end = capture_t + len(body) / ctx.a_sr


def _filter_span(audio: np.ndarray, sr: int, fx: Dict, first: int, sweep_start: int, sweep_end: int,
                 stop: int, release: Optional[int] = None) -> None:
    """
    Filter audio[first:] in place: start_hz until sweep_start, the sweep until sweep_end, then end_hz — held until
    stop, or back to the dry track over `release` samples after the sweep (never past stop). The indices may lie
    outside the audio: the frequency at every sample is still the one of the sweep at that moment.
    """
    first = max(0, first)
    last = min(len(audio), stop if release is None else min(stop, sweep_end + release))
    if last <= first:
        return
    q = filter_q(fx["kind"], fx.get("resonance", 0.707), fx.get("width_octaves", 1.0))
    wet = sweep_filter(audio[first:last], sr, fx["kind"], fx["start_hz"], fx["end_hz"], q,
                       max(1, sweep_end - sweep_start), fx.get("curve", "exponential"), hold_start=sweep_start - first)
    if release is not None:
        mix = np.ones(last - first, dtype=np.float32)
        ramp = np.linspace(1.0, 0.0, release, dtype=np.float32) if release > 0 else np.zeros(0, dtype=np.float32)
        begin = sweep_end - first
        lo, hi = max(0, begin), min(len(mix), begin + release)
        if hi > lo:
            mix[lo:hi] = ramp[lo - begin:hi - begin]
        mix[max(0, begin + release):] = 0.0
        wet = wet * mix[:, None] + audio[first:last] * (1.0 - mix[:, None])
    audio[first:last] = wet


def _apply_filter(ctx: TransitionContext, fx: Dict) -> None:
    side = fx.get("side", "outgoing")
    a_beat_n = int(round(ctx.a_period * ctx.a_sr))
    # A: up to one beat after it stops being audible (the filter state settles, the rest of A is never heard)
    a_stop = ctx.a_index(ctx.a_end) + a_beat_n
    # the return to the dry track lasts at least a few ms (no click)
    release_s = max(EDGE_FADE_S, float(fx.get("release_beats", 1)) * ctx.a_period)
    if side == "outgoing":
        start_i = ctx.a_index(ctx.a_beat(-int(fx["beats"])))
        _filter_span(ctx.a, ctx.a_sr, fx, start_i, start_i, ctx.a_index(ctx.junction_a), a_stop)
    elif side == "incoming":
        junction_i = ctx.b_index(ctx.junction_b)
        b_release = max(EDGE_FADE_S, float(fx.get("release_beats", 1)) * median_period(ctx.b_beats))
        _filter_span(ctx.b, ctx.b_sr, fx, 0, junction_i, ctx.b_index(ctx.b_beat(int(fx["beats"]))), len(ctx.b),
                     int(round(b_release * ctx.b_sr)))
    else:
        # across the junction: one sweep in set time, applied to A and to B at the same moments, so that the two
        # copies mixed by Mixxx sound like the mix going through one filter
        offset = int(fx.get("start_offset_beats", -4))
        sweep_start_t, sweep_end_t = ctx.a_beat(offset), ctx.a_beat(offset + int(fx["beats"]))
        a_start = ctx.a_index(sweep_start_t)
        _filter_span(ctx.a, ctx.a_sr, fx, a_start, a_start, ctx.a_index(sweep_end_t), a_stop,
                     int(round(release_s * ctx.a_sr)))
        to_b = ctx.junction_b - ctx.junction_a
        _filter_span(ctx.b, ctx.b_sr, fx, 0, ctx.b_index(sweep_start_t + to_b), ctx.b_index(sweep_end_t + to_b),
                     len(ctx.b), int(round(release_s * ctx.b_sr)))


def _apply_echo(ctx: TransitionContext, fx: Dict) -> None:
    start_t = ctx.a_beat(int(fx.get("start_offset_beats", -4)))
    start_i = max(0, ctx.a_index(start_t))
    end_i = min(len(ctx.a), ctx.a_index(ctx.a_end))
    if end_i <= start_i:
        return
    dry = ctx.a[start_i:end_i]
    out = tempo_echo(dry, ctx.a_sr, float(fx["delay_beats"]) * ctx.a_period, float(fx["feedback"]), float(fx["mix"]),
                     float(fx.get("damping_hz", 6000.0)), MAX_ECHO_TAIL_BEATS * ctx.a_period)
    ctx.a[start_i:end_i] = out[:len(dry)]
    if len(out) > len(dry):
        _add_layer(ctx, out[len(dry):], ctx.a_end)


def _apply_sample(ctx: TransitionContext, fx: Dict) -> None:
    data = load_sample(fx["file"], ctx.a_sr)
    ratio, _, problem = sample_tempo(fx, ctx.a_local_bpm())
    if problem:
        ctx.warnings.append(N_("{name}: {problem}").format(name=os.path.basename(fx['file']), problem=problem))
    data = fit_tempo(data, ctx.a_sr, ratio, fx.get("tempo", "varispeed"))
    repeats = int(fx.get("repeats", 1))
    if repeats > 1:  # back to back, the fades below apply to the whole run
        fit = max(1, int(MAX_REPEATED_SAMPLE_SECONDS * ctx.a_sr // max(1, len(data))))
        if fit < repeats:
            ctx.warnings.append(N_("{name}: {repeats} repeats would last more than {seconds:.0f} s, reduced to {fit}").format(
                name=os.path.basename(fx['file']), repeats=repeats, seconds=MAX_REPEATED_SAMPLE_SECONDS, fit=fit))
            repeats = fit
        data = np.tile(data, (repeats, 1))
    fade_in = float(fx.get("fade_in_ms", 5)) / 1000.0
    fade_out = float(fx.get("fade_out_ms", 5)) / 1000.0
    data = _fade(data, ctx.a_sr, fade_in, fade_out) * _db(float(fx.get("gain_db", -3.0)))
    anchor_t = ctx.a_beat(float(fx.get("offset_beats", 0.0)))
    length_s = len(data) / ctx.a_sr
    anchor = fx.get("anchor", "end_at_junction")
    if anchor == "end_at_junction":
        start_t = anchor_t - length_s
    elif anchor == "center_on_junction":
        start_t = anchor_t - length_s / 2.0
    else:
        start_t = anchor_t
    _add_layer(ctx, data, start_t)


# ------------------------------------------------------------------ scratch
SCRATCH_COMMAND_LENGTH = 5
SCRATCH_EXTREME_SPEED = 2.0
# one command = 5 characters, hexadecimal values as in a tracker: d|u, factor 0-F, seconds 1-F, b, 0|1
_SCRATCH_COMMAND = re.compile(r"([du])([0-9a-f])([0-9a-f])b([01])", re.IGNORECASE)
_SCRATCH_GAP = re.compile(r"[\s,;]*")


def parse_scratch(sequence: str) -> List[Dict]:
    """
    A scratch sequence of 5-character commands with hexadecimal values, as in a tracker, e.g. "d81b0 u42b1 dF3b1":
    d (slow down) or u (speed up), the factor 1-F (0 keeps the current speed), the duration of the slope in seconds
    1-F, b, then 0 (forwards) or 1 (backwards). "d81b0" reaches a speed 8 times slower in 1 s, forwards. Spaces,
    commas or new lines between commands are optional. Returns [{'kind': 'd'|'u', 'factor', 'seconds', 'backward',
    'text'}]; raises ValueError naming the wrong command.
    """
    steps = []
    for command in scratch_commands(sequence):
        if command["error"]:
            raise ValueError(command["error"])
        steps.append(command["step"])
    if not steps:
        raise ValueError(N_("the sequence is empty"))
    return steps


def scratch_commands(sequence: str) -> List[Dict]:
    """
    The commands of a scratch sequence as typed, readable or not, for an editor: [{'start', 'end' (character offsets
    in the text), 'text', 'error' (None when readable), 'step' (as in parse_scratch, None when unreadable)}].
    """
    text = sequence or ""
    commands, position = [], 0
    while True:
        position = _SCRATCH_GAP.match(text, position).end()
        if position >= len(text):
            break
        command = text[position:position + SCRATCH_COMMAND_LENGTH]
        match = _SCRATCH_COMMAND.fullmatch(command)
        entry = {"start": position, "end": position + len(command), "text": command, "error": None, "step": None}
        if not match:
            entry["error"] = N_("command '{command}': expected 5 characters like d81b0 (d or u, factor 0-F, seconds 1-F, "
                                "b, 0 or 1)").format(command=command)
        elif int(match.group(3), 16) == 0:
            entry["error"] = N_("command '{command}': the duration must be 1 to F seconds").format(command=command)
        else:
            entry["step"] = {"kind": match.group(1).lower(), "factor": float(max(1, int(match.group(2), 16))),
                             "seconds": float(int(match.group(3), 16)), "backward": match.group(4) == "1", "text": command}
        commands.append(entry)
        position += SCRATCH_COMMAND_LENGTH
    return commands


# what each character of a command may be, in order; the arrows of the editor step through them
_SCRATCH_SLOTS = ("du", "0123456789ABCDEF", "123456789ABCDEF", "b", "01")


def scratch_nudge(sequence: str, offset: int, delta: int) -> Optional[str]:
    """
    The sequence with the character at `offset` stepped by `delta` within what its place in the command allows (d/u,
    factor 0-F, seconds 1-F, 0/1), as the arrows of a tracker do; None when that character cannot be stepped.
    """
    text = sequence or ""
    for command in scratch_commands(text):
        if command["start"] <= offset < command["end"]:
            slot = _SCRATCH_SLOTS[offset - command["start"]]
            current = text[offset]
            index = slot.find(current.lower() if slot == "du" else current.upper())
            if index < 0 or len(slot) < 2:
                return None
            # two choices (d/u, 0/1) toggle; the factor and the seconds stop at their ends
            index = (index + delta) % 2 if len(slot) == 2 else max(0, min(len(slot) - 1, index + delta))
            value = slot[index].upper() if slot == "du" and current.isupper() else slot[index]
            return text[:offset] + value + text[offset + 1:]
    return None


def scratch_head(plan: Dict, sr: int) -> Dict:
    """
    Where the read position is during a scratch planned at `sr` values per second: 't' (s), 'speed' and 'offset'
    (seconds of audio ahead of, or behind, the position without the effect; 0 again at the end).
    """
    speed = np.asarray(plan["speed"], dtype=np.float64)
    t = np.arange(len(speed) + 1) / float(sr)
    read = np.concatenate([[0.0], np.cumsum(speed)]) / float(sr)
    return {"t": t, "speed": np.concatenate([speed[:1], speed]) if len(speed) else speed, "offset": read - t}


def scratch_plan(sequence: str, length_s: float, sr: int, ramp: str = "exponential") -> Dict:
    """
    The playback speed of a scratch lasting length_s seconds, one value per sample: the steps of the sequence, then a
    constant catch-up speed so that the read position ends exactly length_s seconds further — where the track would
    be without the effect. Returns {'speed', 'steps' (with 'start'/'end' seconds), 'sequence_end' (s),
    'advance' (seconds of audio read by the sequence), 'catch_up_speed' (None when no time is left), 'warnings'}.
    """
    steps = parse_scratch(sequence)
    n = max(1, int(round(length_s * sr)))
    speed = np.ones(n, dtype=np.float64)
    magnitude, i, placed, warnings = 1.0, 0, [], []
    for step in steps:
        full = max(1, int(round(step["seconds"] * sr)))
        if i >= n or i + full > n:
            warnings.append(N_("the sequence is longer than the effect: it is cut at '{step}'").format(step=step["text"]))
        count = min(full, n - i)
        if count <= 0:
            break
        target = magnitude / step["factor"] if step["kind"] == "d" else magnitude * step["factor"]
        fraction = np.arange(1, count + 1) / full
        if ramp == "linear":
            values = magnitude + (target - magnitude) * fraction
        else:
            values = magnitude * (target / magnitude) ** fraction
        speed[i:i + count] = -values if step["backward"] else values
        placed.append(dict(step, start=i / sr, end=(i + count) / sr))
        magnitude = float(values[-1])
        i += count
        if count < full:
            break
    read = float(np.sum(speed[:i]))
    rest = n - i
    catch_up = None
    if rest > 0:
        catch_up = (n - read) / rest  # exact in samples: the effect ends where the track would be
        speed[i:] = catch_up
        if catch_up < 0:
            warnings.append(N_("the catch-up has to play backwards (x{speed:.2f}): shorten the sequence or the backward steps").format(speed=catch_up))
        elif catch_up > SCRATCH_EXTREME_SPEED:
            warnings.append(N_("extreme catch-up at x{speed:.2f}: shorten the sequence or lengthen the effect").format(speed=catch_up))
    elif abs(n - read) > 1:
        warnings.append(N_("no time left to catch up: the sequence ends {seconds:+.2f} s away from the track").format(
            seconds=(read - n) / sr))
    return {"speed": speed, "steps": placed, "sequence_end": i / sr, "advance": read / sr, "catch_up_speed": catch_up,
            "warnings": warnings}


def render_scratch(audio: np.ndarray, sr: int, start_i: int, speed: np.ndarray) -> np.ndarray:
    """The audio read from start_i at the given per-sample speed (linear interpolation), silent dips where it turns."""
    positions = start_i + np.concatenate([[0.0], np.cumsum(speed[:-1])])
    positions = np.clip(positions, 0.0, len(audio) - 1.0)
    base = np.floor(positions).astype(np.int64)
    nxt = np.minimum(base + 1, len(audio) - 1)
    frac = (positions - base)[:, None].astype(np.float32)
    out = audio[base] * (1.0 - frac) + audio[nxt] * frac
    turns = np.nonzero(np.diff(np.sign(speed)) != 0)[0] + 1
    half = max(1, int(round(EDGE_FADE_S * sr)))
    if len(turns):
        envelope = np.ones(len(speed), dtype=np.float32)
        dip = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, half, dtype=np.float32))  # 0 -> 1
        for turn in turns:
            lo, hi = max(0, turn - half), min(len(speed), turn + half)
            envelope[lo:turn] = np.minimum(envelope[lo:turn], dip[::-1][half - (turn - lo):])
            envelope[turn:hi] = np.minimum(envelope[turn:hi], dip[:hi - turn])
        out = out * envelope[:, None]
    return out.astype(np.float32)


def _scratch_span(ctx: TransitionContext, fx: Dict) -> Tuple[float, float]:
    """(start, end) of a scratch in seconds of its own track."""
    beats = int(fx.get("length_beats", 8))
    offset = float(fx.get("start_offset_beats", -beats))
    if fx.get("side", "outgoing") == "outgoing":
        return ctx.a_beat(offset), ctx.a_beat(offset + beats)
    return ctx.b_beat(offset), ctx.b_beat(offset + beats)


def _apply_scratch(ctx: TransitionContext, fx: Dict) -> None:
    outgoing = fx.get("side", "outgoing") == "outgoing"
    audio, sr = (ctx.a, ctx.a_sr) if outgoing else (ctx.b, ctx.b_sr)
    start_t, end_t = _scratch_span(ctx, fx)
    start_i = ctx.a_index(start_t) if outgoing else ctx.b_index(start_t)
    if end_t <= start_t or start_i < 0 or start_i >= len(audio) - 1:
        ctx.warnings.append(N_("scratch: its beats are outside the audio of the transition"))
        return
    plan = scratch_plan(fx.get("sequence") or "", end_t - start_t, sr, fx.get("ramp", "exponential"))
    ctx.warnings.extend(plan["warnings"])
    n = min(len(plan["speed"]), len(audio) - start_i)
    region = render_scratch(audio, sr, start_i, plan["speed"][:n]) * _db(float(fx.get("gain_db", 0.0)))
    original = audio[start_i:start_i + n]
    edge = min(int(round(EDGE_FADE_S * sr)), n // 2)
    if edge > 0:  # crossfades with the untouched track on both sides
        ramp_in = np.linspace(0.0, 1.0, edge, dtype=np.float32)[:, None]
        region[:edge] = original[:edge] * (1.0 - ramp_in) + region[:edge] * ramp_in
        region[n - edge:] = region[n - edge:] * (1.0 - ramp_in) + original[n - edge:] * ramp_in
    audio[start_i:start_i + n] = region


_APPLY = {"freeze": _apply_freeze, "filter": _apply_filter, "echo": _apply_echo, "sample": _apply_sample,
          "scratch": _apply_scratch}


def apply_effects(ctx: TransitionContext, effects: Sequence[Dict]) -> TransitionContext:
    """Apply the enabled effects (each must pass validate_effect): freezes first, then the others in stack order; then mix the overflow into B."""
    enabled = [fx for fx in effects if fx.get("enabled", True)]
    for fx in enabled:
        problems = validate_effect(fx)
        if problems:
            raise ValueError("; ".join(problems))
    if sum(1 for fx in enabled if fx["type"] == "freeze") > 1:
        raise ValueError("only one freeze per transition")
    # a freeze redefines where A ends and where B enters: freezes first, then the other effects in stack order
    ordered = [fx for fx in enabled if fx["type"] == "freeze"] + [fx for fx in enabled if fx["type"] != "freeze"]
    for fx in ordered:
        _APPLY[fx["type"]](ctx, dict(new_effect(fx["type"]), **fx))
    mix_overflow(ctx)
    return ctx


def mix_overflow(ctx: TransitionContext) -> TransitionContext:
    """Add the overflow to B at the instant A ends (resampled to B's rate), then clear it."""
    if not len(ctx.overflow):
        return ctx
    tail = ctx.overflow
    if ctx.a_sr != ctx.b_sr:
        g = math.gcd(ctx.a_sr, ctx.b_sr)
        tail = signal.resample_poly(tail, ctx.b_sr // g, ctx.a_sr // g, axis=0).astype(np.float32)
    at = ctx.b_index(ctx.junction_b + (ctx.a_end - ctx.junction_a))
    if at < 0:
        tail = tail[-at:]
        at = 0
    need = at + len(tail)
    if need > len(ctx.b):
        ctx.b = np.concatenate([ctx.b, np.zeros((need - len(ctx.b), 2), dtype=np.float32)])
    ctx.b[at:need] += tail
    ctx.overflow = np.zeros((0, 2), dtype=np.float32)
    return ctx


# ------------------------------------------------------------------ preview
def preview_mix(ctx: TransitionContext, b_intro_end: float, length: str = "short") -> Tuple[np.ndarray, int]:
    """
    The rendered transition as one stereo clip at A's rate, faded like Mixxx "Full Intro + Outro": the
    transition lasts L = min(A's junction -> a_end, B's junction -> intro end); A fades out (cos) and
    B (aligned on the junction) fades in (sin) over L from the junction.
    """
    sr = ctx.a_sr
    period = ctx.a_period
    if length == "long":
        start_t = ctx.junction_a - 20.0
        stop_t = max(ctx.junction_a + 10.0, ctx.a_end + 2.0)
    else:
        start_t = ctx.a_beat(-8)
        stop_t = ctx.a_end + 8 * period
    start_t = max(start_t, ctx.a_offset)
    n = int(round((stop_t - start_t) * sr))
    out = np.zeros((max(n, 0), 2), dtype=np.float32)
    # A with its fade-out
    a_i0 = ctx.a_index(start_t)
    a_part = ctx.a[a_i0:a_i0 + n]
    times = start_t + np.arange(len(a_part)) / sr
    fade_len = max(1e-3, min(ctx.a_end - ctx.junction_a, b_intro_end - ctx.junction_b))
    pos = np.clip((times - ctx.junction_a) / fade_len, 0.0, 1.0)
    a_gain = np.where(times < ctx.junction_a, 1.0, np.cos(pos * math.pi / 2)).astype(np.float32)
    a_gain[times >= ctx.a_end] = 0.0
    out[:len(a_part)] += a_part * a_gain[:, None]
    # B aligned on the junction, at A's rate
    b = ctx.b
    if ctx.b_sr != sr:
        g = math.gcd(ctx.b_sr, sr)
        b = signal.resample_poly(b, sr // g, ctx.b_sr // g, axis=0).astype(np.float32)
    b_start_t = ctx.junction_a - (ctx.junction_b - ctx.b_offset)  # set time of B's region start
    b_times = b_start_t + np.arange(len(b)) / sr
    b_pos = np.clip((b_times - ctx.junction_a) / fade_len, 0.0, 1.0)
    b_gain = np.where(b_times < ctx.junction_a, 0.0, np.sin(b_pos * math.pi / 2)).astype(np.float32)
    i0 = int(round((b_start_t - start_t) * sr))
    src0 = max(0, -i0)
    dst0 = max(0, i0)
    count = max(0, min(len(b) - src0, n - dst0))
    if count:
        out[dst0:dst0 + count] += b[src0:src0 + count] * b_gain[src0:src0 + count, None]
    from mastering import true_peak_limiter
    return true_peak_limiter(out, sr, ceiling_db=-1.0).astype(np.float32), sr


# ------------------------------------------------------------------ drawing layout (no audio)
def peak_envelope(data: np.ndarray, sr: int, t0: float = 0.0, step_s: float = 0.01) -> Dict:
    """Peak level of a stereo signal every step_s seconds: {'t0', 'dt', 'peak'} (for waveform drawings)."""
    data = np.asarray(data, dtype=np.float32)
    mono = np.max(np.abs(data), axis=1) if data.ndim == 2 and len(data) else np.abs(data.reshape(-1))
    hop = max(1, int(round(step_s * sr)))
    n = len(mono) // hop
    peak = mono[:n * hop].reshape(n, hop).max(axis=1) if n else np.zeros(0, dtype=np.float32)
    return {"t0": float(t0), "dt": hop / float(sr), "peak": peak.astype(np.float32)}


def _sample_length(path: str, sample_seconds: Optional[Callable[[str], Optional[float]]]) -> Optional[float]:
    if sample_seconds is not None:
        return sample_seconds(path)
    try:
        import soundfile as sf
        return float(sf.info(path).duration)
    except Exception:
        return None


def _layout_freeze(ctx: TransitionContext, fx: Dict, warnings: List[str]) -> Dict:
    cap = int(fx.get("capture_offset_beats", 0))
    capture_t = ctx.a_beat(cap)
    steps = fx.get("steps") or []
    blocks = []
    if steps:
        longest = max(float(s["beats"]) for s in steps)
        blocks.append({"start": ctx.a_beat(cap - longest), "end": capture_t, "kind": "source", "label": "captured"})
    t = capture_t
    for step in steps:
        seg = capture_t - ctx.a_beat(cap - float(step["beats"]))
        for _ in range(int(step["repeats"])):
            blocks.append({"start": t, "end": t + seg, "kind": "repeat", "label": f"{float(step['beats']):g}"})
            t += seg
    tail = float(fx.get("tail_beats", 0)) * ctx.a_period
    if tail > 0:
        blocks.append({"start": t, "end": t + tail, "kind": "tail", "label": "tail"})
    ctx.outro_start = capture_t
    ctx.junction_a = capture_t
    ctx.a_end = t + tail
    return {"type": "freeze", "label": "Freeze", "blocks": blocks}


def _layout_filter(ctx: TransitionContext, fx: Dict, warnings: List[str]) -> Dict:
    beats = int(fx["beats"])
    side = fx.get("side", "outgoing")
    release = float(fx.get("release_beats", 1))
    if side == "outgoing":
        start, sweep_end = ctx.a_beat(-beats), ctx.junction_a
        blocks = [{"start": start, "end": sweep_end, "kind": "sweep", "label": ""},
                  {"start": sweep_end, "end": ctx.a_end, "kind": "hold", "label": "held"}]
    elif side == "incoming":
        shift = ctx.junction_a - ctx.junction_b
        start, sweep_end = ctx.junction_b + shift, ctx.b_beat(beats) + shift
        blocks = [{"start": start, "end": sweep_end, "kind": "sweep", "label": ""}]
        if release > 0:
            blocks.append({"start": sweep_end, "end": sweep_end + release * median_period(ctx.b_beats), "kind": "release",
                           "label": "dry"})
    else:
        offset = int(fx.get("start_offset_beats", -4))
        start, sweep_end = ctx.a_beat(offset), ctx.a_beat(offset + beats)
        blocks = [{"start": start, "end": sweep_end, "kind": "sweep", "label": ""}]
        if release > 0:
            blocks.append({"start": sweep_end, "end": sweep_end + release * ctx.a_period, "kind": "release", "label": "dry"})
    lo, hi = float(fx["start_hz"]), float(fx["end_hz"])
    blocks[0]["label"] = f"{lo:.0f} → {hi:.0f} Hz"
    pos = np.linspace(0.0, 1.0, 24)
    hz = lo * (hi / lo) ** pos if fx.get("curve", "exponential") == "exponential" and lo > 0 else lo + (hi - lo) * pos
    track = {"outgoing": "A", "incoming": "B"}.get(side, "A+B")
    return {"type": "filter", "label": f"Filter {fx['kind']} ({track})",
            "blocks": blocks, "curve": [(float(start + p * (sweep_end - start)), float(h)) for p, h in zip(pos, hz)]}


def _layout_echo(ctx: TransitionContext, fx: Dict, warnings: List[str]) -> Dict:
    start, end = ctx.a_beat(int(fx.get("start_offset_beats", -4))), ctx.a_end
    blocks = []
    if end > start:
        blocks.append({"start": start, "end": end, "kind": "wet", "label": "echo"})
        feedback, delay = float(fx["feedback"]), float(fx["delay_beats"]) * ctx.a_period
        repeats = math.log(1e-3) / math.log(feedback) if 0.0 < feedback < 1.0 else 1.0
        tail = min(MAX_ECHO_TAIL_BEATS * ctx.a_period, repeats * delay) if float(fx["mix"]) > 0 else 0.0
        if tail > 0:
            blocks.append({"start": end, "end": end + tail, "kind": "tail", "label": "tail"})
    return {"type": "echo", "label": "Echo", "blocks": blocks}


def _layout_sample(ctx: TransitionContext, fx: Dict, warnings: List[str], sample_seconds=None) -> Dict:
    path = fx.get("file") or ""
    repeats = int(fx.get("repeats", 1))
    lane = {"type": "sample", "label": f"Sample ×{repeats}" if repeats > 1 else "Sample", "blocks": []}
    length = _sample_length(path, sample_seconds) if path else None
    if not length:
        lane["note"] = "choose a sample" if not path else "sample not found"
        return lane
    name = os.path.basename(path)
    ratio, _, problem = sample_tempo(fx, ctx.a_local_bpm())
    if problem:
        warnings.append(N_("{name}: {problem}").format(name=name, problem=problem))
    one = length / ratio if fx.get("tempo", "varispeed") != "off" else length
    fit = max(1, int(MAX_REPEATED_SAMPLE_SECONDS // max(one, 1e-6)))
    if repeats > fit:
        warnings.append(N_("{name}: {repeats} repeats would last more than {seconds:.0f} s, reduced to {fit}").format(
            name=name, repeats=repeats, seconds=MAX_REPEATED_SAMPLE_SECONDS, fit=fit))
        repeats = fit
    total = one * repeats
    anchor_t = ctx.a_beat(float(fx.get("offset_beats", 0.0)))
    anchor = fx.get("anchor", "end_at_junction")
    start = anchor_t - total if anchor == "end_at_junction" else (anchor_t - total / 2.0 if anchor == "center_on_junction" else anchor_t)
    label = os.path.splitext(name)[0]
    lane["blocks"] = [{"start": start + k * one, "end": start + (k + 1) * one, "kind": "sample", "label": label if k == 0 else ""}
                      for k in range(repeats)]
    return lane


def _layout_scratch(ctx: TransitionContext, fx: Dict, warnings: List[str]) -> Dict:
    lane = {"type": "scratch", "label": "Scratch", "blocks": []}
    start, end = _scratch_span(ctx, fx)
    if fx.get("side", "outgoing") != "outgoing":
        shift = ctx.junction_a - ctx.junction_b
        start, end = start + shift, end + shift
    try:
        plan = scratch_plan(fx.get("sequence") or "", end - start, 200, fx.get("ramp", "exponential"))
    except ValueError as exc:
        lane["note"] = str(exc)
        return lane
    warnings.extend(plan["warnings"])
    for step in plan["steps"]:
        lane["blocks"].append({"start": start + step["start"], "end": start + step["end"],
                               "kind": "scratch_down" if step["kind"] == "d" else "scratch_up", "label": step["text"]})
    if plan["catch_up_speed"] is not None:
        lane["blocks"].append({"start": start + plan["sequence_end"], "end": end, "kind": "catchup",
                               "label": f"×{plan['catch_up_speed']:.2f}"})
    lane["catch_up_speed"] = plan["catch_up_speed"]
    return lane


def transition_layout(a_beats: Sequence[float], b_beats: Sequence[float], a_outro_start: float, a_outro_end: float,
                      b_intro_start: float, effects: Sequence[Dict], nudge_ms: float = 0.0,
                      sample_seconds: Optional[Callable[[str], Optional[float]]] = None, length: str = "short") -> Dict:
    """
    Where things happen in a transition, without audio, by the rules of apply_effects / preview_mix. Times are in
    seconds of track A (B is drawn shifted by 'b_shift'): junction, planned_junction (before a freeze), a_end,
    fade_len, period, beat_times [(t, beats from the junction)], view (start, stop), preview_start (where the
    preview clip starts), lanes (one per enabled effect, in stack order: type, label, blocks [start, end, kind,
    label], optional curve [(t, Hz)] and note) and warnings.
    """
    empty = np.zeros((0, 2), dtype=np.float32)
    nudge = float(nudge_ms) / 1000.0
    junction_a = float(a_beats[nearest_beat_index(a_beats, a_outro_start)]) + nudge
    junction_b = float(b_beats[nearest_beat_index(b_beats, b_intro_start)]) + nudge
    ctx = TransitionContext(a=empty, a_sr=1, a_offset=0.0, a_beats=list(a_beats), junction_a=junction_a,
                            a_end=max(junction_a, float(a_outro_end) + nudge), b=empty, b_sr=1, b_offset=0.0,
                            b_beats=list(b_beats), junction_b=junction_b, outro_start=junction_a)
    enabled = [(i, dict(new_effect(fx["type"]), **fx)) for i, fx in enumerate(effects or [])
               if fx.get("enabled", True) and fx.get("type") in FX_TYPES]
    freezes = [item for item in enabled if item[1]["type"] == "freeze"][:1]
    ordered = freezes + [item for item in enabled if item[1]["type"] != "freeze"]
    warnings: List[str] = []
    lanes = {}
    for i, fx in ordered:
        if fx["type"] == "sample":
            lanes[i] = _layout_sample(ctx, fx, warnings, sample_seconds)
        else:
            lanes[i] = {"freeze": _layout_freeze, "filter": _layout_filter, "echo": _layout_echo,
                        "scratch": _layout_scratch}[fx["type"]](ctx, fx, warnings)
    period = ctx.a_period
    if length == "long":
        view = (ctx.junction_a - 20.0, max(ctx.junction_a + 10.0, ctx.a_end + 2.0))
    else:
        view = (ctx.a_beat(-8), ctx.a_end + 8 * period)
    preview_start = max(view[0], max(0.0, junction_a - 45.0))
    spans = [(b["start"], b["end"]) for lane in lanes.values() for b in lane["blocks"]]
    view = (min([view[0]] + [s for s, _ in spans]) , max([view[1]] + [e for _, e in spans]))
    shift = ctx.junction_a - ctx.junction_b
    beat_times = []
    for k in range(-128, 129):
        t = ctx.a_beat(k) if k <= 0 else ctx.b_beat(k) + shift
        if view[0] - period <= t <= view[1] + period:
            beat_times.append((float(t), k))
    return {"junction": ctx.junction_a, "planned_junction": junction_a, "a_end": ctx.a_end,
            "fade_len": max(1e-3, ctx.a_end - ctx.junction_a), "b_shift": shift, "period": period,
            "beat_times": beat_times, "view": view, "preview_start": preview_start,
            "lanes": [lanes[i] for i in sorted(lanes)], "warnings": warnings}
