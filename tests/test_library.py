import os
import shutil
import tempfile
import unittest

import numpy as np
import soundfile as sf

import analysis_store


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_lib_")
        os.environ["DYNAMIX_HOME"] = os.path.join(self.tmp, "home")
        analysis_store.reset_store()
        self.lib = os.path.join(self.tmp, "Mixes")
        os.makedirs(os.path.join(self.lib, "2025"))
        sr = 8000
        self.one = os.path.join(self.lib, "b one second.wav")
        self.two = os.path.join(self.lib, "2025", "a two seconds.wav")
        sf.write(self.one, np.zeros(sr, dtype="float32"), sr)
        sf.write(self.two, np.zeros(2 * sr, dtype="float32"), sr)
        with open(os.path.join(self.lib, "notes.txt"), "w") as f:
            f.write("not audio")
        self.broken = os.path.join(self.lib, "c broken.wav")
        with open(self.broken, "wb") as f:
            f.write(b"not a wav file")

    def tearDown(self):
        os.environ.pop("DYNAMIX_HOME", None)
        analysis_store.reset_store()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_read_duration(self):
        from library import read_duration
        self.assertAlmostEqual(read_duration(self.one), 1.0)
        self.assertIsNone(read_duration(self.broken))

    def test_scan_reads_durations_and_merges_the_cache(self):
        from library import scan
        analysis_store.get_store().put(self.two, "features",
                                       {"duration": 99.0, "bpm": 128.0, "key": "A minor", "energy_level": 7.0})
        seen = []
        entries = scan(self.lib, progress=lambda i, n, name: seen.append((i, n)))
        self.assertEqual([e["filename"] for e in entries], ["a two seconds.wav", "b one second.wav", "c broken.wav"])
        self.assertEqual(seen[-1], (3, 3))
        cached, plain, broken = entries
        self.assertEqual((cached["analysed"], cached["duration"], cached["bpm"], cached["key"], cached["energy_level"]),
                         (True, 99.0, 128.0, "A minor", 7.0))
        self.assertEqual((plain["analysed"], plain["bpm"]), (False, None))
        self.assertAlmostEqual(plain["duration"], 1.0)
        self.assertIsNone(broken["duration"])
        self.assertEqual(plain["file_path"], os.path.abspath(self.one))

    def test_missing_folder(self):
        from library import scan
        with self.assertRaises(FileNotFoundError):
            scan(os.path.join(self.tmp, "nowhere"))
        with self.assertRaises(FileNotFoundError):
            scan("")

    def test_filter_entries(self):
        from library import filter_entries
        entries = [{"filename": "Deep House Mix.wav"}, {"filename": "techno.flac"}]
        self.assertEqual(filter_entries(entries, "HOUSE"), [entries[0]])
        self.assertEqual(filter_entries(entries, "  "), entries)

    def test_filter_entries_also_matches_the_folder_a_sample_came_from(self):
        from library import filter_entries
        entries = [{"filename": "riser.wav", "root_name": "Vengeance"}, {"filename": "riser.wav", "root_name": "Splice"}]
        self.assertEqual(filter_entries(entries, "vengeance"), [entries[0]])
        self.assertEqual(filter_entries(entries, "riser"), entries)


