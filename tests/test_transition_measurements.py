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


class TestSheetFollowsTheAEndMarkers(unittest.TestCase):
    """The sheet must describe what the set will really play, not only what the plan first decided."""

    def setUp(self):
        self.planner = FakePlanner([{"file_path": A}, {"file_path": B}])
        self.planner.profiles = [profile(A, "a.wav"), profile(B, "b.wav")]
        self.planner._build_transitions()

    def test_for_cues_rebuilds_the_transitions_and_leaves_the_plan_alone(self):
        moved = [dict(self.planner.profiles[0], outro_end=208.0), dict(self.planner.profiles[1])]
        sheet = self.planner.for_cues(moved)
        self.assertEqual(sheet.profiles[0]["outro_end"], 208.0)
        self.assertEqual(sheet.transitions[0]["exit_end"], 208.0)
        self.assertEqual(sheet.transitions[0]["crossfade_seconds"], 8.0)      # 208 - 200, not 16
        # the plan itself is untouched, and so are the profiles handed in
        self.assertEqual(self.planner.profiles[0]["outro_end"], 216.0)
        self.assertEqual(self.planner.transitions[0]["crossfade_seconds"], 16.0)
        self.assertEqual(moved[0]["outro_end"], 208.0)

    def test_the_text_shows_the_moved_outro(self):
        sheet = self.planner.for_cues([dict(self.planner.profiles[0], outro_end=208.0),
                                       dict(self.planner.profiles[1])])
        text = sheet.to_text()
        self.assertIn("outro 3:20.00 -> 3:28.00   blend ~8s", text)           # A: 200 s -> 208 s, 8 s of blend
        self.assertIn("outro 3:20.00 -> 3:36.00   blend ~16s", text)          # B keeps what the plan gave it
        self.assertIn("cue it at 0:00.00, blend ~8s", text)                   # and the transition agrees

    def test_the_blend_of_a_track_is_its_outro_not_the_planned_mix_length(self):
        """A short track already had its outro clamped by its end: the sheet must not promise the full blend."""
        short = dict(self.planner.profiles[0], duration=204.0, outro_end=204.0, mix_duration=16.0)
        text = self.planner.for_cues([short, dict(self.planner.profiles[1])]).to_text()
        self.assertIn("outro 3:20.00 -> 3:24.00   blend ~4s", text)


if __name__ == "__main__":
    unittest.main()
