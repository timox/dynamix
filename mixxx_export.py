#!/usr/bin/env python3
"""
Push DynaMix transitions into Mixxx.

Mixxx Auto DJ uses each track's INTRO and OUTRO cue sections to decide when
to start the next track and how long to crossfade ("Full Intro + Outro" and
"Fade At Outro Start" modes). This module writes the sections computed by
transition_planner.py straight into the Mixxx library database
(mixxxdb.sqlite) and creates a Mixxx playlist with the set order, so that the
whole set can be dropped into Auto DJ with no manual preparation.

Requirements:
- the tracks must already be in the Mixxx library (add the music folder in
  Mixxx: Preferences > Library, then rescan);
- Mixxx must be CLOSED while writing (it keeps the database open and would
  overwrite the changes).

A timestamped backup of the database is created before anything is written.

Usage (command line):
    python mixxx_export.py --project "C:\\Users\\me\\DynaMix Projects\\Saturday"
    python mixxx_export.py --playlist "C:\\Music\\Set" --set-duration 60
    python mixxx_export.py --m3u "C:\\Music\\Set\\Set.m3u" --sheet transitions.txt
    python mixxx_export.py --m3u set.m3u --dry-run
"""

import argparse
import datetime as _dt
import os
import shutil
import sqlite3
import sys
from typing import Dict, List, Optional

from transition_planner import TransitionPlanner, tracks_from_m3u

CUE_TYPE_INTRO = 6
CUE_TYPE_OUTRO = 7
ENGINE_CHANNELS = 2  # Mixxx stores cue positions in stereo-interleaved samples
DEFAULT_CUE_COLOR = 4294901760  # Mixxx default (opaque red)


