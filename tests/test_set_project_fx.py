import json
import os
import shutil
import tempfile
import unittest

from set_project import SetProject


class TestSetProjectFx(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_fxp_")
        self.p = SetProject.create(os.path.join(self.tmp, "projects"), "fx")
        self.a, self.b, self.c = "/lib/a.wav", "/lib/b.wav", "/lib/c.wav"
        self.p.set_tracks([{"file_path": x, "filename": os.path.basename(x)} for x in (self.a, self.b, self.c)])
        self.p.set_order([self.a, self.b, self.c])
        self.freeze = {"type": "freeze", "enabled": True, "steps": [{"beats": 1, "repeats": 4}]}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_recipes_by_pair_survive_reordering(self):
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        self.p.set_fx_nudge(self.a, self.b, 12)
        self.assertEqual(self.p.active_fx_pairs(), [(self.a, self.b)])
        self.p.set_order([self.c, self.a, self.b])
        self.assertEqual(self.p.active_fx_pairs(), [(self.a, self.b)])
        self.assertEqual(self.p.fx_for_pair(self.a, self.b)["nudge_ms"], 12.0)
        self.p.set_order([self.b, self.a, self.c])
        self.assertEqual(self.p.active_fx_pairs(), [])
        self.assertEqual(self.p.inactive_fx_pairs(), [(self.a, self.b)])
        self.p.remove_fx(self.a, self.b)
        self.assertEqual(self.p.inactive_fx_pairs(), [])

    def test_disabled_effects_are_not_active(self):
        self.p.set_fx_effects(self.b, self.c, [dict(self.freeze, enabled=False)])
        self.assertEqual(self.p.active_fx_pairs(), [])

    def test_changes_and_invalidation_keep_recipes(self):
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        self.p.set_fx_render([{"source": self.a, "output": "x"}])
        self.p.mark("fx", count=1)
        self.p.set_fx_nudge(self.a, self.b, 5)
        self.assertIsNone(self.p.data["fx"]["render"])
        self.assertFalse(self.p.is_done("fx"))
        self.p.set_fx_render([{"source": self.a, "output": "x"}])
        self.p.invalidate_from("premaster")
        self.assertIsNone(self.p.data["fx"]["render"])
        self.assertEqual(len(self.p.fx_for_pair(self.a, self.b)["effects"]), 1)
        self.p.set_fx_render([{"source": self.a, "output": "x"}])
        self.p.set_order([self.a, self.c, self.b])
        self.assertIsNone(self.p.data["fx"]["render"])

    def test_fx_map_and_rendered_profiles(self):
        os.makedirs(self.p.fx_dir)
        os.makedirs(self.p.premaster_dir, exist_ok=True)
        fx_copy = os.path.join(self.p.fx_dir, "a.wav")
        pm_copy = os.path.join(self.p.premaster_dir, "b.wav")
        for path in (fx_copy, pm_copy):
            open(path, "wb").close()
        self.p.data["premaster"] = {"results": [{"input": self.a, "output": os.path.join(self.p.premaster_dir, "a.wav")},
                                                {"input": self.b, "output": pm_copy}]}
        self.p.set_fx_render([{"source": self.a, "output": fx_copy, "intro_start": 1.0, "intro_end": 2.0,
                               "outro_start": 8.0, "outro_end": 10.0, "duration": 10.0},
                              {"source": self.c, "output": os.path.join(self.p.fx_dir, "missing.wav")}])
        self.assertEqual(list(self.p.fx_map()), [self.a])
        profiles = [{"file_path": x, "intro_start": 0.0, "intro_end": 1.0, "outro_start": 5.0, "outro_end": 6.0,
                     "duration": 7.0} for x in (self.a, self.b, self.c)]
        out, counts = self.p.rendered_profiles(profiles)
        self.assertEqual(counts, {"fx": 1, "premaster": 1})
        self.assertEqual([q["file_path"] for q in out], [fx_copy, pm_copy, self.c])
        self.assertEqual((out[0]["outro_start"], out[0]["outro_end"], out[0]["duration"]), (8.0, 10.0, 10.0))
        self.assertEqual(out[1]["outro_end"], 6.0)
        self.assertEqual(profiles[0]["file_path"], self.a)   # inputs untouched

    def test_reset_clears_fx(self):
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        os.makedirs(self.p.fx_dir)
        with open(os.path.join(self.p.fx_dir, "a.wav"), "wb") as f:
            f.write(b"\x00" * 7)
        self.assertEqual(self.p.reset_preview()["outputs"], {"files": 1, "bytes": 7})
        self.p.reset()
        self.assertEqual(os.listdir(self.p.fx_dir), [])
        self.assertEqual(self.p.data["fx"], {"transitions": {}, "render": None})

    def test_project_without_fx_block_loads(self):
        with open(self.p.path, encoding="utf-8") as f:
            data = json.load(f)
        data.pop("fx", None)
        with open(self.p.path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        q = SetProject.open(self.p.folder)
        self.assertEqual(q.data["fx"], {"transitions": {}, "render": None})
        q.set_fx_effects(self.a, self.b, [self.freeze])
        q.save()
        self.assertEqual(len(SetProject.open(self.p.folder).fx_for_pair(self.a, self.b)["effects"]), 1)


if __name__ == "__main__":
    unittest.main()
