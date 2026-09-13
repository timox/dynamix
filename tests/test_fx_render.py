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
        data, sr = sf.read(b["output"], dtype="float32")
        original, _ = sf.read(self.paths[1], dtype="float32")
        self.assertEqual(data.shape[1], 2)   # FX copies are always stereo
        diff = np.abs(data[int(3.0 * SR):int(3.5 * SR), 0] - original[int(3.0 * SR):int(3.5 * SR)])
        self.assertGreater(float(np.max(diff)), 0.1)   # sample overflow: A ends at 10 s = B 1.0 + 2.0 s
        self.assertLessEqual(float(np.max(np.abs(data))), 10 ** (-1 / 20) + 1e-3)

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


if __name__ == "__main__":
    unittest.main()
