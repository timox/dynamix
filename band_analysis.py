#!/usr/bin/env python3
"""
Band-wise signal tracking, low-mid masking and resonance detection.

Mixing by bands is about giving each frequency region room to breathe. This
module measures, per track:

- band envelopes over time (RMS per band, attack ~10 ms, release tied to the
  tempo) so you can see whether a band pulses with the beat or stays full;
- how much the 200-500 Hz "mud" band exceeds its neighbours (60-120 Hz and
  1-3 kHz) over time: the masking map, with the share of time it builds up;
- resonances: narrow spectral peaks between 100 and 800 Hz that persist over
  the track, with frequency, prominence and Q, turned into EQ suggestions.

These are diagnostics for the mix stage: a pre-master pass can level a set,
it cannot un-mask a low-mid build-up between elements.
"""

import os
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import signal
from scipy.ndimage import median_filter, maximum_filter1d

BANDS: List[Tuple[str, float, float]] = [
    ("sub", 20, 60), ("low", 60, 120), ("low_mid", 120, 200), ("mud", 200, 500),
    ("mid", 500, 2000), ("high_mid", 2000, 6000), ("high", 6000, 20000),
]
BAND_LABELS = {"sub": "20-60", "low": "60-120", "low_mid": "120-200", "mud": "200-500",
               "mid": "0.5-2k", "high_mid": "2-6k", "high": "6k+"}

ENVELOPE_HOP_S = 0.01           # 10 ms envelope resolution
RESONANCE_RANGE = (100.0, 800.0)
RESONANCE_MIN_PROMINENCE_DB = 5.0
RESONANCE_MIN_Q = 3.0
RESONANCE_MIN_PERSISTENCE = 0.6  # share of segments where the peak is present


def _band_sos(fs: float, lo: float, hi: float, order: int = 4):
    nyq = fs / 2
    hi = min(hi, nyq * 0.98)
    if lo <= 20:
        return signal.butter(order, hi / nyq, btype="low", output="sos")
    if hi >= nyq * 0.98:
        return signal.butter(order, lo / nyq, btype="high", output="sos")
    return signal.butter(order, [lo / nyq, hi / nyq], btype="band", output="sos")


def _follow(rms: np.ndarray, hop_s: float, attack_s: float, release_s: float) -> np.ndarray:
    """Envelope follower: fast attack, tempo-related release (peak-hold style)."""
    a_coef = float(np.exp(-hop_s / max(attack_s, 1e-4)))
    r_coef = float(np.exp(-hop_s / max(release_s, 1e-4)))
    out = np.empty_like(rms)
    env = 0.0
    for i, v in enumerate(rms):
        env = a_coef * env + (1 - a_coef) * v if v > env else r_coef * env + (1 - r_coef) * v
        out[i] = env
    return out


def band_envelopes(y: np.ndarray, fs: float, bpm: Optional[float] = None,
                   hop_s: float = ENVELOPE_HOP_S) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    """Per-band RMS envelopes in dBFS, followed with attack 10 ms / release half a beat."""
    mono = y.mean(axis=1) if y.ndim == 2 else y
    hop = max(1, int(hop_s * fs))
    n_frames = len(mono) // hop
    times = np.arange(n_frames) * hop_s
    release = (60.0 / bpm) / 4 if bpm and bpm > 0 else 0.12  # a quarter beat: shows the ducking, not the notes
    envelopes = {}
    for name, lo, hi in BANDS:
        filtered = signal.sosfilt(_band_sos(fs, lo, hi), mono)
        frames = filtered[:n_frames * hop].reshape(n_frames, hop)
        rms = np.sqrt(np.mean(frames ** 2, axis=1))
        env = _follow(rms, hop_s, 0.010, release)
        envelopes[name] = 20 * np.log10(np.maximum(env, 1e-6))
    return times, envelopes


