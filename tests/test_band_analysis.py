import os
import shutil
import tempfile
import unittest

import numpy as np
import soundfile as sf

from band_analysis import analyze_bands, mix_recommendation, format_band_report


def _track(path, ducked, resonance):
    sr = 22050
    dur = 12
    t = np.linspace(0, dur, dur * sr, endpoint=False)
    b = 126 / 60
    kick = np.exp(-((t * b) % 1) * 25) * np.sin(2 * np.pi * 55 * t) * 0.9
    pad = 0.35 * (np.sin(2 * np.pi * 262 * t) + 0.7 * np.sin(2 * np.pi * 330 * t))
    env = 1 - 0.8 * np.exp(-((t * b) % 1) * 6) if ducked else 1.0
    y = kick + pad * env + (0.3 * np.sin(2 * np.pi * 320 * t) if resonance else 0)
    y = (y / np.max(np.abs(y)) * 0.8).astype("float32")
    sf.write(path, np.stack([y, y], 1), sr)


class TestBandAnalysis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_bands_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_breathing_vs_static(self):
        a = os.path.join(self.tmp, "a.wav")
        b = os.path.join(self.tmp, "b.wav")
        _track(a, ducked=True, resonance=False)
        _track(b, ducked=False, resonance=True)
        ra = analyze_bands(a, bpm=126)
        rb = analyze_bands(b, bpm=126)
        self.assertGreater(ra["stats"]["mud"]["beat_modulation"], rb["stats"]["mud"]["beat_modulation"])
        self.assertTrue(any("does not breathe" in f for f in rb["flags"]))
        self.assertTrue(any(abs(r["freq_hz"] - 320) < 6 for r in rb["resonances"]), rb["resonances"])
        self.assertEqual(rb["verdict"], "mix")
        self.assertIn("MIX REVISION", format_band_report(rb))
        self.assertEqual(set(ra["chart"]), {"times", "bands", "masking", "spectrum_hz", "spectrum_residual_db"})

    def test_recommendation(self):
        self.assertEqual(mix_recommendation(None, None), ("ok", []))
        self.assertEqual(mix_recommendation({"flags": []}, {"flags": ["very quiet master (-24.0 LUFS)"]})[0], "premaster")
        self.assertEqual(mix_recommendation({"flags": ["persistent resonances: 320 Hz"]}, {"flags": []})[0], "mix")
        self.assertEqual(mix_recommendation({"flags": []}, {"flags": ["comb filtering / phase cancellation (delay about 1.5 ms)"]})[0], "mix")


if __name__ == "__main__":
    unittest.main()
