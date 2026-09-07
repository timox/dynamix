import os
import time
import unittest
from unittest.mock import patch

import analysis_store
from analysis_store import AnalysisStore


class TestAnalysisStore(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="dynamix_store_")
        self.db = os.path.join(self.tmp, "analysis.sqlite")
        self.file = os.path.join(self.tmp, "track.wav")
        with open(self.file, "wb") as f:
            f.write(b"\x00" * 1000)
        self.store = AnalysisStore(self.db)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip(self):
        self.assertIsNone(self.store.get(self.file, "features"))
        self.store.put(self.file, "features", {"bpm": 124.0, "sections": [("Intro", 0.0, 10.0)]})
        got = self.store.get(self.file, "features")
        self.assertEqual(got["bpm"], 124.0)
        self.assertEqual(got["sections"], [["Intro", 0.0, 10.0]])
        self.assertTrue(self.store.has(self.file, "features"))
        self.assertFalse(self.store.has(self.file, "mastering"))

    def test_miss_when_file_changes(self):
        self.store.put(self.file, "features", {"bpm": 124.0})
        time.sleep(0.01)
        with open(self.file, "ab") as f:
            f.write(b"\x01")
        self.assertIsNone(self.store.get(self.file, "features"))
        self.assertEqual(self.store.stats()["entries"], 0)  # stale row was dropped

    def test_miss_when_analyzer_version_changes(self):
        self.store.put(self.file, "features", {"bpm": 124.0})
        with patch.object(analysis_store, "ANALYZER_VERSION", "other"):
            self.assertIsNone(self.store.get(self.file, "features"))

    def test_stats_and_clear(self):
        self.store.put(self.file, "features", {"a": 1})
        self.store.put(self.file, "mastering", {"b": 2})
        stats = self.store.stats()
        self.assertEqual((stats["entries"], stats["files"]), (2, 1))
        self.assertEqual(self.store.clear(self.file), 2)
        self.assertEqual(self.store.stats()["entries"], 0)

    def test_unreachable_database_degrades_gracefully(self):
        store = AnalysisStore(self.db)
        store.db_path = os.path.join(self.tmp, "missing_dir", "x.sqlite")  # cannot be opened
        self.assertFalse(store.put(self.file, "features", {"a": 1}))
        self.assertIsNone(store.get(self.file, "features"))

    def test_numpy_values_are_serialised(self):
        import numpy as np
        self.store.put(self.file, "features", {"bpm": np.float64(120.5), "beats": np.array([1, 2])})
        got = self.store.get(self.file, "features")
        self.assertEqual(got["bpm"], 120.5)
        self.assertEqual(got["beats"], [1, 2])


class TestPlaylistManagerUsesCache(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="dynamix_pm_")
        os.environ["DYNAMIX_HOME"] = self.tmp
        analysis_store.reset_store()
        import numpy as np
        import soundfile as sf
        sr = 22050
        t = np.linspace(0, 8, 8 * sr, endpoint=False)
        y = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.5 * (np.sin(2 * np.pi * 2.0 * t) > 0.97)
        self.track = os.path.join(self.tmp, "a.wav")
        sf.write(self.track, y.astype("float32"), sr)

    def tearDown(self):
        import shutil
        os.environ.pop("DYNAMIX_HOME", None)
        analysis_store.reset_store()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_analysis_hits_cache(self):
        from playlist_manager import PlaylistManager
        import playlist_manager
        manager = PlaylistManager(self.tmp)
        manager.analyze_playlist([self.track])
        self.assertEqual(manager.last_run["analyzed"], 1)
        with patch.object(playlist_manager, "AudioAnalyzer", side_effect=AssertionError("should not analyse")):
            manager2 = PlaylistManager(self.tmp)
            manager2.analyze_playlist([self.track])
        self.assertEqual(manager2.last_run["cached"], 1)
        self.assertEqual(manager2.tracks[0]["file_path"], manager.tracks[0]["file_path"])
        self.assertAlmostEqual(manager2.tracks[0]["bpm"], manager.tracks[0]["bpm"])


if __name__ == "__main__":
    unittest.main()