def beat_modulation(env_db: np.ndarray, hop_s: float, bpm: Optional[float]) -> float:
    """How strongly a band pulses at the beat rate (0 = flat, 1 = fully modulated)."""
    if not bpm or bpm <= 0 or len(env_db) < 64:
        return 0.0
    x = env_db - np.mean(env_db)
    x = x * np.hanning(len(x))
    spec = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(len(x), d=hop_s)
    beat_hz = bpm / 60.0
    band = (freqs >= beat_hz * 0.9) & (freqs <= beat_hz * 1.1)
    if not np.any(band):
        return 0.0
    peak = float(np.max(spec[band]))
    ref = float(np.std(env_db)) * len(x) / 2 + 1e-9  # what a pure sine of that std would give
    return float(min(1.0, peak / ref))


def masking_timeline(envelopes: Dict[str, np.ndarray]) -> np.ndarray:
    """dB by which the 200-500 Hz band exceeds the average of its neighbours (60-120 Hz, 0.5-2 kHz)."""
    neighbours = (envelopes["low"] + envelopes["mid"]) / 2
    return envelopes["mud"] - neighbours


def detect_resonances(y: np.ndarray, fs: float, n_segments: int = 8, return_spectrum: bool = False):
    """
    Narrow, persistent peaks of the long-term spectrum between 100 and 800 Hz.
    Returns [{freq_hz, prominence_db, q, persistence}] sorted by prominence
    (and, with return_spectrum, the (freqs, residual_db) used).
    """
    mono = (y.mean(axis=1) if y.ndim == 2 else y).astype(np.float64)
    nperseg = 16384 if fs >= 40000 else 8192
    if len(mono) < nperseg * 2:
        return ([], (np.array([]), np.array([]))) if return_spectrum else []
    freqs, psd = signal.welch(mono, fs=fs, nperseg=nperseg)
    lo, hi = RESONANCE_RANGE
    sel = (freqs >= lo * 0.7) & (freqs <= hi * 1.4)
    f = freqs[sel]
    spec_db = 10 * np.log10(psd[sel] + 1e-20)
    # spectral envelope: median over about 1/3 octave, evaluated in log-frequency by a growing window
    envelope = np.empty_like(spec_db)
    for i, fi in enumerate(f):
        half = fi * (2 ** (1 / 6) - 1)  # +-1/6 octave
        window = (f >= fi - half) & (f <= fi + half)
        envelope[i] = np.median(spec_db[window])
    residual = spec_db - envelope
    peaks, props = signal.find_peaks(residual, prominence=RESONANCE_MIN_PROMINENCE_DB, width=1)
    if len(peaks) == 0:
        return ([], (f, residual)) if return_spectrum else []
    widths_bins = signal.peak_widths(residual, peaks, rel_height=0.5)[0]
    df = float(f[1] - f[0])
    # persistence: the same bin exceeds +4 dB in most time segments
    seg_len = len(mono) // n_segments
    seg_residuals = []
    for k in range(n_segments):
        seg = mono[k * seg_len:(k + 1) * seg_len]
        if len(seg) < nperseg:
            continue
        _, p = signal.welch(seg, fs=fs, nperseg=nperseg)
        s_db = 10 * np.log10(p[sel] + 1e-20)
        seg_residuals.append(s_db - envelope)
    seg_residuals = np.asarray(seg_residuals) if seg_residuals else np.empty((0, len(f)))
    results = []
    for idx, prom, width in zip(peaks, props["prominences"], widths_bins):
        freq = float(f[idx])
        if not (lo <= freq <= hi):
            continue
        bandwidth = max(width * df, df)
        q = freq / bandwidth
        if q < RESONANCE_MIN_Q:
            continue
        if len(seg_residuals):
            near = slice(max(0, idx - 1), idx + 2)
            persistence = float(np.mean(np.max(seg_residuals[:, near], axis=1) > 4.0))
        else:
            persistence = 1.0
        if persistence < RESONANCE_MIN_PERSISTENCE:
            continue
        results.append({"freq_hz": round(freq, 1), "prominence_db": round(float(prom), 1),
                        "q": round(float(q), 1), "persistence": round(persistence, 2)})
    results.sort(key=lambda r: -r["prominence_db"])
    return (results[:6], (f, residual)) if return_spectrum else results[:6]


