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
    def test_compact_and_spaced_forms(self):
        steps = tfx.parse_scratch("d81b0 u42b1")
        self.assertEqual([(s["kind"], s["factor"], s["seconds"], s["backward"]) for s in steps],
                         [("d", 8.0, 1.0, False), ("u", 4.0, 2.0, True)])
        steps = tfx.parse_scratch("D16 0.5 b1, u16/0,5; d1 2")
        self.assertEqual([(s["kind"], s["factor"], s["seconds"], s["backward"]) for s in steps],
                         [("d", 16.0, 0.5, True), ("u", 16.0, 0.5, False), ("d", 1.0, 2.0, False)])
        self.assertEqual(tfx.parse_scratch("d81 b1")[0]["backward"], True)

    def test_errors(self):
        for bad in ("", "   ", "x81", "d8", "d0 1", "d99 1", "d8 0", "d81b2"):
            with self.assertRaises(ValueError, msg=bad):
                tfx.parse_scratch(bad)
        self.assertTrue(any("scratch" in p for p in tfx.validate_effect(dict(tfx.new_effect("scratch"), sequence="zz"))))
        self.assertEqual(tfx.validate_effect(tfx.new_effect("scratch")), [])


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
        self.assertTrue(any("longer than the effect" in w for w in tfx.scratch_plan("d81 u81 d81", 2.5, SR)["warnings"]))
        self.assertTrue(any("extreme catch-up" in w for w in tfx.scratch_plan("d82b1", 2.5, SR)["warnings"]))
        self.assertTrue(any("no time left" in w for w in tfx.scratch_plan("d82", 2.0, SR)["warnings"]))

    def test_linear_ramp(self):
        plan = tfx.scratch_plan("d21", 2.0, SR, ramp="linear")
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
        tfx.apply_effects(ctx, [dict(tfx.new_effect("scratch"), sequence="d1 4", length_beats=8, start_offset_beats=-8)])
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
        self.assertIn("cannot read", bad["note"])


if __name__ == "__main__":
    unittest.main()
