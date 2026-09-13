# FX de transition — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** ajouter des FX de transition (freeze/roll, filtres passe-haut, passe-bas et passe-bande avec résonance, écho, samples) réglés par transition, écoutés en boucle et incrustés dans des copies `fx/`, sans jamais modifier les originaux ni le pré-master.

**Architecture :**
- `transition_fx.py` est un moteur DSP pur (numpy/scipy) : grille de temps, contexte de transition avec règle de débordement, effets, extrait de pré-écoute.
- `fx_render.py` rend un set entier ou un extrait à partir des bases (pré-master ou original).
- `SetProject` stocke les recettes par paire de morceaux et le dernier rendu, et choisit le fichier à jouer : copie FX, sinon pré-master, sinon original.
- `fx_window.py` est la fenêtre Tkinter, branchée dans le Set Builder, la playlist et l'export Mixxx.

**Tech Stack :** Python 3.8+, numpy, scipy.signal, soundfile, Tkinter/ttk, winsound (Windows, bibliothèque standard), `unittest`.

**Spec :** `docs/superpowers/specs/2026-09-14-transition-fx-design.md`

## Global Constraints

- Python 3.8+ : pas de `match`, pas de `list[str]` dans les signatures, utiliser `typing`.
- **Aucune nouvelle dépendance** : `winsound` est dans la bibliothèque standard Windows, `numpy`, `scipy` et `soundfile` sont déjà dans `requirements.txt`.
- Les libellés de l'interface restent en anglais : « Transition FX », « Add ▾ », « ▶ Preview (loop) », « ■ Stop », « Apply all FX », « Nudge (ms): », « FX samples folder: ».
- **Les originaux de la bibliothèque et les copies `premaster/` ne sont jamais écrits.** Le rendu écrit uniquement dans `<projet>/fx/`.
- Les copies FX sont toujours en **stéréo**. Le moteur travaille en `float32` de forme `(n, 2)`, et un fichier mono est dupliqué.
- Commandes à lancer depuis la racine du dépôt, dans Git Bash. Tests : `venv/Scripts/python.exe -m unittest discover -s tests -p "<fichier>" -v` (pytest n'est pas installé dans le venv). Vérification du GUI : `venv/Scripts/python.exe tests/gui_smoke.py`, qui doit se terminer par `GUI smoke OK`.
- **Base de tests actuelle** : 101 tests, dont **13 échecs préexistants** (2 failures, 11 errors) dans `test_audio_utils.py` et `test_dj_tools.py`, dus à des mocks librosa/DJTools périmés. Ils ne doivent ni être corrigés ni s'aggraver. À la fin : 124 tests, avec les mêmes 13 échecs et aucun autre.
- Tout test qui touche le cache ou la configuration isole `DYNAMIX_HOME` dans un dossier temporaire et appelle `analysis_store.reset_store()`.
- Chaque message de commit se termine par ces deux lignes, après une ligne vide :
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MUns5Z6kfLha44xzsbabYX
  ```
- Branche : `feature/transition-fx`. Commits avec des chemins explicites (jamais `git add -A` ni `git add .`).

**Écarts assumés par rapport à la spec** (le code a été prototypé et testé avant d'écrire ce plan) :
- **Pas de fichier `tests/test_mixxx_export.py`.** L'ordre de priorité copie FX > pré-master > original et les repères du rendu passent tous par `SetProject.rendered_profiles()`, utilisé à la fois par le GUI et par la CLI. Ils sont testés dans `tests/test_set_project_fx.py`.
- **Copies en stéréo** : le moteur produit `(n, 2)`. Voir les Global Constraints.

---

## Carte des fichiers

| Fichier | Rôle | Tâche |
|---|---|---|
| `transition_fx.py` (nouveau) | grille de temps, validation, filtres, écho, samples, contexte, effets, débordement, pré-écoute | 1 |
| `mastering.py` | `output_path_for` et `write_audio` extraits (réutilisés par le rendu FX) | 2 |
| `fx_render.py` (nouveau) | rendu d'un set dans `fx/`, extrait de pré-écoute d'une transition | 2 |
| `set_project.py` | bloc `fx`, recettes par paire, `rendered_profiles`, invalidation, reset (tâche 3) ; étape `fx` du workflow (tâche 5) | 3, 5 |
| `config.py`, `charts.py` | clé `fx_samples_folder` ; étiquettes FX sur la Set map | 4 |
| `fx_window.py` (nouveau) | fenêtre « Transition FX » et lecteur `Player` | 5 |
| `set_builder.py`, `mixxx_export.py` | bouton d'étape, ouverture de la fenêtre, `_with_rendered`, export M3U/Mixxx, invalidation après le pré-master, étiquettes Set map, dossier des samples dans Configuration | 4, 5 |
| `tests/gui_smoke.py` | parcours FX complet dans le GUI | 5 |
| `README.md`, `GUI_README.md` | documentation | 6 |

---

### Task 1 : moteur DSP `transition_fx.py`

**Files :**
- Create: `transition_fx.py`
- Test: `tests/test_transition_fx.py`

**Interfaces :**
- Consumes : `analysis_store.get_store()`, `audio_utils.AudioAnalyzer(path).analyze_beat_grid() -> (beat_times, strengths)` et `.duration`, `mastering.true_peak_limiter(x, fs, ceiling_db=-1.0)`.
- Produces (utilisées par les tâches 2 et 5) :
  - `FX_TYPES`, `DEFAULTS`, `MAX_SAMPLE_SECONDS` ;
  - `new_effect(fx_type) -> Dict`, `validate_effect(fx) -> List[str]` ;
  - `beat_grid(path) -> {"beats", "bpm", "has_beat", "duration"}` (cache, type `beats`) ;
  - `usable_beats(grid, fallback_bpm, duration) -> (beats, warning|None)` ;
  - `beat_time(beats, anchor_index, offset_beats)`, `nearest_beat_index`, `median_period` ;
  - `to_stereo(x)` ;
  - `biquad_coefficients(kind, freq, q, sr)`, `filter_q(kind, resonance, width_octaves)`, `sweep_filter(...)`, `tempo_echo(...)`, `load_sample(path, sr)` ;
  - la dataclass `TransitionContext` (`a`, `a_sr`, `a_offset`, `a_beats`, `junction_a`, `a_end`, `b`, `b_sr`, `b_offset`, `b_beats`, `junction_b`, `outro_start`, `overflow`, `warnings`, méthodes `a_index` et `b_index`) ;
  - `make_context(a_audio, a_sr, a_beats, a_outro_start, a_outro_end, b_audio, b_sr, b_beats, b_intro_start, nudge_ms=0.0)` ;
  - `apply_effects(ctx, effects) -> ctx` (lève `ValueError` sur un FX invalide), `mix_overflow(ctx)` ;
  - `preview_mix(ctx, b_intro_end, length="short"|"long") -> (clip, sr)`.

- [ ] **Step 1 : écrire le test qui échoue**

Créer `tests/test_transition_fx.py` :

```python
import os
import shutil
import tempfile
import unittest

import numpy as np
import soundfile as sf
from scipy import signal

import transition_fx as tfx

SR = 44100
PERIOD = 0.5  # 120 BPM


def grid(seconds=60.0):
    return [i * PERIOD for i in range(int(seconds / PERIOD) + 1)]


def sine(freq, seconds, sr=SR, amp=0.5):
    t = np.arange(int(seconds * sr)) / sr
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-12)


def ctx_for(a, b, outro_start=4.0, outro_end=6.0, intro_start=2.0, b_sr=SR):
    return tfx.make_context(a, SR, grid(), outro_start, outro_end, b, b_sr, grid(), intro_start)


class TestGridAndValidation(unittest.TestCase):
    def test_beat_time(self):
        beats = [0.0, 0.5, 1.0, 1.6]
        self.assertAlmostEqual(tfx.beat_time(beats, 1, 1), 1.0)
        self.assertAlmostEqual(tfx.beat_time(beats, 2, 0.5), 1.3)
        self.assertAlmostEqual(tfx.beat_time(beats, 0, -2), -1.0)   # median period 0.5 before the grid
        self.assertAlmostEqual(tfx.beat_time(beats, 3, 2), 2.6)
        self.assertEqual(tfx.nearest_beat_index(beats, 1.2), 2)

    def test_usable_beats_fallback(self):
        beats, warning = tfx.usable_beats({"beats": [0.0, 0.5], "has_beat": False}, 100.0, 3.0)
        self.assertAlmostEqual(beats[1], 0.6)
        self.assertIn("100 BPM", warning)
        real = grid(10)
        self.assertEqual(tfx.usable_beats({"beats": real, "has_beat": True}, 0, 10)[0], real)

    def test_beat_grid_uses_the_cache(self):
        import analysis_store
        tmp = tempfile.mkdtemp(prefix="dynamix_fx_")
        os.environ["DYNAMIX_HOME"] = tmp
        analysis_store.reset_store()
        try:
            path = os.path.join(tmp, "x.wav")
            sf.write(path, np.zeros(SR, dtype="float32"), SR)
            analysis_store.get_store().put(path, "beats", {"beats": [0.0, 0.5], "bpm": 120.0, "has_beat": False, "duration": 1.0})
            self.assertEqual(tfx.beat_grid(path)["bpm"], 120.0)
        finally:
            os.environ.pop("DYNAMIX_HOME", None)
            analysis_store.reset_store()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_validate_effect(self):
        self.assertEqual(tfx.validate_effect(tfx.new_effect("filter")), [])
        bad = dict(tfx.new_effect("filter"), resonance=20, colour="red")
        problems = tfx.validate_effect(bad)
        self.assertTrue(any("resonance" in p for p in problems))
        self.assertTrue(any("colour" in p for p in problems))
        long_freeze = dict(tfx.new_effect("freeze"), steps=[{"beats": 4, "repeats": 20}])
        self.assertTrue(any("longer than 64" in p for p in tfx.validate_effect(long_freeze)))
        self.assertTrue(any("file not found" in p for p in tfx.validate_effect(tfx.new_effect("sample"))))
        self.assertEqual(tfx.validate_effect({"type": "reverb"}), ["Unknown FX type: 'reverb'"])
        with self.assertRaises(ValueError):
            tfx.apply_effects(ctx_for(sine(100, 8), sine(100, 8)), [bad])


class TestFilters(unittest.TestCase):
    def test_outgoing_highpass_closes(self):
        a = sine(100, 8)
        ctx = ctx_for(a, np.zeros_like(a))
        fx = dict(tfx.new_effect("filter"), kind="highpass", start_hz=20, end_hz=2000, beats=4)
        tfx.apply_effects(ctx, [fx])
        before = ctx.a[int(0.5 * SR):int(1.5 * SR)]
        after = ctx.a[int(4.5 * SR):int(6.0 * SR)]
        self.assertLess(rms_db(after), rms_db(before) - 20)
        self.assertAlmostEqual(rms_db(before), rms_db(a[int(0.5 * SR):int(1.5 * SR)]), delta=0.5)

    def test_incoming_lowpass_opens_and_returns_dry(self):
        b = sine(5000, 10)
        ctx = ctx_for(np.zeros_like(b), b, intro_start=2.0)
        fx = dict(tfx.new_effect("filter"), side="incoming", kind="lowpass", start_hz=200, end_hz=20000, beats=4)
        tfx.apply_effects(ctx, [fx])
        start = ctx.b_index(2.0)
        closed = ctx.b[start:start + int(0.2 * SR)]
        dry = ctx.b[ctx.b_index(5.0):ctx.b_index(6.0)]
        self.assertLess(rms_db(closed), rms_db(dry) - 20)
        self.assertAlmostEqual(rms_db(dry), rms_db(b[int(5.0 * SR):int(6.0 * SR)]), delta=0.5)

    def test_resonance_and_bandpass_response(self):
        b, a = tfx.biquad_coefficients("highpass", 1000, tfx.filter_q("highpass", 8, 1), SR)
        _, h = signal.freqz(b, a, worN=[1000], fs=SR)
        self.assertGreater(20 * np.log10(abs(h[0])), 6)
        q = tfx.filter_q("bandpass", 0.707, 1.0)
        b, a = tfx.biquad_coefficients("bandpass", 1000, q, SR)
        _, h = signal.freqz(b, a, worN=[1000, 2000], fs=SR)
        self.assertAlmostEqual(20 * np.log10(abs(h[0])), 0.0, delta=0.5)
        self.assertLess(20 * np.log10(abs(h[1])), -3)


class TestFreeze(unittest.TestCase):
    def test_roll_lengths_content_and_seams(self):
        a = sine(440, 8)
        ctx = ctx_for(a, np.zeros_like(a))
        steps = [{"beats": 4, "repeats": 1}, {"beats": 2, "repeats": 2}, {"beats": 1, "repeats": 4}]
        tfx.apply_effects(ctx, [dict(tfx.new_effect("freeze"), steps=steps)])
        self.assertAlmostEqual(ctx.outro_start, 4.0)
        self.assertAlmostEqual(ctx.a_end, 10.0, places=3)
        self.assertEqual(len(ctx.a), int(4.0 * SR) + int(6.0 * SR))
        body = ctx.a[int(4.0 * SR):]
        guard = int(0.006 * SR)
        np.testing.assert_allclose(body[guard:int(2.0 * SR) - guard], a[int(2.0 * SR) + guard:int(4.0 * SR) - guard], atol=1e-6)
        np.testing.assert_allclose(body[int(2.0 * SR) + guard:int(3.0 * SR) - guard],
                                   a[int(3.0 * SR) + guard:int(4.0 * SR) - guard], atol=1e-6)
        self.assertLess(float(np.max(np.abs(np.diff(ctx.a[:, 0])))), 0.05)

    def test_fade_and_tail(self):
        a = sine(440, 8)
        ctx = ctx_for(a, np.zeros_like(a))
        fx = dict(tfx.new_effect("freeze"), steps=[{"beats": 1, "repeats": 8}], fade_db=-40, tail_beats=2)
        tfx.apply_effects(ctx, [fx])
        self.assertAlmostEqual(ctx.a_end, 4.0 + 4.0 + 1.0, places=3)
        first = ctx.a[int(4.05 * SR):int(4.45 * SR)]
        last = ctx.a[int(7.5 * SR):int(7.95 * SR)]
        self.assertLess(rms_db(last), rms_db(first) - 20)


