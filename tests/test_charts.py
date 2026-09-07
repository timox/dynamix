import os
import shutil
import tempfile
import unittest

import matplotlib
matplotlib.use("Agg")

import charts


def _profile(i, dur=240.0):
    t = [x * 0.5 for x in range(int(dur * 2))]
    env = [0.02 + 0.1 * (1 if 16 < x < dur - 16 else 0.3) for x in t]
    return {
        "file_path": f"/m/track{i}.wav", "filename": f"track{i}.wav", "duration": dur, "bpm": 120.0 + i,
        "key": "A minor", "energy_level": 3.0 + i, "intro_start": 0.5, "intro_end": 16.0,
        "outro_start": dur - 32.0, "outro_end": dur - 16.0, "mix_duration": 16.0,
        "envelope_times": t, "envelope": env,
        "mastering": {"lufs": -14.0 - i, "true_peak_db": -1.0, "plr": 12.0, "score": 90.0 - i,
                      "flags": ["quieter than the rest of the set (-3.0 dB)"] if i == 2 else [],
                      "balance_db": {"sub": -7, "low": -3 + i, "low_mid": -7, "mid": -10, "high_mid": -15 - i, "high": -20}},
    }


class TestCharts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_charts_")
        self.profiles = [_profile(i) for i in range(4)]
        self.transitions = [{"score": 85 - 20 * i, "exit_time": 208.0, "entry_time": 0.5} for i in range(3)]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _check(self, fig, name):
        path = charts.save(fig, os.path.join(self.tmp, name))
        self.assertGreater(os.path.getsize(path), 5000)

    def test_set_overview(self):
        self._check(charts.set_overview(self.profiles, targets=[3, 4.5, 5.5, 6]), "overview.png")
        self._check(charts.set_overview([]), "overview_empty.png")

    def test_set_timeline(self):
        starts = charts.set_start_times(self.profiles)
        self.assertEqual(starts[0], 0.0)
        self.assertAlmostEqual(starts[1], 208.0 - 0.5)
        self._check(charts.set_timeline(self.profiles, self.transitions), "timeline.png")

    def test_track_detail(self):
        median = {"sub": -7, "low": -3, "low_mid": -7, "mid": -10, "high_mid": -15, "high": -20}
        self._check(charts.track_detail(self.profiles[2], median), "track.png")
        self._check(charts.track_detail({"filename": "x.wav", "duration": 100.0}), "track_min.png")

    def test_premaster(self):
        results = [{"output": f"/o/t{i}.flac", "before": {"lufs": -20.0 + i * 3, "true_peak_db": 0.5, "clip_runs": 10 if i else 0},
                    "after": {"lufs": -14.2, "true_peak_db": -1.0}} for i in range(3)]
        results.append({"input": "/o/bad.wav", "error": "boom"})
        self._check(charts.premaster_before_after(results, -14.0), "premaster.png")


if __name__ == "__main__":
    unittest.main()
