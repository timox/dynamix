#!/usr/bin/env python3
"""A steady beat grid over the whole track decides whether a track has a beat (soft percussion, breaks, long intros)."""

import os
import shutil
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analysis_store
from audio_utils import AudioAnalyzer, grid_is_regular, upgrade_features

# measured components of a 129 BPM track with soft percussion (percussive share 0.09 -> beat gate 0.18)
SOFT = {"tempo": 129.0, "onset_rate": 3.0, "percussive": 0.09, "low_end": 0.25, "brightness": 2000.0, "beat_gate": 0.18}
STEADY = [i * 0.465 for i in range(400)]


class TestSteadyBeat(unittest.TestCase):
    def test_grid_is_regular(self):
        self.assertTrue(grid_is_regular(STEADY))
        self.assertFalse(grid_is_regular(np.cumsum(np.random.default_rng(1).uniform(0.2, 0.9, 50))))
        self.assertFalse(grid_is_regular(STEADY[:5]))

    def test_a_steady_beat_counts_the_tempo_in_the_energy_level(self):
        gated = AudioAnalyzer.level_from_components(SOFT)
        steady = AudioAnalyzer.level_from_components(SOFT, beat_regular=True)
        self.assertGreater(steady, gated + 2.0)
        self.assertEqual(AudioAnalyzer.level_from_components(dict(SOFT, beat_gate=1.0)), steady)


class TestUpgradeCachedFeatures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_beat_")
        os.environ["DYNAMIX_HOME"] = self.tmp
        analysis_store.reset_store()
        self.path = os.path.join(self.tmp, "soft.wav")
        sf.write(self.path, np.zeros(22050, dtype="float32"), 22050)
        analysis_store.get_store().put(self.path, "beats", {"beats": STEADY, "bpm": 129.0, "has_beat": True, "duration": 186.0})
        self.old = {"duration": 186.0, "bpm": 129.0, "bpm_confidence": 0.9, "key": "A minor", "key_confidence": 0.5,
                    "avg_energy": 0.1, "max_energy": 0.3, "energy_std": 0.05, "beat_count": 400,
                    "energy_level": AudioAnalyzer.level_from_components(SOFT), "has_beat": False, "energy_components": SOFT}

    def tearDown(self):
        os.environ.pop("DYNAMIX_HOME", None)
        analysis_store.reset_store()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_upgrade_uses_the_beat_grid(self):
        up = upgrade_features(self.path, self.old)
        self.assertTrue(up["beat_regular"] and up["has_beat"])
        self.assertEqual(up["energy_level"], AudioAnalyzer.level_from_components(SOFT, beat_regular=True))
        self.assertFalse(self.old["has_beat"])                                   # the cached dict is not modified
        self.assertIs(upgrade_features(os.path.join(self.tmp, "missing.wav"), self.old), self.old)

    def test_analysis_upgrades_cached_features_once(self):
        from playlist_manager import PlaylistManager
        store = analysis_store.get_store()
        store.put(self.path, "features", self.old)
        manager = PlaylistManager(self.tmp)
        manager.analyze_playlist([self.path])
        self.assertEqual(manager.last_run["cached"], 1)
        self.assertTrue(manager.tracks[0]["has_beat"])
        self.assertGreater(manager.tracks[0]["energy_level"], self.old["energy_level"] + 2.0)
        self.assertTrue(store.get(self.path, "features")["beat_regular"])     # saved: not upgraded again next time


if __name__ == "__main__":
    unittest.main()