class TestScanMany(unittest.TestCase):
    """Several FX sample folders are scanned as one list, and a folder that went away must not break it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_many_")
        os.environ["DYNAMIX_HOME"] = os.path.join(self.tmp, "home")
        analysis_store.reset_store()
        sr = 8000
        self.a = os.path.join(self.tmp, "Vengeance")
        self.b = os.path.join(self.tmp, "Splice")
        for folder, names in ((self.a, ("riser.wav", "zap.wav")), (self.b, ("riser.wav", "impact.wav"))):
            os.makedirs(folder)
            for name in names:
                sf.write(os.path.join(folder, name), np.zeros(sr, dtype="float32"), sr)

    def tearDown(self):
        os.environ.pop("DYNAMIX_HOME", None)
        analysis_store.reset_store()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_folders_are_merged_sorted_and_tagged(self):
        from library import scan_many
        entries, missing = scan_many([self.a, self.b], use_cache=False)
        self.assertEqual(missing, [])
        self.assertEqual([(e["filename"], e["root_name"]) for e in entries],
                         [("impact.wav", "Splice"), ("riser.wav", "Splice"), ("riser.wav", "Vengeance"),
                          ("zap.wav", "Vengeance")])
        self.assertEqual(entries[0]["root"], self.b)

    def test_a_folder_that_went_away_is_reported_not_raised(self):
        from library import scan_many
        gone = os.path.join(self.tmp, "nowhere")
        entries, missing = scan_many([self.a, gone, ""], use_cache=False)
        self.assertEqual(missing, [gone])
        self.assertEqual([e["filename"] for e in entries], ["riser.wav", "zap.wav"])

    def test_the_same_folder_twice_is_read_once(self):
        from library import scan_many
        entries, missing = scan_many([self.a, self.a + os.sep], use_cache=False)
        self.assertEqual(missing, [])
        self.assertEqual([e["filename"] for e in entries], ["riser.wav", "zap.wav"])

    def test_no_folder_at_all(self):
        from library import scan_many
        self.assertEqual(scan_many([], use_cache=False), ([], []))

    def test_same_named_folders_are_told_apart(self):
        """Sample packs are usually sorted into 'loops' and 'oneshots': the bare folder name is not enough."""
        from library import scan_many
        sr = 8000
        deep = []
        for pack in ("Vengeance", "Splice"):
            folder = os.path.join(self.tmp, "Packs", pack, "loops")
            os.makedirs(folder)
            sf.write(os.path.join(folder, "riser.wav"), np.zeros(sr, dtype="float32"), sr)
            deep.append(folder)
        entries, _ = scan_many(deep + [self.a], use_cache=False)
        labels = {(e["filename"], e["root_name"]) for e in entries}
        self.assertIn(("riser.wav", os.path.join("Vengeance", "loops")), labels)
        self.assertIn(("riser.wav", os.path.join("Splice", "loops")), labels)
        self.assertIn(("riser.wav", "Vengeance"), labels)          # that one is already unique: kept short
        self.assertIn(("zap.wav", "Vengeance"), labels)


class TestRootLabels(unittest.TestCase):
    """The shortest tail of each path that tells them all apart."""

    def labels(self, paths):
        from library import root_labels
        return [root_labels([os.path.normpath(p) for p in paths])[os.path.normpath(p)] for p in paths]

    def test_unique_names_stay_short(self):
        self.assertEqual(self.labels([r"D:\Samples\Perso", r"D:\Samples\Splice"]), ["Perso", "Splice"])

    def test_a_clash_grows_by_one_folder_at_a_time(self):
        self.assertEqual(self.labels([r"D:\Packs\Vengeance\loops", r"D:\Packs\Splice\loops"]),
                         [os.path.join("Vengeance", "loops"), os.path.join("Splice", "loops")])

    def test_only_the_clashing_ones_grow(self):
        got = self.labels([r"D:\Packs\Vengeance\loops", r"D:\Packs\Splice\loops", r"D:\Packs\Perso"])
        self.assertEqual(got, [os.path.join("Vengeance", "loops"), os.path.join("Splice", "loops"), "Perso"])

    def test_a_clash_that_needs_the_drive(self):
        self.assertEqual(self.labels([r"D:\loops", r"E:\loops"]),
                         [os.path.normpath(r"D:\loops"), os.path.normpath(r"E:\loops")])

    def test_siblings_of_a_lengthened_folder_follow_it(self):
        """'oneshots' alone would not say which pack it belongs to while its sibling 'loops' does."""
        got = self.labels([r"D:\Packs\Vengeance\loops", r"D:\Packs\Vengeance\oneshots",
                           r"D:\Packs\Splice\loops", r"D:\Perso"])
        self.assertEqual(got, [os.path.join("Vengeance", "loops"), os.path.join("Vengeance", "oneshots"),
                               os.path.join("Splice", "loops"), "Perso"])

    def test_a_lone_folder_is_not_lengthened_by_a_stranger(self):
        """Only the folders under the same parent follow; an unrelated clash elsewhere changes nothing."""
        got = self.labels([r"D:\Packs\Vengeance\loops", r"D:\Packs\Splice\loops", r"D:\Other\oneshots"])
        self.assertEqual(got, [os.path.join("Vengeance", "loops"), os.path.join("Splice", "loops"), "oneshots"])

    def test_one_folder_and_none(self):
        self.assertEqual(self.labels([r"D:\Packs\loops"]), ["loops"])
        from library import root_labels
        self.assertEqual(root_labels([]), {})


if __name__ == "__main__":
    unittest.main()
