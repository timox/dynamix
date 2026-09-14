import os
import shutil
import tempfile
import unittest

import numpy as np
import soundfile as sf
from scipy import signal

import transition_fx as tfx

SR = 44100
PERIOD = 0.5  # 120 BPM


def grid(seconds=60.0):
    return [i * PERIOD for i in range(int(seconds / PERIOD) + 1)]


def sine(freq, seconds, sr=SR, amp=0.5):
    t = np.arange(int(seconds * sr)) / sr
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12)


def ctx_for(a, b, outro_start=4.0, outro_end=6.0, intro_start=2.0, b_sr=SR):
    return tfx.make_context(a, SR, grid(), outro_start, outro_end, b, b_sr, grid(), intro_start)


class TestGridAndValidation(unittest.TestCase):
    def test_beat_time(self):
        beats = [0.0, 0.5, 1.0, 1.6]
        self.assertAlmostEqual(tfx.beat_time(beats, 1, 1), 1.0)
        self.assertAlmostEqual(tfx.beat_time(beats, 2, 0.5), 1.3)
        self.assertAlmostEqual(tfx.beat_time(beats, 0, -2), -1.0)   # median period 0.5 before the grid
        self.assertAlmostEqual(tfx.beat_time(beats, 3, 2), 2.6)
        self.assertEqual(tfx.nearest_beat_index(beats, 1.2), 2)

    def test_usable_beats_fallback(self):
        beats, warning = tfx.usable_beats({"beats": [0.0, 0.5], "has_beat": False}, 100.0, 3.0)
        self.assertAlmostEqual(beats[1], 0.6)
        self.assertIn("100 BPM", warning)
        real = grid(10)
        self.assertEqual(tfx.usable_beats({"beats": real, "has_beat": True}, 0, 10)[0], real)

    def test_grid_is_regular(self):
        self.assertTrue(tfx.grid_is_regular(grid(10)))
        jittered = [t + (0.02 if i % 5 == 0 else 0.0) for i, t in enumerate(grid(10))]
        self.assertTrue(tfx.grid_is_regular(jittered))                       # a few late beats stay steady
        self.assertFalse(tfx.grid_is_regular([0.0, 0.3, 1.1, 1.3, 2.4, 2.6, 3.9, 4.0, 5.5, 5.6]))
        self.assertFalse(tfx.grid_is_regular(grid(2)))                       # too few beats

    def test_beat_grid_uses_the_cache(self):
        import analysis_store
        tmp = tempfile.mkdtemp(prefix="dynamix_fx_")
        os.environ["DYNAMIX_HOME"] = tmp
        analysis_store.reset_store()
        try:
            path = os.path.join(tmp, "x.wav")
            sf.write(path, np.zeros(SR, dtype="float32"), SR)
            analysis_store.get_store().put(path, "beats", {"beats": [0.0, 0.5], "bpm": 120.0, "has_beat": False, "duration": 1.0})
            self.assertEqual(tfx.beat_grid(path)["bpm"], 120.0)
        finally:
            os.environ.pop("DYNAMIX_HOME", None)
            analysis_store.reset_store()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_validate_effect(self):
        self.assertEqual(tfx.validate_effect(tfx.new_effect("filter")), [])
        bad = dict(tfx.new_effect("filter"), resonance=20, colour="red")
        problems = tfx.validate_effect(bad)
        self.assertTrue(any("resonance" in p for p in problems))
        self.assertTrue(any("colour" in p for p in problems))
        long_freeze = dict(tfx.new_effect("freeze"), steps=[{"beats": 4, "repeats": 20}])
        self.assertTrue(any("longer than 64" in p for p in tfx.validate_effect(long_freeze)))
        self.assertTrue(any("file not found" in p for p in tfx.validate_effect(tfx.new_effect("sample"))))
        self.assertEqual(tfx.validate_effect({"type": "reverb"}), ["Unknown FX type: 'reverb'"])
        with self.assertRaises(ValueError):
            tfx.apply_effects(ctx_for(sine(100, 8), sine(100, 8)), [bad])


