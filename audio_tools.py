#!/usr/bin/env python3
"""
External audio tools: FFmpeg (optional, for M4A/AAC decoding) and the audio
editors a track can be opened in (Audacity, Renoise, Ableton Live, Mixbus).

Detection looks at the installed programs declared to Windows (uninstall
registry keys), the usual install folders and the PATH. An editor is started
with a command built from an argument template: "{file}" is replaced by the
audio file; without "{file}" the editor is only started and the file is shown
selected in the file manager, ready to drag into the editor. Audacity opens the
file and Renoise loads it as a sample (checked on Windows); Ableton Live and
Mixbus only open their own projects from the command line.
"""

import fnmatch
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from typing import Dict, List, Optional, Sequence

# key, label, name in the installed programs, executable name (glob), folders under the install roots, default args
EDITORS = [
    {"key": "audacity", "label": "Audacity", "display": r"^Audacity", "exe": "audacity.exe",
     "folders": ["Audacity"], "args": "{file}"},
    {"key": "renoise", "label": "Renoise", "display": r"^Renoise", "exe": "Renoise.exe",
     "folders": ["Renoise*"], "args": "{file}"},
    {"key": "ableton", "label": "Ableton Live", "display": r"^Ableton Live", "exe": "Ableton Live*.exe",
     "folders": [os.path.join("Ableton", "Live*", "Program")], "args": ""},
    {"key": "mixbus", "label": "Mixbus", "display": r"^Mixbus", "exe": "Mixbus.exe",
     "folders": [os.path.join("Mixbus*", "bin")], "args": ""},
]
EDITOR_KEYS = [e["key"] for e in EDITORS]


def editor(key: str) -> Dict:
    return next(e for e in EDITORS if e["key"] == key)


def install_roots() -> List[str]:
    names = ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData")
    roots = [os.environ.get(n) for n in names]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Programs"))
    seen, out = set(), []
    for root in roots:
        if root and os.path.isdir(root) and os.path.normcase(root) not in seen:
            seen.add(os.path.normcase(root))
            out.append(root)
    return out


