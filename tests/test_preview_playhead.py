#!/usr/bin/env python3
"""Playhead of the looping FX preview: position in the loop, and playing the loop from another point."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fx_window import loop_position, rotate_clip


class TestPlayhead(unittest.TestCase):
    def test_loop_position_wraps(self):
        self.assertAlmostEqual(loop_position(100.0, 103.5, 10.0), 3.5)
        self.assertAlmostEqual(loop_position(100.0, 112.0, 10.0), 2.0)        # second time round
        self.assertAlmostEqual(loop_position(95.0, 100.0, 10.0), 5.0)         # started 5 s before (a seek to 5 s)
        self.assertEqual(loop_position(0.0, 5.0, 0.0), 0.0)

    def test_rotated_clip_loops_like_the_clip_from_the_offset(self):
        sr = 10
        clip = np.arange(40, dtype=np.float32).reshape(20, 2)                   # 2 s stereo
        rotated = rotate_clip(clip, sr, 0.5)
        self.assertEqual(rotated.shape, clip.shape)
        self.assertEqual(rotated[0].tolist(), clip[5].tolist())               # starts at 0.5 s
        self.assertEqual(rotated[15].tolist(), clip[0].tolist())              # then wraps to the beginning
        looped = np.concatenate([rotated, rotated])
        self.assertEqual(looped[5:25].tolist(), np.concatenate([clip[10:], clip[:10]]).tolist())
        self.assertEqual(rotate_clip(clip, sr, 0.0).tolist(), clip.tolist())
        self.assertEqual(rotate_clip(clip, sr, 2.0).tolist(), clip.tolist())   # a full turn


if __name__ == "__main__":
    unittest.main()
