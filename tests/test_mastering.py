import unittest

import numpy as np
from scipy import signal

from mastering import true_peak_db


class TestTruePeak(unittest.TestCase):
    def test_blockwise_true_peak_matches_whole_signal(self):
        sr = 8000
        audio = np.random.default_rng(4).normal(0, 0.2, (sr * 11, 2)).astype(np.float32)
        expected = 20 * np.log10(np.max(np.abs(signal.resample_poly(audio, 4, 1, axis=0))))
        self.assertAlmostEqual(true_peak_db(audio, sr), expected, places=5)
