import os
import shutil
import tempfile
import unittest

from set_project import SetProject, STEPS, list_projects


class TestSetProject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_set_")
        self.root = os.path.join(self.tmp, "projects")
        self.music = os.path.join(self.tmp, "music")
        os.makedirs(self.music)
        for name in ("b.wav", "a.wav", "notes.txt"):
            with open(os.path.join(self.music, name), "wb") as f:
                f.write(b"\x00" * (100 if name.endswith(".wav") else 5))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_layout_and_import(self):
        p = SetProject.create(self.root, "Saturday set", self.music)
        self.assertTrue(os.path.isdir(p.source_dir) and os.path.isdir(p.premaster_dir) and os.path.isdir(p.exports_dir))
        counts = p.import_folder(self.music)
        self.assertEqual(counts, {"copied": 2, "skipped": 0, "failed": 0})
        self.assertEqual([os.path.basename(f) for f in p.source_files()], ["a.wav", "b.wav"])
        # importing again copies nothing
        self.assertEqual(p.import_folder(self.music)["skipped"], 2)
        self.assertEqual(len(p.data["imported"]), 2)
        self.assertEqual(list_projects(self.root), [p.folder])
        q = SetProject.open(p.path)
        self.assertEqual(q.name, "Saturday set")
        self.assertEqual(q.data["source_folder"], os.path.abspath(self.music))

    def test_create_twice_fails(self):
        SetProject.create(self.root, "x")
        with self.assertRaises(FileExistsError):
            SetProject.create(self.root, "x")

    def test_set_list_editing_invalidates_later_steps(self):
        p = SetProject.create(self.root, "edit")
        p.set_tracks([{"file_path": "/m/a.wav"}, {"file_path": "/m/b.wav"}, {"file_path": "/m/c.wav"}])
        p.set_set_list([{"file_path": "/m/a.wav"}, {"file_path": "/m/b.wav"}])
        for key, _, _ in STEPS:
            p.mark(key)
        p.data["transitions"] = {"tracks": []}
        p.add_to_set("/m/c.wav")
        self.assertEqual(p.set_list, ["/m/a.wav", "/m/b.wav", "/m/c.wav"])
        self.assertTrue(p.is_done("setlist"))
        self.assertFalse(p.is_done("transitions"))
        self.assertIsNone(p.data["transitions"])
        self.assertEqual(p.move_in_set("/m/c.wav", -2), 0)
        self.assertEqual(p.set_list, ["/m/c.wav", "/m/a.wav", "/m/b.wav"])
        self.assertEqual(p.move_in_set("/m/c.wav", -1), 0)  # already first
        p.remove_from_set("/m/a.wav")
        self.assertEqual(p.set_list, ["/m/c.wav", "/m/b.wav"])
        lib = p.library_tracks()
        self.assertEqual([(t["file_path"], t["set_position"]) for t in lib],
                         [("/m/a.wav", None), ("/m/b.wav", 2), ("/m/c.wav", 1)])
        p.add_to_set("/m/unknown.wav")  # ignored
        self.assertEqual(len(p.set_list), 2)
        p.set_order(["/m/b.wav", "/m/c.wav", "/m/zzz.wav"])
        self.assertEqual(p.set_list, ["/m/b.wav", "/m/c.wav"])

    def test_next_step_order(self):
        p = SetProject.create(self.root, "steps")
        self.assertEqual(p.next_step()[0], "analyze")
        p.mark("analyze"); p.mark("setlist"); p.mark("transitions")
        self.assertEqual(p.next_step()[0], "mixxx")
        p.mark("mixxx")
        self.assertEqual(p.next_step()[0], "done")

    def test_summary_lines(self):
        p = SetProject.create(self.root, "sum")
        p.mark("analyze", count=3)
        lines = p.summary_lines()
        self.assertTrue(any("[x] Analyze the tracks" in l and "count=3" in l for l in lines))
        self.assertTrue(lines[-1].startswith("Next:"))


if __name__ == "__main__":
    unittest.main()
