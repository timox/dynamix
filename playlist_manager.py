import os
import logging
import numpy as np
import pandas as pd
from typing import List, Dict
from audio_utils import AudioAnalyzer
from analysis_store import get_store
from set_proposer import energy_value, propose, transition_cost

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
                        try:
                            store.put(file_path, 'features', features)
                        except OSError:
                            pass  # file not reachable for stat (e.g. mocked): skip caching
                
                self.tracks.append(self.track_record(file_path, features))
                self.analysis_cache[file_path] = features
                self.last_run[status] += 1
                
            except Exception as e:
                print(f"Error analyzing {file_path}: {e}")
                logging.getLogger("dynamix.analysis").warning("Analysis failed for %s: %s", os.path.basename(file_path), e)
                status = 'failed'
                self.last_run['failed'] += 1
            if progress_callback:
                progress_callback(i + 1, len(file_paths), os.path.basename(file_path), status)
                
        return pd.DataFrame(self.tracks)
    
    @staticmethod
    def _energy_value(track: Dict) -> float:
        """Perceived energy level when available, raw RMS energy otherwise."""
        return energy_value(track)

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
                    cost += transition_cost(previous, track, bpm=bpm_transitions, key=key_compatibility)
                elif bpm_transitions:
                    cost += 0.001 * float(track.get('bpm') or 0)  # start with the slower one on ties
                if best_cost is None or cost < best_cost:
                    best, best_cost = idx, cost
            order.append(best)
            remaining.remove(best)
            previous = tracks[best]

        return [tracks[i] for i in order]

    def create_set_list(self, duration_minutes: int = 60,
                       energy_curve: str = 'build', mix_bars: int = 8) -> List[Dict]:
        """
        Best set list for the duration, drawn from the analysed tracks: the first
        variant of set_proposer.propose (the GUI shows several).

        Args:
            duration_minutes: Target set duration in minutes (crossfades overlap)
            energy_curve: 'build', 'wave', 'peak_middle', 'constant' ('build_up' = 'build')
            mix_bars: Length of each crossfade in bars (sets the overlap between tracks)

        Returns: List of tracks for the set, in playing order
        """
        if not self.tracks:
            raise ValueError("No tracks analyzed. Run analyze_playlist() first.")
        curve = {'build_up': 'build'}.get(energy_curve, energy_curve)
        return propose(list(self.tracks), duration_minutes * 60, curve=curve, mix_bars=mix_bars, variants=1)[0]['tracks']
    