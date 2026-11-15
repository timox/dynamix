"""Bounded-memory full-track spectral summaries for the comparison view."""

from typing import Dict

import numpy as np
import soundfile as sf
from scipy import signal


BANDS = (("sub", 20, 60), ("low", 60, 250), ("low_mid", 250, 800),
         ("mid", 800, 2500), ("high_mid", 2500, 6000), ("high", 6000, 20000))
_NFFT = 4096
_HOP = 2048
_READ_FRAMES = 262144


def analyze_spectrum(path: str, max_time_bins: int = 900, freq_bins: int = 256, check=None) -> Dict:
    """Return a display-sized log-frequency spectrogram and full-track band balance."""
    if max_time_bins < 1 or freq_bins < 2:
        raise ValueError("Spectrogram dimensions must be positive")
    with sf.SoundFile(path) as audio:
        fs, frames = int(audio.samplerate), len(audio)
        if frames == 0:
            raise ValueError("Audio file is empty")
        duration = frames / fs
        nyquist = fs / 2
        edges = np.geomspace(20.0, max(20.01, nyquist), freq_bins + 1)
        centers = np.sqrt(edges[:-1] * edges[1:])
        time_bins = min(max_time_bins, max(1, int(np.ceil(duration / 2))))
        band_sum = np.zeros(len(BANDS), dtype=np.float64)
        band_count = np.zeros(len(BANDS), dtype=np.float64)
        image_sum = np.zeros((time_bins, freq_bins), dtype=np.float64)
        image_count = np.zeros(time_bins, dtype=np.uint32)
        frequencies = np.fft.rfftfreq(_NFFT, 1 / fs)
        bands_idx = [(frequencies >= lo) & (frequencies < hi) for _, lo, hi in BANDS]
        window = signal.windows.hann(_NFFT, sym=False).astype(np.float32)
        carry = np.empty((0, audio.channels), dtype=np.float32)
        offset = 0
        while True:
            if check is not None:
                check()
            block = audio.read(_READ_FRAMES, dtype="float32", always_2d=True)
            if not len(block):
                break
            block = np.concatenate((carry, block), axis=0) if len(carry) else block
            usable = max(0, (len(block) - _NFFT) // _HOP + 1)
            if usable:
                frames_view = np.lib.stride_tricks.sliding_window_view(block, _NFFT, axis=0)[::_HOP][:usable]
                # sliding_window_view shape is (frame, channel, sample).
                mono = frames_view.mean(axis=1)
                spec = np.fft.rfft(mono * window, axis=-1)
                pxx = (np.abs(spec) ** 2) / (_NFFT * _NFFT)
                fbin = np.clip(np.searchsorted(edges, frequencies, side="right") - 1, 0, freq_bins - 1)
                binned = np.stack([pxx[:, fbin == j].mean(axis=1) if np.any(fbin == j)
                                   else np.full(usable, 1e-20) for j in range(freq_bins)], axis=1)
                for j, mask in enumerate(bands_idx):
                    if np.any(mask):
                        vals = pxx[:, mask].sum(axis=1)
                        band_sum[j] += vals.sum()
                        band_count[j] += len(vals)
                times = offset + np.arange(usable) * _HOP
                tids = np.minimum(time_bins - 1, (times * time_bins // frames).astype(int))
                # Aggregate spectra into the bounded time-frequency display grid.
                for tid in np.unique(tids):
                    selected = tids == tid
                    image_sum[tid] += np.maximum(1e-20, binned[selected]).sum(axis=0)
                    image_count[tid] += np.count_nonzero(selected)
                offset += usable * _HOP
            keep = min(_NFFT - _HOP, len(block))
            carry = block[-keep:].copy() if keep else np.empty((0, audio.channels), dtype=np.float32)
        balance = {name: float(10 * np.log10(max(band_sum[i] / max(band_count[i], 1), 1e-20)))
                   for i, (name, _, _) in enumerate(BANDS)}
        db = 10 * np.log10(np.maximum(image_sum / np.maximum(image_count[:, None], 1), 1e-20))
        return {"duration_s": duration, "sample_rate": fs,
                "times_s": (np.arange(time_bins) + 0.5) * duration / time_bins,
                "frequencies_hz": centers, "spectrogram_db": db.astype(np.float32),
                "band_balance_db": balance}
