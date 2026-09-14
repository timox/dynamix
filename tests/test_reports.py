#!/usr/bin/env python3
"""Reports of a project: text files in exports/reports, listed in the Log tab."""

import datetime
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reports

NOW = datetime.datetime(2026, 9, 14, 21, 5, 33)


class TestReports(unittest.TestCase):
    def setUp(self):
        self.folder = os.path.join(tempfile.mkdtemp(), "reports")

    def tearDown(self):
        shutil.rmtree(os.path.dirname(self.folder), ignore_errors=True)

    def test_write_names_the_file_after_the_time_and_title(self):
        path = reports.write_report(self.folder, "Band Analysis", "hello", now=NOW)
        self.assertEqual(os.path.basename(path), "2026-09-14 21-05-33 Band Analysis.txt")
        self.assertEqual(reports.read_report(path), "hello")

    def test_forbidden_characters_and_collisions(self):
        first = reports.write_report(self.folder, 'A/B: "x"?', "1", now=NOW)
        second = reports.write_report(self.folder, 'A/B: "x"?', "2", now=NOW)
        self.assertEqual(os.path.basename(first), "2026-09-14 21-05-33 A-B- -x--.txt")
        self.assertEqual(os.path.basename(second), "2026-09-14 21-05-33 A-B- -x-- (2).txt")
        self.assertEqual(reports.read_report(second), "2")

    def test_list_is_oldest_first_with_title_and_time(self):
        reports.write_report(self.folder, "Later", "b", now=NOW + datetime.timedelta(minutes=1))
        reports.write_report(self.folder, "Earlier", "a", now=NOW)
        reports.write_report(self.folder, "Earlier", "a2", now=NOW)
        open(os.path.join(self.folder, "notes.md"), "w").close()
        listed = reports.list_reports(self.folder)
        self.assertEqual([r["title"] for r in listed], ["Earlier", "Earlier (2)", "Later"])
        self.assertEqual(listed[0]["time"], "2026-09-14 21:05:33")
        self.assertTrue(all(os.path.isfile(r["path"]) for r in listed))

    def test_missing_folder_lists_nothing(self):
        self.assertEqual(reports.list_reports(self.folder), [])
        self.assertEqual(reports.list_reports(""), [])


if __name__ == "__main__":
    unittest.main()
