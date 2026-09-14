#!/usr/bin/env python3
"""
Unit tests for audio_utils module
Tests the AudioAnalyzer class and utility functions
"""

import unittest
import numpy as np
import os
import sys
from unittest.mock import patch

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio_utils import AudioAnalyzer

class TestAudioAnalyzer(unittest.TestCase):
    """Test cases for AudioAnalyzer class"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create a mock audio file for testing
        self.mock_audio_data = np.random.rand(44100 * 10)  # 10 seconds of random audio
        self.sample_rate = 44100
        
    def test_audio_analyzer_initialization(self):
        """Test AudioAnalyzer initialization"""
        with patch('librosa.load') as mock_load:
            mock_load.return_value = (self.mock_audio_data, self.sample_rate)
            
            # Mock librosa.get_duration
            with patch('librosa.get_duration') as mock_duration:
                mock_duration.return_value = 10.0
                
                analyzer = AudioAnalyzer("test_file.mp3")
                
                self.assertEqual(analyzer.file_path, "test_file.mp3")
                self.assertEqual(analyzer.sr, self.sample_rate)
                self.assertEqual(analyzer.duration, 10.0)
    
    def test_analyze_energy_profile(self):
        """Test energy profile analysis"""
        with patch('librosa.load') as mock_load:
            mock_load.return_value = (self.mock_audio_data, self.sample_rate)
            
            with patch('librosa.get_duration') as mock_duration:
                mock_duration.return_value = 10.0
                
                # Mock RMS calculation
                with patch('librosa.feature.rms') as mock_rms:
                    mock_rms.return_value = np.random.rand(1, 100)
                    
                    with patch('librosa.frames_to_time') as mock_frames_to_time:
                        mock_frames_to_time.return_value = np.linspace(0, 10, 100)
                        
                        analyzer = AudioAnalyzer("test_file.mp3")
                        times, rms = analyzer.analyze_energy_profile()
                        
                        self.assertIsInstance(times, np.ndarray)
                        self.assertIsInstance(rms, np.ndarray)
                        self.assertEqual(len(times), len(rms))
    
    def test_get_audio_features(self):
        """Test comprehensive audio features extraction"""
        with patch('librosa.load') as mock_load:
            mock_load.return_value = (self.mock_audio_data, self.sample_rate)
            
            with patch('librosa.get_duration') as mock_duration:
                mock_duration.return_value = 10.0
                
                # Mock all analysis methods
                with patch.object(AudioAnalyzer, 'detect_bpm') as mock_bpm:
                    mock_bpm.return_value = (128.0, 0.8)
                    
                    with patch.object(AudioAnalyzer, 'detect_key') as mock_key:
                        mock_key.return_value = ("C major", 0.7)
                        
                        with patch.object(AudioAnalyzer, 'analyze_energy_profile') as mock_energy:
                            mock_energy.return_value = (np.linspace(0, 10, 100), np.random.rand(100))
                            
                            with patch.object(AudioAnalyzer, 'analyze_beat_grid') as mock_beat:
                                mock_beat.return_value = (np.array([0, 0.5, 1.0]), np.array([0.8, 0.9, 0.7]))

                                with patch.object(AudioAnalyzer, 'compute_energy_level') as mock_level:
                                    mock_level.return_value = (6.5, {'beat_gate': 0.9})

                                    analyzer = AudioAnalyzer("test_file.mp3")
                                    features = analyzer.get_audio_features()

                                    required_keys = [
                                        'duration', 'sample_rate', 'bpm', 'bpm_confidence',
                                        'key', 'key_confidence', 'avg_energy', 'max_energy',
                                        'energy_std', 'energy_level', 'has_beat', 'beat_count', 'avg_beat_strength',
                                    ]
                                    for key in required_keys:
                                        self.assertIn(key, features)

                                    self.assertIsInstance(features['duration'], float)
                                    self.assertIsInstance(features['bpm'], float)
                                    self.assertIsInstance(features['key'], str)
                                    self.assertEqual((features['energy_level'], features['has_beat'], features['beat_count']),
                                                     (6.5, True, 3))

class TestErrorHandling(unittest.TestCase):
    """Test error handling scenarios"""
    
    def test_invalid_file_path(self):
        """Test handling of invalid file paths"""
        with self.assertRaises(Exception):
            AudioAnalyzer("nonexistent_file.mp3")
    
if __name__ == '__main__':
    unittest.main() 