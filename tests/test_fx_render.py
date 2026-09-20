import hashlib
import os
import shutil
import tempfile
import unittest

import numpy as np
import soundfile as sf

import analysis_store
import transition_fx as tfx

SR = 22050


def sha1(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


class TestRenderSet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_fxr_")
        os.environ["DYNAMIX_HOME"] = os.path.join(self.tmp, "home")
        analysis_store.reset_store()
        self.lib = os.path.join(self.tmp, "Mixes")
        os.makedirs(self.lib)
        self.paths = []
        for k, freq in enumerate((220, 330, 440)):
            t = np.arange(12 * SR) / SR
            path = os.path.join(self.lib, f"t{k}.wav")
            sf.write(path, (0.3 * np.sin(2 * np.pi * freq * t)).astype("float32"), SR)
            self.paths.append(path)
        self.hashes = [sha1(p) for p in self.paths]
        self.grid = {"beats": [i * 0.5 for i in range(25)], "bpm": 120.0, "has_beat": True, "duration": 12.0}
        self.profiles = [{"file_path": p, "filename": os.path.basename(p), "duration": 12.0, "bpm": 120.0,
                          "intro_start": 1.0, "intro_end": 3.0, "outro_start": 8.0, "outro_end": 10.0} for p in self.paths]
        hit = os.path.join(self.tmp, "hit.wav")
        sf.write(hit, np.full(SR, 0.2, dtype="float32"), SR)
        self.fx = {(self.paths[0], self.paths[1]): {"nudge_ms": 0, "effects": [
            dict(tfx.new_effect("freeze"), steps=[{"beats": 2, "repeats": 2}]),
            # starts 3 beats after the junction (9.5 s): 0.5 s in A (audible until 10 s), 0.5 s overflows into B
            dict(tfx.new_effect("sample"), file=hit, anchor="start_at_junction", offset_beats=3, gain_db=0.0)]}}

    def tearDown(self):
        os.environ.pop("DYNAMIX_HOME", None)
        analysis_store.reset_store()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copies_cues_and_originals(self):
        from fx_render import render_set
        out_dir = os.path.join(self.tmp, "project", "fx")
        grids = {p: self.grid for p in self.paths}
        results, problems = render_set(self.profiles, lambda a, b: self.fx.get((a, b)), {}, out_dir, grids=grids)
        self.assertEqual(problems, [])
        self.assertEqual([r["source"] for r in results], self.paths[:2])
        self.assertEqual(sorted(os.listdir(out_dir)), ["t0.wav", "t1.wav"])
        self.assertEqual([sha1(p) for p in self.paths], self.hashes)
        a, b = results
        self.assertAlmostEqual(a["outro_start"], 8.0)
        self.assertAlmostEqual(a["outro_end"], 10.0, places=3)        # 4 beats of freeze = 2 s
        self.assertAlmostEqual(a["duration"], 10.0, places=2)
        self.assertAlmostEqual(b["intro_start"], 1.0)
        # B's intro lasts at least as long as A's outro, so that Mixxx brings B in on the junction
        self.assertGreaterEqual(b["intro_end"], b["intro_start"] + (a["outro_end"] - a["outro_start"]) - 1e-3)
        data, sr = sf.read(b["output"], dtype="float32")
        original, _ = sf.read(self.paths[1], dtype="float32")
        self.assertEqual(data.shape[1], 2)   # FX copies are always stereo
        diff = np.abs(data[int(3.0 * SR):int(3.5 * SR), 0] - original[int(3.0 * SR):int(3.5 * SR)])
        self.assertGreater(float(np.max(diff)), 0.1)   # sample overflow: A ends at 10 s = B 1.0 + 2.0 s
        self.assertLessEqual(float(np.max(np.abs(data))), 10 ** (-1 / 20) + 1e-3)

    def test_track_both_incoming_and_outgoing(self):
        from fx_render import render_set
        fx = dict(self.fx)
        fx[(self.paths[1], self.paths[2])] = {"effects": [
            dict(tfx.new_effect("filter"), kind="highpass", start_hz=20, end_hz=2000, beats=4)]}
        out_dir = os.path.join(self.tmp, "fx")
        results, problems = render_set(self.profiles, lambda a, b: fx.get((a, b)), {}, out_dir,
                                       grids={p: self.grid for p in self.paths})
        self.assertEqual(problems, [])
        self.assertEqual([r["source"] for r in results], self.paths)
        self.assertEqual(sorted(os.listdir(out_dir)), ["t0.wav", "t1.wav", "t2.wav"])
        data, _ = sf.read(results[1]["output"], dtype="float32")
        base, _ = sf.read(self.paths[1], dtype="float32")
        start = slice(int(3.0 * SR), int(3.5 * SR))   # overflow of the sample of transition 1
        self.assertGreater(float(np.max(np.abs(data[start, 0] - base[start]))), 0.1)
        end = slice(int(7.8 * SR), int(8.3 * SR))     # outgoing high-pass of transition 2 (junction 8.0 s)
        rms = lambda x: 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12)
        self.assertLess(rms(data[end, 0]), rms(base[end]) - 6)
        self.assertEqual([sha1(p) for p in self.paths], self.hashes)

    def test_copy_is_identical_outside_the_modified_spans(self):
        from fx_render import render_set
        sr = 8000
        folder = os.path.join(self.tmp, "long")
        os.makedirs(folder)
        paths, profiles, grids = [], [], {}
        for k, (freq, seconds) in enumerate(zip((220, 330, 440), (12.0, 200.0, 12.0))):
            t = np.arange(int(seconds * sr)) / sr
            path = os.path.join(folder, f"l{k}.wav")
            sf.write(path, (0.8 * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)
            paths.append(path)
            profiles.append({"file_path": path, "filename": os.path.basename(path), "duration": seconds, "bpm": 120.0,
                             "intro_start": 1.0, "intro_end": 3.0, "outro_start": seconds - 4.0, "outro_end": seconds - 2.0})
            grids[path] = {"beats": [i * 0.5 for i in range(int(seconds * 2) + 1)], "bpm": 120.0, "has_beat": True,
                           "duration": seconds}
        fx = {(paths[0], paths[1]): self.fx[(self.paths[0], self.paths[1])],   # the sample overflows into l1 (0.8 + 0.2)
              (paths[1], paths[2]): {"effects": [dict(tfx.new_effect("filter"), beats=4)]}}
        results, problems = render_set(profiles, lambda a, b: fx.get((a, b)), {}, os.path.join(self.tmp, "fx_long"),
                                       grids=grids)
        self.assertEqual(problems, [])
        self.assertEqual(len(results), 3)
        data, _ = sf.read(results[1]["output"], dtype="float32")
        base, _ = sf.read(paths[1], dtype="float32")
        self.assertEqual(len(data), len(base))
        self.assertGreater(results[1]["limiter_reduction_db"], 0.0)
        self.assertLessEqual(float(np.max(np.abs(data))), 10 ** (-1 / 20) + 1e-3)
        # incoming region: until B's junction (1 s) + 120 s; outgoing region: from A's junction (196 s) - 45 s
        middle = slice(int(125 * sr), int(148 * sr))
        np.testing.assert_array_equal(data[middle, 0], base[middle])

    def test_invalid_transition_is_reported_and_skipped(self):
        from fx_render import render_set
        bad = {(self.paths[1], self.paths[2]): {"effects": [dict(tfx.new_effect("filter"), resonance=50)]}}
        results, problems = render_set(self.profiles, lambda a, b: bad.get((a, b)), {}, os.path.join(self.tmp, "fx"),
                                       grids={p: self.grid for p in self.paths})
        self.assertTrue(any("transition 2" in p and "resonance" in p for p in problems))

    def test_preview(self):
        from fx_render import render_preview
        clip, sr, warnings = render_preview(self.profiles[0], self.profiles[1], self.fx[(self.paths[0], self.paths[1])], {},
                                            grids={p: self.grid for p in self.paths})
        self.assertEqual(sr, SR)
        self.assertGreater(len(clip), SR * 5)
        self.assertEqual(warnings, [])

    def test_unreadable_base_skips_only_its_transitions(self):
        from fx_render import render_set
        fx = dict(self.fx)
        fx[(self.paths[1], self.paths[2])] = {"effects": [dict(tfx.new_effect("filter"), beats=4)]}
        bases = {self.paths[0]: os.path.join(self.tmp, "gone.wav")}
        results, problems = render_set(self.profiles, lambda a, b: fx.get((a, b)), bases, os.path.join(self.tmp, "fx"),
                                       grids={p: self.grid for p in self.paths})
        self.assertEqual([r["source"] for r in results], [self.paths[1], self.paths[2]])
        self.assertTrue(any("t0.wav" in p and "cannot be read" in p for p in problems))
        self.assertTrue(any("transition 1" in p and "skipped" in p for p in problems))

    def test_track_called_beatless_keeps_a_steady_detected_grid(self):
        from fx_render import _beats_for
        # soft percussion: the energy analysis says "no beat" but the detected grid is steady
        beats, warning = _beats_for(dict(self.profiles[0], has_beat=False), {self.paths[0]: self.grid}, 12.0)
        self.assertIsNone(warning)
        self.assertEqual(beats, self.grid["beats"])

    def test_track_without_rhythm_uses_a_regular_grid(self):
        from fx_render import _beats_for
        rng = np.random.default_rng(3)
        loose = {"beats": list(np.cumsum(rng.uniform(0.2, 0.9, 24))), "bpm": 120.0, "has_beat": True, "duration": 12.0}
        beats, warning = _beats_for(dict(self.profiles[0], has_beat=False), {self.paths[0]: loose}, 12.0)
        self.assertIn("no steady beat found", warning)
        self.assertIn(self.profiles[0]["filename"], warning)
        self.assertAlmostEqual(beats[1], 0.5)


class TestFilterWithoutReturn(unittest.TestCase):
    """A filter that is never turned back must reach the end of B, not stop where the working region does."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_fxnr_")
        os.environ["DYNAMIX_HOME"] = os.path.join(self.tmp, "home")
        analysis_store.reset_store()
        self.sr = 8000
        self.lib = os.path.join(self.tmp, "Mixes")
        os.makedirs(self.lib)
        self.paths = []
        for k, seconds in enumerate((20.0, 150.0)):          # B is longer than the 120 s working region
            t = np.arange(int(seconds * self.sr)) / self.sr
            path = os.path.join(self.lib, f"n{k}.wav")
            sf.write(path, (0.3 * np.sin(2 * np.pi * 80 * t)).astype("float32"), self.sr)
            self.paths.append(path)
        self.grids = {p: {"beats": [i * 0.5 for i in range(320)], "bpm": 120.0, "has_beat": True, "duration": 150.0}
                      for p in self.paths}
        self.profiles = [{"file_path": p, "filename": os.path.basename(p), "duration": d, "bpm": 120.0,
                          "intro_start": 1.0, "intro_end": 3.0, "outro_start": d - 4.0, "outro_end": d - 2.0}
                         for p, d in zip(self.paths, (20.0, 150.0))]

    def tearDown(self):
        os.environ.pop("DYNAMIX_HOME", None)
        analysis_store.reset_store()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_region_covers_the_whole_track_only_when_needed(self):
        from fx_render import _b_region_seconds
        held = dict(tfx.new_effect("filter"), side="incoming", release_beats=tfx.NO_RELEASE)
        self.assertEqual(_b_region_seconds([held], 150.0), 150.0)
        self.assertEqual(_b_region_seconds([dict(held, side="across")], 150.0), 150.0)
        self.assertEqual(_b_region_seconds([dict(held, side="outgoing")], 150.0), tfx.B_REGION_S)
        self.assertEqual(_b_region_seconds([dict(held, release_beats=1)], 150.0), tfx.B_REGION_S)
        self.assertEqual(_b_region_seconds([tfx.new_effect("echo")], 150.0), tfx.B_REGION_S)
        self.assertEqual(_b_region_seconds([], 150.0), tfx.B_REGION_S)

    def test_b_stays_filtered_to_the_end_of_the_copy(self):
        from fx_render import render_set
        from mastering import load_audio
        fx = {(self.paths[0], self.paths[1]): {"nudge_ms": 0, "effects": [
            dict(tfx.new_effect("filter"), side="incoming", kind="highpass", start_hz=20, end_hz=2000, beats=4,
                 release_beats=tfx.NO_RELEASE)]}}
        out_dir = os.path.join(self.tmp, "fx")
        results, problems = render_set(self.profiles, lambda a, b: fx.get((a, b)), {}, out_dir, grids=self.grids)
        self.assertEqual(problems, [])
        copy = next(r["output"] for r in results if r["source"] == self.paths[1])
        audio, sr = load_audio(copy)
        audio = tfx.to_stereo(audio)

        def level(t):
            seg = audio[int(t * sr):int((t + 1.0) * sr)]
            return 20 * np.log10(np.sqrt(np.mean(np.square(seg))) + 1e-12)

        self.assertLess(level(10.0), level(0.5) - 20)            # inside the old working region: filtered
        self.assertLess(level(140.0), level(0.5) - 20)           # far beyond it: still filtered, no step back
        self.assertLess(abs(level(118.0) - level(122.0)), 3.0)   # and nothing jumps where the region used to end


if __name__ == "__main__":
    unittest.main()
