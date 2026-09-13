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


if __name__ == "__main__":
    unittest.main()
