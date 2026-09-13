import json
import os
import shutil
import tempfile
import unittest

from set_project import SetProject, STEPS


class TestSelectionAndProposals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_v3_")
        self.root = os.path.join(self.tmp, "projects")
        self.lib = os.path.join(self.tmp, "Mixes")
        os.makedirs(self.lib)
        self.a, self.b, self.c = (os.path.join(self.lib, n) for n in ("a.wav", "b.wav", "c.wav"))
        for p in (self.a, self.b, self.c):
            with open(p, "wb") as f:
                f.write(b"\x00" * 10)
        self.p = SetProject.create(self.root, "v3")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _analysed(self, *paths):
        self.p.set_tracks([{"file_path": x, "filename": os.path.basename(x), "duration": 300.0, "bpm": 124.0,
                            "key": "A minor", "energy_level": 5.0} for x in paths])

    def test_new_project_has_no_source_folder(self):
        self.assertFalse(os.path.isdir(self.p.source_dir))
        self.assertTrue(os.path.isdir(self.p.premaster_dir) and os.path.isdir(self.p.exports_dir))
        self.assertEqual(self.p.data["version"], 3)

    def test_add_and_remove_selection(self):
        for key, _, _ in STEPS:
            self.p.mark(key)
        self.assertEqual(self.p.add_to_selection([self.b, self.a, self.b]), 2)
        self.assertEqual(self.p.selection, [self.b, self.a])
        self.assertFalse(self.p.is_done("analyze"))
        self.assertFalse(self.p.is_done("setlist"))
        self.assertEqual(self.p.add_to_selection([self.a]), 0)
        self._analysed(self.a, self.b)
        self.p.set_order([self.a, self.b])
        self.p.data["proposals"] = {"variants": [{}]}
        self.p.mark("analyze")
        self.assertEqual(self.p.remove_from_selection([self.a, "/elsewhere.wav"]), 1)
        self.assertEqual(self.p.selection, [self.b])
        self.assertEqual([t["file_path"] for t in self.p.tracks], [self.b])
        self.assertEqual(self.p.set_list, [self.b])
        self.assertIsNone(self.p.data["proposals"])
        self.assertTrue(self.p.is_done("analyze"))

    def test_selection_states_and_proposal_tracks(self):
        ghost = os.path.join(self.lib, "gone.wav")
        self.p.add_to_selection([self.a, self.b, self.c, ghost])
        self._analysed(self.a)  # b and c exist but are not analysed -> failed
        self.p.add_to_selection([os.path.join(self.lib, "new.wav")])
        with open(os.path.join(self.lib, "new.wav"), "wb") as f:
            f.write(b"\x00")
        states = {os.path.basename(r["file_path"]): r["state"] for r in self.p.selection_rows()}
        self.assertEqual(states, {"a.wav": "analysed", "b.wav": "failed", "c.wav": "failed",
                                  "gone.wav": "missing", "new.wav": "pending"})
        usable, skipped = self.p.proposal_tracks()
        self.assertEqual([t["file_path"] for t in usable], [self.a])
        self.assertNotIn("state", usable[0])
        self.assertEqual(skipped, ["b.wav", "c.wav", "gone.wav", "new.wav"])
        self.assertEqual(self.p.selection_files(), [self.a, self.b, self.c, os.path.join(self.lib, "new.wav")])

    def test_proposals_are_stored_and_used(self):
        self.p.add_to_selection([self.a, self.b, self.c])
        self._analysed(self.a, self.b, self.c)
        self.p.mark("analyze")
        variants = [{"curve": "build", "tracks": [{"file_path": self.b}], "order": [self.b, self.a], "score": 80},
                    {"curve": "wave", "tracks": [], "order": [self.c, self.a, self.b], "score": 70}]
        self.p.set_proposals({"duration_min": 60, "curve": "all"}, variants)
        self.p.save()
        q = SetProject.open(self.p.folder)
        self.assertEqual(len(q.proposal_variants()), 2)
        self.assertNotIn("tracks", q.proposal_variants()[0])
        self.assertEqual(q.data["proposals"]["params"]["curve"], "all")
        q.mark("transitions")
        self.assertEqual(q.use_proposal(1), [self.c, self.a, self.b])
        self.assertTrue(q.is_done("setlist"))
        self.assertEqual(q.step_state("setlist")["details"]["curve"], "wave")
        self.assertFalse(q.is_done("transitions"))
        with self.assertRaises(IndexError):
            q.use_proposal(5)

    def test_set_tracks_with_attempted_files(self):
        self.p.add_to_selection([self.a, self.b])
        attempted = [self.a, self.b]
        self.p.add_to_selection([self.c])  # added while the analysis ran
        self.p.set_tracks([{"file_path": self.a, "filename": "a.wav"}], attempted=attempted)
        self.assertEqual(self.p.data["failed"], [self.b])
        states = {os.path.basename(r["file_path"]): r["state"] for r in self.p.selection_rows()}
        self.assertEqual(states, {"a.wav": "analysed", "b.wav": "failed", "c.wav": "pending"})

    def test_set_tracks_attempted_path_removed_meanwhile_is_not_failed(self):
        self.p.add_to_selection([self.a, self.b])
        attempted = [self.a, self.b]
        self.p.remove_from_selection([self.b])
        self.p.set_tracks([], attempted=attempted)
        self.assertEqual(self.p.data["failed"], [self.a])

    def test_forget_analysis(self):
        self.p.add_to_selection([self.a])
        self._analysed(self.a)
        self.p.set_order([self.a])
        self.p.mark("analyze")
        self.p.mark("setlist")
        self.p.data["proposals"] = {"variants": [{}]}
        self.p.forget_analysis()
        self.assertEqual(self.p.tracks, [])
        self.assertIsNone(self.p.data["proposals"])
        self.assertFalse(self.p.is_done("analyze") or self.p.is_done("setlist"))
        self.assertEqual(self.p.selection, [self.a])
        self.assertEqual(self.p.selection_rows()[0]["state"], "pending")


