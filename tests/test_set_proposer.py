import unittest

import set_proposer
from set_proposer import curve_targets, energy_target, overlap_seconds, propose, transition_cost


def track(name, energy, duration=300.0, bpm=120.0, key="A minor"):
    return {"file_path": f"/lib/{name}.wav", "filename": f"{name}.wav", "duration": duration,
            "bpm": bpm, "key": key, "energy_level": energy, "has_beat": True}


class TestCurvesAndCosts(unittest.TestCase):
    def test_energy_target_values(self):
        self.assertAlmostEqual(energy_target(0.0, "build"), 0.0)
        self.assertAlmostEqual(energy_target(1.0, "build"), 1.0)
        self.assertAlmostEqual(energy_target(0.5, "peak_middle"), 1.0)
        self.assertAlmostEqual(energy_target(0.0, "peak_middle"), 0.0)
        self.assertAlmostEqual(energy_target(0.0, "wave"), 0.0)
        self.assertAlmostEqual(energy_target(0.25, "wave"), 1.0)
        self.assertAlmostEqual(energy_target(0.5, "wave"), 0.0)
        self.assertAlmostEqual(energy_target(0.3, "constant"), 0.5)
        with self.assertRaises(ValueError):
            energy_target(0.5, "zigzag")

    def test_overlap_defaults_to_120_bpm(self):
        self.assertAlmostEqual(overlap_seconds({"bpm": 0}, 8), 16.0)
        self.assertAlmostEqual(overlap_seconds({"bpm": 128.0}, 8), 15.0)

    def test_curve_targets(self):
        tracks = [track("a", 2), track("b", 4), track("c", 6)]
        build = curve_targets(tracks, "build")
        self.assertEqual(len(build), 3)
        self.assertTrue(2.0 <= build[0] < build[1] < build[2] <= 6.0)
        self.assertEqual(curve_targets(tracks, "constant"), [4.0, 4.0, 4.0])
        self.assertIsNone(curve_targets(tracks, "all"))
        self.assertIsNone(curve_targets([], "build"))

    def test_transition_cost(self):
        same = transition_cost(track("a", 5), track("b", 5))
        self.assertAlmostEqual(same, 0.0)
        far = transition_cost(track("a", 5, bpm=120.0, key="C major"), track("b", 5, bpm=130.0, key="F# major"))
        self.assertAlmostEqual(far, 0.03 * 7 + 0.25)
        self.assertAlmostEqual(transition_cost(track("a", 5, bpm=120.0), track("b", 5, bpm=130.0), bpm=False), 0.0)


class TestPropose(unittest.TestCase):
    def test_empty_selection_raises(self):
        with self.assertRaises(ValueError):
            propose([], 600)

    def test_single_track(self):
        variants = propose([track("a", 5)], 3600)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["order"], ["/lib/a.wav"])
        self.assertEqual(variants[0]["score"], 100)
        self.assertIsNone(variants[0]["worst"])

    def test_fits_duration_with_overlaps(self):
        tracks = [track(f"t{i}", 1 + i % 9) for i in range(12)]
        best = propose(tracks, 1800, curve="build")[0]
        self.assertEqual(len(best["order"]), 6)  # 6 x 300 s - 5 x 16 s = 1720 s; 7 tracks = 2004 s
        self.assertLessEqual(best["effective_seconds"], 1800 * 1.03)
        self.assertAlmostEqual(best["effective_seconds"], 1720.0)

    def test_short_selection_uses_every_track_in_build_order(self):
        tracks = [track("e8", 8), track("e2", 2), track("e10", 10), track("e4", 4), track("e6", 6)]
        best = propose(tracks, 3600, curve="build")[0]
        self.assertEqual([t["energy_level"] for t in best["tracks"]], [2, 4, 6, 8, 10])
        self.assertAlmostEqual(best["effective_seconds"], 5 * 300 - 4 * 16)

    def test_peak_middle_puts_the_peak_in_the_middle(self):
        tracks = [track(f"e{e}", e) for e in (1, 3, 5, 7, 9)]
        best = propose(tracks, 3600, curve="peak_middle")[0]
        energies = [t["energy_level"] for t in best["tracks"]]
        self.assertIn(energies.index(9), (1, 2, 3))

    def test_compatible_keys_stay_adjacent(self):
        tracks = [track("am", 5, key="A minor"), track("fs", 5, key="F# major"), track("c", 5, key="C major")]
        order = propose(tracks, 3600, curve="constant")[0]["order"]
        self.assertEqual(abs(order.index("/lib/am.wav") - order.index("/lib/c.wav")), 1)

    def test_variants_are_distinct_and_deterministic(self):
        keys = ["A minor", "C major", "E minor", "G major", "D minor", "F major", "B minor", "D major"]
        tracks = [track(f"t{i}", 1 + i, key=k, bpm=120 + i) for i, k in enumerate(keys)]
        first = propose(tracks, 1500, curve="wave", variants=3)
        second = propose(tracks, 1500, curve="wave", variants=3)
        self.assertEqual([v["order"] for v in first], [v["order"] for v in second])
        self.assertEqual(len(first), 3)
        for i in range(3):
            for j in range(3):
                if i != j:
                    self.assertLess(set_proposer._similarity(first[i]["order"], first[j]["order"]), 0.7)
        for v in first:
            self.assertEqual(len(v["transition_scores"]), len(v["order"]) - 1)
            self.assertEqual(v["worst"]["score"], min(v["transition_scores"]))


if __name__ == "__main__":
    unittest.main()