class TestFilters(unittest.TestCase):
    def test_outgoing_highpass_closes(self):
        a = sine(100, 8)
        ctx = ctx_for(a, np.zeros_like(a))
        fx = dict(tfx.new_effect("filter"), kind="highpass", start_hz=20, end_hz=2000, beats=4)
        tfx.apply_effects(ctx, [fx])
        before = ctx.a[int(0.5 * SR):int(1.5 * SR)]
        after = ctx.a[int(4.5 * SR):int(6.0 * SR)]
        self.assertLess(rms_db(after), rms_db(before) - 20)
        self.assertAlmostEqual(rms_db(before), rms_db(a[int(0.5 * SR):int(1.5 * SR)]), delta=0.5)

    def test_outgoing_filter_stops_a_beat_after_a_end(self):
        a = sine(100, 8)
        ctx = ctx_for(a, np.zeros_like(a))  # A audible until 6.0 s, one beat = 0.5 s
        tfx.apply_effects(ctx, [dict(tfx.new_effect("filter"), kind="highpass", start_hz=20, end_hz=2000, beats=4)])
        np.testing.assert_array_equal(ctx.a[int(6.5 * SR):], a[int(6.5 * SR):])

    def test_incoming_lowpass_opens_and_returns_dry(self):
        b = sine(5000, 10)
        ctx = ctx_for(np.zeros_like(b), b, intro_start=2.0)
        fx = dict(tfx.new_effect("filter"), side="incoming", kind="lowpass", start_hz=200, end_hz=20000, beats=4)
        tfx.apply_effects(ctx, [fx])
        start = ctx.b_index(2.0)
        closed = ctx.b[start:start + int(0.2 * SR)]
        dry = ctx.b[ctx.b_index(5.0):ctx.b_index(6.0)]
        self.assertLess(rms_db(closed), rms_db(dry) - 20)
        self.assertAlmostEqual(rms_db(dry), rms_db(b[int(5.0 * SR):int(6.0 * SR)]), delta=0.5)

    def test_resonance_and_bandpass_response(self):
        b, a = tfx.biquad_coefficients("highpass", 1000, tfx.filter_q("highpass", 8, 1), SR)
        _, h = signal.freqz(b, a, worN=[1000], fs=SR)
        self.assertGreater(20 * np.log10(abs(h[0])), 6)
        q = tfx.filter_q("bandpass", 0.707, 1.0)
        b, a = tfx.biquad_coefficients("bandpass", 1000, q, SR)
        _, h = signal.freqz(b, a, worN=[1000, 2000], fs=SR)
        self.assertAlmostEqual(20 * np.log10(abs(h[0])), 0.0, delta=0.5)
        self.assertLess(20 * np.log10(abs(h[1])), -3)


class TestFreeze(unittest.TestCase):
    def test_roll_lengths_content_and_seams(self):
        a = sine(440, 8)
        ctx = ctx_for(a, np.zeros_like(a))
        steps = [{"beats": 4, "repeats": 1}, {"beats": 2, "repeats": 2}, {"beats": 1, "repeats": 4}]
        tfx.apply_effects(ctx, [dict(tfx.new_effect("freeze"), steps=steps)])
        self.assertAlmostEqual(ctx.outro_start, 4.0)
        self.assertAlmostEqual(ctx.a_end, 10.0, places=3)
        self.assertEqual(len(ctx.a), int(4.0 * SR) + int(6.0 * SR))
        body = ctx.a[int(4.0 * SR):]
        guard = int(0.006 * SR)
        np.testing.assert_allclose(body[guard:int(2.0 * SR) - guard], a[int(2.0 * SR) + guard:int(4.0 * SR) - guard], atol=1e-6)
        np.testing.assert_allclose(body[int(2.0 * SR) + guard:int(3.0 * SR) - guard],
                                   a[int(3.0 * SR) + guard:int(4.0 * SR) - guard], atol=1e-6)
        self.assertLess(float(np.max(np.abs(np.diff(ctx.a[:, 0])))), 0.05)

    def test_only_one_freeze_per_transition(self):
        a = sine(440, 8)
        ctx = ctx_for(a, np.zeros((int(10 * SR), 2), dtype=np.float32))
        freeze = tfx.new_effect("freeze")
        with self.assertRaisesRegex(ValueError, "only one freeze per transition"):
            tfx.apply_effects(ctx, [freeze, dict(freeze, capture_offset_beats=-4)])
        np.testing.assert_array_equal(ctx.a, a)   # nothing applied
        tfx.apply_effects(ctx, [freeze, dict(freeze, enabled=False)])   # a disabled second freeze is fine
        self.assertAlmostEqual(ctx.a_end, 6.0, places=3)

    def test_fade_and_tail(self):
        a = sine(440, 8)
        ctx = ctx_for(a, np.zeros_like(a))
        fx = dict(tfx.new_effect("freeze"), steps=[{"beats": 1, "repeats": 8}], fade_db=-40, tail_beats=2)
        tfx.apply_effects(ctx, [fx])
        self.assertAlmostEqual(ctx.a_end, 4.0 + 4.0 + 1.0, places=3)
        first = ctx.a[int(4.05 * SR):int(4.45 * SR)]
        last = ctx.a[int(7.5 * SR):int(7.95 * SR)]
        self.assertLess(rms_db(last), rms_db(first) - 20)


