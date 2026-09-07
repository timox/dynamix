import os
import json
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple
from audio_utils import AudioAnalyzer, key_compatibility_score, analyze_track_compatibility
from analysis_store import get_store
import matplotlib.pyplot as plt
import seaborn as sns

# Output folders DynaMix creates inside a music folder; never scanned as tracks.
PREMASTER_DIRNAME = "premaster"
EXCLUDED_DIRNAMES = {PREMASTER_DIRNAME}


class PlaylistManager:
    """Manage and analyze playlists for optimal DJ mixing"""
    
    def __init__(self, playlist_directory: str = None):
        """Initialize playlist manager"""
        self.playlist_directory = playlist_directory
        self.tracks = []
        self.analysis_cache = {}
        self.last_run = {'cached': 0, 'analyzed': 0, 'failed': 0}
        
    def scan_directory(self, directory: str = None) -> List[str]:
        """
        Scan directory for audio files
        Returns: List of audio file paths
        """
        if directory is None:
            directory = self.playlist_directory
            
        if not directory or not os.path.exists(directory):
            return []
            
        audio_extensions = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg'}
        audio_files = []
        
        for root, dirs, files in os.walk(directory):
            # skip DynaMix output folders and hidden folders
            dirs[:] = [d for d in dirs if d.lower() not in EXCLUDED_DIRNAMES and not d.startswith('.')]
            for file in files:
                if any(file.lower().endswith(ext) for ext in audio_extensions):
                    audio_files.append(os.path.join(root, file))
                    
        return audio_files
    
    def quick_playlist(self, directory: str = None) -> List[Dict]:
        """
        Build a playlist from the audio files of a directory without analyzing
        them. Entries are sorted by file name and carry the same keys as
        analyzed tracks (with neutral values) so every exporter accepts them.
        Returns: List of track dictionaries
        """
        entries = []
        for file_path in sorted(self.scan_directory(directory), key=lambda p: os.path.basename(p).lower()):
            entries.append({
                'file_path': file_path,
                'filename': os.path.basename(file_path),
                'duration': 0.0,
                'bpm': 0.0,
                'bpm_confidence': 0.0,
                'key': '',
                'key_confidence': 0.0,
                'avg_energy': 0.0,
                'max_energy': 0.0,
                'energy_std': 0.0,
                'beat_count': 0,
                'section_count': 0,
                'drop_count': 0,
            })
        return entries
    
    @staticmethod
    def track_record(file_path: str, features: Dict) -> Dict:
        """Flat track record (what tables, set lists and exports use) from analyzer features."""
        return {
            'file_path': file_path,
            'filename': os.path.basename(file_path),
            'duration': features['duration'],
            'bpm': features['bpm'],
            'bpm_confidence': features['bpm_confidence'],
            'key': features['key'],
            'key_confidence': features['key_confidence'],
            'avg_energy': features['avg_energy'],
            'energy_level': features.get('energy_level', 0.0),
            'has_beat': features.get('has_beat', True),
            'max_energy': features['max_energy'],
            'energy_std': features['energy_std'],
            'beat_count': features['beat_count'],
            'section_count': features['section_count'],
            'drop_count': features['drop_count'],
        }

    def analyze_playlist(self, file_paths: List[str] = None, progress_callback=None,
                         use_cache: bool = True) -> pd.DataFrame:
        """
        Analyze all tracks in playlist. Results are cached per file (analysis_store),
        so only new or changed files are actually decoded.

        Args:
            file_paths: files to analyse (default: scan the playlist directory)
            progress_callback: fn(index, total, filename, status) with status 'cached'|'analyzed'|'failed'
            use_cache: set False to force re-analysis
        Returns: DataFrame with track analysis
        """
        if file_paths is None:
            file_paths = self.scan_directory()
            
        self.tracks = []
        self.last_run = {'cached': 0, 'analyzed': 0, 'failed': 0}
        store = get_store() if use_cache else None
        
        for i, file_path in enumerate(file_paths):
            features = store.get(file_path, 'features') if store else None
            status = 'cached'
            try:
                if features is None:
                    status = 'analyzed'
                    print(f"Analyzing track {i+1}/{len(file_paths)}: {os.path.basename(file_path)}")
                    analyzer = AudioAnalyzer(file_path)
                    features = analyzer.get_audio_features()
                    if store:
                        store.put(file_path, 'features', features)
                
                self.tracks.append(self.track_record(file_path, features))
                self.analysis_cache[file_path] = features
                self.last_run[status] += 1
                
            except Exception as e:
                print(f"Error analyzing {file_path}: {e}")
                status = 'failed'
                self.last_run['failed'] += 1
            if progress_callback:
                progress_callback(i + 1, len(file_paths), os.path.basename(file_path), status)
                
        return pd.DataFrame(self.tracks)
    
    @staticmethod
    def _energy_value(track: Dict) -> float:
        """Perceived energy level when available, raw RMS energy otherwise."""
        level = track.get('energy_level')
        if level:
            return float(level)
        return float(track.get('avg_energy') or 0.0)

    @staticmethod
    def _target_curve(values: List[float], curve: str) -> List[float]:
        """Target energy for each slot of the set, drawn from the available values."""
        n = len(values)
        lo, hi = min(values), max(values)
        if n == 1 or hi == lo:
            return [values[0]] * n
        if curve == 'wave':
            # alternate low / high, easing towards the middle
            ordered = sorted(values)
            lows, highs = ordered, ordered[::-1]
            targets = []
            for i in range(n):
                targets.append(lows[i // 2] if i % 2 == 0 else highs[i // 2])
            return targets
        if curve == 'peak_middle':
            half = (n + 1) // 2
            up = list(np.linspace(lo, hi, half))
            down = list(np.linspace(hi, lo, n - half + 1))[1:]
            return up + down
        if curve == 'constant':
            return [float(np.median(values))] * n
        # default: 'build'
        return list(np.linspace(lo, hi, n))

    def suggest_playlist_order(self, energy_curve: str = 'build', 
                             key_compatibility: bool = True,
                             bpm_transitions: bool = True) -> List[Dict]:
        """
        Suggest a playing order that follows the requested energy curve while
        keeping neighbouring tracks close in tempo and harmonically compatible.
        
        Args:
            energy_curve: 'build' (low to high), 'wave' (alternating),
                          'peak_middle' (rise then fall), 'constant'
            key_compatibility: penalise harmonic clashes between neighbours
            bpm_transitions: penalise tempo jumps between neighbours
            
        Returns: List of track dictionaries in suggested order
        """
        if not self.tracks:
            raise ValueError("No tracks analyzed. Run analyze_playlist() first.")

        tracks = list(self.tracks)
        if len(tracks) == 1:
            return tracks
        values = [self._energy_value(t) for t in tracks]
        targets = self._target_curve(values, energy_curve)
        span = (max(values) - min(values)) or 1.0

        remaining = list(range(len(tracks)))
        order: List[int] = []
        previous = None
        for target in targets:
            best, best_cost = None, None
            for idx in remaining:
                track = tracks[idx]
                # how far from the energy the curve asks for at this slot (0..1)
                cost = abs(self._energy_value(track) - target) / span
                if previous is not None:
                    if bpm_transitions and previous.get('has_beat', True) and track.get('has_beat', True):
                        bpm_a = float(previous.get('bpm') or 0)
                        bpm_b = float(track.get('bpm') or 0)
                        if bpm_a and bpm_b:
                            jump = abs(bpm_b - bpm_a)
                            cost += 0.03 * max(0.0, jump - 3.0)  # free within 3 BPM
                    if key_compatibility:
                        score = key_compatibility_score(previous.get('key', ''), track.get('key', ''))
                        cost += (100.0 - score) / 100.0 * 0.5
                elif bpm_transitions:
                    cost += 0.001 * float(track.get('bpm') or 0)  # start with the slower one on ties
                if best_cost is None or cost < best_cost:
                    best, best_cost = idx, cost
            order.append(best)
            remaining.remove(best)
            previous = tracks[best]

        return [tracks[i] for i in order]

    def _select_for_duration(self, target_seconds: float) -> List[Dict]:
        """Pick a subset that fits the duration while covering the whole energy range."""
        tracks = sorted(self.tracks, key=self._energy_value)
        total = sum(float(t.get('duration') or 0) for t in tracks)
        if total <= target_seconds or len(tracks) <= 1:
            return tracks
        avg = total / len(tracks)
        count = max(1, min(len(tracks), int(target_seconds // max(avg, 1.0))))
        # evenly spaced picks across the energy-sorted list keep low, mid and high tracks
        picks = sorted(set(int(round(i)) for i in np.linspace(0, len(tracks) - 1, count)))
        selected = [tracks[i] for i in picks]
        # trim if the picked tracks are longer than average
        while len(selected) > 1 and sum(float(t.get('duration') or 0) for t in selected) > target_seconds:
            selected.pop(len(selected) // 2)
        return selected

    def create_set_list(self, duration_minutes: int = 60, 
                       energy_curve: str = 'build') -> List[Dict]:
        """
        Create a set list with specified duration
        
        Args:
            duration_minutes: Target set duration in minutes
            energy_curve: Energy curve type
            
        Returns: List of tracks for the set
        """
        if not self.tracks:
            raise ValueError("No tracks analyzed. Run analyze_playlist() first.")
            
        target_duration = duration_minutes * 60  # Convert to seconds
        
        # Choose the tracks first (so the whole energy range is represented),
        # then order the selection along the requested curve.
        selected = self._select_for_duration(target_duration)
        all_tracks = self.tracks
        try:
            self.tracks = selected
            set_list = self.suggest_playlist_order(energy_curve=energy_curve)
        finally:
            self.tracks = all_tracks
        return set_list
    
    def analyze_playlist_compatibility(self) -> pd.DataFrame:
        """
        Analyze compatibility between all track pairs in playlist
        Returns: DataFrame with compatibility matrix
        """
        if not self.tracks:
            raise ValueError("No tracks analyzed. Run analyze_playlist() first.")
            
        compatibility_matrix = []
        
        for i, track1 in enumerate(self.tracks):
            for j, track2 in enumerate(self.tracks):
                if i != j:
                    try:
                        compatibility = analyze_track_compatibility(
                            track1['file_path'], 
                            track2['file_path']
                        )
                        
                        compatibility_matrix.append({
                            'track1': track1['filename'],
                            'track2': track2['filename'],
                            'bpm_compatibility': compatibility['bpm_compatibility'],
                            'key_compatibility': compatibility['key_compatibility'],
                            'energy_compatibility': compatibility['energy_compatibility'],
                            'overall_score': compatibility['overall_score']
                        })
                    except Exception as e:
                        print(f"Error analyzing compatibility: {e}")
                        continue
                        
        return pd.DataFrame(compatibility_matrix)
    
    def plot_playlist_analysis(self):
        """Create comprehensive playlist analysis visualization"""
        if not self.tracks:
            raise ValueError("No tracks analyzed. Run analyze_playlist() first.")
            
        df = pd.DataFrame(self.tracks)
        
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        
        # BPM distribution
        axes[0, 0].hist(df['bpm'], bins=20, alpha=0.7, edgecolor='black')
        axes[0, 0].set_title('BPM Distribution')
        axes[0, 0].set_xlabel('BPM')
        axes[0, 0].set_ylabel('Number of Tracks')
        
        # Energy distribution
        axes[0, 1].hist(df['avg_energy'], bins=20, alpha=0.7, edgecolor='black')
        axes[0, 1].set_title('Energy Distribution')
        axes[0, 1].set_xlabel('Average Energy')
        axes[0, 1].set_ylabel('Number of Tracks')
        
        # Key distribution
        key_counts = df['key'].value_counts()
        axes[1, 0].bar(range(len(key_counts)), key_counts.values)
        axes[1, 0].set_title('Key Distribution')
        axes[1, 0].set_xlabel('Musical Key')
        axes[1, 0].set_ylabel('Number of Tracks')
        axes[1, 0].set_xticks(range(len(key_counts)))
        axes[1, 0].set_xticklabels(key_counts.index, rotation=45)
        
        # Duration vs Energy scatter
        axes[1, 1].scatter(df['duration'], df['avg_energy'], alpha=0.6)
        axes[1, 1].set_title('Duration vs Energy')
        axes[1, 1].set_xlabel('Duration (seconds)')
        axes[1, 1].set_ylabel('Average Energy')
        
        plt.tight_layout()
        plt.show()
    
    def export_playlist(self, output_path: str, format: str = 'json'):
        """
        Export playlist analysis to file
        
        Args:
            output_path: Output file path
            format: 'json' or 'csv'
        """
        if not self.tracks:
            raise ValueError("No tracks analyzed. Run analyze_playlist() first.")
            
        df = pd.DataFrame(self.tracks)
        
        if format.lower() == 'json':
            df.to_json(output_path, orient='records', indent=2)
        elif format.lower() == 'csv':
            df.to_csv(output_path, index=False)
        else:
            raise ValueError("Format must be 'json' or 'csv'")
            
        print(f"Playlist exported to {output_path}")
    
    def load_playlist(self, file_path: str):
        """Load playlist from exported file"""
        if file_path.endswith('.json'):
            with open(file_path, 'r') as f:
                self.tracks = json.load(f)
        elif file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
            self.tracks = df.to_dict('records')
        else:
            raise ValueError("File must be .json or .csv")
            
        print(f"Loaded {len(self.tracks)} tracks from {file_path}")

def create_energy_based_set(playlist_manager: PlaylistManager, 
                           target_duration: int = 60,
                           energy_profile: str = 'peak_middle') -> List[Dict]:
    """
    Create a set list with a specific energy profile
    
    Args:
        playlist_manager: Initialized playlist manager (analyzed tracks)
        target_duration: Set duration in minutes
        energy_profile: 'peak_middle', 'build_up' (or 'build'), 'wave', 'constant'
        
    Returns: List of tracks for the set
    """
    if not playlist_manager.tracks:
        raise ValueError("No tracks analyzed")
    
    curve = {'build_up': 'build'}.get(energy_profile, energy_profile)
    ordering = PlaylistManager.__new__(PlaylistManager)
    ordering.tracks = list(playlist_manager.tracks)
    return ordering.create_set_list(duration_minutes=target_duration, energy_curve=curve)
