"""
Export Tools - M3U playlist of a set list ('Create Playlist' step).
"""

import os
from typing import List, Dict


class ExportTools:
    """Playlist export"""

    @staticmethod
    def export_to_m3u(playlist: List[Dict], output_path: str, extended: bool = True) -> List[str]:
        """
        Export playlist to M3U format
        Supports both standard and extended M3U formats

        Returns the entries that are not on disk: a rendered copy can have been deleted or moved since,
        and a player would just skip them. They are written all the same, so the user can put them back.
        """
        missing = []
        with open(output_path, 'w', encoding='utf-8') as f:
            if extended:
                f.write("#EXTM3U\n")

            for track in playlist:
                if extended:
                    duration = track.get('duration', 0)
                    title = track.get('filename', track.get('file_path', 'Unknown'))
                    f.write(f"#EXTINF:{int(duration)},{title}\n")

                file_path = track.get('file_path', track.get('filename', ''))
                if file_path and not os.path.isfile(file_path):
                    missing.append(file_path)
                f.write(f"{file_path}\n")

        print(f"✅ Exported to M3U: {output_path}")
        return missing
