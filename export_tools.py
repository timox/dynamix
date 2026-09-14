"""
Export Tools - M3U playlist of a set list ('Create Playlist' step).
"""

from typing import List, Dict


class ExportTools:
    """Playlist export"""
    
    @staticmethod
    def export_to_m3u(playlist: List[Dict], output_path: str, extended: bool = True):
        """
        Export playlist to M3U format
        Supports both standard and extended M3U formats
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            if extended:
                f.write("#EXTM3U\n")
            
            for track in playlist:
                if extended:
                    duration = track.get('duration', 0)
                    title = track.get('filename', track.get('file_path', 'Unknown'))
                    f.write(f"#EXTINF:{int(duration)},{title}\n")
                
                file_path = track.get('file_path', track.get('filename', ''))
                f.write(f"{file_path}\n")
        
        print(f"✅ Exported to M3U: {output_path}")
    