def analyze_bands(path: str, bpm: Optional[float] = None, audio: Optional[Tuple[np.ndarray, int]] = None) -> Dict:
    """Full band analysis of one file. bpm (if known) sets the release time and the beat-modulation check."""
    if audio is None:
        import soundfile as sf
        y, fs = sf.read(path, dtype="float32", always_2d=True)
    else:
        y, fs = audio
    if bpm is None:
        try:
            import librosa
            mono = y.mean(axis=1)
            tempo, _ = librosa.beat.beat_track(y=mono[: int(fs * 120)], sr=fs)
            bpm = float(np.atleast_1d(tempo)[0])
        except Exception:
            bpm = None
    times, envs = band_envelopes(y, fs, bpm)
    masking = masking_timeline(envs)
    stats = {}
    for name, _, _ in BANDS:
        e = envs[name]
        stats[name] = {
            "mean_db": round(float(np.mean(e)), 1),
            "range_db": round(float(np.percentile(e, 90) - np.percentile(e, 10)), 1),
            "beat_modulation": round(beat_modulation(e, ENVELOPE_HOP_S, bpm), 2),
        }
    excess_median = float(np.median(masking))
    over = float(np.mean(masking > excess_median + 6.0))
    mud = {
        "excess_median_db": round(excess_median, 1),
        "excess_p90_db": round(float(np.percentile(masking, 90)), 1),
        "buildup_share": round(over, 2),           # share of time > median + 6 dB
        "range_db": stats["mud"]["range_db"],
        "beat_modulation": stats["mud"]["beat_modulation"],
    }
    resonances, (spec_f, spec_res) = detect_resonances(y, fs, return_spectrum=True)

    # downsample for charts (~4 points per second; spectrum limited to 100-800 Hz)
    step = max(1, int(0.25 / ENVELOPE_HOP_S))
    keep = (spec_f >= RESONANCE_RANGE[0]) & (spec_f <= RESONANCE_RANGE[1]) if len(spec_f) else np.array([], dtype=bool)
    chart = {"times": [round(float(t), 2) for t in times[::step]],
             "bands": {name: [round(float(v), 1) for v in envs[name][::step]] for name in ("low", "mud", "mid")},
             "masking": [round(float(v), 1) for v in masking[::step]],
             "spectrum_hz": [round(float(v), 1) for v in spec_f[keep]],
             "spectrum_residual_db": [round(float(v), 1) for v in spec_res[keep]]}

    flags, suggestions = [], []
    if mud["beat_modulation"] < 0.15 and stats["low"]["beat_modulation"] > 0.3:
        flags.append("200-500 Hz does not breathe with the beat: sidechain or dynamic EQ on the low mids")
    if mud["excess_p90_db"] - mud["excess_median_db"] > 6:
        flags.append(f"low-mid build-up +{mud['excess_p90_db'] - mud['excess_median_db']:.0f} dB for {mud['buildup_share'] * 100:.0f}% of the time: "
                     "masking between elements, needs dynamic control")
    if mud["excess_median_db"] > 3:
        flags.append(f"200-500 Hz {mud['excess_median_db']:+.0f} dB above its neighbours: static excess, fixed cut or high-pass the wide elements")
    strong = [r for r in resonances if r["prominence_db"] >= 8]
    if strong:
        flags.append("persistent resonances: " + ", ".join(f"{r['freq_hz']:.0f} Hz" for r in strong[:3]))
    for r in resonances[:3]:
        gain = -min(6.0, max(2.0, r["prominence_db"] * 0.5))
        suggestions.append(f"cut {abs(gain):.0f} dB at {r['freq_hz']:.0f} Hz, Q {min(r['q'], 12):.0f} (+{r['prominence_db']:.0f} dB, {r['persistence'] * 100:.0f}% of the time)")
    # verdict: these problems live in the mix, a pre-master pass cannot fix them
    verdict = "mix" if flags else "ok"
    return {
        "file_path": path, "filename": os.path.basename(path), "bpm": bpm, "sample_rate": int(fs),
        "release_s": round((60.0 / bpm) / 4 if bpm else 0.12, 3),
        "stats": stats, "mud": mud, "resonances": resonances, "chart": chart,
        "flags": flags, "eq_suggestions": suggestions, "verdict": verdict,
    }