class TestMigrationAndReset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_reset_")
        self.root = os.path.join(self.tmp, "projects")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, size):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"\x00" * size)

    def test_version_2_project_is_migrated(self):
        folder = os.path.join(self.root, "old")
        self._write(os.path.join(folder, "source", "x.wav"), 10)
        self._write(os.path.join(folder, "source", "y.mp3"), 10)
        track = {"file_path": os.path.join(folder, "source", "x.wav"), "filename": "x.wav"}
        with open(os.path.join(folder, "project.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 2, "name": "old", "tracks": [track], "set_list": [track["file_path"]],
                       "steps": {"analyze": {"done": True, "at": "2026-09-01T10:00:00", "details": {}}}}, f)
        p = SetProject.open(folder)
        self.assertEqual(p.data["version"], 3)
        self.assertEqual([os.path.basename(x) for x in p.selection], ["x.wav", "y.mp3"])
        self.assertIsNone(p.data["proposals"])
        self.assertEqual(p.set_list, [track["file_path"]])
        self.assertTrue(p.is_done("analyze"))

    def test_reset_keeps_options_and_imported_copies(self):
        p = SetProject.create(self.root, "gig", options={"set_duration": 90})
        p.data["notes"] = "warm-up"
        p.add_to_selection(["/lib/a.wav"])
        p.set_tracks([{"file_path": "/lib/a.wav"}])
        p.set_order(["/lib/a.wav"])
        p.data["transitions"] = {"tracks": []}
        p.data["premaster"] = {"results": []}
        for key, _, _ in STEPS:
            p.mark(key)
        self._write(os.path.join(p.premaster_dir, "a.wav"), 100)
        self._write(os.path.join(p.exports_dir, "charts", "overview.png"), 50)
        self._write(os.path.join(p.exports_dir, "gig.m3u"), 5)
        self._write(os.path.join(p.source_dir, "old.wav"), 1000)
        preview = p.reset_preview()
        self.assertEqual(preview, {"outputs": {"files": 3, "bytes": 155}, "imported": {"files": 1, "bytes": 1000}})
        self.assertEqual(p.reset(), {"files_deleted": 3, "bytes_deleted": 155})
        q = SetProject.open(p.folder)
        self.assertEqual((q.selection, q.tracks, q.set_list), ([], [], []))
        self.assertIsNone(q.data["transitions"])
        self.assertIsNone(q.data["premaster"])
        self.assertTrue(all(not q.is_done(k) for k, _, _ in STEPS))
        self.assertEqual(q.options["set_duration"], 90)
        self.assertEqual((q.name, q.data["notes"]), ("gig", "warm-up"))
        self.assertEqual(os.listdir(q.premaster_dir), [])
        self.assertEqual(os.listdir(q.exports_dir), [])
        self.assertEqual(os.listdir(q.source_dir), ["old.wav"])

    def test_reset_can_delete_imported_copies(self):
        p = SetProject.create(self.root, "gig2")
        self._write(os.path.join(p.source_dir, "old.wav"), 1000)
        p.data["imported"] = [{"original": "/m/old.wav", "path": os.path.join(p.source_dir, "old.wav"), "size": 1000}]
        self.assertEqual(p.reset(delete_imported=True), {"files_deleted": 1, "bytes_deleted": 1000})
        self.assertEqual(os.listdir(p.source_dir), [])
        self.assertEqual(p.data["imported"], [])


if __name__ == "__main__":
    unittest.main()
