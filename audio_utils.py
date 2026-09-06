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
    
    # Calibration of the perceived-energy components (typical club-music ranges).
    # Each component is mapped through a sigmoid centred on `center` with the given
    # `scale`, then combined with `weight`. The result is loudness independent.
    ENERGY_COMPONENTS = {
        #                  center  scale  weight
        'tempo':          (124.0,  12.0,  0.28),   # BPM (only counts when there is a beat)
        'onset_rate':     (3.5,    1.5,   0.28),   # percussive events per second
        'percussive':     (0.30,   0.10,  0.29),   # share of percussive energy (HPSS)
        'low_end':        (0.25,   0.10,  0.05),   # share of energy below 150 Hz (beat-gated)
        'brightness':     (2500.0, 800.0, 0.10),   # spectral centroid in Hz
    }
    # low_end and brightness carry little weight on purpose: they depend on the
    # mastering (muddy or harsh masters would otherwise bias the level).
    # Components that only make sense for rhythmic material are multiplied by a
    # "beat gate" derived from the percussive share: ~0 for pads, ~1 for drums.
    BEAT_GATED_COMPONENTS = ('tempo', 'onset_rate', 'low_end')

    def compute_energy_level(self, bpm: float = None, excerpt_seconds: float = 120.0) -> Tuple[float, dict]:
        """
        Estimate the perceived energy of the track on a 1-10 scale, independent of
        its mastering loudness (the signal is RMS-normalised first). The analysis
        runs on the body of the track (middle part, up to `excerpt_seconds`) so that
        quiet intros/outros do not dilute the result.
        Returns: (energy_level, components)
        """
        if bpm is None:
            bpm, _ = self.detect_bpm()

        # Body excerpt, mono, loudness normalised
        y = self.y if self.y.ndim == 1 else librosa.to_mono(self.y)
        total = len(y)
        excerpt = int(min(total, excerpt_seconds * self.sr))
        start = max(0, (total - excerpt) // 2)
        y = y[start:start + excerpt].astype(np.float32)
        rms_total = float(np.sqrt(np.mean(y ** 2))) if len(y) else 0.0
        if rms_total <= 1e-8:
            return 1.0, {name: 0.0 for name in self.ENERGY_COMPONENTS}
        y = y / rms_total

        hop = 512
        stft = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
        freqs = librosa.fft_frequencies(sr=self.sr, n_fft=2048)
        power = stft ** 2
        total_power = float(np.sum(power)) + 1e-12

        # Percussive share via harmonic/percussive separation
        harmonic, percussive = librosa.decompose.hpss(stft)
        perc_power = float(np.sum(percussive ** 2))
        perc_share = perc_power / (float(np.sum(harmonic ** 2)) + perc_power + 1e-12)

        # Rhythmic activity: onsets per second, measured on the percussive part only
        onset_env = librosa.onset.onset_strength(S=librosa.power_to_db(percussive ** 2 + 1e-10), sr=self.sr)
        onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=self.sr, hop_length=hop)
        duration = len(y) / self.sr
        onset_rate = len(onsets) / duration if duration > 0 else 0.0

        # Low-end share (kick/bass) and brightness
        low_share = float(np.sum(power[freqs < 150.0, :])) / total_power
        centroid = float(np.median(librosa.feature.spectral_centroid(S=stft, sr=self.sr)))

        raw = {
            'tempo': float(bpm or 0.0),
            'onset_rate': float(onset_rate),
            'percussive': perc_share,
            'low_end': low_share,
            'brightness': centroid,
        }
        beat_gate = 1.0 / (1.0 + np.exp(-(perc_share - 0.15) / 0.04))
        raw['beat_gate'] = float(beat_gate)
        score = 0.0
        for name, (center, scale, weight) in self.ENERGY_COMPONENTS.items():
            normalised = 1.0 / (1.0 + np.exp(-(raw[name] - center) / scale))
            if name in self.BEAT_GATED_COMPONENTS:
                normalised *= beat_gate
            score += weight * normalised
        level = float(np.clip(1.0 + 9.0 * score, 1.0, 10.0))
        return round(level, 1), raw

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
        features['energy_level'], features['energy_components'] = self.compute_energy_level(bpm=features['bpm'])
        # Beatless material (pads, ambient) has no meaningful tempo to match
        features['has_beat'] = bool(features['energy_components'].get('beat_gate', 1.0) >= 0.5)
        
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

_PITCH_CLASSES = {'C': 0, 'C#': 1, 'DB': 1, 'D': 2, 'D#': 3, 'EB': 3, 'E': 4, 'F': 5, 'F#': 6, 'GB': 6,
                  'G': 7, 'G#': 8, 'AB': 8, 'A': 9, 'A#': 10, 'BB': 10, 'B': 11}


def parse_key(key: str):
    """'A minor' / 'F# major' / 'Am' -> (pitch_class, is_major) or None."""
    if not key:
        return None
    text = str(key).strip()
    parts = text.split()
    root = parts[0]
    mode = parts[1].lower() if len(parts) > 1 else ''
    if len(parts) == 1 and root.endswith('m') and root[:-1].upper() in _PITCH_CLASSES:
        root, mode = root[:-1], 'minor'
    pc = _PITCH_CLASSES.get(root.upper())
    if pc is None:
        return None
    return pc, not mode.startswith('min')


def key_compatibility_score(key1: str, key2: str) -> float:
    """
    Harmonic compatibility of two keys on a 0-100 scale (Camelot-wheel logic):
    100 same key, 85 relative major/minor, 80 neighbouring fifth, 65 same mode
    two steps away, 50 otherwise.
    """
    k1, k2 = parse_key(key1), parse_key(key2)
    if k1 is None or k2 is None:
        return 50.0
    (pc1, major1), (pc2, major2) = k1, k2
    if k1 == k2:
        return 100.0
    if major1 == major2:
        dist = min((pc1 - pc2) % 12, (pc2 - pc1) % 12)
        if dist in (5, 7):
            return 80.0
        if dist in (2, 10):
            return 65.0
        return 50.0
    # relative keys: A minor <-> C major (minor root = major root + 9)
    major_pc, minor_pc = (pc1, pc2) if major1 else (pc2, pc1)
    if (major_pc + 9) % 12 == minor_pc:
        return 85.0
    return 50.0


def energy_compatibility_score(f1: dict, f2: dict) -> float:
    """Energy compatibility on a 0-100 scale, using energy_level (1-10) when available."""
    l1, l2 = f1.get('energy_level'), f2.get('energy_level')
    if l1 and l2:
        return max(0.0, 100.0 - abs(float(l1) - float(l2)) / 9.0 * 100.0)
    e1 = float(f1.get('avg_energy') or 0)
    e2 = float(f2.get('avg_energy') or 0)
    max_energy = max(e1, e2)
    return max(0.0, 100.0 - abs(e1 - e2) / max_energy * 100.0) if max_energy > 0 else 100.0


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
    
    # Key compatibility (Camelot-wheel logic)
    compatibility['key_compatibility'] = key_compatibility_score(features1['key'], features2['key'])
    
    # Energy compatibility (perceived energy level, loudness independent)
    compatibility['energy_compatibility'] = energy_compatibility_score(features1, features2)
    
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