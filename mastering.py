#!/usr/bin/env python3
"""
Mastering check and pre-master pass for DynaMix.

Badly mastered collections (levels all over the place, clipping, crushed
dynamics, muddy or harsh tone) make automatic transitions sound uneven even
when the DJ software applies ReplayGain, because ReplayGain only fixes the
average level. This module:

- measures each track the way mastering engineers do: integrated loudness
  (LUFS, ITU-R BS.1770 K-weighting with gating), loudness range, true peak
  (4x oversampled), sample clipping, DC offset, spectral balance;
- turns the numbers into plain-language flags ("clipping", "over-compressed",
  "too quiet", "muddy"...) and a 0-100 health score;
- can write corrected COPIES of the tracks into another folder: loudness
  normalised to a common target, optional gentle tone matching towards the
  playlist average, DC removal and a true-peak limiter. The originals are
  never modified.

No FFmpeg needed: decoding and encoding go through soundfile/libsndfile
(WAV, FLAC, OGG, MP3).

Usage:
    python mastering.py check  "C:\\Music\\Set"                # report
    python mastering.py check  track.mp3 other.mp3 --json report.json
    python mastering.py fix    "C:\\Music\\Set" --out "C:\\Music\\Set_premastered"
    python mastering.py fix    set.m3u --out out_dir --lufs -14 --tone --format flac
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import minimum_filter1d

try:  # numba ships with librosa; the limiter loop is much faster with it
    from numba import njit
except Exception:  # pragma: no cover - numba missing
    def njit(*args, **kwargs):
        def wrap(fn):
            return fn
        return wrap if not (args and callable(args[0])) else args[0]

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.ogg', '.aiff', '.aif', '.m4a', '.aac'}


# ============================================================ filters (RBJ biquads)
def _biquad_high_shelf(fs: float, fc: float, gain_db: float, q: float = 1 / np.sqrt(2)):
    a = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * fc / fs
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)
    b0 = a * ((a + 1) + (a - 1) * cos_w0 + 2 * np.sqrt(a) * alpha)
    b1 = -2 * a * ((a - 1) + (a + 1) * cos_w0)
    b2 = a * ((a + 1) + (a - 1) * cos_w0 - 2 * np.sqrt(a) * alpha)
    a0 = (a + 1) - (a - 1) * cos_w0 + 2 * np.sqrt(a) * alpha
    a1 = 2 * ((a - 1) - (a + 1) * cos_w0)
    a2 = (a + 1) - (a - 1) * cos_w0 - 2 * np.sqrt(a) * alpha
    return np.array([b0, b1, b2]) / a0, np.array([1.0, a1 / a0, a2 / a0])


def _biquad_low_shelf(fs: float, fc: float, gain_db: float, q: float = 1 / np.sqrt(2)):
    a = 10 ** (gain_db / 40.0)
    w0 = 2 * np.pi * fc / fs
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)
    b0 = a * ((a + 1) - (a - 1) * cos_w0 + 2 * np.sqrt(a) * alpha)
    b1 = 2 * a * ((a - 1) - (a + 1) * cos_w0)
    b2 = a * ((a + 1) - (a - 1) * cos_w0 - 2 * np.sqrt(a) * alpha)
    a0 = (a + 1) + (a - 1) * cos_w0 + 2 * np.sqrt(a) * alpha
    a1 = -2 * ((a - 1) + (a + 1) * cos_w0)
    a2 = (a + 1) + (a - 1) * cos_w0 - 2 * np.sqrt(a) * alpha
    return np.array([b0, b1, b2]) / a0, np.array([1.0, a1 / a0, a2 / a0])


def _biquad_high_pass(fs: float, fc: float, q: float = 0.5):
    w0 = 2 * np.pi * fc / fs
    alpha = np.sin(w0) / (2 * q)
    cos_w0 = np.cos(w0)
    b0 = (1 + cos_w0) / 2
    b1 = -(1 + cos_w0)
    b2 = (1 + cos_w0) / 2
    a0 = 1 + alpha
    a1 = -2 * cos_w0
    a2 = 1 - alpha
    return np.array([b0, b1, b2]) / a0, np.array([1.0, a1 / a0, a2 / a0])


def k_weight(x: np.ndarray, fs: float) -> np.ndarray:
    """ITU-R BS.1770 K-weighting: +4 dB high shelf at 1.5 kHz then 38 Hz high-pass."""
    b1, a1 = _biquad_high_shelf(fs, 1500.0, 4.0)
    b2, a2 = _biquad_high_pass(fs, 38.0, 0.5)
    y = signal.lfilter(b1, a1, x, axis=0)
    return signal.lfilter(b2, a2, y, axis=0)


# ============================================================ loudness (BS.1770 / EBU R128)
def _block_loudness(x: np.ndarray, fs: float, block_s: float, hop_s: float) -> np.ndarray:
    """Loudness (LKFS) of overlapping blocks of a K-weighted multichannel signal."""
    n_block = int(block_s * fs)
    n_hop = int(hop_s * fs)
    if len(x) < n_block:
        x = np.pad(x, ((0, n_block - len(x)), (0, 0)))
    n_blocks = 1 + (len(x) - n_block) // n_hop
    weights = np.ones(x.shape[1])
    if x.shape[1] >= 5:  # surround: +1.5 dB on Ls/Rs (channels 3 and 4)
        weights[3:5] = 10 ** (1.5 / 10)
    power = np.empty(n_blocks)
    sq = x.astype(np.float64) ** 2
    csum = np.concatenate([np.zeros((1, x.shape[1])), np.cumsum(sq, axis=0)])
    for i in range(n_blocks):
        start = i * n_hop
        mean_sq = (csum[start + n_block] - csum[start]) / n_block
        power[i] = float(np.sum(weights * mean_sq))
    return -0.691 + 10 * np.log10(np.maximum(power, 1e-20))


def integrated_loudness(x: np.ndarray, fs: float) -> float:
    """Integrated loudness in LUFS with absolute (-70) and relative (-10 LU) gating."""
    x = x if x.ndim == 2 else x[:, None]
    blocks = _block_loudness(k_weight(x, fs), fs, 0.4, 0.1)
    gated = blocks[blocks > -70.0]
    if len(gated) == 0:
        return -np.inf
    mean_power = np.mean(10 ** ((gated + 0.691) / 10))
    relative_gate = -0.691 + 10 * np.log10(mean_power) - 10.0
    gated = gated[gated > relative_gate]
    if len(gated) == 0:
        return -np.inf
    return float(-0.691 + 10 * np.log10(np.mean(10 ** ((gated + 0.691) / 10))))


def loudness_range(x: np.ndarray, fs: float) -> float:
    """EBU R128 loudness range (LU) from 3 s short-term blocks."""
    x = x if x.ndim == 2 else x[:, None]
    blocks = _block_loudness(k_weight(x, fs), fs, 3.0, 1.0)
    gated = blocks[blocks > -70.0]
    if len(gated) < 2:
        return 0.0
    mean_power = np.mean(10 ** ((gated + 0.691) / 10))
    relative_gate = -0.691 + 10 * np.log10(mean_power) - 20.0
    gated = gated[gated > relative_gate]
    if len(gated) < 2:
        return 0.0
    return float(np.percentile(gated, 95) - np.percentile(gated, 10))


def true_peak_db(x: np.ndarray, fs: float, oversample: int = 4) -> float:
    """True peak in dBTP (4x oversampled)."""
    up = signal.resample_poly(x, oversample, 1, axis=0)
    peak = float(np.max(np.abs(up))) if len(up) else 0.0
    return 20 * np.log10(max(peak, 1e-9))


# ============================================================ analysis
BANDS = [('sub', 20, 60), ('low', 60, 250), ('low_mid', 250, 800), ('mid', 800, 2500),
         ('high_mid', 2500, 6000), ('high', 6000, 20000)]

# Reference balance (share of total energy, in dB relative to total) for a
# typical well-balanced club master. Only used for the tone flags/matching.
REFERENCE_BALANCE_DB = {'sub': -7.0, 'low': -3.0, 'low_mid': -7.0, 'mid': -10.0, 'high_mid': -15.0, 'high': -20.0}


def spectral_balance(x: np.ndarray, fs: float) -> Dict[str, float]:
    """Energy share of each band in dB relative to the total (average of the channel spectra)."""
    x2 = x if x.ndim == 2 else x[:, None]
    freqs, psd = signal.welch(x2, fs=fs, nperseg=4096, axis=0)
    psd = psd.mean(axis=1)
    total = float(np.sum(psd)) + 1e-20
    balance = {}
    for name, lo, hi in BANDS:
        mask = (freqs >= lo) & (freqs < min(hi, fs / 2))
        balance[name] = float(10 * np.log10(max(float(np.sum(psd[mask])) / total, 1e-12)))
    return balance


def _bandpass(x: np.ndarray, fs: float, lo: Optional[float], hi: Optional[float]) -> np.ndarray:
    nyq = fs / 2
    if lo and hi:
        sos = signal.butter(4, [lo / nyq, min(hi, nyq * 0.99) / nyq], btype='band', output='sos')
    elif lo:
        sos = signal.butter(4, lo / nyq, btype='high', output='sos')
    else:
        sos = signal.butter(4, min(hi, nyq * 0.99) / nyq, btype='low', output='sos')
    return signal.sosfiltfilt(sos, x, axis=0)


def _blockwise_correlation(left: np.ndarray, right: np.ndarray, fs: float, block_s: float = 0.4) -> np.ndarray:
    """Pearson correlation of L/R per block, skipping near-silent blocks."""
    n = int(block_s * fs)
    corrs = []
    for start in range(0, len(left) - n + 1, n):
        l_blk = left[start:start + n]
        r_blk = right[start:start + n]
        energy = float(np.mean(l_blk ** 2) + np.mean(r_blk ** 2))
        if energy < 1e-7:
            continue
        denom = float(np.sqrt(np.sum(l_blk ** 2) * np.sum(r_blk ** 2)))
        if denom <= 0:
            continue
        corrs.append(float(np.sum(l_blk * r_blk) / denom))
    return np.asarray(corrs) if corrs else np.asarray([1.0])


def analyze_phase(x: np.ndarray, fs: float) -> Dict:
    """
    Stereo phase / mono-compatibility analysis:
    - overall and low-band (< 150 Hz) L/R correlation (+1 in phase, 0 uncorrelated, -1 inverted)
    - mono fold-down loss in dB (energy of (L+R)/2 versus the average channel energy)
    - comb-filtering detection on the long-term spectrum (a delayed copy mixed in
      produces a regular ripple, typical of a mis-aligned double track or a bad
      stereo widener). Returns the estimated delay when found.
    """
    result = {'stereo': x.ndim == 2 and x.shape[1] >= 2, 'correlation': 1.0, 'correlation_low': 1.0,
              'correlation_high': 1.0, 'correlation_p10': 1.0, 'mono_loss_db': 0.0, 'comb_delay_ms': None,
              'comb_strength': 0.0, 'flags': []}
    mono = x.mean(axis=1) if x.ndim == 2 else x
    if result['stereo']:
        left = x[:, 0].astype(np.float64)
        right = x[:, 1].astype(np.float64)
        corr = _blockwise_correlation(left, right, fs)
        result['correlation'] = float(np.median(corr))
        result['correlation_p10'] = float(np.percentile(corr, 10))
        low_l = _bandpass(left, fs, None, 150.0)
        low_r = _bandpass(right, fs, None, 150.0)
        result['correlation_low'] = float(np.median(_blockwise_correlation(low_l, low_r, fs)))
        high_l = _bandpass(left, fs, 1000.0, None)
        high_r = _bandpass(right, fs, 1000.0, None)
        result['correlation_high'] = float(np.median(_blockwise_correlation(high_l, high_r, fs)))
        e_avg = 0.5 * (float(np.mean(left ** 2)) + float(np.mean(right ** 2))) + 1e-20
        e_mono = float(np.mean(((left + right) / 2) ** 2)) + 1e-20
        result['mono_loss_db'] = float(10 * np.log10(e_mono / e_avg))

        # whole signal inverted: bass AND highs both anti-correlated
        if result['correlation_low'] < -0.5 and result['correlation_high'] < -0.5:
            result['flags'].append(f"polarity inverted between channels (correlation {result['correlation']:+.2f})")
        elif result['correlation_low'] < 0.3:
            result['flags'].append(f"bass out of phase: low end cancels in mono (correlation {result['correlation_low']:+.2f} below 150 Hz)")
        if result['mono_loss_db'] < -3.0 and result['correlation'] >= -0.5:
            result['flags'].append(f"poor mono compatibility ({result['mono_loss_db']:.1f} dB lost in mono)")
        if -0.5 <= result['correlation'] < 0.2 and not result['flags']:
            result['flags'].append(f"very wide / phasey stereo image (correlation {result['correlation']:+.2f})")

    # comb filtering: a delayed copy leaves evenly spaced notches over the WHOLE
    # spectrum. Pitched harmonics also look periodic, so only the 1.5-8 kHz band
    # (hi-hats, noise, air) is used and the same delay must show up in both
    # halves of the track.
    def _comb_delay(segment: np.ndarray):
        if len(segment) < fs * 2:
            return None, 0.0
        freqs, psd = signal.welch(segment, fs=fs, nperseg=8192)
        band = (freqs >= 1500) & (freqs <= min(8000, fs / 2 - 1))
        if np.sum(band) < 128:
            return None, 0.0
        log_spec = 10 * np.log10(psd[band] + 1e-20)
        smooth = signal.savgol_filter(log_spec, 101, 2)
        ripple = log_spec - smooth
        ripple -= ripple.mean()
        spectrum = np.abs(np.fft.rfft(ripple * np.hanning(len(ripple))))
        df = float(freqs[1] - freqs[0])
        quef = np.fft.rfftfreq(len(ripple), d=df)  # seconds of delay
        valid = (quef >= 0.0002) & (quef <= 0.01)
        if not np.any(valid):
            return None, 0.0
        idx = int(np.argmax(spectrum[valid]))
        floor = float(np.median(spectrum[valid])) + 1e-9
        strength = float(spectrum[valid][idx]) / floor
        delay = float(quef[valid][idx])
        # the ripple of a comb filter has harmonics at 2d, 3d...: prefer the fundamental
        for divisor in (3, 2):
            sub = delay / divisor
            near = valid & (np.abs(quef - sub) <= 1.5 * (quef[1] - quef[0]))
            if np.any(near) and float(np.max(spectrum[near])) > 0.4 * float(spectrum[valid][idx]):
                delay = sub
                break
        return delay * 1000, strength if float(np.std(ripple)) > 1.0 else 0.0

    half = len(mono) // 2
    d1, s1 = _comb_delay(mono[:half])
    d2, s2 = _comb_delay(mono[half:])
    result['comb_strength'] = float(min(s1, s2))
    if d1 and d2 and s1 > 6.0 and s2 > 6.0 and abs(d1 - d2) <= 0.1 * max(d1, d2):
        result['comb_delay_ms'] = float((d1 + d2) / 2)
        result['flags'].append(f"comb filtering / phase cancellation (delay about {result['comb_delay_ms']:.2f} ms)")
    return result


def load_audio(path: str) -> Tuple[np.ndarray, int]:
    """Load any supported file as float32 (n, channels)."""
    x, fs = sf.read(path, dtype='float32', always_2d=True)
    return x, int(fs)


def analyze_mastering(path: str, audio: Optional[Tuple[np.ndarray, int]] = None) -> Dict:
    """Measure one track and derive flags and a 0-100 health score."""
    x, fs = audio if audio is not None else load_audio(path)
    duration = len(x) / fs

    lufs = integrated_loudness(x, fs)
    lra = loudness_range(x, fs)
    tp = true_peak_db(x, fs)
    sample_peak = float(np.max(np.abs(x))) if len(x) else 0.0
    clipped = np.abs(x) >= 0.999
    clip_ratio = float(np.mean(clipped)) if len(x) else 0.0
    # runs of >= 3 consecutive clipped samples on any channel = real clipping
    runs = 0
    if len(x) >= 3:
        any_clip = np.any(clipped, axis=1).astype(np.int8)
        run3 = any_clip[:-2] & any_clip[1:-1] & any_clip[2:]
        runs = int(np.sum(np.diff(np.concatenate([[0], run3])) == 1))
    dc = float(np.max(np.abs(np.mean(x, axis=0)))) if len(x) else 0.0
    plr = tp - lufs if np.isfinite(lufs) else 0.0
    balance = spectral_balance(x, fs)
    tilt = balance['low'] - balance['high_mid']  # positive = dark/heavy, negative = bright/harsh
    ref_tilt = REFERENCE_BALANCE_DB['low'] - REFERENCE_BALANCE_DB['high_mid']

    flags = []
    score = 100.0
    if runs > 0 or clip_ratio > 1e-4:
        flags.append(f"clipping ({runs} clipped runs, {clip_ratio * 100:.3f}% samples)")
        score -= min(35, 10 + runs / 10)
    if tp > -0.1:
        flags.append(f"true peak over 0 dBTP ({tp:+.1f})")
        score -= 10
    if np.isfinite(lufs):
        if lufs > -7:
            flags.append(f"very loud master ({lufs:.1f} LUFS)")
            score -= 10
        elif lufs < -20:
            flags.append(f"very quiet master ({lufs:.1f} LUFS)")
            score -= 10
    if 0 < plr < 6:
        flags.append(f"over-compressed (peak-to-loudness {plr:.1f} dB)")
        score -= 20
    elif plr > 20:
        flags.append(f"very dynamic / uneven (peak-to-loudness {plr:.1f} dB)")
        score -= 5
    if lra > 15:
        flags.append(f"large loudness range ({lra:.1f} LU)")
        score -= 5
    if dc > 0.01:
        flags.append(f"DC offset ({dc:.3f})")
        score -= 10
    if tilt - ref_tilt > 12:
        flags.append(f"very dark / muddy tone (+{tilt - ref_tilt:.0f} dB low vs high-mid)")
        score -= 10
    elif tilt - ref_tilt < -12:
        flags.append(f"very harsh / thin tone ({tilt - ref_tilt:.0f} dB low vs high-mid)")
        score -= 10
    if balance['sub'] > REFERENCE_BALANCE_DB['sub'] + 9:
        flags.append("excess sub bass")
        score -= 5

    phase = analyze_phase(x, fs)
    for flag in phase['flags']:
        flags.append(flag)
        score -= 15 if ('inverted' in flag or 'cancels' in flag or 'comb' in flag) else 8

    return {
        'phase': phase,
        'file_path': path,
        'filename': os.path.basename(path),
        'duration': duration,
        'sample_rate': fs,
        'channels': int(x.shape[1]),
        'lufs': float(lufs) if np.isfinite(lufs) else None,
        'loudness_range': lra,
        'true_peak_db': tp,
        'sample_peak': sample_peak,
        'clip_ratio': clip_ratio,
        'clip_runs': runs,
        'dc_offset': dc,
        'plr': plr,
        'balance_db': balance,
        'tilt_db': tilt,
        'flags': flags,
        'score': float(max(0.0, min(100.0, score))),
    }


def format_check(report: Dict) -> str:
    lufs = f"{report['lufs']:.1f}" if report['lufs'] is not None else "  -inf"
    phase = report.get('phase', {})
    stereo = f"stereo corr {phase.get('correlation', 1.0):+.2f} (bass {phase.get('correlation_low', 1.0):+.2f}), mono loss {phase.get('mono_loss_db', 0.0):+.1f} dB" \
        if phase.get('stereo') else "mono file"
    line = (f"{report['filename']}\n"
            f"    {lufs} LUFS | range {report['loudness_range']:.1f} LU | true peak {report['true_peak_db']:+.1f} dBTP | "
            f"PLR {report['plr']:.1f} dB | tilt {report['tilt_db']:+.1f} dB | score {report['score']:.0f}/100\n"
            f"    {stereo}")
    if report['flags']:
        line += "\n    ! " + "; ".join(report['flags'])
    return line


# ============================================================ processing
@njit(cache=True)
def _limiter_release(gain: np.ndarray, release_coef: float) -> np.ndarray:
    """Asymmetric smoothing: instant attack (gain already look-ahead minimised), exponential release."""
    out = np.empty_like(gain)
    env = 1.0
    for i in range(len(gain)):
        g = gain[i]
        if g < env:
            env = g
        else:
            env = release_coef * env + (1.0 - release_coef) * g
        out[i] = env
    return out


def true_peak_limiter(x: np.ndarray, fs: int, ceiling_db: float = -1.0,
                      lookahead_ms: float = 1.5, release_ms: float = 60.0) -> np.ndarray:
    """Transparent brick-wall limiter with look-ahead, working on the 4x oversampled peak."""
    ceiling = 10 ** (ceiling_db / 20)
    up = signal.resample_poly(x, 4, 1, axis=0)
    peak = np.max(np.abs(up), axis=1)
    peak = peak.reshape(-1, 4).max(axis=1)[:len(x)] if len(peak) >= 4 * len(x) else np.max(np.abs(x), axis=1)
    if len(peak) < len(x):
        peak = np.pad(peak, (0, len(x) - len(peak)), mode='edge')
    needed = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
    if np.all(needed >= 1.0):
        return x
    look = max(1, int(lookahead_ms / 1000 * fs))
    needed = minimum_filter1d(needed, size=2 * look + 1, mode='nearest')
    release_coef = float(np.exp(-1.0 / (release_ms / 1000 * fs)))
    env = _limiter_release(needed.astype(np.float64), release_coef)
    return (x * env[:, None]).astype(np.float32)


def apply_tone_match(x: np.ndarray, fs: int, balance: Dict[str, float], target: Dict[str, float],
                     max_db: float = 3.0) -> Tuple[np.ndarray, Dict[str, float]]:
    """Gentle low/high shelving towards a target balance, limited to +-max_db."""
    low_adj = float(np.clip(target['low'] - balance['low'], -max_db, max_db))
    high_adj = float(np.clip(target['high_mid'] - balance['high_mid'], -max_db, max_db))
    y = x
    if abs(low_adj) > 0.25:
        b, a = _biquad_low_shelf(fs, 200.0, low_adj)
        y = signal.lfilter(b, a, y, axis=0)
    if abs(high_adj) > 0.25:
        b, a = _biquad_high_shelf(fs, 4000.0, high_adj)
        y = signal.lfilter(b, a, y, axis=0)
    return y.astype(np.float32), {'low_shelf_db': low_adj, 'high_shelf_db': high_adj}


def fix_phase(x: np.ndarray, fs: int, phase: Dict, mono_bass_hz: float = 120.0) -> Tuple[np.ndarray, Dict]:
    """
    Repair what can be repaired safely:
    - inverted polarity: flip the right channel;
    - bass out of phase / poor mono compatibility: sum the low end (< mono_bass_hz) to mono
      while keeping the stereo image above it.
    Comb filtering cannot be undone automatically (it would need the original stems).
    """
    actions = {}
    if not phase.get('stereo') or x.ndim != 2 or x.shape[1] < 2:
        return x, actions
    y = x.astype(np.float32).copy()
    if phase.get('correlation_low', 1.0) < -0.5 and phase.get('correlation_high', 1.0) < -0.5:
        y[:, 1] *= -1.0
        actions['polarity_flipped'] = 'right channel'
        phase = dict(phase, correlation=-phase['correlation'], correlation_low=-phase['correlation_low'],
                     correlation_high=-phase['correlation_high'], mono_loss_db=0.0)
    if phase.get('correlation_low', 1.0) < 0.3 or phase.get('mono_loss_db', 0.0) < -3.0:
        low = _bandpass(y[:, :2], fs, None, mono_bass_hz).astype(np.float32)
        if phase.get('correlation_low', 1.0) < -0.3:
            # anti-phase bass would cancel when summed: keep the left channel's bass on both sides
            low_mono = low[:, :1]
        else:
            low_mono = low.mean(axis=1, keepdims=True)
        y[:, :2] = y[:, :2] - low + low_mono
        actions['mono_bass_below_hz'] = mono_bass_hz
    return y, actions


def premaster_track(path: str, output_path: str, target_lufs: float = -14.0, ceiling_db: float = -1.0,
                    tone_target: Optional[Dict[str, float]] = None, remove_dc: bool = True,
                    report: Optional[Dict] = None, repair_phase: bool = True) -> Dict:
    """Write a corrected copy of one track. Returns what was done."""
    x, fs = load_audio(path)
    before = report or analyze_mastering(path, (x, fs))
    actions = {}

    if repair_phase:
        x, phase_actions = fix_phase(x, fs, before.get('phase', {}))
        actions.update(phase_actions)

    if remove_dc:
        b, a = _biquad_high_pass(fs, 20.0, 0.707)
        x = signal.lfilter(b, a, x, axis=0).astype(np.float32)
        actions['dc_high_pass_hz'] = 20.0

    if tone_target is not None:
        balance = spectral_balance(x, fs) if actions else before['balance_db']
        x, tone = apply_tone_match(x, fs, balance, tone_target)
        actions.update(tone)

    lufs = integrated_loudness(x, fs)
    gain_db = float(target_lufs - lufs) if np.isfinite(lufs) else 0.0
    gain_db = float(np.clip(gain_db, -30.0, 30.0))
    x = (x * 10 ** (gain_db / 20)).astype(np.float32)
    actions['gain_db'] = gain_db

    limited = true_peak_limiter(x, fs, ceiling_db=ceiling_db)
    actions['limiter_max_reduction_db'] = float(20 * np.log10(max(np.min(np.abs(limited).max(axis=1) + 1e-9) / max(np.max(np.abs(x)), 1e-9), 1e-9))) if len(x) else 0.0
    x = limited

    ext = os.path.splitext(output_path)[1].lower()
    subtype = 'PCM_24' if ext in ('.wav', '.aiff', '.aif') else None
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if ext == '.mp3':
        sf.write(output_path, x, fs, format='MP3', bitrate_mode='CONSTANT', compression_level=0.0)
    else:
        sf.write(output_path, x, fs, subtype=subtype)

    after = analyze_mastering(output_path)
    return {'input': path, 'output': output_path, 'before': before, 'after': after, 'actions': actions}


def analyze_mastering_cached(path: str) -> Dict:
    """analyze_mastering() through the per-file analysis cache."""
    from analysis_store import get_store
    store = get_store()
    cached = store.get(path, 'mastering')
    if cached is not None:
        return cached
    report = analyze_mastering(path)
    store.put(path, 'mastering', report)
    return report


def collect_files(target: str) -> List[str]:
    """Directory -> audio files (sorted); .m3u -> its entries; file -> [file]."""
    if os.path.isdir(target):
        files = []
        for root, _, names in os.walk(target):
            for name in names:
                if os.path.splitext(name)[1].lower() in AUDIO_EXTENSIONS:
                    files.append(os.path.join(root, name))
        return sorted(files, key=lambda p: os.path.basename(p).lower())
    if target.lower().endswith(('.m3u', '.m3u8')):
        from transition_planner import tracks_from_m3u
        return [t['file_path'] for t in tracks_from_m3u(target)]
    return [target]


def add_set_relative_flags(reports: List[Dict]) -> None:
    """Flag tracks whose tone or loudness stands out from the rest of the set (in place)."""
    valid = [r for r in reports if r.get('lufs') is not None]
    if len(valid) < 2:
        return
    tilt_median = float(np.median([r['tilt_db'] for r in valid]))
    lufs_median = float(np.median([r['lufs'] for r in valid]))
    for r in valid:
        diff = r['tilt_db'] - tilt_median
        if diff > 6:
            r['flags'].append(f"darker than the rest of the set (+{diff:.0f} dB low vs high-mid)")
            r['score'] = max(0.0, r['score'] - 8)
        elif diff < -6:
            r['flags'].append(f"brighter / thinner than the rest of the set ({diff:.0f} dB low vs high-mid)")
            r['score'] = max(0.0, r['score'] - 8)
        ldiff = r['lufs'] - lufs_median
        if abs(ldiff) > 3:
            r['flags'].append(f"{'louder' if ldiff > 0 else 'quieter'} than the rest of the set ({ldiff:+.1f} dB)")
            r['score'] = max(0.0, r['score'] - 5)


def check_files(files: List[str], progress=None, relative: bool = True) -> List[Dict]:
    reports = []
    for i, path in enumerate(files):
        if progress:
            progress(i + 1, len(files), os.path.basename(path))
        try:
            reports.append(analyze_mastering_cached(path))
        except Exception as exc:  # unreadable file: keep going
            reports.append({'file_path': path, 'filename': os.path.basename(path), 'error': str(exc),
                            'flags': [f"could not analyze: {exc}"], 'score': 0.0, 'lufs': None,
                            'loudness_range': 0.0, 'true_peak_db': 0.0, 'plr': 0.0, 'tilt_db': 0.0})
    reports = [dict(r, flags=list(r.get('flags', []))) for r in reports]
    if relative:
        add_set_relative_flags(reports)
    return reports


def playlist_tone_target(reports: List[Dict]) -> Dict[str, float]:
    """Median band balance of the analysed tracks (the 'house sound' of the set)."""
    good = [r for r in reports if 'balance_db' in r]
    if not good:
        return dict(REFERENCE_BALANCE_DB)
    return {band: float(np.median([r['balance_db'][band] for r in good])) for band in REFERENCE_BALANCE_DB}


def format_check_summary(reports: List[Dict]) -> str:
    lines = ["MASTERING CHECK", "-" * 60]
    for r in reports:
        lines.append(format_check(r) if 'error' not in r else f"{r['filename']}\n    ! {r['flags'][0]}")
    valid = [r for r in reports if r.get('lufs') is not None]
    if valid:
        lufs = [r['lufs'] for r in valid]
        lines.append("")
        lines.append(f"Loudness spread across the set: {min(lufs):.1f} to {max(lufs):.1f} LUFS "
                     f"({max(lufs) - min(lufs):.1f} dB), median {np.median(lufs):.1f} LUFS")
        flagged = [r for r in reports if r['flags']]
        lines.append(f"Tracks with issues: {len(flagged)}/{len(reports)}")
        if max(lufs) - min(lufs) > 4 or flagged:
            lines.append("Suggestion: run the pre-master pass (mastering.py fix / GUI 'Pre-master Set') "
                         "to level the set, then let Mixxx play the corrected folder.")
    return "\n".join(lines)


def premaster_files(files: List[str], out_dir: str, target_lufs: float = -14.0, ceiling_db: float = -1.0,
                    tone_match: bool = False, fmt: str = 'same', progress=None, repair_phase: bool = True) -> List[Dict]:
    """Pre-master a list of files into out_dir. Returns per-track results."""
    os.makedirs(out_dir, exist_ok=True)
    if progress:
        progress(0, len(files), "measuring the set")
    reports = check_files(files)
    tone_target = playlist_tone_target(reports) if tone_match else None
    results = []
    for i, (path, report) in enumerate(zip(files, reports)):
        if progress:
            progress(i + 1, len(files), os.path.basename(path))
        if 'error' in report:
            results.append({'input': path, 'error': report['error']})
            continue
        base, ext = os.path.splitext(os.path.basename(path))
        out_ext = ext if fmt == 'same' else f".{fmt}"
        if out_ext.lower() in ('.m4a', '.aac', '.aiff', '.aif'):  # libsndfile cannot write these
            out_ext = '.flac'
        output_path = os.path.join(out_dir, base + out_ext)
        try:
            results.append(premaster_track(path, output_path, target_lufs, ceiling_db, tone_target,
                                           report=report, repair_phase=repair_phase))
        except Exception as exc:
            results.append({'input': path, 'error': str(exc)})
    return results


def format_premaster_summary(results: List[Dict], out_dir: str) -> str:
    lines = ["PRE-MASTER PASS", "-" * 60, f"Output folder: {out_dir}"]
    for r in results:
        if 'error' in r:
            lines.append(f"{os.path.basename(r['input'])}: FAILED ({r['error']})")
            continue
        a = r['actions']
        tone = ""
        if 'low_shelf_db' in a:
            tone = f", tone low {a['low_shelf_db']:+.1f} dB / high {a['high_shelf_db']:+.1f} dB"
        if 'polarity_flipped' in a:
            tone += ", polarity fixed"
        if 'mono_bass_below_hz' in a:
            tone += f", bass mono below {a['mono_bass_below_hz']:.0f} Hz"
        lines.append(f"{os.path.basename(r['output'])}: {r['before']['lufs']:.1f} -> {r['after']['lufs']:.1f} LUFS "
                     f"(gain {a['gain_db']:+.1f} dB{tone}), true peak {r['after']['true_peak_db']:+.1f} dBTP, "
                     f"score {r['before']['score']:.0f} -> {r['after']['score']:.0f}")
    ok = [r for r in results if 'error' not in r]
    if ok:
        lines.append("")
        lines.append(f"{len(ok)} tracks written. Add this folder to the Mixxx library (Preferences > Library, rescan), "
                     "then plan transitions on it.")
    return "\n".join(lines)


# ============================================================ CLI
def main():
    parser = argparse.ArgumentParser(description="DynaMix mastering check and pre-master pass")
    sub = parser.add_subparsers(dest="command", required=True)

    chk = sub.add_parser("check", help="Measure loudness, peaks, clipping and tone; print flags")
    chk.add_argument("targets", nargs="+", help="Directory, .m3u playlist or audio files")
    chk.add_argument("--json", help="Also save the full report as JSON")

    fix = sub.add_parser("fix", help="Write corrected copies of the tracks into another folder")
    fix.add_argument("target", help="Directory, .m3u playlist or audio file")
    fix.add_argument("--out", required=True, help="Output folder (created if needed)")
    fix.add_argument("--lufs", type=float, default=-14.0, help="Target integrated loudness (default -14 LUFS)")
    fix.add_argument("--tp", type=float, default=-1.0, help="True-peak ceiling in dBTP (default -1.0)")
    fix.add_argument("--tone", action="store_true", help="Gently match the tone of every track to the set's median balance")
    fix.add_argument("--format", default="same", choices=["same", "wav", "flac", "mp3", "ogg"],
                     help="Output format (default: same as the source)")
    fix.add_argument("--no-phase-fix", action="store_true", help="Do not flip inverted polarity / mono the bass")
    fix.add_argument("--save-chart", metavar="PNG", help="Write the loudness / true-peak before-after chart")
    args = parser.parse_args()

    if args.command == "check":
        files = []
        for target in args.targets:
            files.extend(collect_files(target))
        if not files:
            print("No audio files found.")
            sys.exit(1)
        reports = check_files(files, progress=lambda i, n, name: print(f"Checking {i}/{n}: {name}"))
        print()
        print(format_check_summary(reports))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(reports, f, indent=2)
            print(f"\nJSON report saved to {args.json}")
    else:
        files = collect_files(args.target)
        if not files:
            print("No audio files found.")
            sys.exit(1)
        results = premaster_files(files, args.out, args.lufs, args.tp, args.tone, args.format,
                                  progress=lambda i, n, name: print(f"Pre-mastering {i}/{n}: {name}"),
                                  repair_phase=not args.no_phase_fix)
        summary = format_premaster_summary(results, args.out)
        print()
        print(summary)
        if os.path.isdir(args.target):
            from set_project import SetProject
            if SetProject.exists(args.target):
                project = SetProject(args.target)
                keep = ('lufs', 'true_peak_db', 'plr', 'score', 'clip_runs', 'flags')
                slim = [({'input': r['input'], 'error': r['error']} if 'error' in r else
                         {'input': r['input'], 'output': r['output'], 'actions': r['actions'],
                          'before': {k: r['before'].get(k) for k in keep}, 'after': {k: r['after'].get(k) for k in keep}})
                        for r in results]
                project.data["premaster"] = {"out_dir": os.path.abspath(args.out), "target_lufs": args.lufs, "tone_match": args.tone,
                                             "fix_phase": not args.no_phase_fix, "results": slim, "summary": summary}
                project.mark("premaster", out_dir=os.path.abspath(args.out), count=sum(1 for r in results if 'error' not in r))
                project.save()
                print(f"Set project updated: {project.path}")
        if args.save_chart:
            import matplotlib
            matplotlib.use("Agg")
            import charts
            charts.save(charts.premaster_before_after(results, args.lufs, args.tp), args.save_chart)
            print(f"Before/after chart written to {args.save_chart}")


if __name__ == "__main__":
    main()
