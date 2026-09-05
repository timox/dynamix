#!/usr/bin/env python3
"""
DynaMix installation checker.

Run it after installing the requirements to make sure everything DynaMix
needs is available on this machine (Windows, Linux or macOS):

    python check_install.py

It checks the Python version, every required package, Tkinter (for the GUI),
MP3 decoding (via soundfile/libsndfile, no FFmpeg needed), FFmpeg (optional,
for M4A/AAC files) and finally runs a short end-to-end analysis on a
synthetic audio clip.
"""

import importlib
import os
import shutil
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")

REQUIRED_PACKAGES = [
    ("librosa", "librosa"),
    ("numpy", "numpy"),
    ("matplotlib", "matplotlib"),
    ("pandas", "pandas"),
    ("seaborn", "seaborn"),
    ("scipy", "scipy"),
    ("scikit-learn", "sklearn"),
    ("soundfile", "soundfile"),
]

results = []


def report(ok, label, detail=""):
    mark = "OK  " if ok else "FAIL"
    results.append(ok)
    line = f"[{mark}] {label}"
    if detail:
        line += f" - {detail}"
    print(line)


def warn(label, detail=""):
    line = f"[WARN] {label}"
    if detail:
        line += f" - {detail}"
    print(line)


def check_python():
    version = sys.version_info
    ok = version >= (3, 8)
    report(ok, "Python version", f"{version.major}.{version.minor}.{version.micro}")
    if version >= (3, 13):
        warn("Python 3.13+ detected", "if pip fails to build numba/llvmlite, use Python 3.11 or 3.12")
    return ok


def check_packages():
    all_ok = True
    for dist_name, module_name in REQUIRED_PACKAGES:
        try:
            module = importlib.import_module(module_name)
            version = getattr(module, "__version__", "?")
            report(True, f"package {dist_name}", version)
        except Exception as exc:  # noqa: BLE001
            report(False, f"package {dist_name}", f"{type(exc).__name__}: {exc}")
            all_ok = False
    return all_ok


def check_tkinter():
    try:
        import tkinter  # noqa: F401

        report(True, "Tkinter (GUI)", f"Tk {tkinter.TkVersion}")
        return True
    except Exception as exc:  # noqa: BLE001
        report(False, "Tkinter (GUI)", f"{exc} - the GUI (gui.py) will not start")
        print(f"       Python used by this venv: {sys.base_prefix}")
        if sys.platform.startswith("win"):
            print("       Fix: Settings > Apps > Installed apps > Python 3.x > Modify > Modify,")
            print("       tick 'tcl/tk and IDLE', finish, then run this script again (no need to recreate venv).")
            print("       Conda users: conda install tk")
        else:
            print("       Fix: install the tk package of your distribution (e.g. apt install python3-tk)")
        return False


def check_mp3():
    try:
        import soundfile as sf

        formats = sf.available_formats()
        ok = "MP3" in formats
        report(ok, "MP3 decoding via soundfile", f"libsndfile {sf.__libsndfile_version__}")
        if not ok:
            warn("MP3 not supported by libsndfile", "install FFmpeg so librosa can fall back to it")
        return ok
    except Exception as exc:  # noqa: BLE001
        report(False, "MP3 decoding via soundfile", str(exc))
        return False


def check_ffmpeg():
    path = shutil.which("ffmpeg")
    if path:
        print(f"[OK  ] FFmpeg (optional, for M4A/AAC) - {path}")
    else:
        warn("FFmpeg not found (optional)", "only needed for .m4a/.aac files; MP3/WAV/FLAC/OGG work without it")
    return True


def check_end_to_end():
    try:
        import numpy as np
        import soundfile as sf

        import matplotlib

        matplotlib.use("Agg")
        from audio_utils import AudioAnalyzer
        from dj_tools import DJTools

        sr = 22050
        t = np.linspace(0, 12, 12 * sr, endpoint=False)
        y = 0.3 * np.sin(2 * np.pi * 220.0 * t) + 0.4 * (np.sin(2 * np.pi * 2.0 * t) > 0.97)
        tmp_dir = tempfile.mkdtemp(prefix="dynamix_check_")
        path = os.path.join(tmp_dir, "check.wav")
        sf.write(path, y.astype("float32"), sr)

        analyzer = AudioAnalyzer(path)
        features = analyzer.get_audio_features()
        dj = DJTools(path)
        cues = dj.detect_cue_points()
        shutil.rmtree(tmp_dir, ignore_errors=True)

        report(True, "End-to-end analysis",
               f"BPM {features['bpm']:.1f}, key {features['key']}, {len(cues)} cue points")
        return True
    except Exception as exc:  # noqa: BLE001
        report(False, "End-to-end analysis", f"{type(exc).__name__}: {exc}")
        return False


def main():
    print("DynaMix installation check")
    print("=" * 40)
    check_python()
    packages_ok = check_packages()
    check_tkinter()
    check_mp3()
    check_ffmpeg()
    if packages_ok:
        check_end_to_end()
    else:
        report(False, "End-to-end analysis", "skipped, install the missing packages first: pip install -r requirements.txt")
    print("=" * 40)
    failed = results.count(False)
    if failed == 0:
        print("All checks passed. Try:  python gui.py")
        return 0
    print(f"{failed} check(s) failed. See messages above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
