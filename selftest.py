#!/usr/bin/env python3
"""
Self-test of an installed or frozen DynaMix, without touching the user's data:

    DynaMix.exe --self-test report.txt      (the shareable build)
    python gui.py --self-test report.txt    (from the sources)

Checks Tk and the fonts, the charts, audio decoding (WAV, FLAC, MP3), the track
analysis (librosa), the mastering check and the limiter (numba), the transition
FX (freeze, filter, echo, time-stretched sample) and the analysis cache.
Exit code 0 when everything works; the report lists each step and its time.
"""

import os
import platform
import shutil
import sys
import tempfile
import time
import traceback

SR = 44100


def _clicks(seconds: float, bpm: float = 120.0, freq: float = 220.0):
    """A stereo test track: a tone with a click on every beat."""
    import numpy as np
    t = np.arange(int(seconds * SR)) / SR
    tone = 0.2 * np.sin(2 * np.pi * freq * t)
    clicks = 0.6 * np.exp(-((t % (60.0 / bpm)) * 40.0))
    mono = (tone + clicks * np.sin(2 * np.pi * 1000.0 * t)).astype("float32")
    return np.stack([mono, mono], axis=1)


def run(report_path=None) -> int:
    tmp = tempfile.mkdtemp(prefix="dynamix_selftest_")
    os.environ["DYNAMIX_HOME"] = os.path.join(tmp, "home")  # the user's cache and settings are never used
    from version import VERSION
    lines = [f"DynaMix {VERSION} self-test - Python {platform.python_version()} - "
             f"{'frozen build' if getattr(sys, 'frozen', False) else 'sources'} - {platform.platform()}"]
    failures = []
    files = {}

    def step(name, fn):
        start = time.time()
        try:
            detail = fn()
            lines.append(f"[OK  ] {name} ({time.time() - start:.1f} s)" + (f": {detail}" if detail else ""))
        except Exception as exc:  # noqa: BLE001 - every failure goes into the report
            failures.append(name)
            lines.append(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
            lines.append(traceback.format_exc().rstrip())

    def tk_fonts():
        import tkinter as tk
        from tkinter import ttk
        import ui_fonts
        root = tk.Tk()
        root.withdraw()
        try:
            size = ui_fonts.apply(root, 12)
            ttk.Treeview(root, columns=("a",), show="headings").pack()
            root.update_idletasks()
        finally:
            root.destroy()
        return f"Tk {tk.TkVersion}, fonts at {size} pt"

    def charts_png():
        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.backends import backend_tkagg  # the GUI's backend must be in the build
        import charts
        assert backend_tkagg.FigureCanvasTkAgg
        import transition_fx as tfx
        beats = [i * 0.5 for i in range(200)]
        layout = tfx.transition_layout(beats, beats, 40.0, 48.0, 8.0, [tfx.new_effect("freeze"), tfx.new_effect("echo")])
        path = charts.save(charts.transition_detail(layout), os.path.join(tmp, "chart.png"))
        return f"{os.path.getsize(path) // 1024} KB PNG"

    def audio_files():
        import soundfile as sf
        from mastering import load_audio
        a, b = _clicks(20.0), _clicks(20.0, freq=330.0)
        files["a"], files["b"] = os.path.join(tmp, "a.wav"), os.path.join(tmp, "b.flac")
        sf.write(files["a"], a, SR)
        sf.write(files["b"], b, SR)
        files["mp3"] = os.path.join(tmp, "c.mp3")
        sf.write(files["mp3"], a, SR, format="MP3")
        decoded = {name: load_audio(path)[0].shape[0] / SR for name, path in files.items()}
        return ", ".join(f"{name} {seconds:.1f} s" for name, seconds in decoded.items()) + f" (libsndfile {sf.__libsndfile_version__})"

    def analysis():
        from audio_utils import AudioAnalyzer
        features = AudioAnalyzer(files["a"]).get_audio_features()
        return f"BPM {features['bpm']:.1f}, key {features['key']}, energy level {features['energy_level']:.1f}"

    def mastering_check():
        import numpy as np
        from mastering import check_files, true_peak_limiter
        limited = true_peak_limiter(_clicks(5.0) * 3.0, SR, ceiling_db=-1.0)
        report = check_files([files["a"]])[0]
        return f"limiter peak {20 * np.log10(np.max(np.abs(limited))):.1f} dBFS, loudness {report.get('lufs', 0):.1f} LUFS"

    def transition_fx():
        import soundfile as sf
        import transition_fx as tfx
        beats = [i * 0.5 for i in range(40)]
        sample = os.path.join(tmp, "riser 100BPM.wav")
        sf.write(sample, _clicks(2.0, bpm=100.0)[:, 0], SR)
        ctx = tfx.make_context(_clicks(20.0), SR, beats, 12.0, 16.0, _clicks(20.0, freq=330.0), SR, beats, 2.0)
        effects = [dict(tfx.new_effect("freeze"), capture_offset_beats=-2),
                   dict(tfx.new_effect("filter"), side="incoming"),
                   tfx.new_effect("echo"),
                   dict(tfx.new_effect("sample"), file=sample, tempo="stretch", repeats=2)]
        tfx.apply_effects(ctx, effects)
        clip, sr = tfx.preview_mix(ctx, 8.0)
        return f"preview {len(clip) / sr:.1f} s" + (f", warnings: {'; '.join(ctx.warnings)}" if ctx.warnings else "")

    def cache():
        from analysis_store import get_store
        store = get_store()
        store.put(files["a"], "features", {"bpm": 120.0})
        if (store.get(files["a"], "features") or {}).get("bpm") != 120.0:
            raise RuntimeError("the cached value was not read back")
        return "SQLite read / write"

    for name, fn in (("Tk and fonts", tk_fonts), ("Charts", charts_png), ("Audio files (WAV, FLAC, MP3)", audio_files),
                     ("Track analysis (librosa)", analysis), ("Mastering check and limiter (numba)", mastering_check),
                     ("Transition FX", transition_fx), ("Analysis cache", cache)):
        if name in ("Track analysis (librosa)", "Mastering check and limiter (numba)") and "a" not in files:
            failures.append(name)
            lines.append(f"[FAIL] {name}: skipped, the test audio could not be written")
            continue
        step(name, fn)

    lines.append("All checks passed." if not failures else f"{len(failures)} check(s) failed: {', '.join(failures)}")
    text = "\n".join(lines) + "\n"
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(text)
    elif sys.stdout is not None:
        sys.stdout.write(text)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