def mix_recommendation(bands: Optional[Dict], mastering: Optional[Dict]) -> Tuple[str, List[str]]:
    """
    ('premaster' | 'mix' | 'ok', reasons): what the track needs.
    Mastering flags a pre-master pass repairs (level, peaks, DC, polarity, bass phase, mono bass)
    count as 'premaster'; band flags and comb filtering count as 'mix'.
    """
    reasons_mix, reasons_pm = [], []
    for f in (bands or {}).get("flags") or []:
        reasons_mix.append(f)
    for f in (mastering or {}).get("flags") or []:
        low = f.lower()
        if "comb" in low or "very dark" in low or "very harsh" in low:
            reasons_mix.append(f)
        else:
            reasons_pm.append(f)
    if reasons_mix:
        return "mix", reasons_mix + reasons_pm
    if reasons_pm:
        return "premaster", reasons_pm
    return "ok", []


def format_recommendation(kind: str, reasons: List[str]) -> str:
    if kind == "mix":
        return "MIX REVISION RECOMMENDED: " + "; ".join(reasons[:4])
    if kind == "premaster":
        return "pre-master pass is enough: " + "; ".join(reasons[:4])
    return "nothing to fix"


def analyze_bands_cached(path: str, bpm: Optional[float] = None) -> Dict:
    from analysis_store import get_store
    store = get_store()
    cached = store.get(path, "bands")
    if cached is not None:
        return cached
    report = analyze_bands(path, bpm)
    store.put(path, "bands", report)
    return report


def format_band_report(report: Dict) -> str:
    lines = [f"{report['filename']}  ({report['bpm']:.0f} BPM, release {report['release_s'] * 1000:.0f} ms)" if report.get("bpm")
             else f"{report['filename']}"]
    lines.append("    band      level   range  pulse")
    for name, _, _ in BANDS:
        st = report["stats"][name]
        lines.append(f"    {BAND_LABELS[name]:8s} {st['mean_db']:6.1f}  {st['range_db']:5.1f}  {st['beat_modulation']:.2f}")
    m = report["mud"]
    lines.append(f"    200-500 Hz vs neighbours: {m['excess_median_db']:+.1f} dB typical, {m['excess_p90_db']:+.1f} dB at worst, "
                 f"build-up {m['buildup_share'] * 100:.0f}% of the time, pulse {m['beat_modulation']:.2f}")
    if report["resonances"]:
        lines.append("    resonances: " + ", ".join(f"{r['freq_hz']:.0f} Hz (+{r['prominence_db']:.0f} dB, Q {r['q']:.0f})" for r in report["resonances"]))
    else:
        lines.append("    resonances: none persistent between 100 and 800 Hz")
    for f in report["flags"]:
        lines.append(f"    ! {f}")
    for s in report["eq_suggestions"]:
        lines.append(f"    EQ: {s}")
    lines.append("    -> " + ("MIX REVISION RECOMMENDED (a pre-master pass cannot fix this)" if report.get("verdict") == "mix" else "low mids OK"))
    return "\n".join(lines)


def format_band_summary(reports: List[Dict]) -> str:
    lines = ["BAND ANALYSIS (signal tracking per band, low-mid masking, resonances)", "-" * 60]
    for r in reports:
        lines.append(format_band_report(r) if "error" not in r else f"{r['filename']}: {r['error']}")
        lines.append("")
    lines.append("Level in dBFS (band RMS, envelope-followed); range = 10th-90th percentile of the envelope;")
    lines.append("pulse = modulation at the beat rate (0 flat, 1 fully pumping). These are mix-stage diagnostics:")
    lines.append("the pre-master pass levels the set but cannot un-mask a low-mid build-up between elements.")
    return "\n".join(lines)
