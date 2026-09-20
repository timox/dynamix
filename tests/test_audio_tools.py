#!/usr/bin/env python3
"""Audio editors and FFmpeg: detection, command lines, PATH."""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audio_tools


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()
    return path


class TestDetection(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dynamix_tools_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_install_folders(self):
        audacity = touch(os.path.join(self.root, "Audacity", "audacity.exe"))
        touch(os.path.join(self.root, "Renoise 3.4.0", "Renoise.exe"))
        renoise = touch(os.path.join(self.root, "Renoise 3.5.4", "Renoise.exe"))
        ableton = touch(os.path.join(self.root, "Ableton", "Live 12 Suite", "Program", "Ableton Live 12 Suite.exe"))
        mixbus = touch(os.path.join(self.root, "Mixbus11", "bin", "Mixbus.exe"))
        found = {key: audio_tools.detect_editor(key, roots=[self.root], programs=[]) for key in audio_tools.EDITOR_KEYS}
        self.assertEqual(found, {"audacity": audacity, "renoise": renoise, "ableton": ableton, "mixbus": mixbus})

    def test_registry_entry_wins(self):
        exe = touch(os.path.join(self.root, "Custom", "Program", "Ableton Live 12 Suite.exe"))
        # the second uninstall entry points at the installer kept by Windows: its name matches too, it must be left out
        installer = touch(os.path.join(self.root, "Package Cache", "{8c15}", "Ableton Live 12 Suite Installer.exe"))
        programs = [{"name": "Ableton Live 12 Suite", "location": "", "icon": f"{installer},0"},
                    {"name": "Ableton Live 12 Suite", "location": os.path.join(self.root, "Custom"), "icon": ""}]
        self.assertEqual(audio_tools.detect_editor("ableton", roots=[], programs=programs), exe)
        icon = touch(os.path.join(self.root, "A", "audacity.exe"))
        self.assertEqual(audio_tools.detect_editor("audacity", roots=[], programs=[{"name": "Audacity 3.7.8", "location": "",
                                                                                     "icon": f'"{icon}",0'}]), icon)

    def test_nothing_found(self):
        self.assertEqual(audio_tools.detect_editor("mixbus", roots=[self.root], programs=[]), "")

    def test_ffmpeg(self):
        ffmpeg = touch(os.path.join(self.root, "ffmpeg", "bin", "ffmpeg.exe"))
        with patch("shutil.which", return_value=None):
            self.assertEqual(audio_tools.detect_ffmpeg(roots=[self.root]), ffmpeg)
        old = os.environ.get("PATH", "")
        try:
            self.assertTrue(audio_tools.apply_ffmpeg_path(ffmpeg))
            self.assertEqual(os.environ["PATH"].split(os.pathsep)[0], os.path.dirname(ffmpeg))
            self.assertFalse(audio_tools.apply_ffmpeg_path(ffmpeg))                   # already there
            self.assertFalse(audio_tools.apply_ffmpeg_path(os.path.join(self.root, "missing.exe")))
        finally:
            os.environ["PATH"] = old


class TestOpening(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dynamix_tools_")
        self.exe = touch(os.path.join(self.root, "editor.exe"))
        self.song = touch(os.path.join(self.root, "my song.wav"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_build_command(self):
        self.assertEqual(audio_tools.build_command("a.exe", "{file}", "x y.wav"), ["a.exe", "x y.wav"])
        self.assertEqual(audio_tools.build_command("a.exe", "--import {file} -n", "s.wav"), ["a.exe", "--import", "s.wav", "-n"])
        self.assertEqual(audio_tools.build_command("a.exe", "", "s.wav"), ["a.exe"])

    def test_open_with_the_file(self):
        with patch("audio_tools.subprocess.Popen") as popen:
            result = audio_tools.open_in_editor(self.exe, "{file}", self.song)
        self.assertEqual(result, {"command": [self.exe, self.song], "revealed": False})
        self.assertEqual(popen.call_count, 1)

    def test_open_without_file_argument_reveals_the_file(self):
        with patch("audio_tools.subprocess.Popen") as popen:
            result = audio_tools.open_in_editor(self.exe, "", self.song)
        self.assertTrue(result["revealed"])
        self.assertEqual(popen.call_count, 2)                                        # the editor, then the file manager
        self.assertEqual(popen.call_args_list[0][0][0], [self.exe])

    def test_errors(self):
        with self.assertRaises(FileNotFoundError):
            audio_tools.open_in_editor(os.path.join(self.root, "none.exe"), "{file}", self.song)
        with self.assertRaises(FileNotFoundError):
            audio_tools.open_in_editor(self.exe, "{file}", os.path.join(self.root, "none.wav"))


class TestFfmpegDownload(unittest.TestCase):
    """FFmpeg is downloaded on request (GPL: never shipped with DynaMix), then kept in the DynaMix home."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="dynamix_ff_")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _archive(self, names=("ffmpeg-8.0-essentials_build/bin/ffmpeg.exe",
                              "ffmpeg-8.0-essentials_build/bin/ffprobe.exe",
                              "ffmpeg-8.0-essentials_build/doc/ffmpeg.html")):
        """A zip shaped like the official Windows build."""
        import zipfile
        path = os.path.join(self.root, "ffmpeg.zip")
        with zipfile.ZipFile(path, "w") as z:
            for name in names:
                z.writestr(name, b"MZ" + name.encode())
        return path

    def _download(self, archive, dest, progress=None):
        """Run download_ffmpeg with the network replaced by a local file."""
        def fake_open(url, timeout=0):
            return open(archive, "rb")
        with patch.object(audio_tools, "_urlopen", fake_open):
            return audio_tools.download_ffmpeg(dest, progress=progress)

    def test_only_the_programs_are_kept_and_the_path_is_returned(self):
        dest = os.path.join(self.root, "home", "ffmpeg")
        exe = self._download(self._archive(), dest)
        self.assertEqual(exe, os.path.join(dest, "ffmpeg.exe"))
        self.assertEqual(sorted(os.listdir(dest)), ["ffmpeg.exe", "ffprobe.exe"])   # the docs are dropped
        with open(exe, "rb") as f:
            self.assertTrue(f.read().startswith(b"MZ"))

    def test_progress_is_reported(self):
        seen = []
        self._download(self._archive(), os.path.join(self.root, "ffmpeg"), progress=lambda done, total: seen.append(done))
        self.assertTrue(seen)
        self.assertEqual(seen[-1], max(seen))

    def test_an_archive_without_ffmpeg_is_refused(self):
        archive = self._archive(names=("build/doc/ffmpeg.html",))
        with self.assertRaises(ValueError) as caught:
            self._download(archive, os.path.join(self.root, "ffmpeg"))
        self.assertIn("ffmpeg.exe", str(caught.exception))

    def test_a_second_download_replaces_the_first(self):
        dest = os.path.join(self.root, "ffmpeg")
        self._download(self._archive(), dest)
        stale = os.path.join(dest, "old.exe")
        open(stale, "wb").close()
        self._download(self._archive(), dest)
        self.assertFalse(os.path.exists(stale))


if __name__ == "__main__":
    unittest.main()
