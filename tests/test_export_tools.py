#!/usr/bin/env python3
"""M3U playlist writing: the entries, and the files that are not on disk."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export_tools import ExportTools


class TestExportToM3u(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_m3u_")
        self.here = os.path.join(self.tmp, "here.wav")
        open(self.here, "wb").close()
        self.gone = os.path.join(self.tmp, "fx", "gone.wav")
        self.out = os.path.join(self.tmp, "set.m3u")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def written(self):
        with open(self.out, encoding="utf-8") as f:
            return f.read()

    def test_extended_entries(self):
        missing = ExportTools.export_to_m3u([{"file_path": self.here, "filename": "here.wav", "duration": 123.7}], self.out)
        self.assertEqual(missing, [])
        lines = self.written().splitlines()
        self.assertEqual(lines, ["#EXTM3U", "#EXTINF:123,here.wav", self.here])

    def test_files_not_on_disk_are_reported(self):
        """A copy that is not there any more must be named, not written in silence."""
        missing = ExportTools.export_to_m3u([{"file_path": self.here}, {"file_path": self.gone}], self.out)
        self.assertEqual(missing, [self.gone])
        self.assertIn(self.gone, self.written())        # still written: the user puts the file back


class TestMixxxCopyFolders(unittest.TestCase):
    """Missing tracks that are DynaMix copies: the report must name the folders to add to the Mixxx library."""

    def test_only_copy_folders_are_named(self):
        from mixxx_export import copy_folders
        root = os.path.join("C:\\", "Projects", "Saturday")
        missing = [os.path.join(root, "fx", "a.wav"), os.path.join(root, "fx", "b.wav"),
                   os.path.join(root, "premaster", "c.wav"), os.path.join("D:\\", "Music", "d.mp3")]
        self.assertEqual(copy_folders(missing), [os.path.join(root, "fx"), os.path.join(root, "premaster")])
        self.assertEqual(copy_folders([os.path.join("D:\\", "Music", "d.mp3")]), [])
        self.assertEqual(copy_folders([]), [])


if __name__ == "__main__":
    unittest.main()