class TestEchoAndSample(unittest.TestCase):
    def test_echo_repeats_and_overflow(self):
        a = np.zeros((int(8 * SR), 2), dtype=np.float32)
        a[int(3.0 * SR)] = 1.0
        b = np.zeros((int(10 * SR), 2), dtype=np.float32)
        ctx = ctx_for(a, b, outro_start=4.0, outro_end=4.5)
        fx = dict(tfx.new_effect("echo"), delay_beats=0.5, feedback=0.5, mix=1.0, damping_hz=20000)
        tfx.apply_effects(ctx, [fx])
        peaks = [float(np.max(np.abs(ctx.a[int((3.0 + k * 0.25) * SR) - 50:int((3.0 + k * 0.25) * SR) + 50]))) for k in (1, 2, 3)]
        self.assertTrue(peaks[0] > peaks[1] > peaks[2] > 0)
        after_end = ctx.b[ctx.b_index(2.0 + 0.5):]
        self.assertGreater(float(np.max(np.abs(after_end))), 0.0)

    def _sample(self, tmp, sr=22050):
        path = os.path.join(tmp, "hit.wav")
        sf.write(path, np.full(sr, 0.5, dtype="float32"), sr)
        return path

    def test_sample_anchors_and_overflow_resampled(self):
        tmp = tempfile.mkdtemp(prefix="dynamix_fx_")
        try:
            path = self._sample(tmp)
            base = dict(tfx.new_effect("sample"), file=path, gain_db=0.0, fade_in_ms=0, fade_out_ms=0)
            a = np.zeros((int(8 * SR), 2), dtype=np.float32)
            for anchor, lo, hi in (("end_at_junction", 3.0, 4.0), ("center_on_junction", 3.5, 4.5),
                                   ("start_at_junction", 4.0, 4.5)):
                ctx = ctx_for(a, np.zeros((int(10 * 48000), 2), dtype=np.float32), outro_end=4.5, b_sr=48000)
                tfx.apply_effects(ctx, [dict(base, anchor=anchor)])
                active = np.nonzero(np.abs(ctx.a[:, 0]) > 0.25)[0]
                self.assertAlmostEqual(active[0] / SR, lo, delta=0.002)
                self.assertAlmostEqual((active[-1] + 1) / SR, hi, delta=0.002)
                b_active = np.nonzero(np.abs(ctx.b[:, 0]) > 0.25)[0]
                if anchor == "start_at_junction":
                    self.assertAlmostEqual(len(b_active) / 48000, 0.5, delta=0.01)
                    self.assertAlmostEqual(b_active[0], ctx.b_index(2.0 + 0.5), delta=5)
                else:
                    self.assertEqual(len(b_active), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_preview_is_limited(self):
        a = sine(440, 8, amp=0.99)
        b = sine(660, 10, amp=0.99)
        ctx = ctx_for(a, b)
        tfx.apply_effects(ctx, [dict(tfx.new_effect("freeze"), steps=[{"beats": 2, "repeats": 2}])])
        clip, sr = tfx.preview_mix(ctx, b_intro_end=4.0, length="short")
        self.assertEqual(sr, SR)
        self.assertAlmostEqual(len(clip) / SR, (ctx.a_end + 4.0) - 0.0, delta=0.01)
        self.assertLessEqual(float(np.max(np.abs(clip))), 10 ** (-1 / 20) + 1e-3)

    def test_preview_fades_b_over_the_transition_length(self):
        # Mixxx "Full Intro + Outro": the transition lasts min(outro, intro); B is at full level after it
        a = np.zeros((int(8 * SR), 2), dtype=np.float32)
        b = sine(440, 40)
        ctx = ctx_for(a, b)   # junction: A 4.0 s, B 2.0 s
        tfx.apply_effects(ctx, [dict(tfx.new_effect("freeze"), steps=[{"beats": 2, "repeats": 1}])])   # 1 s
        clip, sr = tfx.preview_mix(ctx, b_intro_end=ctx.junction_b + 20.0, length="short")
        start_t = max(ctx.a_beat(-8), ctx.a_offset)

        def window(t0, t1):
            return clip[int((ctx.junction_a + t0 - start_t) * sr):int((ctx.junction_a + t1 - start_t) * sr)]
        self.assertAlmostEqual(rms_db(window(1.2, 1.7)), rms_db(window(3.0, 3.5)), delta=1.0)


class TestStacking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_fx_")
        self.hit = os.path.join(self.tmp, "hit.wav")
        sf.write(self.hit, np.full(SR, 0.5, dtype="float32"), SR)
        self.sample = dict(tfx.new_effect("sample"), file=self.hit, anchor="start_at_junction", gain_db=0.0,
                           fade_in_ms=0, fade_out_ms=0)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _start(x, sr=SR):
        active = np.nonzero(np.abs(x[:, 0]) > 0.25)[0]
        return active[0] / sr if len(active) else None

    def test_freeze_moves_the_junction_for_later_effects(self):
        a = np.zeros((int(8 * SR), 2), dtype=np.float32)
        ctx = ctx_for(a, np.zeros((int(10 * SR), 2), dtype=np.float32), outro_start=4.0, outro_end=6.0)
        freeze = dict(tfx.new_effect("freeze"), capture_offset_beats=-4, steps=[{"beats": 1, "repeats": 4}])
        tfx.apply_effects(ctx, [self.sample, freeze])  # listed first, applied after the freeze
        self.assertAlmostEqual(ctx.junction_a, 2.0)
        self.assertAlmostEqual(ctx.outro_start, 2.0)
        self.assertAlmostEqual(ctx.a_end, 4.0, places=3)
        self.assertAlmostEqual(self._start(ctx.a), 2.0, delta=0.002)

    def test_nudge_shifts_every_position(self):
        b = np.zeros((int(10 * SR), 2), dtype=np.float32)
        ctx = tfx.make_context(np.zeros((int(8 * SR), 2), dtype=np.float32), SR, grid(), 4.0, 6.0, b, SR, grid(), 2.0,
                               nudge_ms=20)
        tfx.apply_effects(ctx, [self.sample])
        self.assertAlmostEqual(self._start(ctx.a), 4.02, delta=0.002)
        ctx2 = tfx.make_context(sine(440, 8), SR, grid(), 4.0, 6.0, b, SR, grid(), 2.0, nudge_ms=20)
        tfx.apply_effects(ctx2, [dict(tfx.new_effect("freeze"), steps=[{"beats": 1, "repeats": 2}])])
        self.assertAlmostEqual(ctx2.outro_start, 4.02, places=4)
        self.assertAlmostEqual(ctx2.a_end, 5.02, places=3)

    def test_overflow_is_placed_after_the_freeze_end(self):
        a = np.zeros((int(8 * SR), 2), dtype=np.float32)
        b = np.zeros((int(10 * SR), 2), dtype=np.float32)
        ctx = ctx_for(a, b, outro_start=4.0, outro_end=4.5)
        sample = dict(self.sample, offset_beats=3)  # starts at 5.5 s: 0.5 s before the freeze ends (6.0 s), 0.5 s after
        freeze = dict(tfx.new_effect("freeze"), steps=[{"beats": 1, "repeats": 4}])
        tfx.apply_effects(ctx, [sample, freeze])
        self.assertAlmostEqual(ctx.a_end, 6.0, places=3)
        self.assertAlmostEqual(self._start(ctx.a), 5.5, delta=0.002)
        self.assertAlmostEqual(self._start(ctx.b), 4.0, delta=0.002)  # B junction 2.0 + (6.0 - 4.0)


class TestSampleTempo(unittest.TestCase):
    def test_bpm_from_name(self):
        self.assertEqual(tfx.bpm_from_name("E:/fx/VFX1 FX Loops 005 143BPM.wav"), 143.0)
        self.assertEqual(tfx.bpm_from_name("riser 128.5 bpm.flac"), 128.5)
        self.assertEqual(tfx.bpm_from_name("hit_90Bpm.wav"), 90.0)
        self.assertIsNone(tfx.bpm_from_name("white noise sweep.wav"))
        self.assertIsNone(tfx.bpm_from_name(""))

    def test_sample_tempo_ratio_and_problems(self):
        fx = dict(tfx.new_effect("sample"), file="loop 143BPM.wav")
        ratio, sample_bpm, problem = tfx.sample_tempo(fx, 124.0)
        self.assertAlmostEqual(ratio, 124.0 / 143.0)
        self.assertEqual((sample_bpm, problem), (143.0, None))
        self.assertAlmostEqual(tfx.sample_tempo(dict(fx, sample_bpm=124.0), 124.0)[0], 1.0)   # manual BPM wins
        self.assertEqual(tfx.sample_tempo(dict(fx, tempo="off"), 124.0), (1.0, None, None))
        self.assertEqual(tfx.sample_tempo(dict(fx, file="noise.wav"), 124.0), (1.0, None, None))  # played as it is
        ratio, _, problem = tfx.sample_tempo(dict(fx, sample_bpm=60.0), 150.0)
        self.assertEqual(ratio, 1.0)
        self.assertIn("out of range", problem)
        self.assertTrue(any("sample_bpm" in p for p in tfx.validate_effect(dict(fx, sample_bpm=20.0))))
        self.assertTrue(any("tempo" in p for p in tfx.validate_effect(dict(fx, tempo="fast"))))

    def test_fit_tempo_lengths(self):
        data = sine(440, 1.0)
        fast = tfx.fit_tempo(data, SR, 2.0, "varispeed")
        self.assertAlmostEqual(len(fast) / SR, 0.5, delta=0.01)
        slow = tfx.fit_tempo(data, SR, 124.0 / 143.0, "stretch")
        self.assertAlmostEqual(len(slow) / SR, 143.0 / 124.0, delta=0.02)
        self.assertEqual(slow.shape[1], 2)
        self.assertIs(tfx.fit_tempo(data, SR, 1.3, "off"), data)
        self.assertIs(tfx.fit_tempo(data, SR, 1.0, "varispeed"), data)

    def test_sample_is_fitted_to_the_track_tempo(self):
        tmp = tempfile.mkdtemp(prefix="dynamix_fx_")
        try:
            loop = os.path.join(tmp, "loop 240BPM.wav")   # 1 s at 240 BPM -> 2 s at the track's 120 BPM
            sf.write(loop, np.full(SR, 0.5, dtype="float32"), SR)
            base = dict(tfx.new_effect("sample"), anchor="end_at_junction", gain_db=0.0, fade_in_ms=0, fade_out_ms=0)
            ctx = ctx_for(np.zeros((int(8 * SR), 2), dtype=np.float32), np.zeros((int(10 * SR), 2), dtype=np.float32))
            tfx.apply_effects(ctx, [dict(base, file=loop)])
            active = np.nonzero(np.abs(ctx.a[:, 0]) > 0.25)[0]
            self.assertAlmostEqual(active[0] / SR, 2.0, delta=0.02)
            self.assertAlmostEqual((active[-1] + 1) / SR, 4.0, delta=0.02)
            self.assertEqual(ctx.warnings, [])
            far = os.path.join(tmp, "loop 50BPM.wav")      # 120 / 50 = 2.4: out of range, played as it is
            sf.write(far, np.full(SR, 0.5, dtype="float32"), SR)
            ctx = ctx_for(np.zeros((int(8 * SR), 2), dtype=np.float32), np.zeros((int(10 * SR), 2), dtype=np.float32))
            tfx.apply_effects(ctx, [dict(base, file=far)])
            active = np.nonzero(np.abs(ctx.a[:, 0]) > 0.25)[0]
            self.assertAlmostEqual(active[0] / SR, 3.0, delta=0.02)
            self.assertTrue(any("out of range" in w for w in ctx.warnings))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_sample_repeats(self):
        tmp = tempfile.mkdtemp(prefix="dynamix_fx_")
        try:
            loop = os.path.join(tmp, "loop 240BPM.wav")   # 2 s once fitted to 120 BPM
            sf.write(loop, np.full(SR, 0.5, dtype="float32"), SR)
            base = dict(tfx.new_effect("sample"), file=loop, anchor="end_at_junction", gain_db=0.0,
                        fade_in_ms=0, fade_out_ms=0)
            self.assertEqual(base["repeats"], 1)
            ctx = ctx_for(np.zeros((int(8 * SR), 2), dtype=np.float32), np.zeros((int(10 * SR), 2), dtype=np.float32))
            tfx.apply_effects(ctx, [dict(base, repeats=2)])
            active = np.nonzero(np.abs(ctx.a[:, 0]) > 0.25)[0]
            self.assertAlmostEqual(active[0] / SR, 0.0, delta=0.02)      # the last repeat ends on the junction
            self.assertAlmostEqual((active[-1] + 1) / SR, 4.0, delta=0.02)
            self.assertEqual(len(active), active[-1] - active[0] + 1)    # no gap between the repeats
            self.assertTrue(any("repeats" in p for p in tfx.validate_effect(dict(base, repeats=17))))

            long_loop = os.path.join(tmp, "long.wav")                    # no BPM: 5 s as it is, 16 x 5 > 64 s
            sf.write(long_loop, np.full(5 * SR, 0.5, dtype="float32"), SR)
            ctx = ctx_for(np.zeros((int(8 * SR), 2), dtype=np.float32), np.zeros((int(10 * SR), 2), dtype=np.float32))
            tfx.apply_effects(ctx, [dict(base, file=long_loop, repeats=16)])
            self.assertTrue(any("reduced to 12" in w for w in ctx.warnings))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
