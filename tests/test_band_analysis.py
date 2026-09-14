import os
import shutil
import tempfile
import unittest

import numpy as np
import soundfile as sf

from band_analysis import analyze_bands, describe_resonance, format_band_report, key_note, mix_recommendation, resonance_note


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

    def test_resonance_notes(self):
        self.assertEqual(resonance_note(440.0), {"note": "A4", "cents": 0, "in_key": None, "degree": None})
        self.assertEqual(resonance_note(110.0, "A minor")["degree"], "tonic")
        self.assertEqual((resonance_note(329.6, "A minor")["note"], resonance_note(329.6, "A minor")["degree"]), ("E4", "5th"))
        self.assertIs(resonance_note(233.1, "A minor")["in_key"], False)                    # A#3
        self.assertIs(resonance_note(233.1, "F major")["in_key"], True)                     # A# = Bb, 4th of F
        self.assertEqual(resonance_note(452.0)["cents"], 47)                                 # between A4 and A#4
        self.assertEqual(describe_resonance(330.0, "A minor"), "330 Hz ~ E4 (5th of A minor)")
        self.assertEqual(describe_resonance(320.0), "320 Hz ~ D#4 +49 ct")
        self.assertIn("not in A minor", describe_resonance(233.1, "A minor"))
        resonances = [{"freq_hz": 110.0, "prominence_db": 9, "q": 10}, {"freq_hz": 233.1, "prominence_db": 6, "q": 8}]
        self.assertIn("1/2 resonance(s) on notes of A minor", key_note(resonances, "A minor"))
        self.assertIsNone(key_note(resonances, None))
        report = {"filename": "x.wav", "bpm": None, "stats": {name: {"mean_db": 0, "range_db": 0, "beat_modulation": 0}
                                                             for name in ("sub", "low", "low_mid", "mud", "mid", "high_mid", "high")},
                  "mud": {"excess_median_db": 0, "excess_p90_db": 0, "buildup_share": 0, "beat_modulation": 0},
                  "resonances": resonances, "flags": [], "eq_suggestions": [], "verdict": "ok"}
        text = format_band_report(report, key="A minor")
        self.assertIn("110 Hz ~ A2 (tonic of A minor)", text)
        self.assertIn("may simply be the key of the track", text)

    def test_recommendation(self):
        self.assertEqual(mix_recommendation(None, None), ("ok", []))
        self.assertEqual(mix_recommendation({"flags": []}, {"flags": ["very quiet master (-24.0 LUFS)"]})[0], "premaster")
        self.assertEqual(mix_recommendation({"flags": ["persistent resonances: 320 Hz"]}, {"flags": []})[0], "mix")
        self.assertEqual(mix_recommendation({"flags": []}, {"flags": ["comb filtering / phase cancellation (delay about 1.5 ms)"]})[0], "mix")


if __name__ == "__main__":
    unittest.main()
