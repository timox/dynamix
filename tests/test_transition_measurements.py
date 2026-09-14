#!/usr/bin/env python3
"""The transition sheet measures the files the set plays (pre-mastered copies), the cues stay those of the tracks."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from transition_planner import TransitionPlanner

A, B = "/m/a.wav", "/m/b.wav"
COPY_A = "/p/premaster/a.wav"


def profile(path, name):
    return {"file_path": path, "filename": name, "duration": 240.0, "bpm": 124.0, "key": "A minor", "energy_level": 6.0,
            "has_beat": True, "avg_energy": 0.2, "mix_duration": 16.0,
            "intro_start": 0.0, "intro_end": 16.0, "outro_start": 200.0, "outro_end": 216.0}


class FakePlanner(TransitionPlanner):
    measured = []

    @staticmethod
    def _measurements(path, bpm):
        FakePlanner.measured.append(path)
        lufs = -9.0 if "premaster" in path else -16.0
        return ({"lufs": lufs, "loudness_range": 6.0, "true_peak_db": -1.0, "plr": 8.0, "tilt_db": 0.0, "score": 80,
                 "flags": [], "phase": {}},
                {"flags": [], "verdict": "ok", "resonances": [], "eq_suggestions": [], "mud": {}})


class TestTransitionMeasurements(unittest.TestCase):
    def setUp(self):
        FakePlanner.measured = []
        self.planner = FakePlanner([{"file_path": A}, {"file_path": B}])
        self.planner.profiles = [profile(A, "a.wav"), profile(B, "b.wav")]
        for p in self.planner.profiles:
            self.planner.measure(p)                               # planned on the originals
        self.planner._build_transitions()

    def test_refresh_measures_the_played_files_and_keeps_the_cues(self):
        cues = [(p["intro_start"], p["outro_start"]) for p in self.planner.profiles]
        self.assertEqual(self.planner.refresh_measurements({A: COPY_A}), 1)
        a, b = self.planner.profiles
        self.assertEqual((a["measured_file"], a["mastering"]["lufs"]), (COPY_A, -9.0))
        self.assertEqual((b["measured_file"], b["mastering"]["lufs"]), (B, -16.0))
        self.assertEqual([(p["intro_start"], p["outro_start"]) for p in self.planner.profiles], cues)
        self.assertIn("loudness jump", " ".join(self.planner.transitions[0]["notes"]))   # -9 -> -16 LUFS
        self.assertIn(f"measured on the pre-mastered copy: {COPY_A}", self.planner.to_text())

    def test_nothing_measured_again_when_nothing_changed(self):
        self.planner.refresh_measurements({A: COPY_A})
        FakePlanner.measured = []
        self.assertEqual(self.planner.refresh_measurements({A: COPY_A}), 0)
        self.assertEqual(FakePlanner.measured, [])
        self.assertEqual(self.planner.refresh_measurements({}), 1)                       # back to the original
        self.assertEqual(self.planner.profiles[0]["measured_file"], A)
        self.assertNotIn("measured on the pre-mastered copy", self.planner.to_text())


if __name__ == "__main__":
    unittest.main()
