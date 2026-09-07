import os
import shutil
import tempfile
import unittest

from set_project import SetProject, STEPS


class TestSetProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_set_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip(self):
        p = SetProject(self.tmp)
        self.assertFalse(SetProject.exists(self.tmp))
        p.set_tracks([{"file_path": "/m/a.wav", "bpm": 120.0}, {"file_path": "/m/b.wav", "bpm": 124.0}])
        p.set_set_list([{"file_path": "/m/b.wav"}, {"file_path": "/m/a.wav"}])
        p.options["set_duration"] = 45
        p.mark("analyze", count=2)
        p.save()
        self.assertTrue(SetProject.exists(self.tmp))
        q = SetProject(self.tmp)
        self.assertEqual(q.options["set_duration"], 45)
        self.assertEqual([t["file_path"] for t in q.set_list_tracks()], ["/m/b.wav", "/m/a.wav"])
        self.assertTrue(q.is_done("analyze"))
        self.assertEqual(q.step_state("analyze")["details"], {"count": 2})
        self.assertIsNotNone(q.step_state("analyze")["at"])

    def test_next_step_order(self):
        p = SetProject(self.tmp)
        self.assertEqual(p.next_step()[0], "analyze")
        p.mark("analyze")
        self.assertEqual(p.next_step()[0], "setlist")
        p.mark("setlist")
        p.mark("transitions")
        # premaster and playlist are optional: next required is mixxx
        self.assertEqual(p.next_step()[0], "mixxx")
        p.mark("mixxx")
        self.assertEqual(p.next_step()[0], "done")

    def test_invalidate_from(self):
        p = SetProject(self.tmp)
        for key, _, _ in STEPS:
            p.mark(key)
        p.data["transitions"] = {"tracks": []}
        p.invalidate_from("setlist")
        self.assertTrue(p.is_done("analyze"))
        self.assertTrue(p.is_done("setlist"))
        self.assertFalse(p.is_done("transitions"))
        self.assertFalse(p.is_done("mixxx"))
        self.assertIsNone(p.data["transitions"])

    def test_set_tracks_drops_unknown_from_set_list(self):
        p = SetProject(self.tmp)
        p.set_tracks([{"file_path": "/m/a.wav"}, {"file_path": "/m/b.wav"}])
        p.set_set_list([{"file_path": "/m/b.wav"}, {"file_path": "/m/a.wav"}])
        p.set_tracks([{"file_path": "/m/a.wav"}])
        self.assertEqual(p.data["set_list"], ["/m/a.wav"])

    def test_summary_lines(self):
        p = SetProject(self.tmp)
        p.mark("analyze", count=3)
        lines = p.summary_lines()
        self.assertTrue(any("[x] Analyze the tracks" in l and "count=3" in l for l in lines))
        self.assertTrue(lines[-1].startswith("Next:"))


if __name__ == "__main__":
    unittest.main()
