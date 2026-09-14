#!/usr/bin/env python3
"""Scratch effect: sequence reading, speed curve with an exact catch-up, rendering and layout."""

import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import transition_fx as tfx

SR = 1000
BEATS = [i * 0.5 for i in range(240)]   # 120 BPM


class TestParse(unittest.TestCase):
    def test_five_character_hex_commands(self):
        steps = tfx.parse_scratch("d81b0 u42b1")
        self.assertEqual([(s["kind"], s["factor"], s["seconds"], s["backward"]) for s in steps],
                         [("d", 8.0, 1.0, False), ("u", 4.0, 2.0, True)])
        steps = tfx.parse_scratch("DF3B1,u0Fb0\nd81b0u42b1")                        # hex, any case, separators optional
        self.assertEqual([(s["kind"], s["factor"], s["seconds"], s["backward"], s["text"]) for s in steps],
                         [("d", 15.0, 3.0, True, "DF3B1"), ("u", 1.0, 15.0, False, "u0Fb0"),   # factor 0 keeps the speed
                          ("d", 8.0, 1.0, False, "d81b0"), ("u", 4.0, 2.0, True, "u42b1")])

    def test_errors(self):
        for bad in ("", "   ", "x81b0", "d8", "d81b", "d81b2", "d80b0", "d81 b0", "d16 0.5 b1", "dG1b0", "d81b01"):
            with self.assertRaises(ValueError, msg=bad):
                tfx.parse_scratch(bad)
        with self.assertRaises(ValueError) as caught:
            tfx.parse_scratch("d81b0 d99999b1")
        self.assertIn("command 'd9999'", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            tfx.parse_scratch("u40b1")
        self.assertIn("1 to F seconds", str(caught.exception))
        self.assertTrue(any("scratch" in p for p in tfx.validate_effect(dict(tfx.new_effect("scratch"), sequence="zz"))))
        self.assertEqual(tfx.validate_effect(tfx.new_effect("scratch")), [])


class TestEditorHelpers(unittest.TestCase):
    def test_commands_keep_their_place_in_the_text(self):
        commands = tfx.scratch_commands("d81b0  u40b1\nzz")
        self.assertEqual([(c["start"], c["end"], c["text"]) for c in commands], [(0, 5, "d81b0"), (7, 12, "u40b1"), (13, 15, "zz")])
        self.assertEqual([c["error"] is None for c in commands], [True, False, False])
        self.assertEqual(commands[0]["step"]["factor"], 8.0)

    def test_nudge_steps_each_character_within_its_range(self):
        self.assertEqual(tfx.scratch_nudge("d81b0 u42b1", 0, 1), "u81b0 u42b1")          # d <-> u
        self.assertEqual(tfx.scratch_nudge("D81b0", 0, 1), "U81b0")                       # case kept
        self.assertEqual(tfx.scratch_nudge("d91b0", 1, 1), "dA1b0")                       # hex
        self.assertEqual(tfx.scratch_nudge("dF1b0", 1, 1), "dF1b0")                       # stops at F
        self.assertEqual(tfx.scratch_nudge("d01b0", 1, -1), "d01b0")                      # stops at 0
        self.assertEqual(tfx.scratch_nudge("d81b0", 2, -1), "d81b0")                      # seconds stop at 1
        self.assertEqual(tfx.scratch_nudge("d8ab0", 2, 1), "d8Bb0")
        self.assertEqual(tfx.scratch_nudge("d81b0 u42b1", 10, 1), "d81b0 u42b0")         # 0 <-> 1
        self.assertIsNone(tfx.scratch_nudge("d81b0 u42b1", 3, 1))                          # the b
        self.assertIsNone(tfx.scratch_nudge("d81b0 u42b1", 5, 1))                          # a space
        self.assertIsNone(tfx.scratch_nudge("dz1b0", 1, 1))

    def test_head_ends_back_in_place(self):
        plan = tfx.scratch_plan("d81b0 u81b1", 4.0, 200)
        head = tfx.scratch_head(plan, 200)
        self.assertEqual(len(head["t"]), len(head["offset"]))
        self.assertAlmostEqual(float(head["offset"][-1]), 0.0, places=6)
        self.assertLess(float(head["offset"][400]), 0.0)                                  # behind after slowing then going back

    def test_chart(self):
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        import charts
        plan = tfx.scratch_plan("d81b0 u42b1 dF3b1", 8.0, 200)
        fig = charts.scratch_head(plan, tfx.scratch_head(plan, 200), 8.0, highlight=1)
        self.assertEqual(len(fig.axes), 2)
        FigureCanvasAgg(fig).draw()


class TestPlan(unittest.TestCase):
    def test_catch_up_lands_exactly(self):
        plan = tfx.scratch_plan("d81b0 u81b0", 4.0, SR)
        self.assertAlmostEqual(float(np.sum(plan["speed"])), 4.0 * SR, places=6)      # ends where the track would be
        one_way = (1 - 1 / 8) / math.log(8)                                           # seconds read by d8 over 1 s
        self.assertAlmostEqual(plan["advance"], 2 * one_way, delta=0.002)
        self.assertAlmostEqual(plan["catch_up_speed"], (4.0 - 2 * one_way) / 2.0, delta=0.002)
        self.assertEqual([round(s["start"], 3) for s in plan["steps"]], [0.0, 1.0])
        self.assertAlmostEqual(plan["speed"][999], 1 / 8, places=6)                   # the slope reached 8 times slower
        self.assertEqual(plan["warnings"], [])

    def test_backwards_and_warnings(self):
        plan = tfx.scratch_plan("d11b1", 4.0, SR)                                    # 1 s backwards at normal speed
        self.assertAlmostEqual(plan["advance"], -1.0, delta=0.002)
        self.assertAlmostEqual(plan["catch_up_speed"], 5.0 / 3.0, delta=0.002)
        self.assertAlmostEqual(float(np.sum(plan["speed"])), 4.0 * SR, places=6)
        self.assertTrue(any("longer than the effect" in w for w in tfx.scratch_plan("d81b0u81b0d81b0", 2.5, SR)["warnings"]))
        self.assertTrue(any("extreme catch-up" in w for w in tfx.scratch_plan("d82b1", 2.5, SR)["warnings"]))
        self.assertTrue(any("no time left" in w for w in tfx.scratch_plan("d82b0", 2.0, SR)["warnings"]))

    def test_linear_ramp(self):
        plan = tfx.scratch_plan("d21b0", 2.0, SR, ramp="linear")
        self.assertAlmostEqual(plan["speed"][499], 0.75, delta=0.002)                 # halfway from 1 to 1/2


class TestRender(unittest.TestCase):
    def test_reads_the_track_at_the_integrated_positions(self):
        track = np.stack([np.arange(20 * SR, dtype=np.float32)] * 2, axis=1)          # value = sample index
        plan = tfx.scratch_plan("d81b0 u81b0", 4.0, SR)
        out = tfx.render_scratch(track, SR, 5000, plan["speed"])
        self.assertEqual(out.shape, (4 * SR, 2))
        self.assertAlmostEqual(float(out[2000, 0]), 5000 + plan["advance"] * SR, delta=2.0)   # after the sequence
        self.assertAlmostEqual(float(out[-1, 0]), 5000 + 4 * SR - plan["speed"][-1], delta=1.0)  # back in place

    def test_neutral_sequence_changes_nothing(self):
        track = np.random.default_rng(2).normal(0, 0.3, (12 * SR, 2)).astype(np.float32)
        ctx = tfx.make_context(track.copy(), SR, BEATS, 8.0, 10.0, track.copy(), SR, BEATS, 2.0)
        tfx.apply_effects(ctx, [dict(tfx.new_effect("scratch"), sequence="d14b0", length_beats=8, start_offset_beats=-8)])
        self.assertTrue(np.allclose(ctx.a[:10 * SR], track[:10 * SR], atol=1e-5))

    def test_effect_replaces_its_beats_only(self):
        track = np.random.default_rng(3).normal(0, 0.3, (12 * SR, 2)).astype(np.float32)
        ctx = tfx.make_context(track.copy(), SR, BEATS, 8.0, 10.0, track.copy(), SR, BEATS, 2.0)
        tfx.apply_effects(ctx, [dict(tfx.new_effect("scratch"), sequence="d81b1 u81b0", length_beats=8, start_offset_beats=-8)])
        start, end = ctx.a_index(4.0), ctx.a_index(8.0)                                  # 8 beats before the junction
        self.assertTrue(np.array_equal(ctx.a[:start], track[:start]))
        self.assertTrue(np.array_equal(ctx.a[end:10 * SR], track[end:10 * SR]))
        self.assertFalse(np.allclose(ctx.a[start + 100:end - 100], track[start + 100:end - 100]))


class TestLayout(unittest.TestCase):
    def test_lane_shows_the_steps_and_the_catch_up(self):
        fx = dict(tfx.new_effect("scratch"), sequence="d81b0 u81b1", length_beats=8, start_offset_beats=-8)
        layout = tfx.transition_layout(BEATS, BEATS, 8.0, 10.0, 2.0, [fx])
        lane = layout["lanes"][0]
        self.assertEqual([b["kind"] for b in lane["blocks"]], ["scratch_down", "scratch_up", "catchup"])
        self.assertAlmostEqual(lane["blocks"][0]["start"], 4.0)
        self.assertAlmostEqual(lane["blocks"][-1]["end"], 8.0)
        self.assertTrue(lane["blocks"][-1]["label"].startswith("×"))
        bad = tfx.transition_layout(BEATS, BEATS, 8.0, 10.0, 2.0, [dict(fx, sequence="zz")])["lanes"][0]
        self.assertEqual(bad["blocks"], [])
        self.assertIn("command 'zz'", bad["note"])


if __name__ == "__main__":
    unittest.main()