def find_mixxx_db() -> Optional[str]:
    """Return the default mixxxdb.sqlite location for this platform, if it exists."""
    candidates = []
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(os.path.join(local, "Mixxx", "mixxxdb.sqlite"))
    elif sys.platform == "darwin":
        home = os.path.expanduser("~")
        candidates.append(os.path.join(home, "Library", "Containers", "org.mixxx.mixxx", "Data",
                                       "Library", "Application Support", "Mixxx", "mixxxdb.sqlite"))
        candidates.append(os.path.join(home, "Library", "Application Support", "Mixxx", "mixxxdb.sqlite"))
    else:
        home = os.path.expanduser("~")
        candidates.append(os.path.join(home, ".mixxx", "mixxxdb.sqlite"))
        candidates.append(os.path.join(home, ".var", "app", "org.mixxx.Mixxx", ".mixxx", "mixxxdb.sqlite"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _norm(path: str) -> str:
    """Normalize a path the way Mixxx (Qt) stores it, for comparison only."""
    return os.path.abspath(path).replace("\\", "/").casefold()


class MixxxExporter:
    """Write intro/outro cues and a playlist into a Mixxx database."""

    def __init__(self, db_path: str, backup: bool = True):
        if not os.path.isfile(db_path):
            raise FileNotFoundError(f"Mixxx database not found: {db_path}")
        self.db_path = db_path
        self.backup = backup

    # ---------------------------------------------------------------- helpers
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=1.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _library_index(self, conn: sqlite3.Connection) -> Dict[str, sqlite3.Row]:
        rows = conn.execute(
            "SELECT l.id, l.samplerate, l.duration, tl.location "
            "FROM library l JOIN track_locations tl ON l.location = tl.id "
            "WHERE l.mixxx_deleted = 0"
        ).fetchall()
        return {_norm(r["location"]): r for r in rows}

    def match_tracks(self, profiles: List[Dict]) -> Dict:
        """Return which planned tracks exist in the Mixxx library (no writes)."""
        conn = self._connect()
        try:
            index = self._library_index(conn)
        finally:
            conn.close()
        matched, missing = [], []
        for p in profiles:
            row = index.get(_norm(p["file_path"]))
            if row is None:
                missing.append(p["file_path"])
            else:
                matched.append((p, row))
        return {"matched": matched, "missing": missing}

    def _backup_db(self) -> str:
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{self.db_path}.dynamix-backup-{stamp}"
        shutil.copy2(self.db_path, backup_path)
        return backup_path

    # ---------------------------------------------------------------- export
    def export(self, profiles: List[Dict], playlist_name: Optional[str] = None,
               dry_run: bool = False) -> Dict:
        """
        Write intro/outro cues for every matched track and (optionally) a playlist.

        Args:
            profiles: per-track dicts from TransitionPlanner.profiles (ordered)
            playlist_name: Mixxx playlist to create/replace with that order; None to skip
            dry_run: only report what would be written
        Returns: report dictionary
        """
        report = {
            "db_path": self.db_path,
            "backup_path": None,
            "dry_run": dry_run,
            "matched": [],
            "missing": [],
            "cues_written": 0,
            "playlist_name": playlist_name,
            "playlist_id": None,
        }

        match = self.match_tracks(profiles)
        report["missing"] = match["missing"]
        report["matched"] = [p["file_path"] for p, _ in match["matched"]]
        if dry_run or not match["matched"]:
            return report

        if self.backup:
            report["backup_path"] = self._backup_db()

        conn = self._connect()
        try:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise RuntimeError("The Mixxx database is locked. Close Mixxx and try again.") from exc

            track_ids = []
            for p, row in match["matched"]:
                track_id = int(row["id"])
                samplerate = int(row["samplerate"] or 44100)
                duration = float(row["duration"] or p["duration"] or 0)
                track_ids.append(track_id)

                conn.execute("DELETE FROM cues WHERE track_id = ? AND type IN (?, ?)",
                             (track_id, CUE_TYPE_INTRO, CUE_TYPE_OUTRO))
                for cue_type, start, end, label in (
                    (CUE_TYPE_INTRO, p["intro_start"], p["intro_end"], "DynaMix intro"),
                    (CUE_TYPE_OUTRO, p["outro_start"], p["outro_end"], "DynaMix outro"),
                ):
                    if duration > 0:
                        start = min(start, duration)
                        end = min(end, duration)
                    position = self._to_engine_samples(start, samplerate)
                    length = max(0, self._to_engine_samples(end, samplerate) - position)
                    conn.execute(
                        "INSERT INTO cues (track_id, type, position, length, hotcue, label, color) "
                        "VALUES (?, ?, ?, ?, -1, ?, ?)",
                        (track_id, cue_type, position, length, label, DEFAULT_CUE_COLOR),
                    )
                    report["cues_written"] += 1

            if playlist_name:
                report["playlist_id"] = self._write_playlist(conn, playlist_name, track_ids)

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return report

    @staticmethod
    def _to_engine_samples(seconds: float, samplerate: int) -> int:
        frames = int(round(max(0.0, seconds) * samplerate))
        return frames * ENGINE_CHANNELS

    @staticmethod
    def _write_playlist(conn: sqlite3.Connection, name: str, track_ids: List[int]) -> int:
        now = _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        row = conn.execute("SELECT id FROM Playlists WHERE name = ? AND hidden = 0", (name,)).fetchone()
        if row is None:
            max_pos = conn.execute("SELECT COALESCE(MAX(position), 0) FROM Playlists").fetchone()[0]
            cur = conn.execute(
                "INSERT INTO Playlists (name, position, hidden, date_created, date_modified) "
                "VALUES (?, ?, 0, ?, ?)",
                (name, int(max_pos) + 1, now, now),
            )
            playlist_id = int(cur.lastrowid)
        else:
            playlist_id = int(row["id"])
            conn.execute("DELETE FROM PlaylistTracks WHERE playlist_id = ?", (playlist_id,))
            conn.execute("UPDATE Playlists SET date_modified = ? WHERE id = ?", (now, playlist_id))

        for position, track_id in enumerate(track_ids, start=1):
            conn.execute(
                "INSERT INTO PlaylistTracks (playlist_id, track_id, position, pl_datetime_added) "
                "VALUES (?, ?, ?, ?)",
                (playlist_id, track_id, position, now),
            )
        return playlist_id


def format_report(report: Dict) -> str:
    lines = []
    if report["dry_run"]:
        lines.append("DRY RUN - nothing was written to Mixxx.")
    lines.append(f"Mixxx database: {report['db_path']}")
    if report["backup_path"]:
        lines.append(f"Backup: {report['backup_path']}")
    lines.append(f"Tracks found in Mixxx library: {len(report['matched'])}")
    if report["missing"]:
        lines.append(f"Tracks NOT in Mixxx library ({len(report['missing'])}), add the folder to the Mixxx "
                     "library and rescan, then export again:")
        for path in report["missing"]:
            lines.append(f"  - {path}")
    if not report["dry_run"]:
        lines.append(f"Intro/outro cues written: {report['cues_written']}")
        if report["playlist_id"] is not None:
            lines.append(f"Mixxx playlist '{report['playlist_name']}' ready (id {report['playlist_id']}). "
                         "In Mixxx: Library > Playlists > right-click it > Add to Auto DJ Queue, then enable Auto DJ "
                         "with the 'Full Intro + Outro' transition mode.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Plan DynaMix transitions and push them to Mixxx")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--project", help="Set project folder (or its project.json): reuse its set list and record the steps")
    source.add_argument("--playlist", help="Music directory: analyze it and build a set list (no project)")
    source.add_argument("--m3u", help="Existing M3U/M3U8 playlist: keep its order")
    parser.add_argument("--set-duration", type=int, default=None, help="Set duration in minutes (default 60, or the project's option)")
    parser.add_argument("--energy-curve", default=None, choices=["build", "wave", "peak_middle", "constant"],
                        help="Energy curve for the set list (default build, or the project's option)")
    parser.add_argument("--mix-bars", type=int, default=8, help="Crossfade length in bars (default 8)")
    parser.add_argument("--sheet", help="Save the transition sheet to this text file")
    parser.add_argument("--json", help="Save the per-track analysis and transitions as JSON")
    parser.add_argument("--no-mastering", action="store_true", help="Skip the mastering/phase check of each track")
    parser.add_argument("--save-charts", metavar="DIR", help="Write the overview, set map and per-track charts as PNG files")
    parser.add_argument("--fresh", action="store_true", help="Ignore the saved set project and rebuild the set list")
    parser.add_argument("--originals", action="store_true", help="Export the original files even when pre-mastered copies exist")
    parser.add_argument("--db", help="Path to mixxxdb.sqlite (auto-detected by default)")
    parser.add_argument("--playlist-name", help="Name of the Mixxx playlist to create (default: DynaMix - <folder>)")
    parser.add_argument("--no-mixxx", action="store_true", help="Only plan and print the sheet, do not touch Mixxx")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be written to Mixxx")
    parser.add_argument("--no-backup", action="store_true", help="Do not back up the Mixxx database first")
    args = parser.parse_args()

    project = None
    if args.m3u:
        tracks = tracks_from_m3u(args.m3u)
        default_name = os.path.splitext(os.path.basename(args.m3u))[0]
    elif args.playlist:
        from playlist_manager import PlaylistManager
        default_name = os.path.basename(os.path.normpath(args.playlist))
        manager = PlaylistManager(args.playlist)
        print(f"Analyzing {args.playlist} (cached results are reused) ...")
        manager.analyze_playlist(progress_callback=lambda i, n, name, status: print(f"  {i}/{n} {status}: {name}"))
        tracks = manager.create_set_list(duration_minutes=args.set_duration or 60, energy_curve=args.energy_curve or "build")
    else:
        from playlist_manager import PlaylistManager
        from set_project import SetProject
        project = SetProject.open(args.project)
        default_name = project.name
        files = project.source_files()
        if not files:
            print(f"No audio in {project.source_dir}: import files into the project first.")
            sys.exit(1)
        manager = PlaylistManager(project.source_dir)
        print(f"Analyzing project '{project.name}' (cached results are reused) ...")
        manager.analyze_playlist(files, progress_callback=lambda i, n, name, status: print(f"  {i}/{n} {status}: {name}"))
        project.set_tracks(manager.tracks)
        project.mark("analyze", count=len(manager.tracks), cached=manager.last_run["cached"], analyzed=manager.last_run["analyzed"])
        saved = project.set_list_tracks()
        if saved and not args.fresh:
            tracks = saved
            print(f"Using the saved set list of the project ({len(tracks)} tracks). Use --fresh to rebuild it.")
        else:
            duration = args.set_duration or int(project.options.get("set_duration", 60))
            curve = args.energy_curve or project.options.get("energy_curve", "build")
            tracks = manager.create_set_list(duration_minutes=duration, energy_curve=curve)
            project.set_set_list(tracks)
            project.options.update({"set_duration": duration, "energy_curve": curve})
            project.invalidate_from("setlist")
            project.mark("setlist", count=len(tracks), duration=duration, curve=curve)
        project.save()

    if len(tracks) < 1:
        print("No tracks to plan.")
        sys.exit(1)

    planner = TransitionPlanner(tracks, mix_bars=args.mix_bars, check_mastering=not args.no_mastering)
    planner.plan(progress_callback=lambda i, n, name: print(f"Planning {i}/{n}: {name}"))
    print()
    print(planner.to_text())
    if args.sheet:
        planner.save_text(args.sheet)
        print(f"Transition sheet saved to {args.sheet}")
    if args.json:
        planner.save_json(args.json)
        print(f"Transition data saved to {args.json}")
    if project is not None:
        project.data["transitions"] = planner.to_dict()
        project.mark("transitions", count=len(planner.transitions))
        project.save()
        print(f"Set project updated: {project.path}")
    if project is not None and args.save_charts is None and args.sheet is None:
        # a project always keeps its sheet and charts in exports/
        args.sheet = os.path.join(project.exports_dir, "transitions.txt")
        planner.save_text(args.sheet)
        args.save_charts = os.path.join(project.exports_dir, "charts")
    if args.save_charts:
        import matplotlib
        matplotlib.use("Agg")
        import charts
        os.makedirs(args.save_charts, exist_ok=True)
        targets = None
        if project is not None:
            from playlist_manager import PlaylistManager
            values = [PlaylistManager._energy_value(t) for t in tracks]
            targets = PlaylistManager._target_curve(values, project.options.get("energy_curve", "build"))
        charts.save(charts.set_overview(planner.profiles, targets), os.path.join(args.save_charts, "set_overview.png"))
        charts.save(charts.set_timeline(planner.profiles, planner.transitions), os.path.join(args.save_charts, "set_map.png"))
        from mastering import playlist_tone_target
        reports = [p["mastering"] for p in planner.profiles if p.get("mastering") and p["mastering"].get("lufs") is not None]
        median = playlist_tone_target(reports) if reports else None
        for i, prof in enumerate(planner.profiles, 1):
            charts.save(charts.track_detail(prof, median), os.path.join(args.save_charts, f"track_{i:02d}.png"))
        print(f"Charts written to {args.save_charts}")

    if args.no_mixxx:
        return

    db_path = args.db
    if not db_path:
        from config import Config
        db_path = Config().mixxx_db_path()
    if not db_path:
        print("Mixxx database not found. Pass --db PATH\\to\\mixxxdb.sqlite (Windows default: "
              "%LOCALAPPDATA%\\Mixxx\\mixxxdb.sqlite).")
        sys.exit(2)

    profiles = list(planner.profiles)
    if project is not None and not args.originals:
        mapping = project.premaster_map()
        if mapping:
            profiles = [dict(p, file_path=mapping.get(p["file_path"], p["file_path"])) for p in profiles]
            print(f"Using the pre-mastered copies for {sum(1 for p in planner.profiles if p['file_path'] in mapping)} tracks "
                  f"(--originals to export the original files).")
    exporter = MixxxExporter(db_path, backup=not args.no_backup)
    report = exporter.export(profiles, playlist_name=args.playlist_name or f"DynaMix - {default_name}",
                             dry_run=args.dry_run)
    print(format_report(report))
    if project is not None and not args.dry_run:
        project.mark("mixxx", db=db_path, playlist=args.playlist_name or f"DynaMix - {default_name}", cues=report["cues_written"])
        project.save()


if __name__ == "__main__":
    main()
