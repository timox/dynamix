import librosa
import numpy as np
import matplotlib.pyplot as plt
from typing import Tuple, Optional, List
import warnings
warnings.filterwarnings('ignore')

class AudioAnalyzer:
    """Advanced audio analysis utilities for DJ mixing"""
    
    def __init__(self, file_path: str):
        """Initialize analyzer with audio file"""
        self.file_path = file_path
        self.y, self.sr = librosa.load(file_path, sr=None)
        self.duration = librosa.get_duration(y=self.y, sr=self.sr)
        
    def detect_bpm(self) -> Tuple[float, float]:
        """
        Detect BPM using multiple methods and return the most reliable result
        Returns: (bpm, confidence)
        """
        # librosa >= 0.10 returns tempo as a 1-element array and moved
        # ``librosa.beat.tempo`` to ``librosa.feature.tempo``; handle both.
        tempo_fn = getattr(librosa.feature, "tempo", None) or librosa.beat.tempo

        # Method 1: Using librosa's beat_track
        tempo, beats = librosa.beat.beat_track(y=self.y, sr=self.sr)
        
        # Method 2: Using onset detection
        onset_env = librosa.onset.onset_strength(y=self.y, sr=self.sr)
        tempo_onset = tempo_fn(onset_envelope=onset_env, sr=self.sr)
        
        # Method 3: Using dynamic programming
        tempo_dp = tempo_fn(onset_envelope=onset_env, sr=self.sr, aggregate=None)
        
        # Return the most consistent result
        tempos = np.array([
            float(np.atleast_1d(tempo)[0]),
            float(np.atleast_1d(tempo_onset)[0]),
            float(np.median(tempo_dp)),
        ])
        final_bpm = float(np.median(tempos))
        
        # Calculate confidence based on consistency
        mean_tempo = float(np.mean(tempos))
        confidence = 1.0 - (float(np.std(tempos)) / mean_tempo) if mean_tempo > 0 else 0.0
        
        return final_bpm, confidence
    
    def detect_key(self) -> Tuple[str, float]:
        """
        Detect musical key using chromagram analysis
        Returns: (key, confidence)
        """
        # Extract chromagram and average it over time
        chroma = librosa.feature.chroma_cqt(y=self.y, sr=self.sr)
        chroma_avg = np.mean(chroma, axis=1)
        
        # Krumhansl-Schmuckler key profiles (librosa has no built-in key detector)
        major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                                  2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                                  2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        
        def _corr(a: np.ndarray, b: np.ndarray) -> float:
            if np.std(a) == 0 or np.std(b) == 0:
                return 0.0
            return float(np.corrcoef(a, b)[0, 1])
        
        # Correlate the chroma vector against every rotation of both profiles
        scores = []  # (score, pitch_class, is_major)
        for shift in range(12):
            scores.append((_corr(chroma_avg, np.roll(major_profile, shift)), shift, True))
            scores.append((_corr(chroma_avg, np.roll(minor_profile, shift)), shift, False))
        scores.sort(key=lambda item: item[0], reverse=True)
        best_score, best_shift, is_major = scores[0]
        second_score = scores[1][0]
        
        # Map to readable key names
        key_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        key = key_names[best_shift]
        mode = 'major' if is_major else 'minor'
        
        # Confidence: how clearly the best candidate beats the runner-up (0..1)
        confidence = float(np.clip((best_score - second_score) / max(abs(best_score), 1e-9), 0.0, 1.0))
        if best_score <= 0:
            confidence = 0.0
        
        return f"{key} {mode}", confidence
    
    def analyze_beat_grid(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Analyze beat grid and return beat times and strengths
        Returns: (beat_times, beat_strengths)
        """
        # Get onset strength
        onset_env = librosa.onset.onset_strength(y=self.y, sr=self.sr)
        
        # Detect beats
        tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=self.sr)
        
        # Get beat times
        beat_times = librosa.frames_to_time(beats, sr=self.sr)
        
        # Get beat strengths
        beat_strengths = onset_env[beats]
        
        return beat_times, beat_strengths
    
    def detect_sections(self) -> List[Tuple[str, float, float]]:
        """
        Detect song sections (intro, verse, chorus, etc.)
        Returns: List of (section_name, start_time, end_time)
        """
        # Compute MFCC features
        mfcc = librosa.feature.mfcc(y=self.y, sr=self.sr, n_mfcc=13)
        n_frames = mfcc.shape[1]
        duration = librosa.get_duration(y=self.y, sr=self.sr)
        
        # Aim for roughly one section per 30 seconds, between 1 and 5 sections
        n_sections = int(np.clip(round(duration / 30.0), 1, 5))
        n_sections = max(1, min(n_sections, n_frames))
        
        if n_sections <= 1 or n_frames < 2:
            return [('Intro', 0.0, float(duration))]
        
        # Agglomerative clustering of MFCC frames gives section boundaries
        boundaries = librosa.segment.agglomerative(mfcc, n_sections)
        boundary_times = librosa.frames_to_time(boundaries, sr=self.sr)
        boundary_times = np.concatenate([boundary_times, [duration]])
        
        # Label sections (simplified)
        section_names = ['Intro', 'Verse', 'Chorus', 'Bridge', 'Outro']
        sections = []
        
        for i in range(len(boundary_times) - 1):
            start, end = float(boundary_times[i]), float(boundary_times[i + 1])
            if end <= start:
                continue
            name = section_names[i] if i < len(section_names) else f'Section {i+1}'
            sections.append((name, start, end))
        
        return sections
    
    def analyze_energy_profile(self, window_size: float = 1.0) -> Tuple[np.ndarray, np.ndarray]:
        """
        Analyze energy profile with customizable window size
        Returns: (times, energy_values)
        """
        # Calculate RMS energy
        hop_length = int(self.sr * window_size / 4)  # 25% overlap
        rms = librosa.feature.rms(y=self.y, hop_length=hop_length)[0]
        
        # Convert to time
        times = librosa.frames_to_time(np.arange(len(rms)), sr=self.sr, hop_length=hop_length)
        
        return times, rms
    
    def detect_drops(self, threshold_factor: float = 1.5) -> List[float]:
        """
        Detect energy drops (breakdowns) in the track
        Returns: List of drop times
        """
        times, rms = self.analyze_energy_profile()
        
        # Calculate rolling average
        window = int(len(rms) * 0.1)  # 10% of track length
        rolling_avg = np.convolve(rms, np.ones(window)/window, mode='same')
        
        # Find drops (energy significantly below rolling average)
        drops = []
        for i, (time, energy, avg) in enumerate(zip(times, rms, rolling_avg)):
            if energy < avg / threshold_factor and i > window:
                drops.append(time)
        
        # Remove duplicates (drops within 5 seconds of each other)
        filtered_drops = []
        for drop in drops:
            if not any(abs(drop - existing) < 5 for existing in filtered_drops):
                filtered_drops.append(drop)
        
        return filtered_drops
    
    def get_audio_features(self) -> dict:
        """
        Get comprehensive audio features
        Returns: Dictionary with all analyzed features
        """
        features = {}
        
        # Basic features
        features['duration'] = self.duration
        features['sample_rate'] = self.sr
        
        # BPM and key
        features['bpm'], features['bpm_confidence'] = self.detect_bpm()
        features['key'], features['key_confidence'] = self.detect_key()
        
        # Energy analysis
        times, rms = self.analyze_energy_profile()
        features['avg_energy'] = np.mean(rms)
        features['max_energy'] = np.max(rms)
        features['energy_std'] = np.std(rms)
        
        # Beat analysis
        beat_times, beat_strengths = self.analyze_beat_grid()
        features['beat_count'] = len(beat_times)
        features['avg_beat_strength'] = np.mean(beat_strengths)
        
        # Section analysis
        sections = self.detect_sections()
        features['section_count'] = len(sections)
        features['sections'] = sections
        
        # Drop detection
        drops = self.detect_drops()
        features['drop_count'] = len(drops)
        features['drops'] = drops
        
        return features
    
    def plot_comprehensive_analysis(self):
        """Create a comprehensive visualization of all analyses"""
        fig, axes = plt.subplots(4, 1, figsize=(15, 12))
        
        # Energy profile
        times, rms = self.analyze_energy_profile()
        axes[0].plot(times, rms, label='RMS Energy')
        axes[0].set_title('Energy Profile')
        axes[0].set_ylabel('Energy')
        axes[0].legend()
        
        # Beat grid
        beat_times, beat_strengths = self.analyze_beat_grid()
        axes[1].vlines(beat_times, 0, beat_strengths, alpha=0.5, label='Beats')
        axes[1].set_title('Beat Grid')
        axes[1].set_ylabel('Beat Strength')
        axes[1].legend()
        
        # Chromagram (key analysis)
        chroma = librosa.feature.chroma_cqt(y=self.y, sr=self.sr)
        librosa.display.specshow(chroma, sr=self.sr, x_axis='time', y_axis='chroma', ax=axes[2])
        axes[2].set_title('Chroma Features (Key Analysis)')
        
        # Sections
        sections = self.detect_sections()
        for section_name, start, end in sections:
            axes[3].axvspan(start, end, alpha=0.3, label=section_name)
        axes[3].set_title('Detected Sections')
        axes[3].set_xlabel('Time (s)')
        axes[3].legend()
        
        plt.tight_layout()
        plt.show()

def analyze_track_compatibility(track1_path: str, track2_path: str) -> dict:
    """
    Analyze compatibility between two tracks for mixing
    Returns: Dictionary with compatibility metrics
    """
    analyzer1 = AudioAnalyzer(track1_path)
    analyzer2 = AudioAnalyzer(track2_path)
    
    features1 = analyzer1.get_audio_features()
    features2 = analyzer2.get_audio_features()
    
    compatibility = {}
    
    # BPM compatibility
    bpm_diff = abs(features1['bpm'] - features2['bpm'])
    compatibility['bpm_compatibility'] = max(0, 100 - (bpm_diff * 2))
    compatibility['bpm_difference'] = bpm_diff
    
    # Key compatibility
    key1, key2 = features1['key'], features2['key']
    # Simple key compatibility (can be enhanced with music theory)
    if key1 == key2:
        compatibility['key_compatibility'] = 100
    elif key1.split()[0] == key2.split()[0]:  # Same root note
        compatibility['key_compatibility'] = 80
    else:
        compatibility['key_compatibility'] = 50
    
    # Energy compatibility
    energy_diff = abs(features1['avg_energy'] - features2['avg_energy'])
    max_energy = max(features1['avg_energy'], features2['avg_energy'])
    compatibility['energy_compatibility'] = max(0, 100 - (energy_diff / max_energy * 100))
    
    # Overall compatibility score
    compatibility['overall_score'] = (
        compatibility['bpm_compatibility'] * 0.4 +
        compatibility['key_compatibility'] * 0.3 +
        compatibility['energy_compatibility'] * 0.3
    )
    
    return compatibility

def suggest_mix_points(track1_path: str, track2_path: str) -> dict:
    """
    Suggest optimal mix points for two tracks
    Returns: Dictionary with mix suggestions
    """
    analyzer1 = AudioAnalyzer(track1_path)
    analyzer2 = AudioAnalyzer(track2_path)
    
    # Get features
    features1 = analyzer1.get_audio_features()
    features2 = analyzer2.get_audio_features()
    
    # Analyze energy profiles
    times1, rms1 = analyzer1.analyze_energy_profile()
    times2, rms2 = analyzer2.analyze_energy_profile()
    
    # Find energy valleys in track 1 (good exit points)
    rolling_avg1 = np.convolve(rms1, np.ones(20)/20, mode='same')
    valleys1 = []
    for i, (time, energy, avg) in enumerate(zip(times1, rms1, rolling_avg1)):
        if energy < avg * 0.8 and time > 30:  # Avoid very early valleys
            valleys1.append(time)
    
    # Find energy peaks in track 2 (good entry points)
    rolling_avg2 = np.convolve(rms2, np.ones(20)/20, mode='same')
    peaks2 = []
    for i, (time, energy, avg) in enumerate(zip(times2, rms2, rolling_avg2)):
        if energy > avg * 1.2 and time < features2['duration'] - 30:  # Avoid very late peaks
            peaks2.append(time)
    
    suggestions = {
        'track1_exit_points': valleys1[:5],  # Top 5 exit points
        'track2_entry_points': peaks2[:5],   # Top 5 entry points
        'recommended_mix_duration': min(16, features1['duration'] * 0.1),  # 10% of track or 16 bars
        'bpm_sync_required': abs(features1['bpm'] - features2['bpm']) > 5
    }
    
    return suggestions 