#!/usr/bin/env python3
"""Project snapshots (settings only) and the 'use pre-mastered copies' option."""

import datetime
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from set_project import SetProject

A, B, C = "/m/a.wav", "/m/b.wav", "/m/c.wav"


class ProjectCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_snap_")
        self.p = SetProject.create(os.path.join(self.tmp, "projects"), "snap")
        self.p.set_tracks([{"file_path": f, "filename": os.path.basename(f), "duration": 200.0} for f in (A, B, C)],
                          attempted=[])
        self.p.set_order([A, B, C])
        self.p.mark("analyze")
        self.p.mark("setlist")
        self.p.set_fx_effects(A, B, [{"type": "echo"}])
        self.p.save()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def copy(self, name, size=100):
        path = os.path.join(self.p.folder, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"\x00" * size)
        return path

    def with_copies(self):
        pm = self.copy("premaster/a.wav")
        fx = self.copy("fx/a.wav")
        self.p.data["premaster"] = {"results": [{"input": A, "output": pm}]}
        self.p.mark("premaster")
        self.p.set_fx_render([{"source": A, "output": fx}])
        for step in ("fx", "playlist", "mixxx"):
            self.p.mark(step)
        self.p.save()
        return pm, fx


class TestSnapshots(ProjectCase):
    def test_save_list_and_restore(self):
        path = self.p.save_snapshot("first try", now=datetime.datetime(2026, 9, 14, 18, 40, 12))
        self.assertEqual(os.path.basename(path), "2026-09-14 18-40-12 first try.json")
        self.p.set_order([C, B, A])
        self.p.set_fx_effects(A, B, [])
        self.p.save()
        result = self.p.restore_snapshot(path)
        self.assertEqual(self.p.set_list, [A, B, C])
        self.assertEqual(self.p.fx_for_pair(A, B)["effects"], [{"type": "echo"}])
        self.assertEqual(SetProject.open(self.p.folder).set_list, [A, B, C])     # saved to disk
        snaps = self.p.list_snapshots()
        self.assertEqual(sorted(s["label"] for s in snaps), ["before restore", "first try"])
        before = [s for s in snaps if s["label"] == "before restore"][0]
        self.assertEqual((before["path"], before["set_list"], before["fx"]), (result["before"], 3, 0))
        self.assertEqual(result["stale"], [])

    def test_unchanged_copies_are_kept(self):
        self.with_copies()
        path = self.p.save_snapshot("with copies")
        result = self.p.restore_snapshot(path)
        self.assertEqual(result["stale"], [])
        self.assertTrue(self.p.is_done("premaster") and self.p.is_done("fx"))
        self.assertIsNotNone(self.p.data["fx"]["render"])
        self.assertFalse(self.p.is_done("playlist") or self.p.is_done("mixxx"))   # written outside the project

    def test_rewritten_copies_are_to_redo(self):
        pm, _ = self.with_copies()
        path = self.p.save_snapshot("with copies")
        with open(pm, "wb") as f:
            f.write(b"\x01" * 250)                                               # pre-mastered again since
        result = self.p.restore_snapshot(path)
        self.assertEqual(result["stale"], ["premaster"])
        self.assertIsNone(self.p.data["premaster"])
        self.assertFalse(self.p.is_done("premaster") or self.p.is_done("fx"))
        self.assertIsNone(self.p.data["fx"]["render"])

    def test_missing_fx_copy_is_to_redo(self):
        _, fx = self.with_copies()
        path = self.p.save_snapshot("with copies")
        os.remove(fx)
        result = self.p.restore_snapshot(path)
        self.assertEqual(result["stale"], ["fx"])
        self.assertTrue(self.p.is_done("premaster"))
        self.assertFalse(self.p.is_done("fx"))


class TestUsePremaster(ProjectCase):
    def test_option_switches_the_audio_and_invalidates_the_render(self):
        pm, fx = self.with_copies()
        os.remove(fx)
        self.assertEqual(self.p.premaster_map(), {A: pm})
        self.assertIn("pre-mastered copies 1", self.p.audio_used_text())
        self.assertTrue(self.p.set_use_premaster(False))
        self.assertEqual(self.p.premaster_map(), {})
        self.assertIsNone(self.p.data["fx"]["render"])
        self.assertFalse(self.p.is_done("fx") or self.p.is_done("playlist"))
        self.assertIn("originals 3", self.p.audio_used_text())
        self.assertIn("not used", self.p.audio_used_text())
        self.assertFalse(self.p.set_use_premaster(False))                        # no change
        self.assertTrue(self.p.set_use_premaster(True))
        self.assertEqual(self.p.premaster_map(), {A: pm})

    def test_text_without_pre_master(self):
        self.assertIn("no pre-master yet", self.p.audio_used_text())
        self.assertTrue(SetProject(self.p.folder).options["use_premaster"])       # default for old projects


if __name__ == "__main__":
    unittest.main()
