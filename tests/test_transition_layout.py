#!/usr/bin/env python3
"""Drawing layout of a transition (no audio) and its chart: must follow the rules of the FX engine."""

import math
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")

import charts
import transition_fx as tfx

SR = 8000
BEATS = [i * 0.5 for i in range(120)]   # 120 BPM


def layout(effects, **kw):
    # junction A 4.0 s, A ends 6.0 s, B enters on its beat at 2.0 s
    return tfx.transition_layout(BEATS, BEATS, 4.0, 6.0, 2.0, effects, **kw)


def spans(lane):
    return [(round(b["start"], 3), round(b["end"], 3), b["kind"]) for b in lane["blocks"]]


class TestTransitionLayout(unittest.TestCase):
    def test_without_effects(self):
        lay = layout([])
        self.assertEqual((lay["junction"], lay["a_end"], lay["fade_len"], lay["b_shift"]), (4.0, 6.0, 2.0, 2.0))
        self.assertEqual(lay["lanes"], [])
        self.assertIn((4.0, 0), lay["beat_times"])
        self.assertIn((6.0, 4), lay["beat_times"])        # B's beats after the junction
        self.assertLessEqual(lay["view"][0], 0.0)          # 8 beats before the junction
        self.assertGreaterEqual(lay["view"][1], 10.0)      # 8 beats after A ends

    def test_freeze_moves_the_junction_like_the_engine(self):
        freeze = dict(tfx.new_effect("freeze"), capture_offset_beats=-2, tail_beats=1,
                      steps=[{"beats": 1, "repeats": 2}, {"beats": 0.5, "repeats": 2}])
        lay = layout([freeze])
        self.assertEqual(spans(lay["lanes"][0]), [(2.5, 3.0, "source"), (3.0, 3.5, "repeat"), (3.5, 4.0, "repeat"),
                                                  (4.0, 4.25, "repeat"), (4.25, 4.5, "repeat"), (4.5, 5.0, "tail")])
        self.assertEqual((lay["junction"], lay["planned_junction"], lay["a_end"], lay["b_shift"]), (3.0, 4.0, 5.0, 1.0))
        ctx = tfx.make_context(np.zeros((8 * SR, 2), np.float32), SR, BEATS, 4.0, 6.0,
                               np.zeros((10 * SR, 2), np.float32), SR, BEATS, 2.0)
        tfx.apply_effects(ctx, [freeze])
        self.assertAlmostEqual(ctx.junction_a, lay["junction"], places=3)
        self.assertAlmostEqual(ctx.a_end, lay["a_end"], delta=0.01)

    def test_lanes_follow_the_stack_but_a_freeze_is_applied_first(self):
        filt = dict(tfx.new_effect("filter"), side="outgoing", beats=4)
        freeze = dict(tfx.new_effect("freeze"), capture_offset_beats=-4)
        off = dict(tfx.new_effect("echo"), enabled=False)
        lay = layout([filt, off, freeze])
        self.assertEqual([lane["type"] for lane in lay["lanes"]], ["filter", "freeze"])
        self.assertEqual(spans(lay["lanes"][0])[0], (0.0, 2.0, "sweep"))   # 4 beats before the capture point

    def test_filter_sides_and_curve(self):
        out = layout([dict(tfx.new_effect("filter"), side="outgoing", beats=8, start_hz=200, end_hz=8000)])["lanes"][0]
        self.assertEqual(spans(out), [(0.0, 4.0, "sweep"), (4.0, 6.0, "hold")])
        self.assertAlmostEqual(out["curve"][0][1], 200.0)
        self.assertAlmostEqual(out["curve"][-1][1], 8000.0)
        self.assertAlmostEqual(out["curve"][12][1], 200.0 * 40 ** (12 / 23), places=3)   # exponential
        inc = layout([dict(tfx.new_effect("filter"), side="incoming", beats=4)])["lanes"][0]
        self.assertEqual(spans(inc), [(4.0, 6.0, "sweep"), (6.0, 6.5, "release")])
        across = layout([dict(tfx.new_effect("filter"), side="across", beats=8, start_offset_beats=-4, release_beats=2)])["lanes"][0]
        self.assertEqual(spans(across), [(2.0, 6.0, "sweep"), (6.0, 7.0, "release")])
        self.assertEqual(across["label"], "Filter highpass (A+B)")
        self.assertEqual(across["curve"][0][0], 2.0)

    def test_planned_and_a_ends_labels_do_not_overlap(self):
        # a freeze ending near the planned junction: the two labels go on either side of their lines
        freeze = dict(tfx.new_effect("freeze"), capture_offset_beats=-2, steps=[{"beats": 1, "repeats": 4}])
        lay = layout([freeze])
        span = lay["view"][1] - lay["view"][0]
        self.assertLess(abs(lay["planned_junction"] - lay["a_end"]), span * 0.12)   # close on the chart
        fig = charts.transition_detail(lay)
        labels = {t.get_text().strip(): t.get_horizontalalignment() for t in fig.axes[0].texts}
        planned_left = lay["planned_junction"] < lay["a_end"]
        self.assertEqual(labels["A ends"], "left" if planned_left else "right")
        self.assertEqual(labels["planned"], "right" if planned_left else "left")

    def test_filter_response_chart(self):
        for kind in ("highpass", "lowpass", "bandpass"):
            fig = charts.filter_response(dict(tfx.new_effect("filter"), kind=kind, resonance=4.0))
            self.assertEqual(len(fig.axes), 1)
            charts.save(fig, os.path.join(tempfile.gettempdir(), f"dynamix_filter_{kind}.png"))

    def test_echo_and_its_tail(self):
        echo = dict(tfx.new_effect("echo"), start_offset_beats=-4, delay_beats=0.5, feedback=0.5, mix=0.5)
        lane = layout([echo])["lanes"][0]
        self.assertEqual(spans(lane)[0], (2.0, 6.0, "wet"))
        self.assertAlmostEqual(lane["blocks"][1]["end"], 6.0 + math.log(1e-3) / math.log(0.5) * 0.25, places=3)
        long_tail = layout([dict(echo, feedback=0.85)])["lanes"][0]
        self.assertAlmostEqual(long_tail["blocks"][1]["end"], 6.0 + tfx.MAX_ECHO_TAIL_BEATS * 0.5, places=3)

    def test_sample_repeats_anchor_and_tempo(self):
        sample = dict(tfx.new_effect("sample"), file="loop 240BPM.wav", repeats=2, anchor="end_at_junction")
        lay = layout([sample], sample_seconds=lambda path: 1.0)   # 1 s at 240 BPM -> 2 s at 120 BPM
        self.assertEqual(spans(lay["lanes"][0]), [(0.0, 2.0, "sample"), (2.0, 4.0, "sample")])
        self.assertEqual(lay["lanes"][0]["label"], "Sample ×2")
        start = layout([dict(sample, anchor="start_at_junction", repeats=1, offset_beats=1)], sample_seconds=lambda p: 1.0)
        self.assertEqual(spans(start["lanes"][0]), [(4.5, 6.5, "sample")])
        far = layout([dict(sample, file="loop 50BPM.wav")], sample_seconds=lambda p: 1.0)
        self.assertTrue(any("out of range" in w for w in far["warnings"]))
        many = layout([dict(sample, file="long.wav", repeats=16)], sample_seconds=lambda p: 5.0)
        self.assertEqual(len(many["lanes"][0]["blocks"]), 12)
        self.assertTrue(any("reduced to 12" in w for w in many["warnings"]))
        empty = layout([tfx.new_effect("sample")])["lanes"][0]
        self.assertEqual((empty["blocks"], empty["note"]), ([], "choose a sample"))

    def test_peak_envelope(self):
        t = np.arange(SR) / SR
        mono = (0.5 * np.sin(2 * np.pi * 50 * t)).astype(np.float32)
        env = tfx.peak_envelope(np.stack([mono, mono], axis=1), SR, t0=3.0)
        self.assertEqual(len(env["peak"]), 100)
        self.assertAlmostEqual(env["dt"], 0.01)
        self.assertEqual(env["t0"], 3.0)
        self.assertAlmostEqual(float(env["peak"].max()), 0.5, places=2)


class TestTransitionChart(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_chart_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_chart_with_and_without_waveforms(self):
        effects = [dict(tfx.new_effect("freeze"), capture_offset_beats=-2, tail_beats=2),
                   dict(tfx.new_effect("filter"), side="incoming"),
                   tfx.new_effect("echo"),
                   dict(tfx.new_effect("sample"), file="loop 60BPM.wav", repeats=3)]
        lay = layout(effects, sample_seconds=lambda p: 1.0)
        noise = np.random.default_rng(1).normal(0, 0.2, (20 * SR, 2)).astype(np.float32)
        env = tfx.peak_envelope(noise, SR)
        for name, args in (("full.png", (env, env, env)), ("bare.png", ())):
            fig = charts.transition_detail(lay, *args)
            path = charts.save(fig, os.path.join(self.tmp, name))
            self.assertGreater(os.path.getsize(path), 5000)


if __name__ == "__main__":
    unittest.main()
