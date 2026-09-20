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

    def test_new_transition_plan_invalidates_the_fx_render(self):
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        self.p.data["premaster"] = {"results": []}
        self.p.mark("premaster", count=0)
        self.p.set_fx_render([{"source": self.a, "output": "x"}])
        for step in ("fx", "playlist", "mixxx"):
            self.p.mark(step)
        plan = {"tracks": [{"file_path": x} for x in (self.a, self.b, self.c)], "transitions": [{"score": 50}, {"score": 60}]}
        self.p.set_transitions(plan)
        self.assertIsNone(self.p.data["fx"]["render"])
        for step in ("fx", "playlist", "mixxx"):
            self.assertFalse(self.p.is_done(step), step)
        self.assertEqual(len(self.p.fx_for_pair(self.a, self.b)["effects"]), 1)   # recipes kept
        self.assertIs(self.p.data["transitions"], plan)
        self.assertTrue(self.p.is_done("transitions"))
        self.assertEqual(self.p.step_state("transitions")["details"], {"count": 2})
        # the pre-mastered copies do not depend on the transitions: kept
        self.assertEqual(self.p.data["premaster"], {"results": []})
        self.assertTrue(self.p.is_done("premaster"))

    def test_identical_replan_keeps_the_fx_render(self):
        import copy
        plan = {"tracks": [{"file_path": x, "intro_start": 1.0, "intro_end": 3.0, "outro_start": 8.0, "outro_end": 10.0}
                           for x in (self.a, self.b, self.c)],
                "transitions": [{"score": 50}, {"score": 60}]}
        self.p.set_transitions(plan)
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        self.p.set_fx_render([{"source": self.a, "output": "x"}])
        for step in ("fx", "playlist", "mixxx"):
            self.p.mark(step)
        self.p.set_transitions(copy.deepcopy(plan))  # what mixxx_export.py --project does on every run
        self.assertIsNotNone(self.p.data["fx"]["render"])
        for step in ("fx", "playlist", "mixxx"):
            self.assertTrue(self.p.is_done(step), step)
        moved = copy.deepcopy(plan)
        moved["tracks"][0]["outro_start"] = 8.5
        self.p.set_transitions(moved)
        self.assertIsNone(self.p.data["fx"]["render"])
        self.assertFalse(self.p.is_done("fx"))

    def test_fx_change_resets_the_playlist_and_mixxx_steps(self):
        self.p.mark("playlist", count=3)
        self.p.mark("mixxx", cues=6)
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        self.assertFalse(self.p.is_done("playlist"))
        self.assertFalse(self.p.is_done("mixxx"))

    def test_fx_pending_counts_active_fx_without_a_copy(self):
        """The playlist and the Mixxx export silently ignore FX that were never rendered: they must be counted."""
        self.assertEqual(self.p.fx_pending(), 0)
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        self.p.set_fx_effects(self.b, self.c, [self.freeze])
        self.assertEqual(self.p.fx_pending(), 2)                 # set in the FX tab, never rendered
        os.makedirs(self.p.fx_dir, exist_ok=True)
        a_copy, b_copy = os.path.join(self.p.fx_dir, "a.wav"), os.path.join(self.p.fx_dir, "b.wav")
        for path in (a_copy, b_copy):
            open(path, "wb").close()
        self.p.set_fx_render([{"source": self.a, "output": a_copy}, {"source": self.b, "output": b_copy}])
        self.assertEqual(self.p.fx_pending(), 1)                 # a -> b rendered, b -> c still missing C's copy
        c_copy = os.path.join(self.p.fx_dir, "c.wav")
        open(c_copy, "wb").close()
        self.p.set_fx_render([{"source": x, "output": y} for x, y in ((self.a, a_copy), (self.b, b_copy), (self.c, c_copy))])
        self.assertEqual(self.p.fx_pending(), 0)
        os.remove(c_copy)                                        # a copy deleted behind our back
        self.assertEqual(self.p.fx_pending(), 1)

    def test_audio_used_text_names_the_unrendered_fx(self):
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        text = self.p.audio_used_text()
        self.assertIn("originals 3", text)
        self.assertIn("1 transition", text)
        self.assertIn("not rendered", text)

    def test_a_end_marker_is_stored_and_invalidates_the_render(self):
        """Moving where A ends changes the audio and the Mixxx cue: the FX copies must be made again."""
        self.assertIsNone(self.p.fx_for_pair(self.a, self.b))
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        self.p.set_fx_render([{"source": self.a, "output": "x"}])
        self.p.mark("fx", count=1)
        self.assertTrue(self.p.set_fx_a_end(self.a, self.b, 12.5))
        self.assertEqual(self.p.fx_for_pair(self.a, self.b)["a_end_s"], 12.5)
        self.assertIsNone(self.p.data["fx"]["render"])
        self.assertFalse(self.p.is_done("fx"))
        self.assertFalse(self.p.set_fx_a_end(self.a, self.b, 12.5))    # the same value changes nothing
        self.assertTrue(self.p.set_fx_a_end(self.a, self.b, None))     # back to what the plan says
        self.assertIsNone(self.p.fx_for_pair(self.a, self.b)["a_end_s"])

    def test_rendered_profiles_apply_the_marker_without_any_fx_copy(self):
        """The Mixxx cue and the M3U must follow the marker even on a transition that is only a marker."""
        self.p.set_fx_a_end(self.a, self.b, 9.0)
        profiles = [{"file_path": x, "intro_start": 0.0, "intro_end": 1.0, "outro_start": 5.0, "outro_end": 20.0,
                     "duration": 30.0} for x in (self.a, self.b, self.c)]
        out, counts = self.p.rendered_profiles(profiles)
        self.assertEqual(counts, {"fx": 0, "premaster": 0})
        self.assertEqual(out[0]["outro_end"], 9.0)      # A of the marked transition
        self.assertEqual(out[0]["outro_start"], 5.0)    # the junction does not move
        self.assertEqual(out[1]["outro_end"], 20.0)     # B keeps what the plan says
        self.assertEqual(out[2]["outro_end"], 20.0)

    def test_clearing_a_marker_that_was_never_set_changes_nothing(self):
        """'Planned' on an untouched transition must not create an entry nor throw the FX render away."""
        self.p.set_fx_effects(self.b, self.c, [self.freeze])
        self.p.set_fx_render([{"source": self.b, "output": "x"}])
        self.assertFalse(self.p.set_fx_a_end(self.a, self.b, None))
        self.assertIsNone(self.p.fx_for_pair(self.a, self.b))
        self.assertIsNotNone(self.p.data["fx"]["render"])

    def test_a_marker_alone_is_not_an_active_fx_pair(self):
        """A marker without effects must not make 'Apply all FX' think there is something to render."""
        self.p.set_fx_a_end(self.a, self.b, 9.0)
        self.assertEqual(self.p.active_fx_pairs(), [])
        self.assertEqual(self.p.fx_pending(), 0)

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

    def test_paths_with_a_pipe_and_error_results(self):
        weird = "/lib/a|weird.wav"
        self.p.set_tracks([{"file_path": x, "filename": os.path.basename(x)} for x in (weird, self.b, self.c)])
        self.p.set_order([weird, self.b, self.c])
        self.p.set_fx_effects(weird, self.b, [self.freeze])
        self.p.set_order([self.b, weird, self.c])
        self.assertEqual(self.p.inactive_fx_pairs(), [(weird, self.b)])
        os.makedirs(self.p.fx_dir)
        out = os.path.join(self.p.fx_dir, "b.wav")
        open(out, "wb").close()
        self.p.set_fx_render([{"source": self.b, "output": out, "error": "boom"}])
        self.assertEqual(self.p.fx_map(), {})


if __name__ == "__main__":
    unittest.main()