class TestEchoAndSample(unittest.TestCase):
    def test_echo_repeats_and_overflow(self):
        a = np.zeros((int(8 * SR), 2), dtype=np.float32)
        a[int(3.0 * SR)] = 1.0
        b = np.zeros((int(10 * SR), 2), dtype=np.float32)
        ctx = ctx_for(a, b, outro_start=4.0, outro_end=4.5)
        fx = dict(tfx.new_effect("echo"), delay_beats=0.5, feedback=0.5, mix=1.0, damping_hz=20000)
        tfx.apply_effects(ctx, [fx])
        peaks = [float(np.max(np.abs(ctx.a[int((3.0 + k * 0.25) * SR) - 50:int((3.0 + k * 0.25) * SR) + 50]))) for k in (1, 2, 3)]
        self.assertTrue(peaks[0] > peaks[1] > peaks[2] > 0)
        after_end = ctx.b[ctx.b_index(2.0 + 0.5):]
        self.assertGreater(float(np.max(np.abs(after_end))), 0.0)

    def _sample(self, tmp, sr=22050):
        path = os.path.join(tmp, "hit.wav")
        sf.write(path, np.full(sr, 0.5, dtype="float32"), sr)
        return path

    def test_sample_anchors_and_overflow_resampled(self):
        tmp = tempfile.mkdtemp(prefix="dynamix_fx_")
        try:
            path = self._sample(tmp)
            base = dict(tfx.new_effect("sample"), file=path, gain_db=0.0, fade_in_ms=0, fade_out_ms=0)
            a = np.zeros((int(8 * SR), 2), dtype=np.float32)
            for anchor, lo, hi in (("end_at_junction", 3.0, 4.0), ("center_on_junction", 3.5, 4.5),
                                   ("start_at_junction", 4.0, 4.5)):
                ctx = ctx_for(a, np.zeros((int(10 * 48000), 2), dtype=np.float32), outro_end=4.5, b_sr=48000)
                tfx.apply_effects(ctx, [dict(base, anchor=anchor)])
                active = np.nonzero(np.abs(ctx.a[:, 0]) > 0.25)[0]
                self.assertAlmostEqual(active[0] / SR, lo, delta=0.002)
                self.assertAlmostEqual((active[-1] + 1) / SR, hi, delta=0.002)
                b_active = np.nonzero(np.abs(ctx.b[:, 0]) > 0.25)[0]
                if anchor == "start_at_junction":
                    self.assertAlmostEqual(len(b_active) / 48000, 0.5, delta=0.01)
                    self.assertAlmostEqual(b_active[0], ctx.b_index(2.0 + 0.5), delta=5)
                else:
                    self.assertEqual(len(b_active), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_preview_is_limited(self):
        a = sine(440, 8, amp=0.99)
        b = sine(660, 10, amp=0.99)
        ctx = ctx_for(a, b)
        tfx.apply_effects(ctx, [dict(tfx.new_effect("freeze"), steps=[{"beats": 2, "repeats": 2}])])
        clip, sr = tfx.preview_mix(ctx, b_intro_end=4.0, length="short")
        self.assertEqual(sr, SR)
        self.assertAlmostEqual(len(clip) / SR, (ctx.a_end + 4.0) - 0.0, delta=0.01)
        self.assertLessEqual(float(np.max(np.abs(clip))), 10 ** (-1 / 20) + 1e-3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2 : lancer le test pour vérifier qu'il échoue**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_transition_fx.py" -v`
Expected : ERROR `ModuleNotFoundError: No module named 'transition_fx'`

- [ ] **Step 3 : écrire l'implémentation**

Créer `transition_fx.py` :

```python
#!/usr/bin/env python3
"""
Transition FX for DynaMix: freeze / roll, filter sweeps, tempo-synced echo and
FX samples, placed in musical beats around the junction of two tracks.

A transition goes from track A (outgoing) to track B (incoming). The junction is
where B enters: A.outro_start in A's time, B.intro_start in B's time, both snapped
to a beat. Every effect is positioned in beats relative to the junction.

Overflow rule: what an effect writes while A is audible (until a_end) goes into
A; what lasts past a_end goes into B at the same musical instant, so nothing is
played twice during the crossfade.

Pure numpy / scipy: arrays in, arrays out (float32, shape (n, 2)).
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import signal

FX_TYPES = ("freeze", "filter", "echo", "sample")
BLOCK = 256
EDGE_FADE_S = 0.005
MAX_FREEZE_BEATS = 64
MAX_SAMPLE_SECONDS = 30.0
MAX_ECHO_TAIL_BEATS = 16
DEFAULT_BPM = 120.0
MIN_GRID_BEATS = 8


# ------------------------------------------------------------------ beat grid
def median_period(beats: Sequence[float]) -> float:
    """Median beat duration in seconds (120 BPM when the grid is too short)."""
    if len(beats) >= 2:
        return float(np.median(np.diff(np.asarray(beats, dtype=float))))
    return 60.0 / DEFAULT_BPM


def regular_grid(bpm: float, duration: float) -> List[float]:
    period = 60.0 / (bpm or DEFAULT_BPM)
    return [i * period for i in range(int(max(duration, 0.0) / period) + 2)]


def nearest_beat_index(beats: Sequence[float], t: float) -> int:
    return int(np.argmin(np.abs(np.asarray(beats, dtype=float) - t)))


def beat_time(beats: Sequence[float], anchor_index: int, offset_beats: float) -> float:
    """Seconds of the beat `offset_beats` away from beats[anchor_index] (fractions interpolate, edges extrapolate)."""
    arr = np.asarray(beats, dtype=float)
    period = median_period(arr)
    pos = anchor_index + offset_beats
    last = len(arr) - 1
    if pos <= 0:
        return float(arr[0] + pos * period)
    if pos >= last:
        return float(arr[last] + (pos - last) * period)
    i = int(math.floor(pos))
    return float(arr[i] + (pos - i) * (arr[i + 1] - arr[i]))


def beat_grid(path: str, use_cache: bool = True) -> Dict:
    """{'beats': [s...], 'bpm', 'has_beat', 'duration'} for a file, through the analysis cache (kind 'beats')."""
    from analysis_store import get_store
    store = get_store() if use_cache else None
    cached = store.get(path, "beats") if store else None
    if cached is not None:
        return cached
    from audio_utils import AudioAnalyzer
    analyzer = AudioAnalyzer(path)
    times, _ = analyzer.analyze_beat_grid()
    beats = [float(t) for t in np.atleast_1d(times)]
    grid = {"beats": beats, "bpm": 60.0 / median_period(beats) if len(beats) >= 2 else 0.0,
            "has_beat": len(beats) >= MIN_GRID_BEATS, "duration": float(analyzer.duration)}
    if store:
        store.put(path, "beats", grid)
    return grid


def usable_beats(grid: Dict, fallback_bpm: float, duration: float) -> Tuple[List[float], Optional[str]]:
    """The detected grid, or a regular one (with a warning) when the track has no usable beat."""
    beats = list(grid.get("beats") or [])
    if grid.get("has_beat", True) and len(beats) >= MIN_GRID_BEATS:
        return beats, None
    bpm = float(fallback_bpm or grid.get("bpm") or DEFAULT_BPM)
    return regular_grid(bpm, duration), f"no beat grid detected: using a regular {bpm:.0f} BPM grid"


# ------------------------------------------------------------------ validation
_RANGES = {
    "freeze": {"capture_offset_beats": (-16, 0), "fade_db": (-60, 0), "tail_beats": (0, 8), "gain_db": (-24, 6)},
    "filter": {"start_hz": (20, 20000), "end_hz": (20, 20000), "width_octaves": (0.3, 4), "resonance": (0.7, 12),
               "beats": (2, 16)},
    "echo": {"start_offset_beats": (-16, 0), "delay_beats": (0.25, 1), "feedback": (0, 0.85), "mix": (0, 1),
             "damping_hz": (1000, 20000)},
    "sample": {"offset_beats": (-16, 16), "gain_db": (-24, 6), "fade_in_ms": (0, 2000), "fade_out_ms": (0, 2000)},
}
_CHOICES = {
    "filter": {"side": ("outgoing", "incoming"), "kind": ("highpass", "lowpass", "bandpass"),
               "curve": ("exponential", "linear"), "beats": (2, 4, 8, 16)},
    "echo": {"delay_beats": (0.25, 0.5, 0.75, 1)},
    "sample": {"anchor": ("end_at_junction", "start_at_junction", "center_on_junction")},
}
DEFAULTS = {
    "freeze": {"enabled": True, "capture_offset_beats": 0, "steps": [{"beats": 1, "repeats": 4}], "loop_filter": None,
               "loop_echo": None, "fade_db": 0.0, "tail_beats": 0, "gain_db": 0.0},
    "filter": {"enabled": True, "side": "outgoing", "kind": "highpass", "start_hz": 20.0, "end_hz": 1000.0,
               "width_octaves": 1.0, "resonance": 0.707, "beats": 8, "curve": "exponential"},
    "echo": {"enabled": True, "start_offset_beats": -4, "delay_beats": 0.5, "feedback": 0.5, "mix": 0.5,
             "damping_hz": 6000.0},
    "sample": {"enabled": True, "file": "", "anchor": "end_at_junction", "offset_beats": 0.0, "gain_db": -3.0,
               "fade_in_ms": 5, "fade_out_ms": 5},
}


def new_effect(fx_type: str) -> Dict:
    """A fresh effect of that type with its default settings."""
    if fx_type not in DEFAULTS:
        raise ValueError(f"Unknown FX type: {fx_type}")
    import copy
    return dict(copy.deepcopy(DEFAULTS[fx_type]), type=fx_type)


def _check_ranges(fx_type: str, fx: Dict, label: str = "") -> List[str]:
    errors = []
    for key, (lo, hi) in _RANGES.get(fx_type, {}).items():
        if key in fx and fx[key] is not None and not (lo <= float(fx[key]) <= hi):
            errors.append(f"{label}{fx_type}: {key}={fx[key]} is outside {lo}..{hi}")
    for key, allowed in _CHOICES.get(fx_type, {}).items():
        if key in fx and fx[key] not in allowed:
            errors.append(f"{label}{fx_type}: {key}={fx[key]!r} must be one of {', '.join(map(str, allowed))}")
    return errors


def validate_effect(fx: Dict) -> List[str]:
    """Readable problems with an effect's settings ([] when it can be rendered)."""
    fx_type = fx.get("type")
    if fx_type not in FX_TYPES:
        return [f"Unknown FX type: {fx_type!r}"]
    known = set(DEFAULTS[fx_type]) | {"type"}
    errors = [f"{fx_type}: unknown setting {key!r}" for key in fx if key not in known]
    errors += _check_ranges(fx_type, fx)
    if fx_type == "freeze":
        steps = fx.get("steps") or []
        if not steps:
            errors.append("freeze: at least one step is needed")
        total = 0.0
        for step in steps:
            if step.get("beats") not in (4, 2, 1, 0.5) or int(step.get("repeats", 0)) < 1:
                errors.append(f"freeze: invalid step {step} (beats 4/2/1/0.5, repeats >= 1)")
            else:
                total += float(step["beats"]) * int(step["repeats"])
        if total > MAX_FREEZE_BEATS:
            errors.append(f"freeze: {total:g} beats is longer than {MAX_FREEZE_BEATS}")
        if fx.get("loop_filter"):
            errors += _check_ranges("filter", dict(fx["loop_filter"], side="outgoing"), "loop ")
        if fx.get("loop_echo"):
            errors += _check_ranges("echo", dict(fx["loop_echo"], start_offset_beats=0), "loop ")
    if fx_type == "sample":
        import os
        if not fx.get("file") or not os.path.isfile(fx["file"]):
            errors.append(f"sample: file not found: {fx.get('file') or '(none)'}")
    return errors


# ------------------------------------------------------------------ DSP building blocks
def to_stereo(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    return np.ascontiguousarray(x[:, :2])


def _fade(x: np.ndarray, sr: int, fade_in_s: float = EDGE_FADE_S, fade_out_s: float = EDGE_FADE_S) -> np.ndarray:
    y = np.array(x, dtype=np.float32, copy=True)
    n = len(y)
    fi = min(n, int(round(fade_in_s * sr)))
    fo = min(n, int(round(fade_out_s * sr)))
    if fi > 0:
        y[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)[:, None]
    if fo > 0:
        y[n - fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)[:, None]
    return y


def _db(value: float) -> float:
    return float(10 ** (value / 20.0))


def biquad_coefficients(kind: str, freq: float, q: float, sr: int) -> Tuple[np.ndarray, np.ndarray]:
    """RBJ cookbook biquad (b, a), normalised; bandpass has a 0 dB peak."""
    freq = float(np.clip(freq, 10.0, 0.45 * sr))
    w0 = 2.0 * math.pi * freq / sr
    cos_w, sin_w = math.cos(w0), math.sin(w0)
    alpha = sin_w / (2.0 * max(q, 0.1))
    if kind == "lowpass":
        b = [(1 - cos_w) / 2, 1 - cos_w, (1 - cos_w) / 2]
    elif kind == "highpass":
        b = [(1 + cos_w) / 2, -(1 + cos_w), (1 + cos_w) / 2]
    elif kind == "bandpass":
        b = [alpha, 0.0, -alpha]
    else:
        raise ValueError(f"Unknown filter kind: {kind}")
    a = [1 + alpha, -2 * cos_w, 1 - alpha]
    return np.asarray(b) / a[0], np.asarray(a) / a[0]


def filter_q(kind: str, resonance: float, width_octaves: float) -> float:
    """Q for a filter: the resonance for highpass/lowpass; width-derived Q scaled by resonance for bandpass."""
    if kind != "bandpass":
        return float(resonance)
    bw = 2.0 ** float(width_octaves)
    return float(math.sqrt(bw) / (bw - 1.0) * (float(resonance) / 0.707))


def sweep_filter(x: np.ndarray, sr: int, kind: str, start_hz: float, end_hz: float, q: float,
                 sweep_samples: int, curve: str = "exponential", hold_start: int = 0) -> np.ndarray:
    """
    Time-varying biquad: start_hz during the first `hold_start` samples, then a sweep to end_hz
    over `sweep_samples`, then end_hz. Coefficients change every BLOCK samples; the state is kept.
    """
    x = to_stereo(x)
    y = np.empty_like(x)
    n = len(x)
    if n == 0:
        return y
    zi = None
    for start in range(0, n, BLOCK):
        end = min(n, start + BLOCK)
        centre = (start + end) / 2.0 - hold_start
        t = 0.0 if centre <= 0 else min(1.0, centre / max(1, sweep_samples))
        if curve == "linear":
            freq = start_hz + (end_hz - start_hz) * t
        else:
            freq = start_hz * (end_hz / start_hz) ** t
        b, a = biquad_coefficients(kind, freq, q, sr)
        if zi is None:
            zi = signal.lfilter_zi(b, a)[:, None] * x[0][None, :]
        y[start:end], zi = signal.lfilter(b, a, x[start:end], axis=0, zi=zi)
    return y.astype(np.float32)


def tempo_echo(x: np.ndarray, sr: int, delay_s: float, feedback: float, mix: float, damping_hz: float,
               max_tail_s: float) -> np.ndarray:
    """Dry signal plus feedback echo (one-pole low-pass in the loop); the tail is trimmed below -60 dB."""
    x = to_stereo(x)
    d = max(1, int(round(delay_s * sr)))
    n_in = len(x)
    n_out = n_in + int(round(max_tail_s * sr))
    inp = np.zeros((n_out, 2), dtype=np.float32)
    inp[:n_in] = x
    wet = np.zeros_like(inp)
    coef = math.exp(-2.0 * math.pi * float(damping_hz) / sr)
    b, a = [1.0 - coef], [1.0, -coef]
    zi = np.zeros((1, 2))
    for start in range(d, n_out, d):
        end = min(n_out, start + d)
        src = wet[start - d:end - d]
        damped, zi = signal.lfilter(b, a, src, axis=0, zi=zi)
        wet[start:end] = inp[start - d:end - d] + feedback * damped
    out = inp + mix * wet
    peak = float(np.max(np.abs(out))) if n_out else 0.0
    if n_out > n_in and peak > 0:
        loud = np.nonzero(np.max(np.abs(out[n_in:]), axis=1) > peak * 1e-3)[0]
        keep = n_in + (int(loud[-1]) + 1 if len(loud) else 0)
        out = out[:keep]
    return out


def load_sample(path: str, sr: int) -> np.ndarray:
    """An FX sample as stereo float32 at sr (not time-stretched); refuses files longer than 30 s."""
    import soundfile as sf
    info = sf.info(path)
    if info.duration > MAX_SAMPLE_SECONDS:
        raise ValueError(f"{path}: {info.duration:.1f} s is longer than {MAX_SAMPLE_SECONDS:.0f} s")
    data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    data = to_stereo(data)
    if int(file_sr) != int(sr):
        g = math.gcd(int(sr), int(file_sr))
        data = signal.resample_poly(data, int(sr) // g, int(file_sr) // g, axis=0).astype(np.float32)
    return data


# ------------------------------------------------------------------ transition context
@dataclass
class TransitionContext:
    a: np.ndarray            # outgoing region (n, 2), starting at a_offset seconds in track A
    a_sr: int
    a_offset: float
    a_beats: List[float]     # beat times of track A (absolute seconds)
    junction_a: float        # absolute seconds in A (snapped + nudge)
    a_end: float             # where A stops being audible (outro_end, or the end of a freeze)
    b: np.ndarray            # incoming region (n, 2), starting at b_offset seconds in track B
    b_sr: int
    b_offset: float
    b_beats: List[float]
    junction_b: float
    outro_start: float = 0.0  # A's outro start in the rendered copy (the junction, or the freeze capture point)
    overflow: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), dtype=np.float32))
    warnings: List[str] = field(default_factory=list)

    def a_index(self, t: float) -> int:
        return int(round((t - self.a_offset) * self.a_sr))

    def b_index(self, t: float) -> int:
        return int(round((t - self.b_offset) * self.b_sr))

    @property
    def a_junction_index(self) -> int:
        return nearest_beat_index(self.a_beats, self.junction_a)

    @property
    def b_junction_index(self) -> int:
        return nearest_beat_index(self.b_beats, self.junction_b)

    @property
    def a_period(self) -> float:
        return median_period(self.a_beats)


def make_context(a_audio: np.ndarray, a_sr: int, a_beats: Sequence[float], a_outro_start: float, a_outro_end: float,
                 b_audio: np.ndarray, b_sr: int, b_beats: Sequence[float], b_intro_start: float,
                 nudge_ms: float = 0.0, a_region_s: float = 45.0, b_region_s: float = 120.0) -> TransitionContext:
    """Snap the junction to the beat grids and cut the working regions out of the two tracks."""
    nudge = float(nudge_ms) / 1000.0
    junction_a = float(a_beats[nearest_beat_index(a_beats, a_outro_start)]) + nudge
    junction_b = float(b_beats[nearest_beat_index(b_beats, b_intro_start)]) + nudge
    a_audio, b_audio = to_stereo(a_audio), to_stereo(b_audio)
    a_offset = max(0.0, junction_a - a_region_s)
    b_offset = max(0.0, junction_b - 2.0)
    a_start = int(round(a_offset * a_sr))
    b_start = int(round(b_offset * b_sr))
    b_stop = min(len(b_audio), int(round((junction_b + b_region_s) * b_sr)))
    a_end = max(junction_a, float(a_outro_end) + nudge)
    return TransitionContext(a=np.array(a_audio[a_start:], copy=True), a_sr=int(a_sr), a_offset=a_start / a_sr,
                             a_beats=list(a_beats), junction_a=junction_a, a_end=a_end,
                             b=np.array(b_audio[b_start:b_stop], copy=True), b_sr=int(b_sr), b_offset=b_start / b_sr,
                             b_beats=list(b_beats), junction_b=junction_b, outro_start=junction_a)


def _add_layer(ctx: TransitionContext, layer: np.ndarray, start_t: float) -> None:
    """Mix a layer that starts at absolute A time start_t: into A until a_end, into the overflow after."""
    layer = to_stereo(layer)
    begin = ctx.a_index(start_t)
    if begin < 0:
        layer = layer[-begin:]
        begin = 0
    end_idx = ctx.a_index(ctx.a_end)
    in_a = max(0, min(len(layer), end_idx - begin))
    if in_a:
        stop = begin + in_a
        if stop > len(ctx.a):
            ctx.a = np.concatenate([ctx.a, np.zeros((stop - len(ctx.a), 2), dtype=np.float32)])
        ctx.a[begin:stop] += layer[:in_a]
    rest = layer[in_a:]
    if len(rest):
        at = max(0, begin + in_a - end_idx)
        need = at + len(rest)
        if need > len(ctx.overflow):
            ctx.overflow = np.concatenate([ctx.overflow, np.zeros((need - len(ctx.overflow), 2), dtype=np.float32)])
        ctx.overflow[at:need] += rest


# ------------------------------------------------------------------ effects
def _apply_freeze(ctx: TransitionContext, fx: Dict) -> None:
    j = ctx.a_junction_index
    capture_offset = int(fx.get("capture_offset_beats", 0))
    capture_t = beat_time(ctx.a_beats, j, capture_offset)
    capture_i = ctx.a_index(capture_t)
    pieces = []
    for step in fx.get("steps") or []:
        seg_start = ctx.a_index(beat_time(ctx.a_beats, j, capture_offset - float(step["beats"])))
        segment = _fade(ctx.a[max(0, seg_start):capture_i], ctx.a_sr)
        pieces.extend([segment] * int(step["repeats"]))
    freeze = np.concatenate(pieces) if pieces else np.zeros((0, 2), dtype=np.float32)
    n_freeze = len(freeze)
    tail = np.zeros((int(round(float(fx.get("tail_beats", 0)) * ctx.a_period * ctx.a_sr)), 2), dtype=np.float32)
    body = np.concatenate([freeze, tail])
    if fx.get("loop_filter"):
        lf = dict(new_effect("filter"), **fx["loop_filter"])
        q = filter_q(lf["kind"], lf["resonance"], lf["width_octaves"])
        body = sweep_filter(body, ctx.a_sr, lf["kind"], lf["start_hz"], lf["end_hz"], q, n_freeze, lf["curve"])
    if fx.get("loop_echo"):
        le = dict(new_effect("echo"), **fx["loop_echo"])
        body = tempo_echo(body, ctx.a_sr, le["delay_beats"] * ctx.a_period, le["feedback"], le["mix"],
                          le["damping_hz"], 0.0)
    gain = np.ones(len(body), dtype=np.float32) * _db(float(fx.get("gain_db", 0.0)))
    fade_db = float(fx.get("fade_db", 0.0))
    if fade_db and n_freeze:
        ramp = np.concatenate([np.linspace(0.0, fade_db, n_freeze), np.full(len(body) - n_freeze, fade_db)])
        gain *= (10 ** (ramp / 20.0)).astype(np.float32)
    body = _fade(body * gain[:, None], ctx.a_sr, fade_in_s=EDGE_FADE_S, fade_out_s=EDGE_FADE_S)
    head = _fade(ctx.a[:capture_i], ctx.a_sr, fade_in_s=0.0)
    ctx.a = np.concatenate([head, body]).astype(np.float32)
    ctx.outro_start = capture_t
    ctx.a_end = capture_t + len(body) / ctx.a_sr


def _apply_filter(ctx: TransitionContext, fx: Dict) -> None:
    q = filter_q(fx["kind"], fx.get("resonance", 0.707), fx.get("width_octaves", 1.0))
    if fx.get("side", "outgoing") == "outgoing":
        j = ctx.a_junction_index
        start_i = max(0, ctx.a_index(beat_time(ctx.a_beats, j, -int(fx["beats"]))))
        sweep = max(1, ctx.a_index(ctx.junction_a) - start_i)
        ctx.a[start_i:] = sweep_filter(ctx.a[start_i:], ctx.a_sr, fx["kind"], fx["start_hz"], fx["end_hz"], q, sweep,
                                       fx.get("curve", "exponential"))
    else:
        j = ctx.b_junction_index
        junction_i = max(0, ctx.b_index(ctx.junction_b))
        sweep_end_i = ctx.b_index(beat_time(ctx.b_beats, j, int(fx["beats"])))
        back_i = min(len(ctx.b), sweep_end_i + int(round(median_period(ctx.b_beats) * ctx.b_sr)))
        wet = sweep_filter(ctx.b[:back_i], ctx.b_sr, fx["kind"], fx["start_hz"], fx["end_hz"], q,
                           max(1, sweep_end_i - junction_i), fx.get("curve", "exponential"), hold_start=junction_i)
        # back to the dry track over the beat after the sweep
        n_back = max(0, back_i - sweep_end_i)
        mix = np.ones(back_i, dtype=np.float32)
        if n_back:
            mix[sweep_end_i:back_i] = np.linspace(1.0, 0.0, n_back, dtype=np.float32)
        ctx.b[:back_i] = wet * mix[:, None] + ctx.b[:back_i] * (1.0 - mix[:, None])


def _apply_echo(ctx: TransitionContext, fx: Dict) -> None:
    j = ctx.a_junction_index
    start_t = beat_time(ctx.a_beats, j, int(fx.get("start_offset_beats", -4)))
    start_i = max(0, ctx.a_index(start_t))
    end_i = min(len(ctx.a), ctx.a_index(ctx.a_end))
    if end_i <= start_i:
        return
    dry = ctx.a[start_i:end_i]
    out = tempo_echo(dry, ctx.a_sr, float(fx["delay_beats"]) * ctx.a_period, float(fx["feedback"]), float(fx["mix"]),
                     float(fx.get("damping_hz", 6000.0)), MAX_ECHO_TAIL_BEATS * ctx.a_period)
    ctx.a[start_i:end_i] = out[:len(dry)]
    if len(out) > len(dry):
        _add_layer(ctx, out[len(dry):], ctx.a_end)


def _apply_sample(ctx: TransitionContext, fx: Dict) -> None:
    data = load_sample(fx["file"], ctx.a_sr)
    fade_in = float(fx.get("fade_in_ms", 5)) / 1000.0
    fade_out = float(fx.get("fade_out_ms", 5)) / 1000.0
    data = _fade(data, ctx.a_sr, fade_in, fade_out) * _db(float(fx.get("gain_db", -3.0)))
    anchor_t = beat_time(ctx.a_beats, ctx.a_junction_index, float(fx.get("offset_beats", 0.0)))
    length_s = len(data) / ctx.a_sr
    anchor = fx.get("anchor", "end_at_junction")
    if anchor == "end_at_junction":
        start_t = anchor_t - length_s
    elif anchor == "center_on_junction":
        start_t = anchor_t - length_s / 2.0
    else:
        start_t = anchor_t
    _add_layer(ctx, data, start_t)


_APPLY = {"freeze": _apply_freeze, "filter": _apply_filter, "echo": _apply_echo, "sample": _apply_sample}


def apply_effects(ctx: TransitionContext, effects: Sequence[Dict]) -> TransitionContext:
    """Apply the enabled effects in order (each must pass validate_effect), then mix the overflow into B."""
    for fx in effects:
        if not fx.get("enabled", True):
            continue
        problems = validate_effect(fx)
        if problems:
            raise ValueError("; ".join(problems))
        _APPLY[fx["type"]](ctx, dict(new_effect(fx["type"]), **fx))
    mix_overflow(ctx)
    return ctx


def mix_overflow(ctx: TransitionContext) -> TransitionContext:
    """Add the overflow to B at the instant A ends (resampled to B's rate), then clear it."""
    if not len(ctx.overflow):
        return ctx
    tail = ctx.overflow
    if ctx.a_sr != ctx.b_sr:
        g = math.gcd(ctx.a_sr, ctx.b_sr)
        tail = signal.resample_poly(tail, ctx.b_sr // g, ctx.a_sr // g, axis=0).astype(np.float32)
    at = ctx.b_index(ctx.junction_b + (ctx.a_end - ctx.junction_a))
    if at < 0:
        tail = tail[-at:]
        at = 0
    need = at + len(tail)
    if need > len(ctx.b):
        ctx.b = np.concatenate([ctx.b, np.zeros((need - len(ctx.b), 2), dtype=np.float32)])
    ctx.b[at:need] += tail
    ctx.overflow = np.zeros((0, 2), dtype=np.float32)
    return ctx


# ------------------------------------------------------------------ preview
def preview_mix(ctx: TransitionContext, b_intro_end: float, length: str = "short") -> Tuple[np.ndarray, int]:
    """
    The rendered transition as one stereo clip at A's rate: A fades out (cos) from the junction to a_end,
    B (aligned on the junction) fades in (sin) from its junction to its intro end.
    """
    sr = ctx.a_sr
    period = ctx.a_period
    if length == "long":
        start_t = ctx.junction_a - 20.0
        stop_t = max(ctx.junction_a + 10.0, ctx.a_end + 2.0)
    else:
        start_t = beat_time(ctx.a_beats, ctx.a_junction_index, -8)
        stop_t = ctx.a_end + 8 * period
    start_t = max(start_t, ctx.a_offset)
    n = int(round((stop_t - start_t) * sr))
    out = np.zeros((max(n, 0), 2), dtype=np.float32)
    # A with its fade-out
    a_i0 = ctx.a_index(start_t)
    a_part = ctx.a[a_i0:a_i0 + n]
    times = start_t + np.arange(len(a_part)) / sr
    fade_len = max(1e-3, ctx.a_end - ctx.junction_a)
    pos = np.clip((times - ctx.junction_a) / fade_len, 0.0, 1.0)
    a_gain = np.where(times < ctx.junction_a, 1.0, np.cos(pos * math.pi / 2)).astype(np.float32)
    a_gain[times >= ctx.a_end] = 0.0
    out[:len(a_part)] += a_part * a_gain[:, None]
    # B aligned on the junction, at A's rate
    b = ctx.b
    if ctx.b_sr != sr:
        g = math.gcd(ctx.b_sr, sr)
        b = signal.resample_poly(b, sr // g, ctx.b_sr // g, axis=0).astype(np.float32)
    b_start_t = ctx.junction_a - (ctx.junction_b - ctx.b_offset)  # set time of B's region start
    b_times = b_start_t + np.arange(len(b)) / sr
    b_fade = max(1e-3, b_intro_end - ctx.junction_b)
    b_pos = np.clip((b_times - ctx.junction_a) / b_fade, 0.0, 1.0)
    b_gain = np.where(b_times < ctx.junction_a, 0.0, np.sin(b_pos * math.pi / 2)).astype(np.float32)
    i0 = int(round((b_start_t - start_t) * sr))
    src0 = max(0, -i0)
    dst0 = max(0, i0)
    count = max(0, min(len(b) - src0, n - dst0))
    if count:
        out[dst0:dst0 + count] += b[src0:src0 + count] * b_gain[src0:src0 + count, None]
    from mastering import true_peak_limiter
    return true_peak_limiter(out, sr, ceiling_db=-1.0).astype(np.float32), sr
```

- [ ] **Step 4 : lancer le test pour vérifier qu'il passe**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_transition_fx.py" -v`
Expected : `Ran 12 tests` … `OK`

- [ ] **Step 5 : commit**

```bash
git add transition_fx.py tests/test_transition_fx.py
git commit -m "Transition FX engine: beat grid, freeze/roll, filter sweeps, echo, samples, overflow, preview mix"
```
(avec les deux lignes d'attribution)

---

### Task 2 : rendu `fx_render.py`, avec l'écriture audio extraite de `mastering.py`

**Files :**
- Modify: `mastering.py` (`premaster_track` l.572-578, avant `analyze_mastering_cached` l.584, `premaster_files` l.693-697)
- Create: `fx_render.py`
- Test: `tests/test_fx_render.py`

**Interfaces :**
- Consumes : tout `transition_fx` (tâche 1), `mastering.load_audio`, `mastering.true_peak_limiter`.
- Produces :
  - `mastering.output_path_for(path, out_dir, fmt="same") -> str` et `mastering.write_audio(output_path, x, fs)` ;
  - `fx_render.render_set(profiles, fx_for_pair, bases, out_dir, fmt="same", grids=None, progress=None) -> (results, problems)`. Chaque résultat contient `source`, `input`, `output`, `limiter_reduction_db`, `duration`, `intro_start`, `intro_end`, `outro_start` et `outro_end`. `fx_for_pair(a, b)` renvoie `{"effects", "nudge_ms"}` ou `None`.
  - `fx_render.render_preview(profile_a, profile_b, entry, bases, length="short", grids=None) -> (clip, sr, warnings)`.

- [ ] **Step 1 : écrire le test qui échoue**

Créer `tests/test_fx_render.py` :

```python
import hashlib
import os
import shutil
import tempfile
import unittest

import numpy as np
import soundfile as sf

import analysis_store
import transition_fx as tfx

SR = 22050


def sha1(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


class TestRenderSet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_fxr_")
        os.environ["DYNAMIX_HOME"] = os.path.join(self.tmp, "home")
        analysis_store.reset_store()
        self.lib = os.path.join(self.tmp, "Mixes")
        os.makedirs(self.lib)
        self.paths = []
        for k, freq in enumerate((220, 330, 440)):
            t = np.arange(12 * SR) / SR
            path = os.path.join(self.lib, f"t{k}.wav")
            sf.write(path, (0.3 * np.sin(2 * np.pi * freq * t)).astype("float32"), SR)
            self.paths.append(path)
        self.hashes = [sha1(p) for p in self.paths]
        self.grid = {"beats": [i * 0.5 for i in range(25)], "bpm": 120.0, "has_beat": True, "duration": 12.0}
        self.profiles = [{"file_path": p, "filename": os.path.basename(p), "duration": 12.0, "bpm": 120.0,
                          "intro_start": 1.0, "intro_end": 3.0, "outro_start": 8.0, "outro_end": 10.0} for p in self.paths]
        hit = os.path.join(self.tmp, "hit.wav")
        sf.write(hit, np.full(SR, 0.2, dtype="float32"), SR)
        self.fx = {(self.paths[0], self.paths[1]): {"nudge_ms": 0, "effects": [
            dict(tfx.new_effect("freeze"), steps=[{"beats": 2, "repeats": 2}]),
            # starts 3 beats after the junction (9.5 s): 0.5 s in A (audible until 10 s), 0.5 s overflows into B
            dict(tfx.new_effect("sample"), file=hit, anchor="start_at_junction", offset_beats=3, gain_db=0.0)]}}

    def tearDown(self):
        os.environ.pop("DYNAMIX_HOME", None)
        analysis_store.reset_store()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_copies_cues_and_originals(self):
        from fx_render import render_set
        out_dir = os.path.join(self.tmp, "project", "fx")
        grids = {p: self.grid for p in self.paths}
        results, problems = render_set(self.profiles, lambda a, b: self.fx.get((a, b)), {}, out_dir, grids=grids)
        self.assertEqual(problems, [])
        self.assertEqual([r["source"] for r in results], self.paths[:2])
        self.assertEqual(sorted(os.listdir(out_dir)), ["t0.wav", "t1.wav"])
        self.assertEqual([sha1(p) for p in self.paths], self.hashes)
        a, b = results
        self.assertAlmostEqual(a["outro_start"], 8.0)
        self.assertAlmostEqual(a["outro_end"], 10.0, places=3)        # 4 beats of freeze = 2 s
        self.assertAlmostEqual(a["duration"], 10.0, places=2)
        self.assertAlmostEqual(b["intro_start"], 1.0)
        data, sr = sf.read(b["output"], dtype="float32")
        original, _ = sf.read(self.paths[1], dtype="float32")
        self.assertEqual(data.shape[1], 2)   # FX copies are always stereo
        diff = np.abs(data[int(3.0 * SR):int(3.5 * SR), 0] - original[int(3.0 * SR):int(3.5 * SR)])
        self.assertGreater(float(np.max(diff)), 0.1)   # sample overflow: A ends at 10 s = B 1.0 + 2.0 s
        self.assertLessEqual(float(np.max(np.abs(data))), 10 ** (-1 / 20) + 1e-3)

    def test_invalid_transition_is_reported_and_skipped(self):
        from fx_render import render_set
        bad = {(self.paths[1], self.paths[2]): {"effects": [dict(tfx.new_effect("filter"), resonance=50)]}}
        results, problems = render_set(self.profiles, lambda a, b: bad.get((a, b)), {}, os.path.join(self.tmp, "fx"),
                                       grids={p: self.grid for p in self.paths})
        self.assertTrue(any("transition 2" in p and "resonance" in p for p in problems))

    def test_preview(self):
        from fx_render import render_preview
        clip, sr, warnings = render_preview(self.profiles[0], self.profiles[1], self.fx[(self.paths[0], self.paths[1])], {},
                                            grids={p: self.grid for p in self.paths})
        self.assertEqual(sr, SR)
        self.assertGreater(len(clip), SR * 5)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2 : lancer le test pour vérifier qu'il échoue**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_fx_render.py" -v`
Expected : ERROR `ModuleNotFoundError: No module named 'fx_render'`

- [ ] **Step 3 : extraire l'écriture audio dans `mastering.py`**

Remplacer :
```python
    ext = os.path.splitext(output_path)[1].lower()
    subtype = 'PCM_24' if ext in ('.wav', '.aiff', '.aif') else None
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if ext == '.mp3':
        sf.write(output_path, x, fs, format='MP3', bitrate_mode='CONSTANT', compression_level=0.0)
    else:
        sf.write(output_path, x, fs, subtype=subtype)

    after = analyze_mastering(output_path)
```
par :
```python
    write_audio(output_path, x, fs)

    after = analyze_mastering(output_path)
```

Remplacer :
```python
def analyze_mastering_cached(path: str) -> Dict:
```
par :
```python
def output_path_for(path: str, out_dir: str, fmt: str = 'same') -> str:
    """Where a processed copy of path goes in out_dir (libsndfile cannot write M4A/AAC/AIFF: FLAC instead)."""
    base, ext = os.path.splitext(os.path.basename(path))
    out_ext = ext if fmt == 'same' else f".{fmt}"
    if out_ext.lower() in ('.m4a', '.aac', '.aiff', '.aif'):
        out_ext = '.flac'
    return os.path.join(out_dir, base + out_ext)


def write_audio(output_path: str, x: np.ndarray, fs: int) -> None:
    """Write float audio: 24-bit PCM for WAV/AIFF, constant-bitrate MP3, the format's default otherwise."""
    ext = os.path.splitext(output_path)[1].lower()
    subtype = 'PCM_24' if ext in ('.wav', '.aiff', '.aif') else None
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if ext == '.mp3':
        sf.write(output_path, x, fs, format='MP3', bitrate_mode='CONSTANT', compression_level=0.0)
    else:
        sf.write(output_path, x, fs, subtype=subtype)


def analyze_mastering_cached(path: str) -> Dict:
```

Remplacer :
```python
        base, ext = os.path.splitext(os.path.basename(path))
        out_ext = ext if fmt == 'same' else f".{fmt}"
        if out_ext.lower() in ('.m4a', '.aac', '.aiff', '.aif'):  # libsndfile cannot write these
            out_ext = '.flac'
        output_path = os.path.join(out_dir, base + out_ext)
```
par :
```python
        output_path = output_path_for(path, out_dir, fmt)
```

- [ ] **Step 4 : créer `fx_render.py`**

```python
#!/usr/bin/env python3
"""
Rendering of transition FX into copies (fx/ folder of a set project).

For every set-list track touched by an active transition FX, the base (the
pre-mastered copy when there is one, else the original, read only) gets the
incoming-side FX of the previous transition and the outgoing-side FX of the next
one, then a true-peak limiter pass, and is written to out_dir with its new
intro/outro positions. Also renders the looped preview clip of one transition.
"""

import logging
import os
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

import transition_fx as tfx
from mastering import load_audio, output_path_for, true_peak_limiter, write_audio

log = logging.getLogger("dynamix.fx")


def _active(effects: Sequence[Dict]) -> List[Dict]:
    return [fx for fx in effects or [] if fx.get("enabled", True)]


def _beats_for(profile: Dict, grids: Optional[Dict[str, Dict]], duration: float) -> Tuple[List[float], Optional[str]]:
    path = profile["file_path"]
    grid = (grids or {}).get(path) or tfx.beat_grid(path)
    return tfx.usable_beats(grid, float(profile.get("bpm") or 0), duration)


def _cues(profile: Dict) -> Dict[str, float]:
    duration = float(profile.get("duration") or 0.0)
    return {"intro_start": float(profile.get("intro_start", 0.0)), "intro_end": float(profile.get("intro_end", 0.0)),
            "outro_start": float(profile.get("outro_start", duration)), "outro_end": float(profile.get("outro_end", duration))}


def render_set(profiles: Sequence[Dict], fx_for_pair: Callable[[str, str], Optional[Dict]], bases: Dict[str, str],
               out_dir: str, fmt: str = "same", grids: Optional[Dict[str, Dict]] = None,
               progress: Optional[Callable[[int, int, str], None]] = None) -> Tuple[List[Dict], List[str]]:
    """
    profiles: planner profiles in set order (original file_path, intro/outro, bpm, duration).
    fx_for_pair(a_path, b_path) -> {"effects": [...], "nudge_ms": n} or None.
    bases: original path -> file to read (pre-mastered copy); missing = the original.
    Returns (results, problems): one result per written copy, readable problems per skipped transition.
    """
    n = len(profiles)
    active = []
    for i in range(n - 1):
        entry = fx_for_pair(profiles[i]["file_path"], profiles[i + 1]["file_path"]) or {}
        if _active(entry.get("effects")):
            active.append((i, entry))
    involved = sorted({i for i, _ in active} | {i + 1 for i, _ in active})
    audio, rates, beats, cues, problems = {}, {}, {}, {}, []
    for i in involved:
        prof = profiles[i]
        base = bases.get(prof["file_path"], prof["file_path"])
        data, rates[i] = load_audio(base)
        audio[i] = tfx.to_stereo(data)
        beats[i], warning = _beats_for(prof, grids, len(audio[i]) / rates[i])
        if warning:
            problems.append(f"{prof.get('filename') or os.path.basename(prof['file_path'])}: {warning}")
        cues[i] = _cues(prof)
    steps = len(active) + len(involved)
    done = 0
    for i, entry in active:
        a, b = i, i + 1
        done += 1
        if progress:
            progress(done, steps, f"{profiles[a].get('filename', '')} -> {profiles[b].get('filename', '')}")
        ctx = tfx.make_context(audio[a], rates[a], beats[a], cues[a]["outro_start"], cues[a]["outro_end"],
                               audio[b], rates[b], beats[b], cues[b]["intro_start"], entry.get("nudge_ms", 0.0))
        b_start = int(round(ctx.b_offset * rates[b]))
        b_len = len(ctx.b)
        try:
            tfx.apply_effects(ctx, _active(entry["effects"]))
        except (ValueError, OSError) as exc:
            problems.append(f"transition {a + 1}: {exc}")
            continue
        a_start = int(round(ctx.a_offset * rates[a]))
        audio[a] = np.concatenate([audio[a][:a_start], ctx.a]).astype(np.float32)
        audio[b] = np.concatenate([audio[b][:b_start], ctx.b, audio[b][b_start + b_len:]]).astype(np.float32)
        cues[a]["outro_start"], cues[a]["outro_end"] = ctx.outro_start, ctx.a_end
        cues[b]["intro_start"] = ctx.junction_b
        cues[b]["intro_end"] = max(cues[b]["intro_end"], ctx.junction_b)
        problems.extend(ctx.warnings)
    results = []
    os.makedirs(out_dir, exist_ok=True)
    for i in involved:
        prof = profiles[i]
        done += 1
        if progress:
            progress(done, steps, prof.get("filename", ""))
        x = audio[i]
        before = float(np.max(np.abs(x))) if len(x) else 0.0
        limited = true_peak_limiter(x, rates[i], ceiling_db=-1.0)
        after = float(np.max(np.abs(limited))) if len(limited) else 0.0
        reduction = max(0.0, 20 * np.log10(max(before, 1e-9) / max(after, 1e-9))) if before > 0 else 0.0
        if reduction > 3.0:
            log.warning("FX render: the limiter reduced %s by %.1f dB", prof.get("filename", ""), reduction)
        base = bases.get(prof["file_path"], prof["file_path"])
        output = output_path_for(base, out_dir, fmt)
        write_audio(output, limited, rates[i])
        duration = len(limited) / rates[i]
        result = {"source": prof["file_path"], "input": base, "output": output,
                  "limiter_reduction_db": round(reduction, 2), "duration": duration}
        result.update({k: round(min(v, duration), 4) for k, v in cues[i].items()})
        results.append(result)
    return results, problems


def render_preview(profile_a: Dict, profile_b: Dict, entry: Dict, bases: Dict[str, str], length: str = "short",
                   grids: Optional[Dict[str, Dict]] = None) -> Tuple[np.ndarray, int, List[str]]:
    """The looped preview clip of one transition (only its own FX)."""
    a_path = bases.get(profile_a["file_path"], profile_a["file_path"])
    b_path = bases.get(profile_b["file_path"], profile_b["file_path"])
    a_audio, a_sr = load_audio(a_path)
    b_audio, b_sr = load_audio(b_path)
    a_audio, b_audio = tfx.to_stereo(a_audio), tfx.to_stereo(b_audio)
    a_beats, wa = _beats_for(profile_a, grids, len(a_audio) / a_sr)
    b_beats, wb = _beats_for(profile_b, grids, len(b_audio) / b_sr)
    ca, cb = _cues(profile_a), _cues(profile_b)
    ctx = tfx.make_context(a_audio, a_sr, a_beats, ca["outro_start"], ca["outro_end"], b_audio, b_sr, b_beats,
                           cb["intro_start"], entry.get("nudge_ms", 0.0))
    tfx.apply_effects(ctx, _active(entry.get("effects")))
    clip, sr = tfx.preview_mix(ctx, cb["intro_end"], length)
    return clip, sr, [w for w in (wa, wb) if w] + ctx.warnings
```

- [ ] **Step 5 : lancer les tests**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_fx_render.py" -v`, puis `venv/Scripts/python.exe -c "import mastering; print(mastering.output_path_for('C:/x/a.m4a', 'C:/o', 'same'))"`
Expected : `Ran 3 tests` … `OK`, puis un chemin se terminant par `a.flac`.

- [ ] **Step 6 : commit**

```bash
git add mastering.py fx_render.py tests/test_fx_render.py
git commit -m "FX render: copies with transition FX into fx/, preview clip; audio writing shared with the pre-master"
```

---

### Task 3 : données FX dans `SetProject`

**Files :**
- Modify: `set_project.py`
- Test: `tests/test_set_project_fx.py`

**Interfaces :**
- Produces (utilisées par les tâches 5 et 6) :
  - `SetProject.FX_DIR`, `fx_dir` ;
  - `data["fx"] = {"transitions": {"<a>|<b>": {"nudge_ms", "effects"}}, "render": None | {"at", "results"}}` ;
  - `fx_key(a, b)`, `fx_for_pair(a, b) -> Optional[Dict]`, `fx_transition(a, b)` ;
  - `set_fx_effects(a, b, effects)`, `set_fx_nudge(a, b, ms)`, `remove_fx(a, b)`. Toute modification met le rendu à `None` et remet l'étape `fx` à « non faite ».
  - `set_list_pairs()`, `active_fx_pairs()`, `inactive_fx_pairs()` ;
  - `set_fx_render(results)`, `fx_map() -> {source: result}` ;
  - `rendered_profiles(profiles) -> (profiles, {"fx": n, "premaster": n})` ;
  - `invalidate_from("analyze"|"setlist"|"transitions"|"premaster")` met `fx.render` à `None` en gardant les recettes ;
  - `reset()` vide `fx/` et le bloc `fx`, et `reset_preview()["outputs"]` compte `fx/`.

- [ ] **Step 1 : écrire le test qui échoue**

Créer `tests/test_set_project_fx.py` :

```python
import json
import os
import shutil
import tempfile
import unittest

from set_project import SetProject


class TestSetProjectFx(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_fxp_")
        self.p = SetProject.create(os.path.join(self.tmp, "projects"), "fx")
        self.a, self.b, self.c = "/lib/a.wav", "/lib/b.wav", "/lib/c.wav"
        self.p.set_tracks([{"file_path": x, "filename": os.path.basename(x)} for x in (self.a, self.b, self.c)])
        self.p.set_order([self.a, self.b, self.c])
        self.freeze = {"type": "freeze", "enabled": True, "steps": [{"beats": 1, "repeats": 4}]}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_recipes_by_pair_survive_reordering(self):
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        self.p.set_fx_nudge(self.a, self.b, 12)
        self.assertEqual(self.p.active_fx_pairs(), [(self.a, self.b)])
        self.p.set_order([self.c, self.a, self.b])
        self.assertEqual(self.p.active_fx_pairs(), [(self.a, self.b)])
        self.assertEqual(self.p.fx_for_pair(self.a, self.b)["nudge_ms"], 12.0)
        self.p.set_order([self.b, self.a, self.c])
        self.assertEqual(self.p.active_fx_pairs(), [])
        self.assertEqual(self.p.inactive_fx_pairs(), [(self.a, self.b)])
        self.p.remove_fx(self.a, self.b)
        self.assertEqual(self.p.inactive_fx_pairs(), [])

    def test_disabled_effects_are_not_active(self):
        self.p.set_fx_effects(self.b, self.c, [dict(self.freeze, enabled=False)])
        self.assertEqual(self.p.active_fx_pairs(), [])

    def test_changes_and_invalidation_keep_recipes(self):
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        self.p.set_fx_render([{"source": self.a, "output": "x"}])
        self.p.mark("fx", count=1)
        self.p.set_fx_nudge(self.a, self.b, 5)
        self.assertIsNone(self.p.data["fx"]["render"])
        self.assertFalse(self.p.is_done("fx"))
        self.p.set_fx_render([{"source": self.a, "output": "x"}])
        self.p.invalidate_from("premaster")
        self.assertIsNone(self.p.data["fx"]["render"])
        self.assertEqual(len(self.p.fx_for_pair(self.a, self.b)["effects"]), 1)
        self.p.set_fx_render([{"source": self.a, "output": "x"}])
        self.p.set_order([self.a, self.c, self.b])
        self.assertIsNone(self.p.data["fx"]["render"])

    def test_fx_map_and_rendered_profiles(self):
        os.makedirs(self.p.fx_dir)
        os.makedirs(self.p.premaster_dir, exist_ok=True)
        fx_copy = os.path.join(self.p.fx_dir, "a.wav")
        pm_copy = os.path.join(self.p.premaster_dir, "b.wav")
        for path in (fx_copy, pm_copy):
            open(path, "wb").close()
        self.p.data["premaster"] = {"results": [{"input": self.a, "output": os.path.join(self.p.premaster_dir, "a.wav")},
                                                {"input": self.b, "output": pm_copy}]}
        self.p.set_fx_render([{"source": self.a, "output": fx_copy, "intro_start": 1.0, "intro_end": 2.0,
                               "outro_start": 8.0, "outro_end": 10.0, "duration": 10.0},
                              {"source": self.c, "output": os.path.join(self.p.fx_dir, "missing.wav")}])
        self.assertEqual(list(self.p.fx_map()), [self.a])
        profiles = [{"file_path": x, "intro_start": 0.0, "intro_end": 1.0, "outro_start": 5.0, "outro_end": 6.0,
                     "duration": 7.0} for x in (self.a, self.b, self.c)]
        out, counts = self.p.rendered_profiles(profiles)
        self.assertEqual(counts, {"fx": 1, "premaster": 1})
        self.assertEqual([q["file_path"] for q in out], [fx_copy, pm_copy, self.c])
        self.assertEqual((out[0]["outro_start"], out[0]["outro_end"], out[0]["duration"]), (8.0, 10.0, 10.0))
        self.assertEqual(out[1]["outro_end"], 6.0)
        self.assertEqual(profiles[0]["file_path"], self.a)   # inputs untouched

    def test_reset_clears_fx(self):
        self.p.set_fx_effects(self.a, self.b, [self.freeze])
        os.makedirs(self.p.fx_dir)
        with open(os.path.join(self.p.fx_dir, "a.wav"), "wb") as f:
            f.write(b"\x00" * 7)
        self.assertEqual(self.p.reset_preview()["outputs"], {"files": 1, "bytes": 7})
        self.p.reset()
        self.assertEqual(os.listdir(self.p.fx_dir), [])
        self.assertEqual(self.p.data["fx"], {"transitions": {}, "render": None})

    def test_project_without_fx_block_loads(self):
        with open(self.p.path, encoding="utf-8") as f:
            data = json.load(f)
        data.pop("fx", None)
        with open(self.p.path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        q = SetProject.open(self.p.folder)
        self.assertEqual(q.data["fx"], {"transitions": {}, "render": None})
        q.set_fx_effects(self.a, self.b, [self.freeze])
        q.save()
        self.assertEqual(len(SetProject.open(self.p.folder).fx_for_pair(self.a, self.b)["effects"]), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2 : lancer le test pour vérifier qu'il échoue**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_set_project_fx.py" -v`
Expected : erreurs `AttributeError: 'SetProject' object has no attribute 'set_fx_effects'` (et d'autres).

- [ ] **Step 3 : implémenter dans `set_project.py`**

Appliquer, dans l'ordre, ces remplacements exacts :

1. Remplacer :

```python
        premaster/       corrected copies written by the pre-master pass
```

   par :

```python
        premaster/       corrected copies written by the pre-master pass
        fx/              copies with transition FX (freeze, filters, echo, samples)
```

2. Remplacer :

```python
    PREMASTER_DIR = "premaster"
```

   par :

```python
    PREMASTER_DIR = "premaster"
    FX_DIR = "fx"
```

3. Remplacer :

```python
            "premaster": None,
            "notes": "",
```

   par :

```python
            "premaster": None,
            "fx": {"transitions": {}, "render": None},  # FX recipes per track pair, and the last render
            "notes": "",
```

4. Remplacer :

```python
    @property
    def exports_dir(self) -> str:
```

   par :

```python
    @property
    def fx_dir(self) -> str:
        return os.path.join(self.folder, self.FX_DIR)

    @property
    def exports_dir(self) -> str:
```

5. Remplacer :

```python
            elif key == "options":
                self.data["options"].update(value)
```

   par :

```python
            elif key == "options":
                self.data["options"].update(value)
            elif key == "fx":
                self.data["fx"] = {"transitions": dict((value or {}).get("transitions") or {}),
                                   "render": (value or {}).get("render")}
```

6. Remplacer :

```python
    # ------------------------------------------------------------- reset
```

   par :

```python
    # ------------------------------------------------------------- transition FX
    @staticmethod
    def fx_key(a: str, b: str) -> str:
        return f"{a}|{b}"

    def fx_for_pair(self, a: str, b: str) -> Optional[Dict]:
        """The FX entry {nudge_ms, effects} of the transition a -> b, or None."""
        return self.data["fx"]["transitions"].get(self.fx_key(a, b))

    def fx_transition(self, a: str, b: str) -> Dict:
        """The FX entry of a -> b, created empty when missing."""
        return self.data["fx"]["transitions"].setdefault(self.fx_key(a, b), {"nudge_ms": 0.0, "effects": []})

    def _fx_changed(self) -> None:
        self.data["fx"]["render"] = None
        self.mark("fx", done=False)

    def set_fx_effects(self, a: str, b: str, effects: List[Dict]) -> None:
        self.fx_transition(a, b)["effects"] = [dict(fx) for fx in effects]
        self._fx_changed()

    def set_fx_nudge(self, a: str, b: str, nudge_ms: float) -> None:
        self.fx_transition(a, b)["nudge_ms"] = float(nudge_ms)
        self._fx_changed()

    def remove_fx(self, a: str, b: str) -> None:
        if self.data["fx"]["transitions"].pop(self.fx_key(a, b), None) is not None:
            self._fx_changed()

    def set_list_pairs(self) -> List[Tuple[str, str]]:
        lst = self.data["set_list"]
        return list(zip(lst, lst[1:]))

    def active_fx_pairs(self) -> List[Tuple[str, str]]:
        """Neighbouring set-list pairs with at least one enabled effect, in set order."""
        active = []
        for a, b in self.set_list_pairs():
            entry = self.fx_for_pair(a, b)
            if entry and any(fx.get("enabled", True) for fx in entry.get("effects") or []):
                active.append((a, b))
        return active

    def inactive_fx_pairs(self) -> List[Tuple[str, str]]:
        """Pairs that have effects but are no longer neighbours in the set list."""
        neighbours = set(self.set_list_pairs())
        out = []
        for key, entry in self.data["fx"]["transitions"].items():
            a, _, b = key.partition("|")
            if entry.get("effects") and (a, b) not in neighbours:
                out.append((a, b))
        return out

    def set_fx_render(self, results: List[Dict]) -> None:
        self.data["fx"]["render"] = {"at": _now(), "results": [dict(r) for r in results]}

    def fx_map(self) -> Dict[str, Dict]:
        """original file path -> FX render result, for copies that exist on disk."""
        render = self.data["fx"].get("render") or {}
        return {r["source"]: r for r in render.get("results") or [] if r.get("output") and os.path.exists(r["output"])}

    def rendered_profiles(self, profiles: List[Dict]) -> Tuple[List[Dict], Dict[str, int]]:
        """
        Profiles pointing at the file to play: the FX copy (with its rendered intro/outro positions),
        else the pre-mastered copy, else the original. Returns (profiles, {'fx': n, 'premaster': n}).
        """
        fx, premaster = self.fx_map(), self.premaster_map()
        out, counts = [], {"fx": 0, "premaster": 0}
        for p in profiles:
            src = p.get("file_path")
            if src in fx:
                r = fx[src]
                q = dict(p, file_path=r["output"], filename=os.path.basename(r["output"]))
                for key in ("intro_start", "intro_end", "outro_start", "outro_end", "duration"):
                    if key in r:
                        q[key] = r[key]
                counts["fx"] += 1
            elif src in premaster:
                q = dict(p, file_path=premaster[src], filename=os.path.basename(premaster[src]))
                counts["premaster"] += 1
            else:
                q = dict(p)
            out.append(q)
        return out, counts

    # ------------------------------------------------------------- reset
```

7. Remplacer :

```python
        """What reset() would delete: {'outputs': premaster/ + exports/, 'imported': source/}."""
        return {"outputs": self._count([self.premaster_dir, self.exports_dir]),
```

   par :

```python
        """What reset() would delete: {'outputs': premaster/ + fx/ + exports/, 'imported': source/}."""
        return {"outputs": self._count([self.premaster_dir, self.fx_dir, self.exports_dir]),
```

8. Remplacer :

```python
        folders = [self.premaster_dir, self.exports_dir] + ([self.source_dir] if delete_imported else [])
```

   par :

```python
        folders = [self.premaster_dir, self.fx_dir, self.exports_dir] + ([self.source_dir] if delete_imported else [])
```

9. Remplacer :

```python
        self.data.update(selection=[], tracks=[], failed=[], proposals=None, set_list=[],
                         transitions=None, premaster=None)
```

   par :

```python
        self.data.update(selection=[], tracks=[], failed=[], proposals=None, set_list=[],
                         transitions=None, premaster=None, fx={"transitions": {}, "render": None})
```

10. Remplacer :

```python
        if step in ("analyze", "setlist", "transitions"):
            self.data["premaster"] = None
```

   par :

```python
        if step in ("analyze", "setlist", "transitions"):
            self.data["premaster"] = None
        if step in ("analyze", "setlist", "transitions", "premaster"):
            self.data["fx"]["render"] = None  # the recipes are kept
```


- [ ] **Step 4 : lancer les tests**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_set_project*.py" -v`
Expected : `Ran 21 tests` … `OK` (6 nouveaux et 15 existants).

- [ ] **Step 5 : commit**

```bash
git add set_project.py tests/test_set_project_fx.py
git commit -m "Set project: transition FX recipes per track pair, render results, copy priority for playback"
```

---

### Task 4 : dossier des samples FX (config) et étiquettes FX sur la Set map

**Files :**
- Modify: `config.py` (`DEFAULTS` l.17-29)
- Modify: `charts.py` (`set_timeline` l.142-174)
- Modify: `set_builder.py` (`create_config_tab` l.1305-1311, `save_config` l.1378)
- Test: `tests/test_config.py`, `tests/test_charts.py`

**Interfaces :**
- Produces : `Config.get("fx_samples_folder")`, vide par défaut ; `self.cfg_fx_samples_var` ; `charts.set_timeline(profiles, transitions=None, fx_labels=None)`, où `fx_labels` associe l'indice d'une transition à un texte.

- [ ] **Step 1 : écrire les tests qui échouent**

Dans `tests/test_config.py`, ajouter dans `TestConfig`, après `test_library_folder` :
```python
    def test_fx_samples_folder(self):
        from config import Config
        c = Config()
        self.assertEqual(c.get("fx_samples_folder"), "")
        c.set("fx_samples_folder", os.path.join(self.tmp, "FX"))
        c.save()
        self.assertEqual(Config().get("fx_samples_folder"), os.path.join(self.tmp, "FX"))
```

Dans `tests/test_charts.py`, ajouter dans la classe qui contient `test_set_timeline`, juste après cette méthode :
```python
    def test_set_timeline_fx_labels(self):
        self._check(charts.set_timeline(self.profiles, self.transitions, fx_labels={0: "freeze · sample"}), "timeline_fx.png")
```

- [ ] **Step 2 : lancer les tests pour vérifier qu'ils échouent**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_config.py"` puis `venv/Scripts/python.exe -m unittest discover -s tests -p "test_charts.py"`
Expected : `test_fx_samples_folder` échoue avec `None != ''`, et `test_set_timeline_fx_labels` échoue avec `TypeError: set_timeline() got an unexpected keyword argument 'fx_labels'`.

- [ ] **Step 3 : implémenter**

Dans `config.py`, remplacer :
```python
    "library_folder": "",          # every track you mixed, one folder, scanned in place (library.py)
```
par :
```python
    "library_folder": "",          # every track you mixed, one folder, scanned in place (library.py)
    "fx_samples_folder": "",       # FX samples (risers, impacts, sweeps) used by the transition FX
```

Dans `charts.py`, remplacer :
```python
def set_timeline(profiles: Sequence[Dict], transitions: Optional[Sequence[Dict]] = None) -> Figure:
    """Where each track plays in the set, with intro/outro sections and transition scores."""
```
par :
```python
def set_timeline(profiles: Sequence[Dict], transitions: Optional[Sequence[Dict]] = None,
                 fx_labels: Optional[Dict[int, str]] = None) -> Figure:
    """Where each track plays in the set, with intro/outro sections, transition scores and transition FX."""
```
et remplacer :
```python
            score = float(t.get("score", 100))
            if score < 70:
                ax.text(x, y_bot - height / 2 - 0.08, f"score {score:.0f}", ha="center", va="top",
                        fontsize=7, color=TEXT2)
```
par :
```python
            score = float(t.get("score", 100))
            if score < 70:
                ax.text(x, y_bot - height / 2 - 0.08, f"score {score:.0f}", ha="center", va="top",
                        fontsize=7, color=TEXT2)
            label = (fx_labels or {}).get(i)
            if label:
                ax.text(x, y_top + height / 2 + 0.06, label, ha="center", va="bottom", fontsize=7, color=BLUE)
```

Dans `set_builder.py`, remplacer :
```python
        ttk.Label(grid, text="Every track you mixed, in one folder (subfolders included). Scanned in place, never copied.",
                  foreground=MUTED).grid(row=6, column=1, sticky="w", padx=4)
        grid.columnconfigure(1, weight=1)
```
par :
```python
        ttk.Label(grid, text="Every track you mixed, in one folder (subfolders included). Scanned in place, never copied.",
                  foreground=MUTED).grid(row=6, column=1, sticky="w", padx=4)
        ttk.Label(grid, text="FX samples folder:").grid(row=7, column=0, sticky="w", pady=3)
        self.cfg_fx_samples_var = tk.StringVar(value=cfg.get("fx_samples_folder") or "")
        ttk.Entry(grid, textvariable=self.cfg_fx_samples_var, width=70).grid(row=7, column=1, sticky="we", padx=4)
        ttk.Button(grid, text="Browse", command=lambda: self._cfg_pick_dir(self.cfg_fx_samples_var)).grid(row=7, column=2)
        ttk.Label(grid, text="Risers, impacts, sweeps... used by Transition FX (30 s max per sample).",
                  foreground=MUTED).grid(row=8, column=1, sticky="w", padx=4)
        grid.columnconfigure(1, weight=1)
```
et remplacer :
```python
        cfg.set("library_folder", self.cfg_library_var.get().strip())
```
par :
```python
        cfg.set("library_folder", self.cfg_library_var.get().strip())
        cfg.set("fx_samples_folder", self.cfg_fx_samples_var.get().strip())
```

- [ ] **Step 4 : lancer les tests et la vérification GUI**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_config.py"`, `venv/Scripts/python.exe -m unittest discover -s tests -p "test_charts.py"`, puis `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `test_config.py` donne `Ran 4 tests` OK, `test_charts.py` passe avec un test de plus, et `GUI smoke OK`.

- [ ] **Step 5 : commit**

```bash
git add config.py charts.py set_builder.py tests/test_config.py tests/test_charts.py
git commit -m "FX samples folder setting; set map shows the transition FX"
```

---

### Task 5 : fenêtre « Transition FX » et intégration dans le Set Builder

**Files :**
- Create: `fx_window.py`
- Modify: `set_project.py` (`STEPS`, `HINTS`)
- Modify: `set_builder.py` (imports, actions du workflow l.81-88, `premaster_set` l.1029-1037, `_with_premastered` l.1054-1065 et ses deux appelants, `_show_transition_window` l.1164, `_render_overview` l.1223, texte du dialogue de reset)
- Modify: `mixxx_export.py` (l.363-369), `mastering.py` (l.839)
- Modify: `tests/gui_smoke.py`

**Interfaces :**
- Consumes : `fx_render.render_set`, `fx_render.render_preview` (tâche 2) ; les méthodes FX de `SetProject` (tâche 3) ; `Config.get("fx_samples_folder")` et `charts.set_timeline(..., fx_labels=)` (tâche 4) ; `library.scan`, `library.filter_entries` ; `app.root`, `app.project`, `app.config`, `app.update_status`, `app._report_error`, `app._save_project`, `app._render_overview`, `app._refresh_workflow`.
- Produces :
  - `fx_window.TransitionFxWindow(app, player=None)`, avec les méthodes `add_effect(type)`, `update_effect(changes, rebuild_settings=False)`, `pick_sample()`, `start_preview()`, `stop_preview()`, `apply_all()`, `close()`, et les attributs `trans_tree`, `fx_tree`, `nudge_var`, `samples`, `sample_list`, `pair_index`, `fx_index` ;
  - `fx_window.Player` (`play_loop`, `play_once`, `stop`), `fx_window.effect_summary(fx)` ;
  - `SetBuilderMixin.open_fx_window(player=None) -> Optional[TransitionFxWindow]`, `_with_rendered(tracks) -> (tracks, counts)`, `_fx_labels() -> Dict[int, str]` ;
  - étape `fx` dans `STEPS`.

- [ ] **Step 1 : ajouter la vérification GUI (échec attendu)**

Dans `tests/gui_smoke.py`, remplacer :
```python
        # --- checks added by later tasks go above this line ---
```
par :
```python
        sr = 22050
        fx_tracks = []
        for k, freq in enumerate((220, 330)):
            path = os.path.join(HOME, f"fx_t{k}.wav")
            t = np.arange(12 * sr) / sr
            sf.write(path, (0.3 * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)
            get_store().put(path, "beats", {"beats": [i * 0.5 for i in range(25)], "bpm": 120.0, "has_beat": True,
                                            "duration": 12.0})
            fx_tracks.append(path)
        fx_samples = os.path.join(HOME, "fx_samples")
        os.makedirs(fx_samples)
        sf.write(os.path.join(fx_samples, "riser.wav"), np.full(sr, 0.2, dtype="float32"), sr)
        app.config.set("fx_samples_folder", fx_samples)
        project = app.project
        project.set_tracks([{"file_path": p, "filename": os.path.basename(p), "duration": 12.0, "bpm": 120.0} for p in fx_tracks])
        project.set_order(fx_tracks)
        profiles = [{"file_path": p, "filename": os.path.basename(p), "duration": 12.0, "bpm": 120.0, "key": "A minor",
                     "intro_start": 1.0, "intro_end": 3.0, "outro_start": 8.0, "outro_end": 10.0} for p in fx_tracks]
        project.data["transitions"] = {"tracks": profiles, "transitions": [{"score": 55}]}
        project.mark("transitions", count=1)
        project.save()
        app.load_project(project.folder)
        original = open(fx_tracks[0], "rb").read()

        class FakePlayer:
            def __init__(self):
                self.loops, self.once, self.stops = [], [], 0

            def play_loop(self, path):
                self.loops.append(path)
                return True

            def play_once(self, path):
                self.once.append(path)

            def stop(self):
                self.stops += 1

        player = FakePlayer()
        win = app.open_fx_window(player=player)
        check(win is not None, "the Transition FX window opens once transitions are planned")
        check(pump(lambda: len(win.samples) == 1, 5.0), "the FX samples folder is scanned")
        win.trans_tree.selection_set("T0")
        check(pump(lambda: win.pair_index == 0, 2.0), "a transition can be selected")
        win.add_effect("freeze")
        win.add_effect("sample")
        check(pump(lambda: hasattr(win, "sample_list") and win.sample_list.size() == 1, 5.0), "the sample list is shown")
        win.sample_list.selection_set(0)
        win.pick_sample()
        check(win.effects()[1]["file"].endswith("riser.wav"), "a sample can be picked")
        win.fx_tree.selection_set("F0")
        check(pump(lambda: win.fx_index == 0, 2.0), "an effect can be selected")
        win.update_effect({"steps": [{"beats": 2, "repeats": 2}]}, rebuild_settings=True)
        win.start_preview()
        check(pump(lambda: player.loops and os.path.exists(player.loops[-1]), 20.0), "the preview is rendered and looped")
        win.nudge_var.set("10")
        check(app.project.fx_for_pair(*fx_tracks)["nudge_ms"] == 10.0, "the nudge is stored")
        check(pump(lambda: len(player.loops) >= 2, 20.0), "a change re-renders the looped preview")
        win.apply_all()
        check(pump(lambda: app.project.data["fx"]["render"] is not None, 30.0), "Apply all FX renders the copies")
        check(app.project.is_done("fx"), "the FX step is marked done")
        _, counts = app.project.rendered_profiles(app.transition_planner.profiles)
        check(counts["fx"] == 2, f"the export uses the two FX copies, got {counts}")
        check(app._fx_labels() == {0: "freeze · sample"}, "the set map labels the transition FX")
        check(open(fx_tracks[0], "rb").read() == original, "the original file is untouched")
        win.close()
        check(player.stops >= 1, "closing the window stops the preview")

        # --- checks added by later tasks go above this line ---
```

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `AttributeError: 'DynaMixGUI' object has no attribute 'open_fx_window'`

- [ ] **Step 2 : créer `fx_window.py`**

```python
#!/usr/bin/env python3
"""
"Transition FX" window of the Set Builder: per transition, a stack of effects
(freeze / roll, filter sweep, echo, FX sample) with their settings, a looped
preview while tweaking, and "Apply all FX" which renders the copies into fx/.
"""

import copy
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import soundfile as sf

import library
import transition_fx as tfx
from analysis_store import dynamix_home
from fx_render import render_preview, render_set

log = logging.getLogger("dynamix.fx")
MUTED = "#52514e"

FX_NAMES = {"freeze": "Freeze", "filter": "Filter", "echo": "Echo", "sample": "Sample"}

# (key, label, kind, choices or (min, max))
FIELDS = {
    "freeze": [("capture_offset_beats", "Capture point (beats)", "int", (-16, 0)),
               ("fade_db", "Fade to (dB)", "float", (-60, 0)),
               ("tail_beats", "Tail (beats)", "int", (0, 8)),
               ("gain_db", "Gain (dB)", "float", (-24, 6))],
    "filter": [("side", "Side", "choice", ("outgoing", "incoming")),
               ("kind", "Type", "choice", ("highpass", "lowpass", "bandpass")),
               ("start_hz", "From (Hz)", "float", (20, 20000)),
               ("end_hz", "To (Hz)", "float", (20, 20000)),
               ("width_octaves", "Band width (octaves)", "float", (0.3, 4)),
               ("resonance", "Resonance (Q)", "float", (0.7, 12)),
               ("beats", "Length (beats)", "choice", (2, 4, 8, 16)),
               ("curve", "Curve", "choice", ("exponential", "linear"))],
    "echo": [("start_offset_beats", "Start (beats)", "int", (-16, 0)),
             ("delay_beats", "Delay (beats)", "choice", (0.25, 0.5, 0.75, 1)),
             ("feedback", "Feedback", "float", (0, 0.85)),
             ("mix", "Mix", "float", (0, 1)),
             ("damping_hz", "Damping (Hz)", "float", (1000, 20000))],
    "sample": [("anchor", "Anchor", "choice", ("end_at_junction", "start_at_junction", "center_on_junction")),
               ("offset_beats", "Offset (beats)", "float", (-16, 16)),
               ("gain_db", "Gain (dB)", "float", (-24, 6)),
               ("fade_in_ms", "Fade in (ms)", "int", (0, 2000)),
               ("fade_out_ms", "Fade out (ms)", "int", (0, 2000))],
}
LOOP_FILTER_FIELDS = [f for f in FIELDS["filter"] if f[0] not in ("side", "beats")]
LOOP_ECHO_FIELDS = [f for f in FIELDS["echo"] if f[0] != "start_offset_beats"]


class Player:
    """WAV playback: looped with winsound on Windows, the default player elsewhere (no loop)."""

    def play_loop(self, path: str) -> bool:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
            return True
        self._open(path)
        return False

    def play_once(self, path: str) -> None:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            self._open(path)

    def stop(self) -> None:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(None, 0)

    @staticmethod
    def _open(path: str) -> None:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


def effect_summary(fx: dict) -> str:
    t = fx.get("type")
    if t == "freeze":
        steps = " → ".join(f"{float(s['beats']):g}×{int(s['repeats'])}" for s in fx.get("steps") or [])
        extra = (" +filter" if fx.get("loop_filter") else "") + (" +echo" if fx.get("loop_echo") else "")
        return f"Freeze {steps}{extra}"
    if t == "filter":
        return (f"Filter {fx.get('side')} {fx.get('kind')} {float(fx.get('start_hz', 0)):.0f}→"
                f"{float(fx.get('end_hz', 0)):.0f} Hz, {fx.get('beats')} beats")
    if t == "echo":
        return f"Echo {float(fx.get('delay_beats', 0)):g} beat, feedback {float(fx.get('feedback', 0)):.2f}"
    if t == "sample":
        name = os.path.basename(fx.get("file") or "") or "(choose a sample)"
        return f"Sample {name} ({fx.get('anchor')})"
    return str(t)


def _fmt(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


class TransitionFxWindow(tk.Toplevel):
    """Needs `app` with: root, project, config, update_status, _report_error, _save_project, _render_overview."""

    def __init__(self, app, player=None):
        super().__init__(app.root)
        self.app = app
        self.project = app.project
        self.player = player or Player()
        data = self.project.data.get("transitions") or {}
        self.profiles = list(data.get("tracks") or [])
        self.transitions = list(data.get("transitions") or [])
        self.pair_index = None
        self.fx_index = None
        self.samples = []
        self._previewing = False
        self._preview_job = None
        self._preview_seq = 0
        self.title(f"Transition FX - {self.project.name}")
        self.geometry("1250x700")
        self._build()
        self.refresh_transitions()
        self.scan_samples()
        self.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------------ layout
    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=6)
        ttk.Button(bar, text="▶ Preview (loop)", command=self.start_preview).pack(side=tk.LEFT)
        ttk.Button(bar, text="■ Stop", command=self.stop_preview).pack(side=tk.LEFT, padx=4)
        ttk.Label(bar, text="Length:").pack(side=tk.LEFT, padx=(12, 2))
        self.length_var = tk.StringVar(value="short")
        length = ttk.Combobox(bar, textvariable=self.length_var, values=("short", "long"), width=7, state="readonly")
        length.pack(side=tk.LEFT)
        length.bind("<<ComboboxSelected>>", lambda e: self.schedule_preview())
        ttk.Button(bar, text="Apply all FX", command=self.apply_all).pack(side=tk.LEFT, padx=12)
        self.status_label = ttk.Label(bar, text="", foreground=MUTED)
        self.status_label.pack(side=tk.LEFT, padx=8)

        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        left = ttk.Frame(panes)
        panes.add(left, weight=1)
        ttk.Label(left, text="Transitions", foreground=MUTED).pack(anchor="w")
        self.trans_tree = ttk.Treeview(left, columns=("#", "Transition", "Score", "FX", "State"), show="headings",
                                       height=12, selectmode="browse")
        for col, width in (("#", 30), ("Transition", 260), ("Score", 50), ("FX", 35), ("State", 45)):
            self.trans_tree.heading(col, text=col)
            self.trans_tree.column(col, width=width, anchor="w" if col == "Transition" else "center",
                                   stretch=(col == "Transition"))
        self.trans_tree.pack(fill=tk.BOTH, expand=True)
        self.trans_tree.bind("<<TreeviewSelect>>", lambda e: self.on_transition_selected())
        self.info_label = ttk.Label(left, text="", foreground=MUTED, justify=tk.LEFT, wraplength=380)
        self.info_label.pack(anchor="w", pady=4)
        nudge_row = ttk.Frame(left)
        nudge_row.pack(anchor="w")
        ttk.Label(nudge_row, text="Nudge (ms):").pack(side=tk.LEFT)
        self.nudge_var = tk.StringVar(value="0")
        ttk.Spinbox(nudge_row, from_=-50, to=50, increment=1, textvariable=self.nudge_var, width=6).pack(side=tk.LEFT, padx=4)
        self.nudge_var.trace_add("write", lambda *a: self.on_nudge())
        inactive = ttk.LabelFrame(left, text="Inactive FX (pairs no longer next to each other)")
        inactive.pack(fill=tk.X, pady=6)
        self.inactive_list = tk.Listbox(inactive, height=3)
        self.inactive_list.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(inactive, text="Remove", command=self.remove_inactive).pack(anchor="w", padx=4, pady=2)

        mid = ttk.Frame(panes)
        panes.add(mid, weight=1)
        ttk.Label(mid, text="FX stack (top to bottom)", foreground=MUTED).pack(anchor="w")
        self.fx_tree = ttk.Treeview(mid, columns=("On", "Effect"), show="headings", height=12, selectmode="browse")
        self.fx_tree.heading("On", text="On")
        self.fx_tree.heading("Effect", text="Effect")
        self.fx_tree.column("On", width=35, anchor="center", stretch=False)
        self.fx_tree.column("Effect", width=300, anchor="w")
        self.fx_tree.pack(fill=tk.BOTH, expand=True)
        self.fx_tree.bind("<<TreeviewSelect>>", lambda e: self.on_fx_selected())
        buttons = ttk.Frame(mid)
        buttons.pack(fill=tk.X, pady=4)
        add = ttk.Menubutton(buttons, text="Add ▾")
        menu = tk.Menu(add, tearoff=False)
        for fx_type in tfx.FX_TYPES:
            menu.add_command(label=FX_NAMES[fx_type], command=lambda t=fx_type: self.add_effect(t))
        add["menu"] = menu
        add.pack(side=tk.LEFT)
        for text, command in (("Remove", self.remove_effect), ("▲", lambda: self.move_effect(-1)),
                              ("▼", lambda: self.move_effect(1)), ("Duplicate", self.duplicate_effect),
                              ("On/Off", self.toggle_effect)):
            ttk.Button(buttons, text=text, command=command).pack(side=tk.LEFT, padx=2)

        right = ttk.LabelFrame(panes, text="Settings")
        panes.add(right, weight=2)
        self.settings = ttk.Frame(right)
        self.settings.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def status(self, text):
        if self.winfo_exists():
            self.status_label.config(text=text)

    # ------------------------------------------------------------------ transitions
    def pair(self, index=None):
        index = self.pair_index if index is None else index
        return self.profiles[index]["file_path"], self.profiles[index + 1]["file_path"]

    def entry(self):
        a, b = self.pair()
        return self.project.fx_for_pair(a, b) or {"nudge_ms": 0.0, "effects": []}

    def effects(self):
        return [dict(fx) for fx in self.entry().get("effects") or []]

    def refresh_transitions(self):
        selected = self.pair_index
        self.trans_tree.delete(*self.trans_tree.get_children())
        rendered = self.project.data["fx"].get("render") is not None
        for i in range(len(self.profiles) - 1):
            a, b = self.pair(i)
            entry = self.project.fx_for_pair(a, b) or {}
            count = sum(1 for fx in entry.get("effects") or [] if fx.get("enabled", True))
            state = ("✓" if rendered else "*") if count else ""
            score = self.transitions[i].get("score", "") if i < len(self.transitions) else ""
            name = f"{self.profiles[i].get('filename', os.path.basename(a))} → {self.profiles[i + 1].get('filename', os.path.basename(b))}"
            self.trans_tree.insert("", tk.END, iid=f"T{i}", values=(i + 1, name, f"{float(score):.0f}" if score != "" else "",
                                                                   count or "", state))
        self.inactive_list.delete(0, tk.END)
        self._inactive = self.project.inactive_fx_pairs()
        for a, b in self._inactive:
            self.inactive_list.insert(tk.END, f"{os.path.basename(a)} → {os.path.basename(b)}")
        if selected is not None and f"T{selected}" in self.trans_tree.get_children():
            self.trans_tree.selection_set(f"T{selected}")

    def on_transition_selected(self):
        sel = self.trans_tree.selection()
        if not sel:
            return
        index = int(sel[0][1:])
        if index == self.pair_index:
            return
        self.pair_index = index
        self.fx_index = None
        pa, pb = self.profiles[index], self.profiles[index + 1]
        t = self.transitions[index] if index < len(self.transitions) else {}
        bpm_a = float(pa.get("bpm") or 0)
        beat = f"{60.0 / bpm_a:.3f} s" if bpm_a else "-"
        self.info_label.config(text=(
            f"Junction A {_fmt(pa.get('outro_start', 0))} · B {_fmt(pb.get('intro_start', 0))}\n"
            f"{bpm_a:.1f} → {float(pb.get('bpm') or 0):.1f} BPM · {pa.get('key') or '-'} → {pb.get('key') or '-'} · "
            f"beat {beat} · score {float(t.get('score', 0)):.0f}"))
        self._setting_nudge = True
        self.nudge_var.set(str(int(round(float(self.entry().get("nudge_ms", 0))))))
        self._setting_nudge = False
        self.refresh_fx()
        self.show_settings()
        self.schedule_preview()

    def on_nudge(self):
        if getattr(self, "_setting_nudge", False) or self.pair_index is None:
            return
        try:
            value = max(-50.0, min(50.0, float(self.nudge_var.get())))
        except ValueError:
            return
        a, b = self.pair()
        self.project.set_fx_nudge(a, b, value)
        self._saved()

    def remove_inactive(self):
        sel = self.inactive_list.curselection()
        if not sel:
            return
        a, b = self._inactive[sel[0]]
        self.project.remove_fx(a, b)
        self._saved()

    # ------------------------------------------------------------------ FX stack
    def _store(self, effects, rebuild_settings=False):
        a, b = self.pair()
        self.project.set_fx_effects(a, b, effects)
        self._saved()
        self.refresh_fx()
        if rebuild_settings:
            self.show_settings()

    def _saved(self):
        self.project.save()
        self.refresh_transitions()
        if hasattr(self.app, "_refresh_workflow"):
            self.app._refresh_workflow()
        self.schedule_preview()

    def refresh_fx(self):
        self.fx_tree.delete(*self.fx_tree.get_children())
        if self.pair_index is None:
            return
        for i, fx in enumerate(self.effects()):
            self.fx_tree.insert("", tk.END, iid=f"F{i}", values=("✓" if fx.get("enabled", True) else "", effect_summary(fx)))
        if self.fx_index is not None and f"F{self.fx_index}" in self.fx_tree.get_children():
            self.fx_tree.selection_set(f"F{self.fx_index}")

    def on_fx_selected(self):
        sel = self.fx_tree.selection()
        index = int(sel[0][1:]) if sel else None
        if index != self.fx_index:
            self.fx_index = index
            self.show_settings()

    def add_effect(self, fx_type):
        if self.pair_index is None:
            messagebox.showinfo("Transition FX", "Select a transition first", parent=self)
            return
        effects = self.effects()
        effects.append(tfx.new_effect(fx_type))
        self.fx_index = len(effects) - 1
        self._store(effects, rebuild_settings=True)

    def remove_effect(self):
        if self.fx_index is None:
            return
        effects = self.effects()
        effects.pop(self.fx_index)
        self.fx_index = None
        self._store(effects, rebuild_settings=True)

    def move_effect(self, delta):
        if self.fx_index is None:
            return
        effects = self.effects()
        j = max(0, min(len(effects) - 1, self.fx_index + delta))
        effects.insert(j, effects.pop(self.fx_index))
        self.fx_index = j
        self._store(effects)

    def duplicate_effect(self):
        if self.fx_index is None:
            return
        effects = self.effects()
        effects.insert(self.fx_index + 1, copy.deepcopy(effects[self.fx_index]))
        self.fx_index += 1
        self._store(effects, rebuild_settings=True)

    def toggle_effect(self):
        if self.fx_index is None:
            return
        effects = self.effects()
        effects[self.fx_index]["enabled"] = not effects[self.fx_index].get("enabled", True)
        self._store(effects)

    def update_effect(self, changes, rebuild_settings=False):
        effects = self.effects()
        if self.fx_index is None or self.fx_index >= len(effects):
            return
        effects[self.fx_index].update(changes)
        self._store(effects, rebuild_settings)

    # ------------------------------------------------------------------ settings panel
    def show_settings(self):
        for child in self.settings.winfo_children():
            child.destroy()
        if self.pair_index is None or self.fx_index is None:
            ttk.Label(self.settings, text="Select a transition, then add or select an effect.", foreground=MUTED).pack(anchor="w")
            return
        fx = self.effects()[self.fx_index]
        ttk.Label(self.settings, text=FX_NAMES[fx["type"]], font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        form = ttk.Frame(self.settings)
        form.pack(fill=tk.X, pady=4)
        self._fields(form, FIELDS[fx["type"]], fx, lambda key, value: self.update_effect({key: value}))
        if fx["type"] == "freeze":
            self._freeze_extras(fx)
        if fx["type"] == "sample":
            self._sample_extras(fx)

    def _fields(self, parent, fields, values, on_change):
        for row, (key, label, kind, spec) in enumerate(fields):
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=str(values.get(key)))
            if kind == "choice":
                widget = ttk.Combobox(parent, textvariable=var, values=[str(c) for c in spec], width=18, state="readonly")
            else:
                lo, hi = spec
                step = 1 if kind == "int" else (0.05 if hi <= 1 else (0.1 if hi <= 20 else 10))
                widget = ttk.Spinbox(parent, from_=lo, to=hi, increment=step, textvariable=var, width=10)
            widget.grid(row=row, column=1, sticky="w", padx=6)
            var.trace_add("write", lambda *a, k=key, v=var, kd=kind, s=spec: self._field_changed(k, v, kd, s, on_change))

    @staticmethod
    def _field_changed(key, var, kind, spec, on_change):
        text = var.get()
        if kind == "choice":
            value = next((c for c in spec if str(c) == text), None)
            if value is None:
                return
        else:
            try:
                value = float(text)
            except ValueError:
                return
            lo, hi = spec
            if not lo <= value <= hi:
                return
            if kind == "int":
                value = int(round(value))
        on_change(key, value)

    def _freeze_extras(self, fx):
        steps_box = ttk.LabelFrame(self.settings, text="Steps (a roll shortens the loop)")
        steps_box.pack(fill=tk.X, pady=4)
        steps = [dict(s) for s in fx.get("steps") or []]

        def set_steps(new_steps, rebuild=True):
            self.update_effect({"steps": new_steps}, rebuild_settings=rebuild)

        for i, step in enumerate(steps):
            row = ttk.Frame(steps_box)
            row.pack(anchor="w", padx=4, pady=1)
            ttk.Label(row, text=f"{i + 1}.").pack(side=tk.LEFT)
            beats_var = tk.StringVar(value=f"{float(step['beats']):g}")
            ttk.Combobox(row, textvariable=beats_var, values=("4", "2", "1", "0.5"), width=4, state="readonly").pack(side=tk.LEFT, padx=2)
            ttk.Label(row, text="beats ×").pack(side=tk.LEFT)
            rep_var = tk.StringVar(value=str(int(step["repeats"])))
            ttk.Spinbox(row, from_=1, to=32, increment=1, textvariable=rep_var, width=4).pack(side=tk.LEFT, padx=2)

            def changed(*a, i=i, bv=beats_var, rv=rep_var):
                try:
                    beats, repeats = float(bv.get()), int(float(rv.get()))
                except ValueError:
                    return
                if repeats < 1:
                    return
                new = [dict(s) for s in self.effects()[self.fx_index].get("steps") or []]
                new[i] = {"beats": int(beats) if beats >= 1 else beats, "repeats": repeats}
                set_steps(new, rebuild=False)
            beats_var.trace_add("write", changed)
            rep_var.trace_add("write", changed)
            ttk.Button(row, text="−", width=2,
                       command=lambda i=i: set_steps([s for k, s in enumerate(steps) if k != i] or steps)).pack(side=tk.LEFT, padx=4)
        ttk.Button(steps_box, text="+ step", command=lambda: set_steps(steps + [{"beats": 1, "repeats": 2}])).pack(anchor="w", padx=4, pady=2)

        for key, label, fields, defaults in (
                ("loop_filter", "Loop filter", LOOP_FILTER_FIELDS,
                 {k: v for k, v in tfx.new_effect("filter").items() if k not in ("type", "enabled", "side", "beats")}),
                ("loop_echo", "Loop echo", LOOP_ECHO_FIELDS,
                 {k: v for k, v in tfx.new_effect("echo").items() if k not in ("type", "enabled", "start_offset_beats")})):
            box = ttk.LabelFrame(self.settings, text=label)
            box.pack(fill=tk.X, pady=4)
            on = tk.BooleanVar(value=bool(fx.get(key)))
            ttk.Checkbutton(box, text="On", variable=on,
                            command=lambda k=key, v=on, d=defaults: self.update_effect({k: dict(d) if v.get() else None},
                                                                                        rebuild_settings=True)).pack(anchor="w", padx=4)
            if fx.get(key):
                inner = ttk.Frame(box)
                inner.pack(fill=tk.X, padx=4)
                self._fields(inner, fields, fx[key],
                             lambda k2, value, k=key: self.update_effect({k: dict(self.effects()[self.fx_index][k], **{k2: value})}))

    def _sample_extras(self, fx):
        box = ttk.LabelFrame(self.settings, text="Sample")
        box.pack(fill=tk.BOTH, expand=True, pady=4)
        folder = self.app.config.get("fx_samples_folder") or ""
        if not folder:
            ttk.Label(box, text="Set the FX samples folder in the Configuration tab.", foreground=MUTED).pack(anchor="w", padx=4)
            return
        top = ttk.Frame(box)
        top.pack(fill=tk.X, padx=4)
        ttk.Label(top, text="Filter:").pack(side=tk.LEFT)
        filter_var = tk.StringVar()
        ttk.Entry(top, textvariable=filter_var, width=20).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="▶ Sample", command=self.audition_sample).pack(side=tk.LEFT, padx=4)
        ttk.Label(box, text=f"Current: {os.path.basename(fx.get('file') or '') or '-'}", foreground=MUTED).pack(anchor="w", padx=4)
        self.sample_list = tk.Listbox(box, height=8)
        self.sample_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
        self._shown_samples = []

        def fill(*a):
            self.sample_list.delete(0, tk.END)
            self._shown_samples = library.filter_entries(self.samples, filter_var.get())
            for entry in self._shown_samples:
                too_long = (entry.get("duration") or 0) > tfx.MAX_SAMPLE_SECONDS
                self.sample_list.insert(tk.END, f"{entry['filename']}  ({(entry.get('duration') or 0):.1f} s)"
                                        + ("  - too long" if too_long else ""))
                if too_long:
                    self.sample_list.itemconfig(tk.END, foreground="#9a9a9a")
        filter_var.trace_add("write", fill)
        fill()

        self.sample_list.bind("<Double-1>", lambda e: self.pick_sample())
        self.sample_list.bind("<Return>", lambda e: self.pick_sample())

    def pick_sample(self):
        """Use the sample selected in the list for the current sample effect."""
        sel = self.sample_list.curselection()
        if not sel:
            return
        entry = self._shown_samples[sel[0]]
        if (entry.get("duration") or 0) > tfx.MAX_SAMPLE_SECONDS:
            self.status(f"{entry['filename']} is longer than {tfx.MAX_SAMPLE_SECONDS:.0f} s")
            return
        self.update_effect({"file": entry["file_path"]}, rebuild_settings=True)

    def scan_samples(self):
        folder = (self.app.config.get("fx_samples_folder") or "").strip()
        if not folder:
            return

        def work():
            try:
                entries = library.scan(folder, use_cache=False)
            except Exception as e:
                self.app._report_error(f"FX samples scan failed: {e}", e)
                return

            def done():
                if not self.winfo_exists():
                    return
                self.samples = entries
                if self.fx_index is not None and self.effects()[self.fx_index]["type"] == "sample":
                    self.show_settings()
            self.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def audition_sample(self):
        sel = self.sample_list.curselection() if hasattr(self, "sample_list") else ()
        path = self._shown_samples[sel[0]]["file_path"] if sel else (self.effects()[self.fx_index].get("file") if self.fx_index is not None else "")
        if not path:
            return
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
            out = os.path.join(self._tmp_dir(), "sample_preview.wav")
            self.player.stop()
            sf.write(out, data, sr, subtype="PCM_16")
            self.player.play_once(out)
        except Exception as e:
            self.app._report_error(f"Cannot play {os.path.basename(path)}: {e}", e)

    # ------------------------------------------------------------------ preview
    @staticmethod
    def _tmp_dir():
        folder = os.path.join(dynamix_home(), "tmp")
        os.makedirs(folder, exist_ok=True)
        return folder

    def start_preview(self):
        if self.pair_index is None:
            messagebox.showinfo("Transition FX", "Select a transition first", parent=self)
            return
        self._previewing = True
        self.render_preview()

    def schedule_preview(self):
        if not self._previewing:
            return
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(400, self.render_preview)

    def render_preview(self):
        self._preview_job = None
        if self.pair_index is None:
            return
        self._preview_seq += 1
        seq = self._preview_seq
        index = self.pair_index
        entry = copy.deepcopy(self.entry())
        bases = self.project.premaster_map()
        length = self.length_var.get()
        path = os.path.join(self._tmp_dir(), f"preview_{'a' if seq % 2 else 'b'}.wav")
        self.status("Rendering the preview ...")

        def work():
            try:
                clip, sr, warnings = render_preview(self.profiles[index], self.profiles[index + 1], entry, bases, length)
                if seq != self._preview_seq:
                    return
                sf.write(path, clip, sr, subtype="PCM_16")
            except Exception as e:
                self.app._report_error(f"Preview failed: {e}", e)
                self.after(0, self.status, "Preview failed (see the Log)")
                return

            def done():
                if seq != self._preview_seq or not self._previewing or not self.winfo_exists():
                    return
                looping = self.player.play_loop(path)
                for w in warnings:
                    log.warning("Preview: %s", w)
                self.status(("Looping the preview" if looping else "Preview opened in the default player")
                            + (f" - {warnings[0]}" if warnings else ""))
            self.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def stop_preview(self):
        self._previewing = False
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
            self._preview_job = None
        self._preview_seq += 1
        self.player.stop()
        self.status("Stopped")

    def close(self):
        self.stop_preview()
        self.destroy()

    # ------------------------------------------------------------------ render
    def apply_all(self):
        pairs = self.project.active_fx_pairs()
        if not pairs:
            messagebox.showinfo("Transition FX", "No active FX on the transitions of the set list", parent=self)
            return
        self.stop_preview()
        app, project = self.app, self.project
        profiles = list(self.profiles)
        lookup = {project.fx_key(a, b): copy.deepcopy(project.fx_for_pair(a, b)) for a, b in pairs}
        bases = project.premaster_map()
        fmt = app.config.get("output_format", "same")
        out_dir = project.fx_dir
        self.status(f"Rendering FX for {len(pairs)} transitions ...")

        def work():
            try:
                results, problems = render_set(
                    profiles, lambda a, b: lookup.get(project.fx_key(a, b)), bases, out_dir, fmt,
                    progress=lambda i, n, name: app.root.after(0, app.update_status, f"Rendering FX {i}/{n}: {name}"))
            except Exception as e:
                app._report_error(f"FX render failed: {e}", e)
                return

            def done():
                project.set_fx_render(results)
                project.mark("fx", count=len(results))
                for problem in problems:
                    log.warning("FX: %s", problem)
                message = f"FX rendered: {len(results)} copies in {out_dir}" + (
                    f" ({len(problems)} problems, see the Log)" if problems else "")
                log.info(message)
                if app.project is not project:
                    project.save()
                    return
                app._save_project()
                app._render_overview()
                app.update_status(message)
                if self.winfo_exists():
                    self.refresh_transitions()
                    self.status(message)
            app.root.after(0, done)
        threading.Thread(target=work, daemon=True).start()
```

- [ ] **Step 3 : étape `fx` du workflow (`set_project.py`)**

Remplacer :
```python
    ("premaster", "Pre-master the set (optional)", False),
```
par :
```python
    ("premaster", "Pre-master the set (optional)", False),
    ("fx", "Add transition FX (optional)", False),
```
et remplacer :
```python
    "playlist": "Optional: 'Create Playlist' writes the set order as an M3U file into the project's exports folder.",
```
par :
```python
    "fx": "Optional: 'Transition FX' adds freezes, filter sweeps, echoes and samples on chosen transitions, rendered into the project's fx folder.",
    "playlist": "Optional: 'Create Playlist' writes the set order as an M3U file into the project's exports folder.",
```

- [ ] **Step 4 : brancher le Set Builder (`set_builder.py`)**

Remplacer :
```python
from transition_planner import TransitionPlanner
```
par :
```python
from fx_window import TransitionFxWindow
from transition_planner import TransitionPlanner
```

Remplacer :
```python
            "premaster": ("Pre-master Set", self.premaster_set),
```
par :
```python
            "premaster": ("Pre-master Set", self.premaster_set),
            "fx": ("Transition FX", self.open_fx_window),
```

Dans `premaster_set`, remplacer :
```python
                    project.data["premaster"] = {"out_dir": out_dir, "target_lufs": target_lufs, "tone_match": tone,
```
par :
```python
                    project.invalidate_from("premaster")  # FX renders were made from the previous copies
                    project.data["premaster"] = {"out_dir": out_dir, "target_lufs": target_lufs, "tone_match": tone,
```

Remplacer toute la méthode :
```python
    def _with_premastered(self, tracks):
        mapping = self.project.premaster_map() if self.project else {}
        if not mapping:
            return list(tracks), 0
        swapped, count = [], 0
        for t in tracks:
            out = mapping.get(t.get("file_path"))
            if out:
                t = dict(t, file_path=out, filename=os.path.basename(out))
                count += 1
            swapped.append(t)
        return swapped, count
```
par :
```python
    def _with_rendered(self, tracks):
        """Tracks pointing at the file to play: FX copy (with its cue positions), else pre-master, else original."""
        if self.project is None:
            return list(tracks), {"fx": 0, "premaster": 0}
        return self.project.rendered_profiles(list(tracks))
    
    @staticmethod
    def _copies_note(counts):
        parts = [f"{counts[k]} {label}" for k, label in (("fx", "FX copies"), ("premaster", "pre-mastered copies")) if counts[k]]
        return ", ".join(parts)
    
    def _fx_labels(self):
        """Transition index -> its enabled FX types (for the set map)."""
        if self.project is None:
            return {}
        labels = {}
        lst = self.project.set_list
        for i, (a, b) in enumerate(zip(lst, lst[1:])):
            entry = self.project.fx_for_pair(a, b) or {}
            types = [fx["type"] for fx in entry.get("effects") or [] if fx.get("enabled", True)]
            if types:
                labels[i] = " · ".join(types)
        return labels
    
    def open_fx_window(self, player=None):
        if not self._require_project():
            return None
        data = self.project.data.get("transitions")
        if not data or len(data.get("tracks") or []) < 2:
            messagebox.showwarning("Warning", "Plan the transitions first (step 3)")
            return None
        return TransitionFxWindow(self, player=player)
```

Dans `create_playlist_from_directory`, remplacer :
```python
        tracks, premastered = self._with_premastered(tracks)
```
par :
```python
        tracks, counts = self._with_rendered(tracks)
```
et remplacer :
```python
        note = f" ({premastered} pre-mastered copies)" if premastered else ""
```
par :
```python
        note = f" ({self._copies_note(counts)})" if counts["fx"] or counts["premaster"] else ""
```

Dans `export_to_mixxx`, remplacer :
```python
        profiles, premastered = self._with_premastered(planner.profiles)
```
par :
```python
        profiles, counts = self._with_rendered(planner.profiles)
```
et remplacer :
```python
        if premastered:
            summary = f"Using the pre-mastered copies for {premastered} tracks.\n" + summary
```
par :
```python
        if counts["fx"] or counts["premaster"]:
            summary = f"Using {self._copies_note(counts)}.\n" + summary
```

Dans `_show_transition_window`, remplacer :
```python
        ttk.Button(toolbar, text="Export to Mixxx...", command=lambda: self.export_to_mixxx(text)).pack(side=tk.RIGHT, padx=5)
```
par :
```python
        ttk.Button(toolbar, text="Export to Mixxx...", command=lambda: self.export_to_mixxx(text)).pack(side=tk.RIGHT, padx=5)
        ttk.Button(toolbar, text="Transition FX...", command=self.open_fx_window).pack(side=tk.RIGHT, padx=5)
```

Dans `_render_overview`, remplacer :
```python
            self._show_figure(self.overview_frame, charts.set_timeline(planner.profiles, planner.transitions), replace=False)
```
par :
```python
            self._show_figure(self.overview_frame, charts.set_timeline(planner.profiles, planner.transitions,
                                                                       fx_labels=self._fx_labels()), replace=False)
```

Dans `reset_project`, remplacer le texte `in premaster/ and exports/` par `in premaster/, fx/ and exports/`. Il apparaît une seule fois, dans la chaîne f qui construit le message de confirmation.

- [ ] **Step 5 : CLI (`mixxx_export.py`, `mastering.py`)**

Dans `mixxx_export.py`, remplacer :
```python
    profiles = list(planner.profiles)
    if project is not None and not args.originals:
        mapping = project.premaster_map()
        if mapping:
            profiles = [dict(p, file_path=mapping.get(p["file_path"], p["file_path"])) for p in profiles]
            print(f"Using the pre-mastered copies for {sum(1 for p in planner.profiles if p['file_path'] in mapping)} tracks "
                  f"(--originals to export the original files).")
```
par :
```python
    profiles = list(planner.profiles)
    if project is not None and not args.originals:
        profiles, counts = project.rendered_profiles(profiles)
        if counts["fx"] or counts["premaster"]:
            print(f"Using {counts['fx']} FX copies and {counts['premaster']} pre-mastered copies "
                  f"(--originals to export the original files).")
```

Dans `mastering.py`, remplacer :
```python
                project.data["premaster"] = {"out_dir": os.path.abspath(args.out), "target_lufs": args.lufs, "tone_match": args.tone,
```
par :
```python
                project.invalidate_from("premaster")  # FX renders were made from the previous copies
                project.data["premaster"] = {"out_dir": os.path.abspath(args.out), "target_lufs": args.lufs, "tone_match": args.tone,
```

- [ ] **Step 6 : lancer les vérifications**

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `GUI smoke OK`

Run : `venv/Scripts/python.exe -c "import gui, mixxx_export, mastering, fx_window; print('ok')"`
Expected : `ok`

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected : `Ran 124 tests`, `FAILED (failures=2, errors=11)`, uniquement les échecs préexistants.

- [ ] **Step 7 : commit**

```bash
git add fx_window.py set_project.py set_builder.py mixxx_export.py mastering.py tests/gui_smoke.py
git commit -m "Transition FX window: per-transition FX stack, looped preview, Apply all FX; exports use the FX copies"
```

---

### Task 6 : documentation et vérification finale

**Files :**
- Modify: `GUI_README.md`, `README.md`

- [ ] **Step 1 : `GUI_README.md`**

Remplacer :
```markdown
    4. Pre-master Set (optional, into the project's premaster folder)
    5. Create Playlist (optional, M3U into exports/)
    6. Export to Mixxx (uses the database set in the Configuration tab)
```
par :
```markdown
    4. Pre-master Set (optional, into the project's premaster folder)
    5. Transition FX (optional, copies with FX into the project's fx folder)
    6. Create Playlist (optional, M3U into exports/)
    7. Export to Mixxx (uses the database set in the Configuration tab)
```

Remplacer :
```markdown
- **Log tab**: everything DynaMix prints and every error with its traceback,
```
par :
```markdown
- **Transition FX** window (workflow step 5, or the button of the transition
  sheet): pick a transition, then stack effects on it — **Freeze** (loops the
  last beats of the outgoing track, with a roll such as 4×1 → 2×2 → 1×4, an
  optional loop filter / echo, a fade and a tail), **Filter** (high-pass,
  low-pass or band-pass sweep with resonance, closing the outgoing track or
  opening the incoming one), **Echo** (tempo-synced) and **Sample** (from the
  FX samples folder, anchored to end at, start at or centre on the junction; it
  may run over into the next track). **▶ Preview (loop)** plays the transition
  in a loop and re-renders it when a setting changes; **Nudge (ms)** shifts the
  junction by ear. **Apply all FX** writes copies into `fx/` (the library and
  the pre-mastered copies are never modified); the playlist and the Mixxx
  export then use those copies, with the cue positions of the rendered files.
- **Log tab**: everything DynaMix prints and every error with its traceback,
```

Remplacer :
```markdown
- **Paths**: the projects folder, the Mixxx database (Browse / Detect, empty
  = auto-detect), and where DynaMix keeps its cache and configuration
```
par :
```markdown
- **Paths**: the projects folder, the Mixxx database (Browse / Detect, empty
  = auto-detect), the music library folder, the FX samples folder, and where
  DynaMix keeps its cache and configuration
```

- [ ] **Step 2 : `README.md`**

Remplacer :
```markdown
(`app_log.py`, also written to `<DynaMix home>/logs/dynamix.log`). Projects created before
this version keep working: their imported `source/` copies become their selection.
```
par :
```markdown
(`app_log.py`, also written to `<DynaMix home>/logs/dynamix.log`). Projects created before
this version keep working: their imported `source/` copies become their selection.

**Transition FX** (`transition_fx.py`, `fx_render.py`, `fx_window.py`): per transition, a stack of
freeze / roll, filter sweeps (high-pass, low-pass, band-pass with resonance), tempo-synced echo
and FX samples, placed in beats around the junction. The Transition FX window previews a
transition in a loop while you tweak it; **Apply all FX** renders copies into the project's
`fx/` folder (effects that outlast the outgoing track continue at the start of the next one).
Settings are kept per track pair in `project.json`, so reordering the set keeps them; the
library and the pre-mastered copies are never modified. Playback files are chosen in this
order: FX copy, pre-mastered copy, original.
```

Remplacer :
```markdown
- **Command line**: `mixxx_export.py --project <folder>` reuses the project's set list, writes
  the sheet and charts into `exports/` and records the steps; `mastering.py fix <project folder>`
  pre-masters the set list into `premaster/`.
```
par :
```markdown
- **Command line**: `mixxx_export.py --project <folder>` reuses the project's set list, writes
  the sheet and charts into `exports/`, exports the FX or pre-mastered copies when they exist
  (`--originals` to skip them) and records the steps; `mastering.py fix <project folder>`
  pre-masters the set list into `premaster/`.
```

Remplacer :
```markdown
Charts (`charts.py`): set energy curve vs. target and tempo, set map with intro/outro sections
and transition scores, per-track energy envelope and tone balance against the set, and
```
par :
```markdown
Charts (`charts.py`): set energy curve vs. target and tempo, set map with intro/outro sections,
transition scores and transition FX, per-track energy envelope and tone balance against the set, and
```

- [ ] **Step 3 : vérification finale**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected : `Ran 124 tests`, `FAILED (failures=2, errors=11)`, uniquement les échecs préexistants.

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `GUI smoke OK`

Run : `venv/Scripts/python.exe -c "import gui, mixxx_export, mastering, mix_enhanced, fx_window, fx_render, transition_fx; print('ok')"`
Expected : `ok`

- [ ] **Step 4 : commit**

```bash
git add README.md GUI_README.md
git commit -m "Docs: transition FX"
```

La vérification manuelle dans l'application réelle (pré-écoute audible en boucle, rendu sur de vrais morceaux, export Mixxx) est faite ensuite par l'utilisateur. Un agent ne peut pas écouter ni manipuler l'interface.