def _registry_programs() -> List[Dict[str, str]]:
    """Installed programs declared to Windows: [{'name', 'location', 'icon'}] ([] elsewhere)."""
    if not sys.platform.startswith("win"):
        return []
    import winreg
    found = []
    places = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
              (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in places:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                        values = {}
                        for name in ("DisplayName", "InstallLocation", "DisplayIcon"):
                            try:
                                values[name] = str(winreg.QueryValueEx(sub, name)[0])
                            except OSError:
                                values[name] = ""
                except OSError:
                    continue
                if values["DisplayName"]:
                    found.append({"name": values["DisplayName"], "location": values["InstallLocation"],
                                  "icon": values["DisplayIcon"]})
    return found


_INSTALLER_NAME = re.compile(r"install|setup|uninst|unins\d", re.IGNORECASE)


def _is_program(path: str) -> bool:
    """An existing executable that is not an installer, an uninstaller or a copy kept in Windows' Package Cache."""
    parts = os.path.normcase(os.path.abspath(path)).split(os.sep)
    return (os.path.isfile(path) and not _INSTALLER_NAME.search(os.path.basename(path))
            and "package cache" not in parts)


def _newest(paths: Sequence[str]) -> str:
    """The newest program among the candidates ("Renoise 3.5.4" before "Renoise 3.4")."""
    existing = sorted({p for p in paths if _is_program(p)}, reverse=True)
    return existing[0] if existing else ""


def detect_editor(key: str, roots: Optional[Sequence[str]] = None, programs: Optional[List[Dict[str, str]]] = None) -> str:
    """Path of an installed editor, or ''."""
    spec = editor(key)
    programs = _registry_programs() if programs is None else programs
    candidates = []
    for program in programs:
        if not re.search(spec["display"], program["name"], re.IGNORECASE):
            continue
        icon = program["icon"].strip().strip('"').split(",")[0].strip('"')
        if icon and fnmatch.fnmatch(os.path.basename(icon).lower(), spec["exe"].lower()):
            candidates.append(icon)
        location = program["location"].strip().strip('"')
        if location:
            for sub in ("", "Program", "bin"):
                candidates.extend(glob.glob(os.path.join(location, sub, spec["exe"])))
    found = _newest(candidates)
    if found:
        return found
    for root in (install_roots() if roots is None else roots):
        for folder in spec["folders"]:
            candidates.extend(glob.glob(os.path.join(root, folder, spec["exe"])))
    return _newest(candidates) or (shutil.which(spec["exe"]) if "*" not in spec["exe"] else "") or ""


def detect_ffmpeg(roots: Optional[Sequence[str]] = None) -> str:
    """FFmpeg on the PATH, else in the usual install folders (winget links, Program Files), or ''."""
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    candidates = []
    local = os.environ.get("LOCALAPPDATA")
    if local and roots is None:
        candidates.append(os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"))
    for root in (install_roots() if roots is None else roots):
        candidates.extend(glob.glob(os.path.join(root, "ffmpeg*", "bin", "ffmpeg.exe")))
    return _newest(candidates)


# The build ffmpeg.org points to for Windows. FFmpeg is GPL and DynaMix is MIT: it is never shipped with
# DynaMix, only downloaded when the user asks for it in the Configuration tab.
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_PROGRAMS = ("ffmpeg.exe", "ffprobe.exe")


def _urlopen(url: str, timeout: float = 30.0):
    """Opened through this function so a test can read a local file instead of the network."""
    from urllib.request import Request, urlopen
    return urlopen(Request(url, headers={"User-Agent": "DynaMix"}), timeout=timeout)


def download_ffmpeg(dest_dir: str, url: str = FFMPEG_URL, progress=None) -> str:
    """
    Download the static Windows build of FFmpeg and keep only its programs in dest_dir (emptied first).

    progress(bytes_read, total_bytes) is called while downloading; total is 0 when the server does not
    say. Returns the path of ffmpeg.exe. Raises ValueError when the archive holds no ffmpeg.exe.
    """
    archive = None
    try:
        with _urlopen(url) as response:
            total = int(getattr(response, "headers", {}).get("Content-Length", 0) or 0)
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                archive = tmp.name
                read = 0
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    tmp.write(chunk)
                    read += len(chunk)
                    if progress:
                        progress(read, total)
        with zipfile.ZipFile(archive) as z:
            wanted = {}
            for name in z.namelist():
                base = name.rsplit("/", 1)[-1].lower()
                if base in FFMPEG_PROGRAMS:
                    wanted[base] = name
            if "ffmpeg.exe" not in wanted:
                raise ValueError(f"no ffmpeg.exe in the archive downloaded from {url}")
            shutil.rmtree(dest_dir, ignore_errors=True)
            os.makedirs(dest_dir, exist_ok=True)
            for base, name in wanted.items():
                with z.open(name) as src, open(os.path.join(dest_dir, base), "wb") as out:
                    shutil.copyfileobj(src, out)
    finally:
        if archive and os.path.exists(archive):
            os.remove(archive)
    return os.path.join(dest_dir, "ffmpeg.exe")


def apply_ffmpeg_path(path: str) -> bool:
    """Put the configured FFmpeg first on this process's PATH (used by the M4A/AAC decoders); True if added."""
    if not path or not os.path.isfile(path):
        return False
    folder = os.path.dirname(os.path.abspath(path))
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if any(os.path.normcase(p) == os.path.normcase(folder) for p in parts):
        return False
    os.environ["PATH"] = os.pathsep.join([folder] + parts)
    return True


def build_command(exe: str, args: str, file: str) -> List[str]:
    """[exe, arguments...] with every "{file}" replaced by the audio file (each space-separated word is one argument)."""
    return [exe] + [word.replace("{file}", file) for word in (args or "").split()]


def reveal(file: str) -> None:
    """Show the file selected in the file manager."""
    file = os.path.normpath(os.path.abspath(file))
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", f"/select,{file}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", file])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(file)])


def open_in_editor(exe: str, args: str, file: str) -> Dict:
    """Start the editor; without "{file}" in args the file is shown in the file manager. Returns {'command', 'revealed'}."""
    if not exe or not os.path.isfile(exe):
        raise FileNotFoundError(f"editor not found: {exe or '(not set)'}")
    if not os.path.isfile(file):
        raise FileNotFoundError(f"audio file not found: {file}")
    command = build_command(exe, args, file)
    subprocess.Popen(command, cwd=os.path.dirname(os.path.abspath(file)))
    revealed = "{file}" not in (args or "")
    if revealed:
        reveal(file)
    return {"command": command, "revealed": revealed}
