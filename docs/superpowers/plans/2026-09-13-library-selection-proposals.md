# Bibliothèque, sélection, propositions, réinitialisation et journal — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** remplacer l'import par projet par une bibliothèque unique scannée sur place, une sélection par set, plusieurs propositions de set calculées uniquement à partir de la sélection, deux actions de remise à zéro et un onglet Log.

**Architecture :**
- Trois modules purs et testables :
  - `set_proposer.py` : recherche en faisceau ;
  - `library.py` : scan du dossier, qui lit les en-têtes et le cache ;
  - `app_log.py` : capture de logging, stdout, stderr, warnings et exceptions.
- `SetProject` passe au schéma v3 : `selection`, `failed`, `proposals`, migration, `reset`.
- Le GUI Tkinter (`set_builder.py`, nouveau `log_tab.py`, `gui.py`) s'appuie sur ces modules.
- `PlaylistManager.create_set_list` garde sa signature pour les CLI et délègue à `set_proposer`.

**Tech Stack :** Python 3.8+, Tkinter/ttk, sqlite3, soundfile, numpy, matplotlib (existant), `unittest`.

**Spec :** `docs/superpowers/specs/2026-09-13-library-selection-proposals-design.md`

## Global Constraints

- Python 3.8+ : pas de `match`, pas de types `list[str]` dans les signatures. Utiliser `typing`.
- Aucune nouvelle dépendance : `soundfile`, `numpy` et `matplotlib` sont déjà dans `requirements.txt`.
- Les libellés de l'interface restent en anglais : « Reset project... », « Clear analysis cache... », « Log », « Propose », « Use this proposal », « Add to selection → », « Analyze selection ».
- Commandes à lancer depuis la racine du dépôt, dans Git Bash.
- Les tests se lancent avec `venv/Scripts/python.exe -m unittest discover -s tests -p "<fichier>" -v`. Pytest n'est pas installé dans le venv.
- **Base de tests existante** : 66 tests, dont 2 échecs et 11 erreurs **déjà présents avant ce chantier**, tous dans `test_audio_utils.py` et `test_dj_tools.py`. Ils viennent de mocks librosa/DJTools périmés. Ils ne doivent ni être corrigés ni s'aggraver. Aucun autre échec n'est acceptable.
- Tout test qui touche au cache ou à la configuration isole `DYNAMIX_HOME` dans un dossier temporaire et appelle `analysis_store.reset_store()`.
- Chemins des morceaux : `os.path.abspath` produit par `library.scan`. `selection`, `tracks[].file_path` et le cache utilisent exactement ces chaînes.
- Chaque message de commit se termine par ces deux lignes :
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01MUns5Z6kfLha44xzsbabYX
  ```
- Branche : `feature/library-selection-proposals`.

---

## Carte des fichiers

| Fichier | Rôle | Tâche |
|---|---|---|
| `set_proposer.py` (nouveau) | courbes, coûts, recherche en faisceau, variantes, `curve_targets` | 1 |
| `playlist_manager.py` | `transition_cost` partagé, `create_set_list` délègue, suppression de `_select_for_duration` | 2 |
| `analysis_store.py` | `clear_paths` | 3 |
| `config.py` | clé `library_folder` | 3 |
| `set_project.py` | schéma v3, sélection, propositions, migration, reset | 4 |
| `mixxx_export.py`, `mastering.py` | `selection_files()` au lieu de `source_files()` | 4 |
| `library.py` (nouveau) | scan du dossier bibliothèque | 5 |
| `app_log.py` (nouveau) | capture du journal | 6 |
| `log_tab.py` (nouveau) | onglet Log (mixin) | 7 |
| `gui.py` | installation du journal, onglet Log | 7 |
| `set_builder.py` | `_report_error` (7), Configuration (8), colonnes Library/Selection (9), propositions (10), reset/cache/new project (11) | 7-11 |
| `tests/gui_smoke.py` (nouveau) | vérification du GUI complet (hors pytest/unittest) | 7-11 |
| `README.md`, `GUI_README.md` | nouveau flux | 12 |

---

### Task 1 : module `set_proposer.py`

**Files :**
- Create: `set_proposer.py`
- Test: `tests/test_set_proposer.py`

**Interfaces :**
- Consumes : `audio_utils.key_compatibility_score(key1, key2) -> float`, `transition_planner.compatibility_from_features(f1, f2) -> Dict` (clé `"overall_score"`).
- Produces :
  - `CURVES = ("build", "wave", "peak_middle", "constant")`
  - `energy_value(track: Dict) -> float`
  - `energy_target(position: float, curve: str) -> float` (lève `ValueError` si la courbe est inconnue)
  - `transition_cost(a: Dict, b: Dict, bpm: bool = True, key: bool = True) -> float`
  - `overlap_seconds(track: Dict, mix_bars: int = 8) -> float`
  - `curve_targets(tracks, curve, mix_bars=8) -> Optional[List[float]]`
  - `propose(tracks, target_seconds, curve="build", mix_bars=8, variants=3, beam_width=50, tolerance=0.03) -> List[Dict]`. Chaque variante contient `curve`, `tracks` (fiches ordonnées), `order` (chemins), `effective_seconds`, `target_seconds`, `cost`, `score` (int), `transition_scores` (List[int]), `worst` (`{"index", "score"}` ou `None`).
  - `_similarity(a, b) -> float` (utilisée par les tests).

- [ ] **Step 1 : écrire le test qui échoue**

Créer `tests/test_set_proposer.py` :

```python
import unittest

import set_proposer
from set_proposer import curve_targets, energy_target, overlap_seconds, propose, transition_cost


def track(name, energy, duration=300.0, bpm=120.0, key="A minor"):
    return {"file_path": f"/lib/{name}.wav", "filename": f"{name}.wav", "duration": duration,
            "bpm": bpm, "key": key, "energy_level": energy, "has_beat": True}


class TestCurvesAndCosts(unittest.TestCase):
    def test_energy_target_values(self):
        self.assertAlmostEqual(energy_target(0.0, "build"), 0.0)
        self.assertAlmostEqual(energy_target(1.0, "build"), 1.0)
        self.assertAlmostEqual(energy_target(0.5, "peak_middle"), 1.0)
        self.assertAlmostEqual(energy_target(0.0, "peak_middle"), 0.0)
        self.assertAlmostEqual(energy_target(0.0, "wave"), 0.0)
        self.assertAlmostEqual(energy_target(0.25, "wave"), 1.0)
        self.assertAlmostEqual(energy_target(0.5, "wave"), 0.0)
        self.assertAlmostEqual(energy_target(0.3, "constant"), 0.5)
        with self.assertRaises(ValueError):
            energy_target(0.5, "zigzag")

    def test_overlap_defaults_to_120_bpm(self):
        self.assertAlmostEqual(overlap_seconds({"bpm": 0}, 8), 16.0)
        self.assertAlmostEqual(overlap_seconds({"bpm": 128.0}, 8), 15.0)

    def test_curve_targets(self):
        tracks = [track("a", 2), track("b", 4), track("c", 6)]
        build = curve_targets(tracks, "build")
        self.assertEqual(len(build), 3)
        self.assertTrue(2.0 <= build[0] < build[1] < build[2] <= 6.0)
        self.assertEqual(curve_targets(tracks, "constant"), [4.0, 4.0, 4.0])
        self.assertIsNone(curve_targets(tracks, "all"))
        self.assertIsNone(curve_targets([], "build"))

    def test_transition_cost(self):
        same = transition_cost(track("a", 5), track("b", 5))
        self.assertAlmostEqual(same, 0.0)
        far = transition_cost(track("a", 5, bpm=120.0, key="C major"), track("b", 5, bpm=130.0, key="F# major"))
        self.assertAlmostEqual(far, 0.03 * 7 + 0.25)
        self.assertAlmostEqual(transition_cost(track("a", 5, bpm=120.0), track("b", 5, bpm=130.0), bpm=False), 0.0)


class TestPropose(unittest.TestCase):
    def test_empty_selection_raises(self):
        with self.assertRaises(ValueError):
            propose([], 600)

    def test_single_track(self):
        variants = propose([track("a", 5)], 3600)
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["order"], ["/lib/a.wav"])
        self.assertEqual(variants[0]["score"], 100)
        self.assertIsNone(variants[0]["worst"])

    def test_fits_duration_with_overlaps(self):
        tracks = [track(f"t{i}", 1 + i % 9) for i in range(12)]
        best = propose(tracks, 1800, curve="build")[0]
        self.assertEqual(len(best["order"]), 6)  # 6 x 300 s - 5 x 16 s = 1720 s; 7 tracks = 2004 s
        self.assertLessEqual(best["effective_seconds"], 1800 * 1.03)
        self.assertAlmostEqual(best["effective_seconds"], 1720.0)

    def test_short_selection_uses_every_track_in_build_order(self):
        tracks = [track("e8", 8), track("e2", 2), track("e10", 10), track("e4", 4), track("e6", 6)]
        best = propose(tracks, 3600, curve="build")[0]
        self.assertEqual([t["energy_level"] for t in best["tracks"]], [2, 4, 6, 8, 10])
        self.assertAlmostEqual(best["effective_seconds"], 5 * 300 - 4 * 16)

    def test_peak_middle_puts_the_peak_in_the_middle(self):
        tracks = [track(f"e{e}", e) for e in (1, 3, 5, 7, 9)]
        best = propose(tracks, 3600, curve="peak_middle")[0]
        energies = [t["energy_level"] for t in best["tracks"]]
        self.assertIn(energies.index(9), (1, 2, 3))

    def test_compatible_keys_stay_adjacent(self):
        tracks = [track("am", 5, key="A minor"), track("fs", 5, key="F# major"), track("c", 5, key="C major")]
        order = propose(tracks, 3600, curve="constant")[0]["order"]
        self.assertEqual(abs(order.index("/lib/am.wav") - order.index("/lib/c.wav")), 1)

    def test_variants_are_distinct_and_deterministic(self):
        keys = ["A minor", "C major", "E minor", "G major", "D minor", "F major", "B minor", "D major"]
        tracks = [track(f"t{i}", 1 + i, key=k, bpm=120 + i) for i, k in enumerate(keys)]
        first = propose(tracks, 1500, curve="wave", variants=3)
        second = propose(tracks, 1500, curve="wave", variants=3)
        self.assertEqual([v["order"] for v in first], [v["order"] for v in second])
        self.assertEqual(len(first), 3)
        for i in range(3):
            for j in range(3):
                if i != j:
                    self.assertLess(set_proposer._similarity(first[i]["order"], first[j]["order"]), 0.7)
        for v in first:
            self.assertEqual(len(v["transition_scores"]), len(v["order"]) - 1)
            self.assertEqual(v["worst"]["score"], min(v["transition_scores"]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2 : lancer le test pour vérifier qu'il échoue**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_set_proposer.py" -v`
Expected : ERROR `ModuleNotFoundError: No module named 'set_proposer'`

- [ ] **Step 3 : écrire l'implémentation**

Créer `set_proposer.py` :

```python
#!/usr/bin/env python3
"""
Set proposals: several playing orders drawn only from the tracks the user
selected, fitted to a target duration and an energy curve.

A beam search builds sequences track by track. A sequence costs:
- per track, the distance between its energy and the curve at its midpoint in time;
- per transition, the tempo jump and the key clash (same penalties as the
  greedy PlaylistManager.suggest_playlist_order);
- once finished, the gap between its effective duration and the target.
Crossfades overlap: each incoming track starts mix_bars bars before the end of
the previous one, so a set is shorter than the sum of its tracks.
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

from audio_utils import key_compatibility_score

CURVES = ("build", "wave", "peak_middle", "constant")
DEFAULT_BPM = 120.0
DURATION_WEIGHT = 2.0
SIMILARITY_LIMIT = 0.7


def energy_value(track: Dict) -> float:
    """Perceived energy level when available, raw RMS energy otherwise."""
    level = track.get("energy_level")
    if level:
        return float(level)
    return float(track.get("avg_energy") or 0.0)


def energy_target(position: float, curve: str) -> float:
    """Target energy (0..1 of the selection's range) at a position (0..1) of the set."""
    p = min(1.0, max(0.0, float(position)))
    if curve == "build":
        return p
    if curve == "peak_middle":
        return 1.0 - abs(2.0 * p - 1.0)
    if curve == "wave":
        return 0.5 - 0.5 * math.cos(4.0 * math.pi * p)  # two waves, starting low
    if curve == "constant":
        return 0.5
    raise ValueError(f"Unknown energy curve: {curve}")


def transition_cost(a: Dict, b: Dict, bpm: bool = True, key: bool = True) -> float:
    """Penalty for playing b right after a: tempo jump beyond 3 BPM, key clash."""
    cost = 0.0
    if bpm and a.get("has_beat", True) and b.get("has_beat", True):
        bpm_a = float(a.get("bpm") or 0)
        bpm_b = float(b.get("bpm") or 0)
        if bpm_a and bpm_b:
            cost += 0.03 * max(0.0, abs(bpm_b - bpm_a) - 3.0)  # free within 3 BPM
    if key:
        score = key_compatibility_score(a.get("key", ""), b.get("key", ""))
        cost += (100.0 - score) / 100.0 * 0.5
    return cost


def overlap_seconds(track: Dict, mix_bars: int = 8) -> float:
    """How long an incoming track plays under the previous one (4 beats per bar)."""
    bpm = float(track.get("bpm") or 0) or DEFAULT_BPM
    return mix_bars * 4 * 60.0 / bpm


def curve_targets(tracks: Sequence[Dict], curve: str, mix_bars: int = 8) -> Optional[List[float]]:
    """Target energy of each track of an ordered set along a curve (Overview chart); None for an unknown curve."""
    if curve not in CURVES or not tracks:
        return None
    energies = [energy_value(t) for t in tracks]
    lo, hi = min(energies), max(energies)
    starts, end = [], 0.0
    for i, t in enumerate(tracks):
        duration = float(t.get("duration") or 0.0)
        start = 0.0 if i == 0 else end - min(overlap_seconds(t, mix_bars), duration)
        starts.append(start)
        end = start + duration
    total = max(end, 1.0)
    return [lo + (hi - lo) * energy_target((s + float(t.get("duration") or 0.0) / 2.0) / total, curve)
            for s, t in zip(starts, tracks)]


def _ident(track: Dict, index: int) -> str:
    return track.get("file_path") or track.get("filename") or f"#{index:05d}"


def _pairs(order: Sequence[str]) -> set:
    return set(zip(order, order[1:]))


def _similarity(a: Sequence[str], b: Sequence[str]) -> float:
    """Share of a's consecutive pairs that b also plays."""
    pa = _pairs(a)
    if not pa:
        return 1.0 if list(a) == list(b) else 0.0
    return len(pa & _pairs(b)) / len(pa)


def _score(order_tracks: List[Dict]) -> Tuple[int, List[int], Optional[Dict]]:
    from transition_planner import compatibility_from_features
    scores = [int(round(compatibility_from_features(a, b)["overall_score"]))
              for a, b in zip(order_tracks, order_tracks[1:])]
    if not scores:
        return 100, [], None
    worst = min(range(len(scores)), key=lambda i: scores[i])
    return int(round(sum(scores) / len(scores))), scores, {"index": worst, "score": scores[worst]}


def propose(tracks: List[Dict], target_seconds: float, curve: str = "build", mix_bars: int = 8,
            variants: int = 3, beam_width: int = 50, tolerance: float = 0.03) -> List[Dict]:
    """
    Best distinct playing orders of (a subset of) tracks for the target duration.

    Returns up to `variants` dicts: curve, tracks (ordered records), order (ids),
    effective_seconds, target_seconds, cost, score (0-100), transition_scores, worst.
    """
    if not tracks:
        raise ValueError("No analysed tracks in the selection")
    energy_target(0.0, curve)  # validates the curve name
    n = len(tracks)
    ids = [_ident(t, i) for i, t in enumerate(tracks)]
    durations = [float(t.get("duration") or 0.0) for t in tracks]
    overlaps = [min(overlap_seconds(t, mix_bars), d) for t, d in zip(tracks, durations)]
    energies = [energy_value(t) for t in tracks]
    lo, hi = min(energies), max(energies)
    span = hi - lo
    target = float(target_seconds)
    limit = target * (1.0 + tolerance)
    full = sum(durations) - (sum(overlaps) - max(overlaps))
    reference = max(1.0, min(target, full))
    trans = [[transition_cost(tracks[i], tracks[j]) if i != j else 0.0 for j in range(n)] for i in range(n)]

    def energy_cost(i: int, start: float) -> float:
        if span <= 0:
            return 0.0
        wanted = lo + span * energy_target((start + durations[i] / 2.0) / reference, curve)
        return abs(energies[i] - wanted) / span

    def rank(state):
        seq, cost, _end = state
        return (cost / len(seq), tuple(ids[i] for i in seq))

    frontier = sorted((((i,), energy_cost(i, 0.0), durations[i]) for i in range(n)), key=rank)[:beam_width]
    finished = []
    while frontier:
        grown = []
        for seq, cost, end in frontier:
            used = set(seq)
            extended = False
            for j in range(n):
                if j in used:
                    continue
                start = end - overlaps[j]
                new_end = start + durations[j]
                if new_end > limit:
                    continue
                grown.append((seq + (j,), cost + trans[seq[-1]][j] + energy_cost(j, start), new_end))
                extended = True
            if not extended:
                finished.append((seq, cost, end))
        frontier = sorted(grown, key=rank)[:beam_width]

    def final_cost(state):
        seq, cost, end = state
        gap = 0.0 if (len(seq) == n and end <= target) else abs(target - end) / target
        return cost / len(seq) + DURATION_WEIGHT * gap

    finished.sort(key=lambda s: (final_cost(s), tuple(ids[i] for i in s[0])))
    chosen = []
    for state in finished:
        order = [ids[i] for i in state[0]]
        if all(_similarity(order, [ids[i] for i in c[0]]) < SIMILARITY_LIMIT for c in chosen):
            chosen.append(state)
        if len(chosen) >= variants:
            break
    for state in finished:
        if len(chosen) >= variants:
            break
        if state not in chosen:
            chosen.append(state)

    out = []
    for state in chosen:
        seq, _cost, end = state
        ordered = [tracks[i] for i in seq]
        score, scores, worst = _score(ordered)
        out.append({
            "curve": curve,
            "tracks": ordered,
            "order": [ids[i] for i in seq],
            "effective_seconds": round(end, 1),
            "target_seconds": target,
            "cost": round(final_cost(state), 4),
            "score": score,
            "transition_scores": scores,
            "worst": worst,
        })
    return out
```

- [ ] **Step 4 : lancer le test pour vérifier qu'il passe**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_set_proposer.py" -v`
Expected : `Ran 11 tests` … `OK`

- [ ] **Step 5 : commit**

```bash
git add set_proposer.py tests/test_set_proposer.py
git commit -m "Set proposer: beam search for several set variants from a selection"
```
(avec les deux lignes d'attribution des Global Constraints)

---

### Task 2 : `PlaylistManager` délègue à `set_proposer`

**Files :**
- Modify: `playlist_manager.py` (import l.7, `_energy_value` l.143-149, coût dans `suggest_playlist_order` l.210-220, `_select_for_duration` + `create_set_list` l.230-271)
- Test: `tests/test_playlist_manager.py` (inchangé : tous ses tests doivent passer)

**Interfaces :**
- Consumes : `set_proposer.energy_value`, `set_proposer.transition_cost`, `set_proposer.propose` (Task 1).
- Produces : `PlaylistManager.create_set_list(duration_minutes=60, energy_curve='build') -> List[Dict]`, même signature qu'avant. Il renvoie les fiches de la meilleure variante. `'build_up'` est accepté comme `'build'`. Il lève `ValueError` sans morceaux. `_select_for_duration` n'existe plus.

- [ ] **Step 1 : vérifier que les tests actuels passent avant la modification**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_playlist_manager.py"`
Expected : `Ran 19 tests` … `OK`

- [ ] **Step 2 : importer `set_proposer`**

Dans `playlist_manager.py`, remplacer :
```python
from analysis_store import get_store
```
par :
```python
from analysis_store import get_store
from set_proposer import energy_value, propose, transition_cost
```

- [ ] **Step 3 : déléguer `_energy_value`**

Remplacer :
```python
    @staticmethod
    def _energy_value(track: Dict) -> float:
        """Perceived energy level when available, raw RMS energy otherwise."""
        level = track.get('energy_level')
        if level:
            return float(level)
        return float(track.get('avg_energy') or 0.0)
```
par :
```python
    @staticmethod
    def _energy_value(track: Dict) -> float:
        """Perceived energy level when available, raw RMS energy otherwise."""
        return energy_value(track)
```

- [ ] **Step 4 : utiliser `transition_cost` dans `suggest_playlist_order`**

Remplacer :
```python
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
```
par :
```python
                if previous is not None:
                    cost += transition_cost(previous, track, bpm=bpm_transitions, key=key_compatibility)
                elif bpm_transitions:
```

- [ ] **Step 5 : remplacer `_select_for_duration` et `create_set_list`**

Supprimer entièrement la méthode `_select_for_duration`, de `    def _select_for_duration(self, target_seconds: float) -> List[Dict]:` à la ligne `        return selected` incluse. Remplacer ensuite toute la méthode `create_set_list`, de `    def create_set_list(self, duration_minutes: int = 60, ` à `        return set_list` incluse, par :

```python
    def create_set_list(self, duration_minutes: int = 60,
                       energy_curve: str = 'build') -> List[Dict]:
        """
        Best set list for the duration, drawn from the analysed tracks: the first
        variant of set_proposer.propose (the GUI shows several).

        Args:
            duration_minutes: Target set duration in minutes (crossfades overlap)
            energy_curve: 'build', 'wave', 'peak_middle', 'constant' ('build_up' = 'build')

        Returns: List of tracks for the set, in playing order
        """
        if not self.tracks:
            raise ValueError("No tracks analyzed. Run analyze_playlist() first.")
        curve = {'build_up': 'build'}.get(energy_curve, energy_curve)
        return propose(list(self.tracks), duration_minutes * 60, curve=curve, variants=1)[0]['tracks']
```

La ligne `import numpy as np` reste en place : `_target_curve` l'utilise toujours.

- [ ] **Step 6 : lancer les tests**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_playlist_manager.py"` puis `venv/Scripts/python.exe -m unittest discover -s tests -p "test_set_proposer.py"`
Expected : `Ran 19 tests` OK, puis `Ran 11 tests` OK.

- [ ] **Step 7 : vérifier que les CLI importent toujours**

Run : `venv/Scripts/python.exe -c "import mixxx_export, mix_enhanced; print('ok')"`
Expected : `ok`

- [ ] **Step 8 : commit**

```bash
git add playlist_manager.py
git commit -m "PlaylistManager: create_set_list uses the set proposer, shared transition cost"
```

---

### Task 3 : `AnalysisStore.clear_paths` et clé `library_folder`

**Files :**
- Modify: `analysis_store.py` (import `typing` l.19, après `clear` l.134-141)
- Modify: `config.py` (`DEFAULTS` l.17-28)
- Test: `tests/test_analysis_store.py`, `tests/test_config.py`

**Interfaces :**
- Produces : `AnalysisStore.clear_paths(paths: List[str]) -> int` (lignes supprimées, tous types confondus) ; `Config.get("library_folder")`, qui vaut `""` par défaut.

- [ ] **Step 1 : écrire les tests qui échouent**

Dans `tests/test_analysis_store.py`, ajouter dans `TestAnalysisStore`, après `test_stats_and_clear` :
```python
    def test_clear_paths(self):
        other = os.path.join(self.tmp, "other.wav")
        with open(other, "wb") as f:
            f.write(b"\x00" * 10)
        self.store.put(self.file, "features", {"a": 1})
        self.store.put(self.file, "bands", {"b": 2})
        self.store.put(other, "features", {"c": 3})
        self.assertEqual(self.store.clear_paths([self.file, os.path.join(self.tmp, "never.wav")]), 2)
        self.assertIsNone(self.store.get(self.file, "features"))
        self.assertEqual(self.store.get(other, "features"), {"c": 3})
        self.assertEqual(self.store.clear_paths([]), 0)
```

Dans `tests/test_config.py`, ajouter dans `TestConfig` :
```python
    def test_library_folder(self):
        from config import Config
        c = Config()
        self.assertEqual(c.get("library_folder"), "")
        c.set("library_folder", os.path.join(self.tmp, "Mixes"))
        c.save()
        self.assertEqual(Config().get("library_folder"), os.path.join(self.tmp, "Mixes"))
```

- [ ] **Step 2 : lancer les tests pour vérifier qu'ils échouent**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_analysis_store.py"` et `venv/Scripts/python.exe -m unittest discover -s tests -p "test_config.py"`
Expected : `AttributeError: 'AnalysisStore' object has no attribute 'clear_paths'`. `test_library_folder` échoue avec `None != ''`.

- [ ] **Step 3 : implémenter**

Dans `analysis_store.py`, remplacer `from typing import Any, Dict, Optional` par `from typing import Any, Dict, List, Optional`. Après la méthode `clear`, ajouter :
```python
    def clear_paths(self, paths: List[str]) -> int:
        """Forget every result (all kinds) about these files. Returns rows removed."""
        removed = 0
        with self._connect() as conn:
            for path in paths:
                removed += conn.execute("DELETE FROM analyses WHERE path = ?", (os.path.abspath(path),)).rowcount
        return removed
```

Dans `config.py`, remplacer :
```python
    "mixxx_db": "",                # empty = auto-detect
```
par :
```python
    "mixxx_db": "",                # empty = auto-detect
    "library_folder": "",          # every track you mixed, one folder, scanned in place (library.py)
```

- [ ] **Step 4 : lancer les tests**

Run : les deux commandes du Step 2.
Expected : `test_analysis_store.py` donne `Ran 8 tests` OK. `test_config.py` donne `Ran 3 tests` OK.

- [ ] **Step 5 : commit**

```bash
git add analysis_store.py config.py tests/test_analysis_store.py tests/test_config.py
git commit -m "Analysis cache: clear a list of files; config: library folder"
```

---

### Task 4 : `SetProject` v3 (sélection, propositions, migration, reset)

**Files :**
- Modify: `set_project.py`
- Modify: `mixxx_export.py:282-286`, `mastering.py:766`, `mastering.py:810`
- Modify: `tests/test_set_project.py` (2 assertions)
- Create: `tests/test_set_project_selection.py`

**Interfaces :**
- Consumes : rien de nouveau.
- Produces (utilisées par les tâches 9 à 11) :
  - `SetProject.selection -> List[str]`
  - `selection_files() -> List[str]`
  - `add_to_selection(paths) -> int`
  - `remove_from_selection(paths) -> int`
  - `selection_rows() -> List[Dict]` (fiche + `state` parmi `analysed|pending|failed|missing`)
  - `proposal_tracks() -> Tuple[List[Dict], List[str]]`
  - `forget_analysis() -> None`
  - `set_proposals(params: Dict, variants: List[Dict]) -> None`
  - `proposal_variants() -> List[Dict]`
  - `use_proposal(index: int) -> List[str]` (lève `IndexError`)
  - `reset_preview() -> {"outputs": {"files", "bytes"}, "imported": {"files", "bytes"}}`
  - `reset(delete_imported: bool = False) -> {"files_deleted", "bytes_deleted"}`
  - `data["version"] == 3`
  - `create()` ne crée plus `source/`.

- [ ] **Step 1 : écrire les tests qui échouent**

Créer `tests/test_set_project_selection.py` :

```python
import json
import os
import shutil
import tempfile
import unittest

from set_project import SetProject, STEPS


class TestSelectionAndProposals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_v3_")
        self.root = os.path.join(self.tmp, "projects")
        self.lib = os.path.join(self.tmp, "Mixes")
        os.makedirs(self.lib)
        self.a, self.b, self.c = (os.path.join(self.lib, n) for n in ("a.wav", "b.wav", "c.wav"))
        for p in (self.a, self.b, self.c):
            with open(p, "wb") as f:
                f.write(b"\x00" * 10)
        self.p = SetProject.create(self.root, "v3")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _analysed(self, *paths):
        self.p.set_tracks([{"file_path": x, "filename": os.path.basename(x), "duration": 300.0, "bpm": 124.0,
                            "key": "A minor", "energy_level": 5.0} for x in paths])

    def test_new_project_has_no_source_folder(self):
        self.assertFalse(os.path.isdir(self.p.source_dir))
        self.assertTrue(os.path.isdir(self.p.premaster_dir) and os.path.isdir(self.p.exports_dir))
        self.assertEqual(self.p.data["version"], 3)

    def test_add_and_remove_selection(self):
        for key, _, _ in STEPS:
            self.p.mark(key)
        self.assertEqual(self.p.add_to_selection([self.b, self.a, self.b]), 2)
        self.assertEqual(self.p.selection, [self.b, self.a])
        self.assertFalse(self.p.is_done("analyze"))
        self.assertFalse(self.p.is_done("setlist"))
        self.assertEqual(self.p.add_to_selection([self.a]), 0)
        self._analysed(self.a, self.b)
        self.p.set_order([self.a, self.b])
        self.p.data["proposals"] = {"variants": [{}]}
        self.p.mark("analyze")
        self.assertEqual(self.p.remove_from_selection([self.a, "/elsewhere.wav"]), 1)
        self.assertEqual(self.p.selection, [self.b])
        self.assertEqual([t["file_path"] for t in self.p.tracks], [self.b])
        self.assertEqual(self.p.set_list, [self.b])
        self.assertIsNone(self.p.data["proposals"])
        self.assertTrue(self.p.is_done("analyze"))

    def test_selection_states_and_proposal_tracks(self):
        ghost = os.path.join(self.lib, "gone.wav")
        self.p.add_to_selection([self.a, self.b, self.c, ghost])
        self._analysed(self.a)  # b and c exist but are not analysed -> failed
        self.p.add_to_selection([os.path.join(self.lib, "new.wav")])
        with open(os.path.join(self.lib, "new.wav"), "wb") as f:
            f.write(b"\x00")
        states = {os.path.basename(r["file_path"]): r["state"] for r in self.p.selection_rows()}
        self.assertEqual(states, {"a.wav": "analysed", "b.wav": "failed", "c.wav": "failed",
                                  "gone.wav": "missing", "new.wav": "pending"})
        usable, skipped = self.p.proposal_tracks()
        self.assertEqual([t["file_path"] for t in usable], [self.a])
        self.assertNotIn("state", usable[0])
        self.assertEqual(skipped, ["b.wav", "c.wav", "gone.wav", "new.wav"])
        self.assertEqual(self.p.selection_files(), [self.a, self.b, self.c, os.path.join(self.lib, "new.wav")])

    def test_proposals_are_stored_and_used(self):
        self.p.add_to_selection([self.a, self.b, self.c])
        self._analysed(self.a, self.b, self.c)
        self.p.mark("analyze")
        variants = [{"curve": "build", "tracks": [{"file_path": self.b}], "order": [self.b, self.a], "score": 80},
                    {"curve": "wave", "tracks": [], "order": [self.c, self.a, self.b], "score": 70}]
        self.p.set_proposals({"duration_min": 60, "curve": "all"}, variants)
        self.p.save()
        q = SetProject.open(self.p.folder)
        self.assertEqual(len(q.proposal_variants()), 2)
        self.assertNotIn("tracks", q.proposal_variants()[0])
        self.assertEqual(q.data["proposals"]["params"]["curve"], "all")
        q.mark("transitions")
        self.assertEqual(q.use_proposal(1), [self.c, self.a, self.b])
        self.assertTrue(q.is_done("setlist"))
        self.assertEqual(q.step_state("setlist")["details"]["curve"], "wave")
        self.assertFalse(q.is_done("transitions"))
        with self.assertRaises(IndexError):
            q.use_proposal(5)

    def test_forget_analysis(self):
        self.p.add_to_selection([self.a])
        self._analysed(self.a)
        self.p.set_order([self.a])
        self.p.mark("analyze")
        self.p.mark("setlist")
        self.p.data["proposals"] = {"variants": [{}]}
        self.p.forget_analysis()
        self.assertEqual(self.p.tracks, [])
        self.assertIsNone(self.p.data["proposals"])
        self.assertFalse(self.p.is_done("analyze") or self.p.is_done("setlist"))
        self.assertEqual(self.p.selection, [self.a])
        self.assertEqual(self.p.selection_rows()[0]["state"], "pending")


class TestMigrationAndReset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_reset_")
        self.root = os.path.join(self.tmp, "projects")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, path, size):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"\x00" * size)

    def test_version_2_project_is_migrated(self):
        folder = os.path.join(self.root, "old")
        self._write(os.path.join(folder, "source", "x.wav"), 10)
        self._write(os.path.join(folder, "source", "y.mp3"), 10)
        track = {"file_path": os.path.join(folder, "source", "x.wav"), "filename": "x.wav"}
        with open(os.path.join(folder, "project.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 2, "name": "old", "tracks": [track], "set_list": [track["file_path"]],
                       "steps": {"analyze": {"done": True, "at": "2026-09-01T10:00:00", "details": {}}}}, f)
        p = SetProject.open(folder)
        self.assertEqual(p.data["version"], 3)
        self.assertEqual([os.path.basename(x) for x in p.selection], ["x.wav", "y.mp3"])
        self.assertIsNone(p.data["proposals"])
        self.assertEqual(p.set_list, [track["file_path"]])
        self.assertTrue(p.is_done("analyze"))

    def test_reset_keeps_options_and_imported_copies(self):
        p = SetProject.create(self.root, "gig", options={"set_duration": 90})
        p.data["notes"] = "warm-up"
        p.add_to_selection(["/lib/a.wav"])
        p.set_tracks([{"file_path": "/lib/a.wav"}])
        p.set_order(["/lib/a.wav"])
        p.data["transitions"] = {"tracks": []}
        p.data["premaster"] = {"results": []}
        for key, _, _ in STEPS:
            p.mark(key)
        self._write(os.path.join(p.premaster_dir, "a.wav"), 100)
        self._write(os.path.join(p.exports_dir, "charts", "overview.png"), 50)
        self._write(os.path.join(p.exports_dir, "gig.m3u"), 5)
        self._write(os.path.join(p.source_dir, "old.wav"), 1000)
        preview = p.reset_preview()
        self.assertEqual(preview, {"outputs": {"files": 3, "bytes": 155}, "imported": {"files": 1, "bytes": 1000}})
        self.assertEqual(p.reset(), {"files_deleted": 3, "bytes_deleted": 155})
        q = SetProject.open(p.folder)
        self.assertEqual((q.selection, q.tracks, q.set_list), ([], [], []))
        self.assertIsNone(q.data["transitions"])
        self.assertIsNone(q.data["premaster"])
        self.assertTrue(all(not q.is_done(k) for k, _, _ in STEPS))
        self.assertEqual(q.options["set_duration"], 90)
        self.assertEqual((q.name, q.data["notes"]), ("gig", "warm-up"))
        self.assertEqual(os.listdir(q.premaster_dir), [])
        self.assertEqual(os.listdir(q.exports_dir), [])
        self.assertEqual(os.listdir(q.source_dir), ["old.wav"])

    def test_reset_can_delete_imported_copies(self):
        p = SetProject.create(self.root, "gig2")
        self._write(os.path.join(p.source_dir, "old.wav"), 1000)
        p.data["imported"] = [{"original": "/m/old.wav", "path": os.path.join(p.source_dir, "old.wav"), "size": 1000}]
        self.assertEqual(p.reset(delete_imported=True), {"files_deleted": 1, "bytes_deleted": 1000})
        self.assertEqual(os.listdir(p.source_dir), [])
        self.assertEqual(p.data["imported"], [])


if __name__ == "__main__":
    unittest.main()
```

Dans `tests/test_set_project.py`, remplacer :
```python
        self.assertTrue(os.path.isdir(p.source_dir) and os.path.isdir(p.premaster_dir) and os.path.isdir(p.exports_dir))
```
par :
```python
        self.assertTrue(os.path.isdir(p.premaster_dir) and os.path.isdir(p.exports_dir))
        self.assertFalse(os.path.isdir(p.source_dir))  # only created by import_audio (projects before v3)
```
et remplacer :
```python
        self.assertTrue(any("[x] Analyze the tracks" in l and "count=3" in l for l in lines))
```
par :
```python
        self.assertTrue(any("[x] Select and analyze the tracks" in l and "count=3" in l for l in lines))
```

- [ ] **Step 2 : lancer les tests pour vérifier qu'ils échouent**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_set_project*.py"`
Expected : erreurs `AttributeError: 'SetProject' object has no attribute 'add_to_selection'` (et autres). `test_create_layout_and_import` et `test_summary_lines` échouent.

- [ ] **Step 3 : docstring, libellés et indices**

Dans `set_project.py`, remplacer la docstring du module :
```python
"""
Set project: one folder per set, with the audio brought into it.

    <projects root>/<name>/
        project.json     options, tracks, set list, step states, results
        source/          the audio files imported for this set (copies)
        premaster/       corrected copies written by the pre-master pass
        exports/         M3U playlists, transition sheets, JSON, charts

The music folder you started from is never written to. The GUI and the
command-line tools read and update project.json, so you always know where
you are and never redo a step.
"""
```
par :
```python
"""
Set project: one folder per set.

    <projects root>/<name>/
        project.json     selection, tracks, proposals, set list, step states, results
        premaster/       corrected copies written by the pre-master pass
        exports/         M3U playlists, transition sheets, JSON, charts
        source/          (projects created before version 3 only) imported copies

The tracks of a set are picked in the music library (one folder holding every
track, see library.py) and referenced by absolute path: nothing is copied and
the library is never written to. The GUI and the command-line tools read and
update project.json, so you always know where you are and never redo a step.
"""
```

Remplacer `    ("analyze", "Analyze the tracks", True),` par `    ("analyze", "Select and analyze the tracks", True),`.

Remplacer :
```python
    "analyze": "Click 'Analyze' to measure BPM, key and energy of every imported track (cached: only new files take time).",
    "setlist": "Click 'Propose' for an automatic order, then adjust it with Add / Remove / Up / Down in the Tracks tab.",
```
par :
```python
    "analyze": "Pick tracks in the Library, add them to the Selection, then 'Analyze selection' (cached tracks are instant).",
    "setlist": "Click 'Propose', compare the variants, then 'Use this proposal' and adjust the order.",
```

- [ ] **Step 4 : schéma v3, création, dossiers, migration**

Remplacer `            "version": 2,` par `            "version": 3,`.

Remplacer :
```python
            "tracks": [],          # analysed track records (one per source file)
            "set_list": [],        # ordered file paths of the proposal / edited set
```
par :
```python
            "selection": [],       # absolute paths of the tracks picked in the library
            "tracks": [],          # analysed track records (selected files only)
            "failed": [],          # selected files whose analysis failed
            "proposals": None,     # {params, created, variants[]} from set_proposer
            "set_list": [],        # ordered file paths of the chosen proposal / edited set
```

Dans `create`, remplacer :
```python
        for sub in (cls.SOURCE_DIR, cls.PREMASTER_DIR, cls.EXPORTS_DIR):
            os.makedirs(os.path.join(folder, sub), exist_ok=True)
        project.save()
```
par :
```python
        project.ensure_dirs()
        project.save()
```

Remplacer :
```python
    def ensure_dirs(self) -> None:
        for d in (self.source_dir, self.premaster_dir, self.exports_dir):
            os.makedirs(d, exist_ok=True)
```
par :
```python
    def ensure_dirs(self) -> None:
        for d in (self.premaster_dir, self.exports_dir):
            os.makedirs(d, exist_ok=True)
```

Dans `load`, remplacer :
```python
            else:
                self.data[key] = value
        return self
```
par :
```python
            else:
                self.data[key] = value
        self._migrate()
        return self

    def _migrate(self) -> None:
        """Version 2 projects: the imported copies in source/ become the selection."""
        if int(self.data.get("version") or 0) >= 3:
            return
        if not self.data.get("selection"):
            self.data["selection"] = self.source_files()
        self.data["version"] = 3
```

Dans `import_audio`, remplacer :
```python
        Returns counts {'copied', 'skipped', 'failed'}.
        """
        self.ensure_dirs()
```
par :
```python
        Returns counts {'copied', 'skipped', 'failed'}.
        """
        os.makedirs(self.source_dir, exist_ok=True)
```

- [ ] **Step 5 : sélection et propositions**

Remplacer :
```python
    def set_tracks(self, tracks: List[Dict]) -> None:
        self.data["tracks"] = [dict(t) for t in tracks]
        known = {t["file_path"] for t in self.data["tracks"]}
        self.data["set_list"] = [p for p in self.data["set_list"] if p in known]
```
par :
```python
    def set_tracks(self, tracks: List[Dict]) -> None:
        self.data["tracks"] = [dict(t) for t in tracks]
        known = {t["file_path"] for t in self.data["tracks"]}
        self.data["set_list"] = [p for p in self.data["set_list"] if p in known]
        self.data["failed"] = [p for p in self.selection_files() if p not in known]

    # ------------------------------------------------------------- selection (picked in the library)
    @property
    def selection(self) -> List[str]:
        return self.data["selection"]

    def selection_files(self) -> List[str]:
        """Selected files that exist on disk (what gets analysed)."""
        return [p for p in self.data["selection"] if os.path.isfile(p)]

    def add_to_selection(self, paths: List[str]) -> int:
        """Append new paths (in the given order). Returns how many were added."""
        added = 0
        for p in paths:
            if p not in self.data["selection"]:
                self.data["selection"].append(p)
                added += 1
        if added:
            self.data["proposals"] = None
            self.mark("analyze", done=False)
            self.invalidate_from("analyze")
        return added

    def remove_from_selection(self, paths: List[str]) -> int:
        """Drop paths from the selection, the analysed tracks and the set list."""
        gone = set(paths) & set(self.data["selection"])
        if not gone:
            return 0
        self.data["selection"] = [p for p in self.data["selection"] if p not in gone]
        self.data["tracks"] = [t for t in self.data["tracks"] if t["file_path"] not in gone]
        self.data["failed"] = [p for p in self.data.get("failed", []) if p not in gone]
        self.data["set_list"] = [p for p in self.data["set_list"] if p not in gone]
        self.data["proposals"] = None
        self.invalidate_from("analyze")
        return len(gone)

    def selection_rows(self) -> List[Dict]:
        """One row per selected file: its analysed record when there is one, plus a 'state'."""
        by_path = {t["file_path"]: t for t in self.data["tracks"]}
        failed = set(self.data.get("failed") or [])
        rows = []
        for p in self.data["selection"]:
            row = dict(by_path[p]) if p in by_path else {"file_path": p, "filename": os.path.basename(p)}
            if not os.path.isfile(p):
                row["state"] = "missing"
            elif p in by_path:
                row["state"] = "analysed"
            elif p in failed:
                row["state"] = "failed"
            else:
                row["state"] = "pending"
            rows.append(row)
        return rows

    def proposal_tracks(self) -> Tuple[List[Dict], List[str]]:
        """(analysed selected tracks whose file exists, file names of the selected tracks left out)."""
        usable, skipped = [], []
        for row in self.selection_rows():
            if row["state"] == "analysed":
                usable.append({k: v for k, v in row.items() if k != "state"})
            else:
                skipped.append(row["filename"])
        return usable, skipped

    def forget_analysis(self) -> None:
        """After clearing the analysis cache: the selection must be analysed again."""
        self.data["tracks"] = []
        self.data["failed"] = []
        self.data["proposals"] = None
        self.mark("analyze", done=False)
        self.invalidate_from("analyze")

    # ------------------------------------------------------------- proposals
    def set_proposals(self, params: Dict, variants: List[Dict]) -> None:
        """Keep the variants returned by set_proposer.propose (without their track records)."""
        self.data["proposals"] = {
            "params": dict(params),
            "created": _now(),
            "variants": [{k: v for k, v in variant.items() if k != "tracks"} for variant in variants],
        }

    def proposal_variants(self) -> List[Dict]:
        return (self.data.get("proposals") or {}).get("variants") or []

    def use_proposal(self, index: int) -> List[str]:
        """Copy a proposal into the set list (later steps are invalidated). Returns the set list."""
        variants = self.proposal_variants()
        if not 0 <= index < len(variants):
            raise IndexError(f"No proposal #{index + 1}")
        variant = variants[index]
        self.set_order(variant["order"])
        self.mark("setlist", count=len(self.data["set_list"]), curve=variant["curve"], score=variant["score"])
        return self.data["set_list"]
```

- [ ] **Step 6 : reset et résumé**

Remplacer :
```python
    # ------------------------------------------------------------- steps
    def mark(
```
par :
```python
    # ------------------------------------------------------------- reset
    @staticmethod
    def _files_under(path: str) -> List[str]:
        if os.path.isfile(path):
            return [path]
        found = []
        for root, _dirs, names in os.walk(path):
            found.extend(os.path.join(root, n) for n in names)
        return found

    def _count(self, folders: List[str]) -> Dict[str, int]:
        files = [f for d in folders if os.path.isdir(d) for f in self._files_under(d)]
        return {"files": len(files), "bytes": sum(os.path.getsize(f) for f in files)}

    def reset_preview(self) -> Dict[str, Dict[str, int]]:
        """What reset() would delete: {'outputs': premaster/ + exports/, 'imported': source/}."""
        return {"outputs": self._count([self.premaster_dir, self.exports_dir]),
                "imported": self._count([self.source_dir])}

    def reset(self, delete_imported: bool = False) -> Dict[str, int]:
        """
        Start the set again from an empty selection. Keeps the name, options, notes
        and the analysis cache; empties premaster/ and exports/ (and source/ when
        delete_imported). Returns {'files_deleted', 'bytes_deleted'}.
        """
        folders = [self.premaster_dir, self.exports_dir] + ([self.source_dir] if delete_imported else [])
        result = {"files_deleted": 0, "bytes_deleted": 0}
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                files = self._files_under(path)
                size = sum(os.path.getsize(f) for f in files)
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                result["files_deleted"] += len(files)
                result["bytes_deleted"] += size
        self.data.update(selection=[], tracks=[], failed=[], proposals=None, set_list=[],
                         transitions=None, premaster=None)
        if delete_imported:
            self.data["imported"] = []
        for key, _, _ in STEPS:
            self.mark(key, done=False)
        self.save()
        return result

    # ------------------------------------------------------------- steps
    def mark(
```

Dans `summary_lines`, remplacer :
```python
                 f"Imported files: {len(self.data['imported'])} | analysed: {len(self.tracks)} | in set list: {len(self.data['set_list'])}"]
```
par :
```python
                 f"Selected: {len(self.data['selection'])} | analysed: {len(self.tracks)} | failed: {len(self.data.get('failed') or [])}"
                 f" | proposals: {len(self.proposal_variants())} | in set list: {len(self.data['set_list'])}"]
```

- [ ] **Step 7 : CLI sur la sélection**

Dans `mixxx_export.py`, remplacer :
```python
        files = project.source_files()
        if not files:
            print(f"No audio in {project.source_dir}: import files into the project first.")
            sys.exit(1)
        manager = PlaylistManager(project.source_dir)
```
par :
```python
        files = project.selection_files()
        if not files:
            print(f"No selected tracks in project '{project.name}': pick them in the GUI's Set Builder (Library -> Selection) first.")
            sys.exit(1)
        manager = PlaylistManager(project.folder)
```

Dans `mastering.py`, remplacer :
```python
                files.extend([t['file_path'] for t in tracks] or project.source_files())
```
par :
```python
                files.extend([t['file_path'] for t in tracks] or project.selection_files())
```
et :
```python
            files = [t['file_path'] for t in tracks] or project.source_files()
```
par :
```python
            files = [t['file_path'] for t in tracks] or project.selection_files()
```

- [ ] **Step 8 : lancer les tests**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_set_project*.py" -v` puis `venv/Scripts/python.exe -c "import mixxx_export, mastering; print('ok')"`
Expected : `Ran 13 tests` OK, puis `ok`.

- [ ] **Step 9 : commit**

```bash
git add set_project.py mixxx_export.py mastering.py tests/test_set_project.py tests/test_set_project_selection.py
git commit -m "Set project v3: selection, proposals, v2 migration, reset"
```

---

### Task 5 : module `library.py`

**Files :**
- Create: `library.py`
- Test: `tests/test_library.py`

**Interfaces :**
- Consumes : `analysis_store.get_store()`, `set_project.audio_files_in(folder, recursive=True)`.
- Produces :
  - `scan(folder, progress=None, use_cache=True) -> List[Dict]`. Chaque entrée contient `file_path` (abspath), `filename`, `duration` (float|None), `bpm`, `key`, `energy_level` (None si non analysé) et `analysed` (bool). Lève `FileNotFoundError` si le dossier est vide ou absent.
  - `read_duration(path) -> Optional[float]`
  - `library_entry(path, store=None) -> Dict`
  - `filter_entries(entries, text) -> List[Dict]`

- [ ] **Step 1 : écrire le test qui échoue**

Créer `tests/test_library.py` :

```python
import os
import shutil
import tempfile
import unittest

import numpy as np
import soundfile as sf

import analysis_store


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_lib_")
        os.environ["DYNAMIX_HOME"] = os.path.join(self.tmp, "home")
        analysis_store.reset_store()
        self.lib = os.path.join(self.tmp, "Mixes")
        os.makedirs(os.path.join(self.lib, "2025"))
        sr = 8000
        self.one = os.path.join(self.lib, "b one second.wav")
        self.two = os.path.join(self.lib, "2025", "a two seconds.wav")
        sf.write(self.one, np.zeros(sr, dtype="float32"), sr)
        sf.write(self.two, np.zeros(2 * sr, dtype="float32"), sr)
        with open(os.path.join(self.lib, "notes.txt"), "w") as f:
            f.write("not audio")
        self.broken = os.path.join(self.lib, "c broken.wav")
        with open(self.broken, "wb") as f:
            f.write(b"not a wav file")

    def tearDown(self):
        os.environ.pop("DYNAMIX_HOME", None)
        analysis_store.reset_store()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_read_duration(self):
        from library import read_duration
        self.assertAlmostEqual(read_duration(self.one), 1.0)
        self.assertIsNone(read_duration(self.broken))

    def test_scan_reads_durations_and_merges_the_cache(self):
        from library import scan
        analysis_store.get_store().put(self.two, "features",
                                       {"duration": 99.0, "bpm": 128.0, "key": "A minor", "energy_level": 7.0})
        seen = []
        entries = scan(self.lib, progress=lambda i, n, name: seen.append((i, n)))
        self.assertEqual([e["filename"] for e in entries], ["a two seconds.wav", "b one second.wav", "c broken.wav"])
        self.assertEqual(seen[-1], (3, 3))
        cached, plain, broken = entries
        self.assertEqual((cached["analysed"], cached["duration"], cached["bpm"], cached["key"], cached["energy_level"]),
                         (True, 99.0, 128.0, "A minor", 7.0))
        self.assertEqual((plain["analysed"], plain["bpm"]), (False, None))
        self.assertAlmostEqual(plain["duration"], 1.0)
        self.assertIsNone(broken["duration"])
        self.assertEqual(plain["file_path"], os.path.abspath(self.one))

    def test_missing_folder(self):
        from library import scan
        with self.assertRaises(FileNotFoundError):
            scan(os.path.join(self.tmp, "nowhere"))
        with self.assertRaises(FileNotFoundError):
            scan("")

    def test_filter_entries(self):
        from library import filter_entries
        entries = [{"filename": "Deep House Mix.wav"}, {"filename": "techno.flac"}]
        self.assertEqual(filter_entries(entries, "HOUSE"), [entries[0]])
        self.assertEqual(filter_entries(entries, "  "), entries)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2 : lancer le test pour vérifier qu'il échoue**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_library.py" -v`
Expected : ERROR `ModuleNotFoundError: No module named 'library'`

- [ ] **Step 3 : écrire l'implémentation**

Créer `library.py` :

```python
#!/usr/bin/env python3
"""
The music library: every track the user mixed, kept in one folder.

The folder is scanned in place (nothing is copied). Durations come from the
file headers; BPM, key and energy come from the analysis cache when the track
was already analysed, so a scan never decodes audio.
"""

import logging
import os
from typing import Callable, Dict, List, Optional

from analysis_store import get_store
from set_project import audio_files_in

log = logging.getLogger("dynamix.library")


def read_duration(path: str) -> Optional[float]:
    """Duration in seconds from the file header, None when the file cannot be read."""
    try:
        import soundfile as sf
        return float(sf.info(path).duration)
    except Exception:
        return None


def library_entry(path: str, store=None) -> Dict:
    """One row of the library table."""
    features = None
    if store is not None:
        try:
            features = store.get(path, "features")
        except Exception:
            features = None
    entry = {
        "file_path": os.path.abspath(path),
        "filename": os.path.basename(path),
        "duration": None,
        "bpm": None,
        "key": None,
        "energy_level": None,
        "analysed": features is not None,
    }
    if features:
        entry["duration"] = float(features.get("duration") or 0) or None
        entry["bpm"] = float(features.get("bpm") or 0) or None
        entry["key"] = features.get("key") or None
        entry["energy_level"] = float(features.get("energy_level") or 0) or None
    if entry["duration"] is None:
        entry["duration"] = read_duration(path)
    return entry


def scan(folder: str, progress: Optional[Callable[[int, int, str], None]] = None,
         use_cache: bool = True) -> List[Dict]:
    """All audio files under folder (recursive), sorted by file name."""
    if not folder or not os.path.isdir(folder):
        raise FileNotFoundError(f"Library folder not found: {folder or '(not set)'}")
    files = audio_files_in(folder, recursive=True)
    store = get_store() if use_cache else None
    entries = []
    for i, path in enumerate(files, 1):
        entries.append(library_entry(path, store))
        if progress:
            progress(i, len(files), os.path.basename(path))
    minutes = sum(e["duration"] or 0 for e in entries) / 60
    log.info("Library scanned: %d files (%d analysed, %.0f min) in %s",
             len(entries), sum(1 for e in entries if e["analysed"]), minutes, folder)
    return entries


def filter_entries(entries: List[Dict], text: str) -> List[Dict]:
    """Entries whose file name contains text (case-insensitive)."""
    needle = (text or "").strip().lower()
    if not needle:
        return list(entries)
    return [e for e in entries if needle in e["filename"].lower()]
```

- [ ] **Step 4 : lancer le test pour vérifier qu'il passe**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_library.py" -v`
Expected : `Ran 4 tests` … `OK`

- [ ] **Step 5 : commit**

```bash
git add library.py tests/test_library.py
git commit -m "Library: scan the music folder in place (headers and cache only)"
```

---

### Task 6 : module `app_log.py`

**Files :**
- Create: `app_log.py`
- Test: `tests/test_app_log.py`

**Interfaces :**
- Produces :
  - `install(log_dir: str, max_lines: int = 5000) -> LogBuffer` (idempotent) et `uninstall() -> None`
  - `class LogBuffer(logging.Handler)` avec `records(min_level=logging.DEBUG) -> List[LogRecord]`, `drain() -> List[LogRecord]` et `clear()`
  - `format_record(record) -> str` (`HH:MM:SS LEVEL message` + trace)
  - `log_exception(exc_type, exc_value, exc_traceback, where="Unhandled error") -> None`
  - `log_dir() -> str`
  - `LOGGER_NAME = "dynamix"`
  - Fichier : `<log_dir>/dynamix.log`

- [ ] **Step 1 : écrire le test qui échoue**

Créer `tests/test_app_log.py` :

```python
import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest

import app_log


class TestAppLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dynamix_log_")
        self.stdout, self.stderr = sys.stdout, sys.stderr
        self.buffer = app_log.install(os.path.join(self.tmp, "logs"), max_lines=50)

    def tearDown(self):
        app_log.uninstall()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_uninstall_restores_streams(self):
        app_log.uninstall()
        self.assertIs(sys.stdout, self.stdout)
        self.assertIs(sys.stderr, self.stderr)
        self.buffer = app_log.install(os.path.join(self.tmp, "logs"))

    def test_logger_messages_are_kept_and_drained(self):
        logging.getLogger("dynamix.test").warning("careful %d", 3)
        records = self.buffer.drain()
        self.assertEqual([(r.levelno, r.getMessage()) for r in records], [(logging.WARNING, "careful 3")])
        self.assertEqual(self.buffer.drain(), [])
        self.assertEqual(len(self.buffer.records()), 1)
        self.buffer.clear()
        self.assertEqual(self.buffer.records(), [])

    def test_buffer_is_bounded(self):
        log = logging.getLogger("dynamix.test")
        for i in range(80):
            log.info("line %d", i)
        records = self.buffer.records()
        self.assertEqual(len(records), 50)
        self.assertEqual(records[-1].getMessage(), "line 79")

    def test_print_and_stderr_are_captured(self):
        print("hello from print")
        sys.stderr.write("broken thing\npartial")
        messages = [(r.levelno, r.getMessage()) for r in self.buffer.drain()]
        self.assertIn((logging.INFO, "hello from print"), messages)
        self.assertIn((logging.ERROR, "broken thing"), messages)
        self.assertNotIn((logging.ERROR, "partial"), messages)  # no newline yet

    def test_thread_exception_is_logged_with_traceback(self):
        def boom():
            raise ZeroDivisionError("nope")
        t = threading.Thread(target=boom, name="worker-1")
        t.start()
        t.join()
        errors = self.buffer.records(logging.ERROR)
        self.assertEqual(len(errors), 1)
        text = app_log.format_record(errors[0])
        self.assertIn("Error in thread worker-1: nope", text)
        self.assertIn("Traceback", text)
        self.assertIn("ZeroDivisionError", text)

    def test_python_warnings_are_warnings(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            warnings.warn("old api", DeprecationWarning)
        records = self.buffer.drain()
        self.assertTrue(any(r.levelno == logging.WARNING and "old api" in r.getMessage() for r in records))
        self.assertEqual(self.buffer.records(logging.ERROR), [])

    def test_file_is_written(self):
        logging.getLogger("dynamix.test").error("to the file")
        app_log._STATE["file_handler"].flush()
        with open(os.path.join(self.tmp, "logs", "dynamix.log"), encoding="utf-8") as f:
            self.assertIn("to the file", f.read())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2 : lancer le test pour vérifier qu'il échoue**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_app_log.py" -v`
Expected : ERROR `ModuleNotFoundError: No module named 'app_log'`

- [ ] **Step 3 : écrire l'implémentation**

Créer `app_log.py` :

```python
#!/usr/bin/env python3
"""
Application log for DynaMix: what the GUI's Log tab shows.

The GUI runs under pythonw.exe on Windows, which has no console: without this
module every print() and every error raised in a worker thread is lost.
install() routes them all to the "dynamix" logger, which keeps the last lines
in memory (LogBuffer, read by the Log tab) and writes a rotating file under
<DynaMix home>/logs/.
"""

import collections
import datetime as _dt
import logging
import logging.handlers
import os
import sys
import threading
from typing import Dict, List

LOGGER_NAME = "dynamix"
LOG_FILENAME = "dynamix.log"
_STATE: Dict = {}


class LogBuffer(logging.Handler):
    """Keeps the most recent records; drain() hands the new ones to the GUI."""

    def __init__(self, max_lines: int = 5000):
        super().__init__(level=logging.DEBUG)
        self._records = collections.deque(maxlen=max_lines)
        self._pending = collections.deque(maxlen=max_lines)
        self._guard = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        with self._guard:
            self._records.append(record)
            self._pending.append(record)

    def records(self, min_level: int = logging.DEBUG) -> List[logging.LogRecord]:
        with self._guard:
            return [r for r in self._records if r.levelno >= min_level]

    def drain(self) -> List[logging.LogRecord]:
        with self._guard:
            out = list(self._pending)
            self._pending.clear()
        return out

    def clear(self) -> None:
        with self._guard:
            self._records.clear()
            self._pending.clear()


def format_record(record: logging.LogRecord) -> str:
    """'HH:MM:SS LEVEL message' plus the traceback when there is one."""
    when = _dt.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
    text = f"{when} {record.levelname:<7} {record.getMessage()}"
    if record.exc_text:
        text += "\n" + record.exc_text
    return text


class _StreamToLog:
    """File-like object: complete lines go to a logger, text also to the original stream."""

    def __init__(self, logger: logging.Logger, level: int, original):
        self.logger = logger
        self.level = level
        self.original = original
        self._pending = ""
        self._guard = threading.Lock()
        self._local = threading.local()

    def write(self, text: str) -> int:
        if self.original is not None:
            try:
                self.original.write(text)
            except Exception:
                pass
        if getattr(self._local, "busy", False):
            return len(text)  # a handler is itself writing to this stream: do not loop
        self._local.busy = True
        try:
            with self._guard:
                self._pending += text
                lines = self._pending.split("\n")
                self._pending = lines.pop()
            for line in lines:
                if line.strip():
                    self.logger.log(self.level, line.rstrip())
        finally:
            self._local.busy = False
        return len(text)

    def flush(self) -> None:
        if self.original is not None:
            try:
                self.original.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False


def log_exception(exc_type, exc_value, exc_traceback, where: str = "Unhandled error") -> None:
    logging.getLogger(LOGGER_NAME).error("%s: %s", where, exc_value, exc_info=(exc_type, exc_value, exc_traceback))


def _sys_excepthook(exc_type, exc_value, exc_traceback) -> None:
    log_exception(exc_type, exc_value, exc_traceback)


def _thread_excepthook(args) -> None:
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread is not None else "?"
    log_exception(args.exc_type, args.exc_value, args.exc_traceback, f"Error in thread {name}")


def install(log_dir: str, max_lines: int = 5000) -> LogBuffer:
    """Route logging, stdout, stderr, warnings and uncaught exceptions to the buffer and the log file."""
    if _STATE:
        return _STATE["buffer"]
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    buffer = LogBuffer(max_lines)
    os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, LOG_FILENAME), maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(buffer)
    logger.addHandler(file_handler)
    warnings_logger = logging.getLogger("py.warnings")  # warnings.warn(...) -> WARNING, not stderr
    warnings_logger.propagate = False
    warnings_logger.addHandler(buffer)
    warnings_logger.addHandler(file_handler)
    logging.captureWarnings(True)
    _STATE.update(buffer=buffer, file_handler=file_handler, log_dir=log_dir,
                  stdout=sys.stdout, stderr=sys.stderr,
                  excepthook=sys.excepthook, threading_excepthook=threading.excepthook)
    sys.stdout = _StreamToLog(logging.getLogger(LOGGER_NAME + ".stdout"), logging.INFO, _STATE["stdout"])
    sys.stderr = _StreamToLog(logging.getLogger(LOGGER_NAME + ".stderr"), logging.ERROR, _STATE["stderr"])
    sys.excepthook = _sys_excepthook
    threading.excepthook = _thread_excepthook
    return buffer


def uninstall() -> None:
    """Restore the streams and hooks and detach the handlers (tests)."""
    if not _STATE:
        return
    sys.stdout = _STATE["stdout"]
    sys.stderr = _STATE["stderr"]
    sys.excepthook = _STATE["excepthook"]
    threading.excepthook = _STATE["threading_excepthook"]
    logging.captureWarnings(False)
    logger = logging.getLogger(LOGGER_NAME)
    warnings_logger = logging.getLogger("py.warnings")
    for handler in (_STATE["buffer"], _STATE["file_handler"]):
        logger.removeHandler(handler)
        warnings_logger.removeHandler(handler)
        handler.close()
    warnings_logger.propagate = True
    _STATE.clear()


def log_dir() -> str:
    """Folder of the log files (valid after install)."""
    return _STATE.get("log_dir", "")
```

- [ ] **Step 4 : lancer le test pour vérifier qu'il passe**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_app_log.py" -v`
Expected : `Ran 7 tests` … `OK`

- [ ] **Step 5 : commit**

```bash
git add app_log.py tests/test_app_log.py
git commit -m "App log: capture logging, print, stderr, warnings and thread errors"
```

---

### Task 7 : onglet Log, installation du journal et erreurs journalisées

**Files :**
- Create: `log_tab.py`
- Create: `tests/gui_smoke.py`
- Modify: `gui.py` (imports l.7-24, classe l.27, `__init__` l.30-57, `main` l.685-689)
- Modify: `set_builder.py` (imports l.11, après `MUTED` l.28, après `_require_project` l.332-336, 6 gestionnaires d'erreur)

**Interfaces :**
- Consumes : `app_log.install`, `app_log.format_record`, `app_log.log_exception`, `app_log.log_dir`, `LogBuffer.records/drain/clear` (Task 6).
- Produces :
  - `DynaMixGUI(root, log_buffer=None)` et `LogTabMixin.create_log_tab()`
  - attributs `self.log_buffer`, `self.log_frame`, `self.log_text`
  - `SetBuilderMixin._report_error(message: str, exc: Optional[BaseException] = None)` (utilisable depuis un thread)
  - `log = logging.getLogger("dynamix.gui")` au niveau module dans `set_builder.py`
  - `tests/gui_smoke.py` avec la ligne marqueur `    # --- checks added by later tasks go above this line ---`

- [ ] **Step 1 : écrire la vérification GUI qui échoue**

Créer `tests/gui_smoke.py` :

```python
#!/usr/bin/env python3
"""
GUI smoke check (needs a display; not collected by the unit test runs):
builds the whole DynaMix window against a throwaway DynaMix home, drives the
Set Builder, and fails when an assertion fails or anything is logged as ERROR.

    venv/Scripts/python.exe tests/gui_smoke.py
"""
import json
import logging
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
HOME = tempfile.mkdtemp(prefix="dynamix_gui_")
os.environ["DYNAMIX_HOME"] = HOME

import numpy as np
import soundfile as sf

LIBRARY = os.path.join(HOME, "Mixes")
os.makedirs(os.path.join(LIBRARY, "2025"))
for name, seconds in (("one.wav", 2), (os.path.join("2025", "two.wav"), 3)):
    sf.write(os.path.join(LIBRARY, name), np.zeros(8000 * seconds, dtype="float32"), 8000)
with open(os.path.join(HOME, "config.json"), "w", encoding="utf-8") as f:
    json.dump({"projects_root": os.path.join(HOME, "projects"), "library_folder": LIBRARY}, f)

import tkinter as tk
from tkinter import messagebox

import app_log

messagebox.showinfo = lambda *a, **k: print("info:", a)
messagebox.showwarning = lambda *a, **k: print("warning:", a)
messagebox.showerror = lambda *a, **k: print("error dialog:", a)
messagebox.askyesno = lambda *a, **k: True

buffer = app_log.install(os.path.join(HOME, "logs"))
import gui
from set_project import SetProject


def pump(until=lambda: False, seconds=10.0):
    """Run the Tk loop until until() is true or the time is up; returns until()."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        root.update()
        if until():
            return True
        time.sleep(0.05)
    return until()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


root = tk.Tk()
root.withdraw()
root.report_callback_exception = lambda t, e, tb: app_log.log_exception(t, e, tb, "Error in the interface")
errors = []
try:
    app = gui.DynaMixGUI(root, log_buffer=buffer)
    project = SetProject.create(app.config.projects_root, "smoke")
    app.load_project(project.folder)
    pump(seconds=0.5)

    logging.getLogger("dynamix.smoke").warning("smoke warning")
    check(pump(lambda: app.notebook.tab(app.log_frame, "text").startswith("Log ("), 2.0),
          "the Log tab title counts new warnings")
    app.notebook.select(app.log_frame)
    check(pump(lambda: app.notebook.tab(app.log_frame, "text") == "Log", 2.0), "opening the Log tab resets the counter")
    check("smoke warning" in app.log_text.get("1.0", tk.END), "the Log tab shows the records")
    app.notebook.select(0)

    # --- checks added by later tasks go above this line ---
finally:
    errors = buffer.records(logging.ERROR)
    try:
        root.destroy()
    except tk.TclError:
        pass
    app_log.uninstall()
    shutil.rmtree(HOME, ignore_errors=True)
for record in errors:
    print(app_log.format_record(record))
if errors:
    sys.exit(1)
print("GUI smoke OK")
```

- [ ] **Step 2 : lancer la vérification pour voir qu'elle échoue**

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `TypeError: __init__() got an unexpected keyword argument 'log_buffer'`

- [ ] **Step 3 : créer `log_tab.py`**

```python
#!/usr/bin/env python3
"""
Log tab of the DynaMix GUI (mixin for DynaMixGUI): what DynaMix printed and
every error with its traceback, as captured by app_log.
"""

import logging
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

import app_log

LEVELS = {"All": logging.DEBUG, "Warnings and errors": logging.WARNING, "Errors": logging.ERROR}


class LogTabMixin:
    """The Log tab: live application log, level filter, copy / clear / open folder."""

    def create_log_tab(self):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Log")
        self.log_frame = frame
        self._log_unseen = 0
        self._log_title = "Log"
        bar = ttk.Frame(frame)
        bar.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(bar, text="Show:").pack(side=tk.LEFT)
        self.log_level_var = tk.StringVar(value="All")
        combo = ttk.Combobox(bar, textvariable=self.log_level_var, values=list(LEVELS), width=20, state="readonly")
        combo.pack(side=tk.LEFT, padx=4)
        combo.bind("<<ComboboxSelected>>", lambda e: self._log_rebuild())
        ttk.Button(bar, text="Copy", command=self._log_copy).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Clear view", command=self._log_clear).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Open log folder", command=self._log_open_folder).pack(side=tk.LEFT, padx=4)
        body = ttk.Frame(frame)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(body, wrap=tk.NONE, font=("Consolas", 9), state=tk.DISABLED)
        vsb = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.log_text.yview)
        hsb = ttk.Scrollbar(body, orient=tk.HORIZONTAL, command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_text.tag_configure("WARNING", foreground="#b25e00")
        self.log_text.tag_configure("ERROR", foreground="#c0262d")
        self.notebook.bind("<<NotebookTabChanged>>", lambda e: self._log_tab_changed(), add="+")
        if self.log_buffer is None:
            self._log_append("Log capture is not installed (start DynaMix with gui.py to see the application log).",
                             logging.WARNING)
            return
        self._log_rebuild()
        self.root.after(200, self._poll_log)

    def _log_min_level(self):
        return LEVELS.get(self.log_level_var.get(), logging.DEBUG)

    def _log_append(self, text, levelno):
        at_bottom = self.log_text.yview()[1] >= 0.999
        tag = "ERROR" if levelno >= logging.ERROR else ("WARNING" if levelno >= logging.WARNING else None)
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + "\n", (tag,) if tag else ())
        self.log_text.configure(state=tk.DISABLED)
        if at_bottom:
            self.log_text.see(tk.END)

    def _log_rebuild(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        if self.log_buffer is None:
            return
        self.log_buffer.drain()
        for record in self.log_buffer.records(self._log_min_level()):
            self._log_append(app_log.format_record(record), record.levelno)
        self.log_text.see(tk.END)

    def _poll_log(self):
        try:
            visible = self._log_tab_visible()
            for record in self.log_buffer.drain():
                if record.levelno >= self._log_min_level():
                    self._log_append(app_log.format_record(record), record.levelno)
                if record.levelno >= logging.WARNING and not visible:
                    self._log_unseen += 1
            self._log_update_title()
        finally:
            self.root.after(200, self._poll_log)

    def _log_tab_visible(self):
        try:
            return self.notebook.select() == str(self.log_frame)
        except tk.TclError:
            return False

    def _log_update_title(self):
        title = f"Log ({self._log_unseen} ⚠)" if self._log_unseen else "Log"
        if title != self._log_title:
            self._log_title = title
            self.notebook.tab(self.log_frame, text=title)

    def _log_tab_changed(self):
        if self._log_tab_visible() and self._log_unseen:
            self._log_unseen = 0
            self._log_update_title()

    def _log_copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", tk.END))
        self.update_status("Log copied to the clipboard")

    def _log_clear(self):
        if self.log_buffer is not None:
            self.log_buffer.clear()
        self._log_rebuild()

    def _log_open_folder(self):
        folder = app_log.log_dir()
        if not folder:
            return
        if sys.platform.startswith("win"):
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
```

- [ ] **Step 4 : brancher `gui.py`**

Remplacer `import tkinter as tk` (ligne 7) par :
```python
import logging
import tkinter as tk
```
Remplacer `from config import Config` par :
```python
from config import Config
from log_tab import LogTabMixin
```
Remplacer `class DynaMixGUI(SetBuilderMixin, ConfigTabMixin):` par `class DynaMixGUI(SetBuilderMixin, ConfigTabMixin, LogTabMixin):`.

Remplacer :
```python
    def __init__(self, root):
```
par :
```python
    def __init__(self, root, log_buffer=None):
```
Remplacer :
```python
        self.config = Config()
```
par :
```python
        self.config = Config()
        self.log_buffer = log_buffer  # app_log.LogBuffer shown by the Log tab (None: not captured)
```
Remplacer :
```python
        self.create_config_tab()
```
par :
```python
        self.create_config_tab()
        self.create_log_tab()
```
Remplacer `main` :
```python
def main():
    """Main entry point for GUI"""
    root = tk.Tk()
    app = DynaMixGUI(root)
    root.mainloop()
```
par :
```python
def main():
    """Main entry point for GUI"""
    import app_log
    from analysis_store import dynamix_home
    log_buffer = app_log.install(os.path.join(dynamix_home(), "logs"))
    root = tk.Tk()
    root.report_callback_exception = lambda exc_type, exc, tb: app_log.log_exception(exc_type, exc, tb, "Error in the interface")
    app = DynaMixGUI(root, log_buffer=log_buffer)
    logging.getLogger("dynamix.gui").info("DynaMix started")
    root.mainloop()
```

- [ ] **Step 5 : journaliser les erreurs du Set Builder**

Dans `set_builder.py`, remplacer `import os` (ligne 11) par :
```python
import logging
import os
```
Remplacer `MUTED = "#52514e"` par :
```python
MUTED = "#52514e"
log = logging.getLogger("dynamix.gui")
```
Remplacer :
```python
    def _require_project(self):
        if self.project is None:
            messagebox.showinfo("Project", "Create or open a project first ('New project...')")
            return False
        return True
```
par :
```python
    def _require_project(self):
        if self.project is None:
            messagebox.showinfo("Project", "Create or open a project first ('New project...')")
            return False
        return True
    
    def _report_error(self, message, exc=None):
        """Log an error (with its traceback) and show it; safe to call from a worker thread."""
        log.error(message, exc_info=exc)
        self.root.after(0, messagebox.showerror, "Error", message)
```
Puis faire ces six remplacements exacts :
1. `self.root.after(0, messagebox.showerror, "Error", f"Analysis failed: {str(e)}")` → `self._report_error(f"Analysis failed: {e}", e)`
2. `messagebox.showerror("Error", f"Set list creation failed: {str(e)}")` → `self._report_error(f"Set list creation failed: {e}", e)`
3. `self.root.after(0, messagebox.showerror, "Error", f"Transition planning failed: {str(e)}")` → `self._report_error(f"Transition planning failed: {e}", e)`
4. `self.root.after(0, messagebox.showerror, "Error", f"Mastering check failed: {str(e)}")` → `self._report_error(f"Mastering check failed: {e}", e)`
5. `self.root.after(0, messagebox.showerror, "Error", f"Band analysis failed: {str(e)}")` → `self._report_error(f"Band analysis failed: {e}", e)`
6. `self.root.after(0, messagebox.showerror, "Error", f"Pre-master failed: {str(e)}")` → `self._report_error(f"Pre-master failed: {e}", e)`

- [ ] **Step 6 : lancer la vérification GUI et les tests**

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : dernière ligne `GUI smoke OK`. S'il échoue **uniquement** à cause d'enregistrements ERROR venant d'une bibliothèque tierce qui écrit sur stderr (sans lien avec DynaMix), noter le texte exact dans le rapport de tâche et ne pas masquer le problème.

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected : `Ran 98 tests` et `FAILED (failures=2, errors=11)`. Ce sont uniquement les échecs préexistants listés dans les Global Constraints.

- [ ] **Step 7 : commit**

```bash
git add log_tab.py gui.py set_builder.py tests/gui_smoke.py
git commit -m "Log tab: application log with level filter; Set Builder errors are logged with tracebacks"
```

---

### Task 8 : onglet Configuration — dossier bibliothèque et vidage complet du cache

**Files :**
- Modify: `set_builder.py` (`ConfigTabMixin` : `create_config_tab`, `save_config`, `refresh_environment`)
- Modify: `tests/gui_smoke.py`

**Interfaces :**
- Consumes : `Config.get("library_folder")` (Task 3), `AnalysisStore.stats()/clear()`, `log` (Task 7).
- Produces :
  - `self.cfg_library_var`
  - `ConfigTabMixin.clear_whole_cache()`
  - `save_config` appelle `self.rescan_library()` s'il existe (Task 9)
  - `clear_whole_cache` appelle `self._after_cache_cleared()` s'il existe (Task 11)

- [ ] **Step 1 : ajouter la vérification GUI (échec attendu)**

Dans `tests/gui_smoke.py`, remplacer :
```python
    # --- checks added by later tasks go above this line ---
```
par :
```python
    check(app.cfg_library_var.get() == LIBRARY, "the Configuration tab shows the library folder")

    # --- checks added by later tasks go above this line ---
```

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `AttributeError: 'DynaMixGUI' object has no attribute 'cfg_library_var'`

- [ ] **Step 2 : implémenter**

Remplacer :
```python
        ttk.Label(grid, text="Each set is a subfolder: project.json, source/, premaster/, exports/", foreground=MUTED).grid(row=1, column=1, sticky="w", padx=4)
```
par :
```python
        ttk.Label(grid, text="Each set is a subfolder: project.json, premaster/, exports/", foreground=MUTED).grid(row=1, column=1, sticky="w", padx=4)
```

Remplacer :
```python
        ttk.Label(grid, text=dynamix_home()).grid(row=4, column=1, sticky="w", padx=4)
        grid.columnconfigure(1, weight=1)
```
par :
```python
        ttk.Label(grid, text=dynamix_home()).grid(row=4, column=1, sticky="w", padx=4)
        ttk.Label(grid, text="Music library folder:").grid(row=5, column=0, sticky="w", pady=3)
        self.cfg_library_var = tk.StringVar(value=cfg.get("library_folder") or "")
        ttk.Entry(grid, textvariable=self.cfg_library_var, width=70).grid(row=5, column=1, sticky="we", padx=4)
        ttk.Button(grid, text="Browse", command=lambda: self._cfg_pick_dir(self.cfg_library_var)).grid(row=5, column=2)
        ttk.Label(grid, text="Every track you mixed, in one folder (subfolders included). Scanned in place, never copied.",
                  foreground=MUTED).grid(row=6, column=1, sticky="w", padx=4)
        grid.columnconfigure(1, weight=1)
```

Remplacer :
```python
        ttk.Button(env, text="Refresh", command=self.refresh_environment).pack(anchor="w", padx=6, pady=4)
```
par :
```python
        env_bar = ttk.Frame(env)
        env_bar.pack(anchor="w", padx=6, pady=4)
        ttk.Button(env_bar, text="Refresh", command=self.refresh_environment).pack(side=tk.LEFT)
        ttk.Button(env_bar, text="Clear whole cache...", command=self.clear_whole_cache).pack(side=tk.LEFT, padx=6)
```

Remplacer :
```python
        cfg.set("mixxx_db", self.cfg_mixxx_var.get().strip())
```
par :
```python
        cfg.set("mixxx_db", self.cfg_mixxx_var.get().strip())
        cfg.set("library_folder", self.cfg_library_var.get().strip())
```

Remplacer :
```python
        if hasattr(self, "refresh_project_list"):
            self.refresh_project_list()
```
par :
```python
        if hasattr(self, "refresh_project_list"):
            self.refresh_project_list()
        if hasattr(self, "rescan_library"):
            self.rescan_library()
```

Remplacer :
```python
    def refresh_environment(self):
        self.env_text.delete("1.0", tk.END)
        self.env_text.insert(tk.END, format_environment_report())
```
par :
```python
    def refresh_environment(self):
        self.env_text.delete("1.0", tk.END)
        self.env_text.insert(tk.END, format_environment_report())
    
    def clear_whole_cache(self):
        store = get_store()
        stats = store.stats()
        if not messagebox.askyesno("Clear whole cache",
                                   f"Forget every analysis result ({stats['files']} files, {stats['entries']} results, "
                                   f"{stats['size_bytes'] / 1e6:.1f} MB)?\n\nEvery track will be analysed again when needed. "
                                   "Your library and the projects' selections are not changed.", icon="warning"):
            return
        removed = store.clear()
        message = f"Analysis cache cleared: {removed} results removed"
        log.info(message)
        self.refresh_environment()
        if hasattr(self, "_after_cache_cleared"):
            self._after_cache_cleared()
        self.update_status(message)
```

- [ ] **Step 3 : lancer la vérification GUI**

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `GUI smoke OK`

- [ ] **Step 4 : commit**

```bash
git add set_builder.py tests/gui_smoke.py
git commit -m "Configuration tab: music library folder and clear whole cache"
```

---

### Task 9 : onglet Tracks — colonnes Library et Selection, analyse de la sélection

**Files :**
- Modify: `set_builder.py` (`SetBuilderMixin`)
- Modify: `tests/gui_smoke.py`

**Interfaces :**
- Consumes :
  - `library.scan`, `library.filter_entries` (Task 5)
  - `SetProject.selection`, `selection_files`, `add_to_selection`, `remove_from_selection`, `selection_rows` (Task 4)
  - `_report_error`, `log` (Task 7)
- Produces (utilisées par les tâches 10 et 11) :
  - `rescan_library()`, `_refresh_library_table(caption=None)`, `_merge_into_library(tracks)`
  - `selection_add()`, `selection_remove()`, `_after_selection_change(message)`
  - `_selected_many(tree, rows)`, `_fmt_time(seconds) -> str` (staticmethod), `_short_values(row, duration, last)` (staticmethod)
  - attributs `library_tree`, `selection_tree`, `set_tree`, `_library_entries`, `_library_rows`, `_selection_rows`, `_set_rows`, `_library_scanning`, `_previewing`, `library_filter_var`, `library_caption`, `selection_caption`, `set_caption`
  - `_make_tree(parent, columns, widths, selectmode="browse", height=14)`
  - un conteneur `right_col` (colonne 3) où la tâche 10 insère les propositions avant `set_frame`

- [ ] **Step 1 : ajouter la vérification GUI (échec attendu)**

Dans `tests/gui_smoke.py`, remplacer :
```python
    # --- checks added by later tasks go above this line ---
```
par :
```python
    check(pump(lambda: not app._library_scanning and len(app._library_rows) == 2, 10.0),
          "the library lists the 2 tracks of the library folder")
    app.library_filter_var.set("two")
    check(len(app._library_rows) == 1, "the filter narrows the library")
    app.library_filter_var.set("")
    app.library_tree.selection_set(app.library_tree.get_children())
    app.selection_add()
    check(len(app.project.selection) == 2, "both tracks are selected")
    check([r["state"] for r in app._selection_rows] == ["pending", "pending"], "new selection rows are pending")
    app.selection_tree.selection_set("C1")
    app.selection_remove()
    check(len(app.project.selection) == 1, "remove drops a track from the selection")
    app.library_tree.selection_set(app.library_tree.get_children())
    app.selection_add()
    check(len(app.project.selection) == 2, "adding again keeps one entry per track")

    # --- checks added by later tasks go above this line ---
```

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `AttributeError: 'DynaMixGUI' object has no attribute '_library_scanning'`

- [ ] **Step 2 : imports et état initial**

Remplacer :
```python
import logging
import os
```
par :
```python
import collections
import logging
import os
```
Remplacer `import charts` par :
```python
import charts
import library
```
Remplacer :
```python
        self._library_rows = []
        self._set_rows = []
```
par :
```python
        self._library_rows = []
        self._set_rows = []
        self._selection_rows = []
        self._library_entries = []
        self._library_scanning = False
        self._previewing = False
```

- [ ] **Step 3 : retirer durée et courbe du panneau Options (elles passent dans Proposals)**

Remplacer :
```python
        ttk.Label(grid, text="Set duration (min):").grid(row=0, column=0, sticky="w", pady=2)
        self.set_duration_var = tk.IntVar(value=int(self.config.get("set_duration")))
        ttk.Spinbox(grid, from_=15, to=240, textvariable=self.set_duration_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Label(grid, text="Energy curve:").grid(row=1, column=0, sticky="w", pady=2)
        self.energy_curve_var = tk.StringVar(value=self.config.get("energy_curve"))
        ttk.Combobox(grid, textvariable=self.energy_curve_var, values=["build", "wave", "peak_middle", "constant"],
                     width=12, state="readonly").grid(row=1, column=1, sticky="w")
```
par :
```python
        # set duration and energy curve are edited in the Proposals panel of the Tracks tab
        self.set_duration_var = tk.IntVar(value=int(self.config.get("set_duration")))
        self.energy_curve_var = tk.StringVar(value=self.config.get("energy_curve"))
```

- [ ] **Step 4 : les trois colonnes de l'onglet Tracks**

Remplacer tout le bloc qui va de :
```python
        lists = ttk.PanedWindow(tracks_tab, orient=tk.HORIZONTAL)
        lists.pack(fill=tk.BOTH, expand=True)
        
        lib_frame = ttk.Frame(lists)
```
jusqu'à la ligne incluse :
```python
        self.playlist_tree = self.set_tree  # older code paths
```
(soit les lignes 133 à 160 d'origine : Library, boutons du milieu, Set list) par :
```python
        lists = ttk.PanedWindow(tracks_tab, orient=tk.HORIZONTAL)
        lists.pack(fill=tk.BOTH, expand=True)
        
        # column 1: every track of the library folder
        lib_frame = ttk.Frame(lists)
        lists.add(lib_frame, weight=1)
        self.library_caption = ttk.Label(lib_frame, text="Library", foreground=MUTED, anchor="w")
        self.library_caption.pack(fill=tk.X, padx=4, pady=(4, 0))
        lib_bar = ttk.Frame(lib_frame)
        lib_bar.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(lib_bar, text="Filter:").pack(side=tk.LEFT)
        self.library_filter_var = tk.StringVar()
        ttk.Entry(lib_bar, textvariable=self.library_filter_var, width=16).pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        ttk.Button(lib_bar, text="Rescan", command=self.rescan_library).pack(side=tk.LEFT, padx=2)
        ttk.Button(lib_bar, text="Add to selection →", command=self.selection_add).pack(side=tk.LEFT, padx=2)
        self.library_tree = self._make_tree(lib_frame, ("Filename", "Dur", "BPM", "Key", "Energy", "Sel"),
                                            {"Filename": 220, "Dur": 55, "BPM": 50, "Key": 75, "Energy": 50, "Sel": 35},
                                            selectmode="extended")
        self.library_tree.bind("<Double-1>", lambda e: self.selection_add())
        self.library_filter_var.trace_add("write", lambda *args: self._refresh_library_table())
        
        # column 2: the tracks picked for this set
        sel_frame = ttk.Frame(lists)
        lists.add(sel_frame, weight=1)
        self.selection_caption = ttk.Label(sel_frame, text="Selection", foreground=MUTED, anchor="w")
        self.selection_caption.pack(fill=tk.X, padx=4, pady=(4, 0))
        sel_bar = ttk.Frame(sel_frame)
        sel_bar.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(sel_bar, text="← Remove", command=self.selection_remove).pack(side=tk.LEFT, padx=2)
        ttk.Button(sel_bar, text="Analyze selection", command=self.analyze_playlist).pack(side=tk.LEFT, padx=2)
        ttk.Button(sel_bar, text="Add to set list ▶", command=self.set_add).pack(side=tk.LEFT, padx=2)
        self.selection_tree = self._make_tree(sel_frame, ("Filename", "Dur", "BPM", "Key", "Energy", "State"),
                                              {"Filename": 220, "Dur": 55, "BPM": 50, "Key": 75, "Energy": 50, "State": 70},
                                              selectmode="extended")
        self.selection_tree.bind("<<TreeviewSelect>>", lambda e: self.on_track_selected(self.selection_tree))
        self.selection_tree.bind("<Double-1>", lambda e: self.selection_remove())
        
        # column 3: proposals and the set list
        right_col = ttk.Frame(lists)
        lists.add(right_col, weight=1)
        set_frame = ttk.Frame(right_col)
        set_frame.pack(fill=tk.BOTH, expand=True)
        self.set_caption = ttk.Label(set_frame, text="Set list (playing order)", foreground=MUTED, anchor="w")
        self.set_caption.pack(fill=tk.X, padx=4, pady=(4, 0))
        set_bar = ttk.Frame(set_frame)
        set_bar.pack(fill=tk.X, padx=4, pady=2)
        for text, cmd in (("▲ Up", lambda: self.set_move(-1)), ("▼ Down", lambda: self.set_move(1)), ("Remove", self.set_remove)):
            ttk.Button(set_bar, text=text, command=cmd, width=9).pack(side=tk.LEFT, padx=2)
        self.set_tree = self._make_tree(set_frame, ("#", "Filename", "BPM", "Key", "Dur", "Energy", "Master", "Flags"),
                                        {"#": 35, "Filename": 200, "BPM": 55, "Key": 75, "Dur": 50, "Energy": 55, "Master": 55, "Flags": 240})
        self.set_tree.tag_configure("preview", foreground=MUTED)
        self.set_tree.bind("<<TreeviewSelect>>", lambda e: self.on_track_selected(self.set_tree))
        self.set_tree.bind("<Double-1>", lambda e: self.set_remove())
        self.playlist_tree = self.set_tree  # older code paths
```

Remplacer :
```python
        projects = list_projects(self.config.projects_root)
        if projects:
            self.load_project(projects[0])
```
par :
```python
        projects = list_projects(self.config.projects_root)
        if projects:
            self.load_project(projects[0])
        self.rescan_library()
```

Remplacer :
```python
    def _make_tree(self, parent, columns, widths):
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=14, selectmode="browse")
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=widths.get(col, 80), anchor="w" if col in ("Filename", "Key", "Flags") else "center",
```
par :
```python
    def _make_tree(self, parent, columns, widths, selectmode="browse", height=14):
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=height, selectmode=selectmode)
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=widths.get(col, 80), anchor="w" if col in ("Filename", "Key", "Flags", "Curve", "Worst") else "center",
```

- [ ] **Step 5 : `load_project` sur la sélection**

Remplacer :
```python
        manager = PlaylistManager(project.source_dir)
        manager.tracks = list(project.tracks)
        self.playlist_manager = manager
        self.current_set_list = project.set_list_tracks() or None
        self.transition_planner = self._planner_from_project()
        self.transition_source_dir = project.exports_dir
        self.current_playlist_dir = project.source_dir
        
        n_files = len(project.source_files())
        self.project_path_label.config(text=f"{project.folder}   ·   {n_files} audio files in source/   ·   from {project.data.get('source_folder') or '-'}")
        self.refresh_project_list()
        self._refresh_tables()
```
par :
```python
        manager = PlaylistManager(project.folder)
        manager.tracks = list(project.tracks)
        self.playlist_manager = manager
        self.current_set_list = project.set_list_tracks() or None
        self.transition_planner = self._planner_from_project()
        self.transition_source_dir = project.exports_dir
        self.current_playlist_dir = project.folder
        
        self.project_path_label.config(text=f"{project.folder}   ·   {len(project.selection)} selected tracks   ·   "
                                            f"library: {self.config.get('library_folder') or 'not set (Configuration tab)'}")
        self.refresh_project_list()
        self._refresh_tables()
        self._refresh_library_table()
```

- [ ] **Step 6 : tables Library et Selection**

Remplacer toute la méthode `_refresh_tables`, de `    def _refresh_tables(self):` jusqu'à la ligne `        self.set_caption.config(text=f"Set list: {len(self._set_rows)} tracks, {total:.0f} min — playing order (Add/Remove/Up/Down to edit)")` incluse, par :
```python
    @staticmethod
    def _fmt_time(seconds):
        """h:mm:ss or m:ss, '-' when unknown."""
        if not seconds:
            return "-"
        total = int(round(float(seconds)))
        hours, rest = divmod(total, 3600)
        minutes, secs = divmod(rest, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    
    @staticmethod
    def _short_values(row, duration, last):
        """Filename, Dur, BPM, Key, Energy, <last> (library and selection tables)."""
        bpm = row.get("bpm") or 0
        energy = row.get("energy_level") or 0
        return [row.get("filename", ""), SetBuilderMixin._fmt_time(duration), f"{bpm:.1f}" if bpm else "-",
                row.get("key") or "-", f"{energy:.1f}" if energy else "-", last]
    
    def _refresh_library_table(self, caption=None):
        tree = self.library_tree
        for item in tree.get_children():
            tree.delete(item)
        selected = set(self.project.selection) if self.project else set()
        rows = library.filter_entries(self._library_entries, self.library_filter_var.get())
        self._library_rows = rows
        for i, entry in enumerate(rows, 1):
            tree.insert("", tk.END, iid=f"L{i}",
                        values=self._short_values(entry, entry.get("duration"), "✓" if entry["file_path"] in selected else ""))
        folder = self.config.get("library_folder") or ""
        if caption is None:
            if not folder:
                caption = "Library: set the library folder in the Configuration tab"
            elif self._library_scanning:
                caption = f"Library: scanning {folder} ..."
            else:
                total = len(self._library_entries)
                hours = sum(e.get("duration") or 0 for e in self._library_entries) / 3600
                shown = f"{len(rows)} shown of " if len(rows) != total else ""
                caption = f"Library: {shown}{total} tracks, {hours:.1f} h ({folder})"
        self.library_caption.config(text=caption)
    
    def rescan_library(self):
        """Scan the library folder in the background (headers and cache only, no audio decoding)."""
        folder = (self.config.get("library_folder") or "").strip()
        if not folder:
            self._library_entries = []
            self._refresh_library_table()
            return
        if self._library_scanning:
            return
        self._library_scanning = True
        self._refresh_library_table()
        
        def progress(i, n, name):
            if i % 50 == 0 or i == n:
                self.root.after(0, self.update_status, f"Scanning library {i}/{n}: {name}")
        
        def work():
            try:
                entries = library.scan(folder, progress=progress)
            except Exception as e:
                entries = []
                self._report_error(f"Library scan failed: {e}", e)
            
            def done():
                self._library_scanning = False
                self._library_entries = entries
                self._refresh_library_table()
                self.update_status(f"Library: {len(entries)} tracks in {folder}")
            self.root.after(0, done)
        threading.Thread(target=work, daemon=True).start()
    
    def _merge_into_library(self, tracks):
        """Show freshly analysed values in the library table without rescanning."""
        by_path = {t["file_path"]: t for t in tracks}
        for entry in self._library_entries:
            t = by_path.get(entry["file_path"])
            if t:
                entry.update(analysed=True, duration=t.get("duration") or entry.get("duration"),
                             bpm=t.get("bpm") or None, key=t.get("key") or None, energy_level=t.get("energy_level") or None)
    
    def _refresh_tables(self):
        self._previewing = False
        for tree in (self.selection_tree, self.set_tree):
            for item in tree.get_children():
                tree.delete(item)
        self._selection_rows, self._set_rows = [], []
        if self.project is None:
            return
        mastering = self._mastering_by_path()
        lib_by_path = {e["file_path"]: e for e in self._library_entries}
        for i, row in enumerate(self.project.selection_rows(), 1):
            row["duration"] = row.get("duration") or lib_by_path.get(row["file_path"], {}).get("duration")
            self.selection_tree.insert("", tk.END, iid=f"C{i}", values=self._short_values(row, row["duration"], row["state"]))
            self._selection_rows.append(row)
        for i, t in enumerate(self.project.set_list_tracks(), 1):
            self.set_tree.insert("", tk.END, iid=f"S{i}", values=self._row_values(t, i, mastering.get(t["file_path"])))
            self._set_rows.append(t)
        counts = collections.Counter(r["state"] for r in self._selection_rows)
        others = ", ".join(f"{n} {state}" for state, n in sorted(counts.items()) if state != "analysed")
        sel_seconds = sum(float(r.get("duration") or 0) for r in self._selection_rows)
        self.selection_caption.config(text=f"Selection: {len(self._selection_rows)} tracks · {self._fmt_time(sel_seconds)}"
                                           + (f" ({others})" if others else ""))
        set_seconds = sum(float(t.get("duration") or 0) for t in self._set_rows)
        self.set_caption.config(text=f"Set list: {len(self._set_rows)} tracks, {self._fmt_time(set_seconds)} — playing order")
```

Après la méthode `_selected` (qui se termine par `        return rows[idx] if 0 <= idx < len(rows) else None`), ajouter :
```python
    
    def _selected_many(self, tree, rows):
        out = []
        for iid in tree.selection():
            try:
                idx = int(iid[1:]) - 1
            except ValueError:
                continue
            if 0 <= idx < len(rows):
                out.append(rows[idx])
        return out
```

- [ ] **Step 7 : ajouter à la sélection, en retirer, et ajouter à la set list**

Remplacer :
```python
    def set_add(self):
        if not self._require_project():
            return
        track = self._selected(self.library_tree, self._library_rows)
        if track is None:
            return
        # insert after the selected set-list row, else at the end
        current = self._selected(self.set_tree, self._set_rows)
        position = (self.project.set_list.index(current["file_path"]) + 1) if current else None
        self.project.add_to_set(track["file_path"], position)
        self._after_manual_edit()
```
par :
```python
    def selection_add(self):
        if not self._require_project():
            return
        entries = self._selected_many(self.library_tree, self._library_rows)
        if not entries:
            return
        added = self.project.add_to_selection([e["file_path"] for e in entries])
        self._after_selection_change(f"Selection: {added} tracks added ({len(self.project.selection)} selected)")
    
    def selection_remove(self):
        if not self._require_project():
            return
        rows = self._selected_many(self.selection_tree, self._selection_rows)
        if not rows:
            return
        removed = self.project.remove_from_selection([r["file_path"] for r in rows])
        self._after_selection_change(f"Selection: {removed} tracks removed ({len(self.project.selection)} selected)")
    
    def _after_selection_change(self, message):
        self.playlist_manager.tracks = list(self.project.tracks)
        self.current_set_list = self.project.set_list_tracks() or None
        self.transition_planner = None
        self._save_project()
        self._refresh_tables()
        self._refresh_library_table()
        self._render_overview()
        log.info(message)
        self.update_status(message)
    
    def set_add(self):
        if not self._require_project():
            return
        rows = [r for r in self._selected_many(self.selection_tree, self._selection_rows) if r["state"] == "analysed"]
        if not rows:
            messagebox.showinfo("Set list", "Select analysed tracks in the Selection first")
            return
        # insert after the selected set-list row, else at the end
        current = self._selected(self.set_tree, self._set_rows)
        position = (self.project.set_list.index(current["file_path"]) + 1) if current else None
        for offset, row in enumerate(rows):
            self.project.add_to_set(row["file_path"], None if position is None else position + offset)
        self._after_manual_edit()
```

- [ ] **Step 8 : analyser la sélection**

Remplacer :
```python
        files = project.source_files()
        if not files:
            messagebox.showwarning("Warning", "No audio files in the project. Use 'Import audio...' first.")
            return
```
par :
```python
        files = project.selection_files()
        if not files:
            messagebox.showwarning("Warning", "No selected tracks on disk: pick tracks in the Library and click 'Add to selection →'.")
            return
```
Remplacer :
```python
                manager = PlaylistManager(project.source_dir)
                manager.analyze_playlist(files,
```
par :
```python
                manager = PlaylistManager(project.folder)
                manager.analyze_playlist(files,
```
Remplacer :
```python
                    self._save_project()
                    self._refresh_tables()
                    self._render_overview()
                    self.update_status(f"Analyzed {len(manager.tracks)} tracks ({run['cached']} from cache, {run['analyzed']} new, {run['failed']} failed)")
```
par :
```python
                    self._save_project()
                    self._merge_into_library(manager.tracks)
                    self._refresh_tables()
                    self._refresh_library_table()
                    self._render_overview()
                    message = (f"Analysis: {len(manager.tracks)} tracks ({run['cached']} from cache, "
                               f"{run['analyzed']} new, {run['failed']} failed)")
                    log.info(message)
                    failed = [os.path.basename(p) for p in project.data.get("failed") or []]
                    if failed:
                        log.warning("Analysis failed for %d tracks: %s (see the errors above)", len(failed), ", ".join(failed))
                    self.update_status(message)
```
Remplacer :
```python
        files = [t["file_path"] for t in tracks] or self.project.source_files()
```
par :
```python
        files = [t["file_path"] for t in tracks] or self.project.selection_files()
```
Dans `on_track_selected`, remplacer :
```python
        rows = self._set_rows if tree is self.set_tree else self._library_rows
        track = self._selected(tree, rows)
        if track is None:
            return
```
par :
```python
        rows = self._set_rows if tree is self.set_tree else self._selection_rows
        track = self._selected(tree, rows)
        if track is None or track.get("state", "analysed") != "analysed":
            return
```

- [ ] **Step 9 : lancer la vérification GUI**

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `GUI smoke OK`

- [ ] **Step 10 : commit**

```bash
git add set_builder.py tests/gui_smoke.py
git commit -m "Tracks tab: library and selection columns, analysis of the selection"
```

---

### Task 10 : propositions — calcul, aperçu, utilisation

**Files :**
- Modify: `set_builder.py`
- Modify: `tests/gui_smoke.py`

**Interfaces :**
- Consumes :
  - `set_proposer.propose`, `set_proposer.CURVES`, `set_proposer.curve_targets` (Task 1)
  - `SetProject.proposal_tracks`, `set_proposals`, `proposal_variants`, `use_proposal` (Task 4)
  - de la Task 9 : `right_col`, `_make_tree`, `_fmt_time`, `_refresh_tables`, `_previewing`
- Produces :
  - `create_set_list()` (bouton Propose), `preview_proposal()`, `use_selected_proposal()`
  - `_selected_proposal() -> (variant|None, index|None)`, `_proposal_values(number, variant)` (staticmethod)
  - `_end_preview() -> bool`, `_mix_bars() -> int`, `_set_curve() -> str`
  - attribut `proposal_tree` (iids `P1..Pn`)

- [ ] **Step 1 : ajouter la vérification GUI (échec attendu)**

Dans `tests/gui_smoke.py`, remplacer :
```python
    # --- checks added by later tasks go above this line ---
```
par :
```python
    fake = [{"file_path": p, "filename": os.path.basename(p), "duration": 300.0, "bpm": 120.0 + i, "key": "A minor",
             "energy_level": 3.0 + i, "has_beat": True} for i, p in enumerate(app.project.selection)]
    app.project.set_tracks(fake)
    app.project.mark("analyze", count=len(fake))
    app._refresh_tables()
    check([r["state"] for r in app._selection_rows] == ["analysed", "analysed"], "analysed rows are shown as analysed")
    app.energy_curve_var.set("all")
    app.set_duration_var.set(15)
    app.create_set_list()
    check(pump(lambda: len(app.project.proposal_variants()) == 4, 15.0), "curve 'all' gives one proposal per curve")
    check(pump(lambda: app._previewing, 3.0), "the first proposal is previewed")
    app.set_move(1)
    check(not app._previewing, "an edit closes the preview first")
    app.proposal_tree.selection_set("P2")
    check(pump(lambda: app._previewing, 3.0), "selecting a proposal previews it")
    app.use_selected_proposal()
    check(len(app.project.set_list) == 2 and app.project.is_done("setlist"), "the proposal became the set list")
    check(app.project.options["energy_curve"] != "all", "'all' is not saved as the project's energy curve")

    # --- checks added by later tasks go above this line ---
```

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : échec, par exemple `AssertionError: curve 'all' gives one proposal per curve`, ou une erreur `Unknown energy curve: all` journalisée par l'ancien `create_set_list`.

- [ ] **Step 2 : import et panneau Proposals**

Remplacer `import library` par :
```python
import library
import set_proposer
```

Remplacer :
```python
        right_col = ttk.Frame(lists)
        lists.add(right_col, weight=1)
        set_frame = ttk.Frame(right_col)
```
par :
```python
        right_col = ttk.Frame(lists)
        lists.add(right_col, weight=1)
        prop_frame = ttk.LabelFrame(right_col, text="Proposals (from the analysed selection)")
        prop_frame.pack(fill=tk.X, padx=4, pady=(4, 2))
        prop_bar = ttk.Frame(prop_frame)
        prop_bar.pack(fill=tk.X, padx=4, pady=2)
        ttk.Label(prop_bar, text="Duration (min):").pack(side=tk.LEFT)
        ttk.Spinbox(prop_bar, from_=15, to=240, textvariable=self.set_duration_var, width=5).pack(side=tk.LEFT, padx=3)
        ttk.Label(prop_bar, text="Curve:").pack(side=tk.LEFT, padx=(6, 0))
        ttk.Combobox(prop_bar, textvariable=self.energy_curve_var, values=list(set_proposer.CURVES) + ["all"],
                     width=11, state="readonly").pack(side=tk.LEFT, padx=3)
        ttk.Button(prop_bar, text="Propose", command=self.create_set_list).pack(side=tk.LEFT, padx=3)
        prop_body = ttk.Frame(prop_frame)
        prop_body.pack(fill=tk.X, padx=4)
        self.proposal_tree = self._make_tree(prop_body, ("#", "Curve", "Tracks", "Duration", "Score", "Worst"),
                                             {"#": 30, "Curve": 90, "Tracks": 50, "Duration": 120, "Score": 50, "Worst": 90},
                                             height=4)
        self.proposal_tree.bind("<<TreeviewSelect>>", lambda e: self.preview_proposal())
        self.proposal_tree.bind("<Double-1>", lambda e: self.use_selected_proposal())
        ttk.Button(prop_frame, text="Use this proposal", command=self.use_selected_proposal).pack(anchor="w", padx=4, pady=4)
        set_frame = ttk.Frame(right_col)
```

- [ ] **Step 3 : ne pas enregistrer `all` comme courbe du projet, afficher le score dans le workflow**

Remplacer :
```python
            "energy_curve": self.energy_curve_var.get(),
```
par :
```python
            "energy_curve": (self.energy_curve_var.get() if self.energy_curve_var.get() in set_proposer.CURVES
                             else self.project.options.get("energy_curve", "build")),
```
Remplacer :
```python
            for k in ("count", "cached", "analyzed", "manual", "duration", "curve", "file", "playlist", "cues"):
```
par :
```python
            for k in ("count", "cached", "analyzed", "manual", "duration", "curve", "score", "file", "playlist", "cues"):
```

- [ ] **Step 4 : la table des propositions dans `_refresh_tables`**

Remplacer :
```python
        for tree in (self.selection_tree, self.set_tree):
```
par :
```python
        for tree in (self.selection_tree, self.set_tree, self.proposal_tree):
```
Remplacer :
```python
        counts = collections.Counter(r["state"] for r in self._selection_rows)
```
par :
```python
        for i, variant in enumerate(self.project.proposal_variants(), 1):
            self.proposal_tree.insert("", tk.END, iid=f"P{i}", values=self._proposal_values(i, variant))
        counts = collections.Counter(r["state"] for r in self._selection_rows)
```

- [ ] **Step 5 : les éditions de la set list ferment l'aperçu**

Remplacer :
```python
    def set_add(self):
        if not self._require_project():
            return
```
par :
```python
    def set_add(self):
        if not self._require_project() or self._end_preview():
            return
```
Remplacer :
```python
    def set_remove(self):
        if not self._require_project():
            return
```
par :
```python
    def set_remove(self):
        if not self._require_project() or self._end_preview():
            return
```
Remplacer :
```python
    def set_move(self, delta):
        if not self._require_project():
            return
```
par :
```python
    def set_move(self, delta):
        if not self._require_project() or self._end_preview():
            return
```

- [ ] **Step 6 : Propose, aperçu, utilisation**

Remplacer toute la méthode `create_set_list`, de `    def create_set_list(self):` à la ligne `            self._report_error(f"Set list creation failed: {e}", e)` incluse, par :
```python
    def create_set_list(self):
        """Compute proposals from the analysed selection (worker thread); the set list changes on 'Use this proposal'."""
        if not self._require_project():
            return
        project = self.project
        tracks, skipped = project.proposal_tracks()
        if not tracks:
            messagebox.showwarning("Warning", "No analysed tracks in the selection: add tracks, then click 'Analyze selection'")
            return
        if skipped:
            log.warning("Proposals: %d selected tracks left out (not analysed or missing): %s", len(skipped), ", ".join(skipped))
        duration = int(self.set_duration_var.get())
        curve = self.energy_curve_var.get()
        mix_bars = self._mix_bars()
        
        def work():
            try:
                if curve == "all":
                    variants = [set_proposer.propose(tracks, duration * 60, curve=c, mix_bars=mix_bars, variants=1)[0]
                                for c in set_proposer.CURVES]
                    variants.sort(key=lambda v: (-v["score"], v["cost"]))
                else:
                    variants = set_proposer.propose(tracks, duration * 60, curve=curve, mix_bars=mix_bars, variants=3)
            except Exception as e:
                self._report_error(f"Proposal failed: {e}", e)
                return
            
            def done():
                if self.project is not project:
                    return  # another project was opened meanwhile
                project.set_proposals({"duration_min": duration, "curve": curve, "mix_bars": mix_bars}, variants)
                self._save_project()
                self._refresh_tables()
                message = (f"Proposals: {len(variants)} variants for {duration} min ({curve}) from {len(tracks)} tracks, "
                           f"best score {max(v['score'] for v in variants)}")
                log.info(message)
                self.update_status(message + " - select one to preview it, then 'Use this proposal'")
                self.proposal_tree.selection_set("P1")
            self.root.after(0, done)
        
        self.update_status(f"Computing proposals from {len(tracks)} tracks ...")
        threading.Thread(target=work, daemon=True).start()
    
    @staticmethod
    def _proposal_values(number, variant):
        worst = variant.get("worst")
        duration = f"{SetBuilderMixin._fmt_time(variant['effective_seconds'])} / {SetBuilderMixin._fmt_time(variant['target_seconds'])}"
        return [number, variant["curve"], len(variant["order"]), duration, variant["score"],
                f"{worst['index'] + 1}→{worst['index'] + 2} · {worst['score']}" if worst else "-"]
    
    def _selected_proposal(self):
        """(variant, index) of the selected row of the Proposals table, else (None, None)."""
        sel = self.proposal_tree.selection()
        if not sel or self.project is None:
            return None, None
        index = int(sel[0][1:]) - 1
        variants = self.project.proposal_variants()
        return (variants[index], index) if 0 <= index < len(variants) else (None, None)
    
    def preview_proposal(self):
        """Show the selected proposal in the set list table (greyed) and the Overview, without saving."""
        variant, index = self._selected_proposal()
        if variant is None:
            return
        by_path = {t["file_path"]: t for t in self.project.tracks}
        tracks = [by_path[p] for p in variant["order"] if p in by_path]
        for item in self.set_tree.get_children():
            self.set_tree.delete(item)
        mastering = self._mastering_by_path()
        for i, t in enumerate(tracks, 1):
            self.set_tree.insert("", tk.END, iid=f"S{i}", values=self._row_values(t, i, mastering.get(t["file_path"])),
                                 tags=("preview",))
        self._set_rows = tracks
        self._previewing = True
        self.set_caption.config(text=f"Preview of proposal {index + 1} ({variant['curve']}, score {variant['score']}): "
                                     f"{len(tracks)} tracks, {self._fmt_time(variant['effective_seconds'])} — "
                                     "'Use this proposal' to keep it")
        self._clear_frame(self.overview_frame)
        self._show_figure(self.overview_frame,
                          charts.set_overview(tracks, set_proposer.curve_targets(tracks, variant["curve"], self._mix_bars())))
    
    def use_selected_proposal(self):
        if not self._require_project():
            return
        variant, index = self._selected_proposal()
        if variant is None:
            messagebox.showinfo("Proposals", "Select a proposal first (click 'Propose' when the list is empty)")
            return
        self.project.use_proposal(index)
        self.current_set_list = self.project.set_list_tracks() or None
        self.transition_planner = None
        self._save_project()
        self._refresh_tables()
        self._render_overview()
        message = (f"Proposal {index + 1} ({variant['curve']}, score {variant['score']}) is now the set list: "
                   f"{len(self.project.set_list)} tracks")
        log.info(message)
        self.update_status(message)
    
    def _end_preview(self):
        """If a proposal preview is showing, show the set list again and return True (the edit is skipped)."""
        if not self._previewing:
            return False
        self._refresh_tables()
        self._render_overview()
        self.update_status("Preview closed: the set list is shown again (click again to edit it)")
        return True
    
    def _mix_bars(self):
        return int(self.project.options.get("mix_bars", 8)) if self.project else 8
    
    def _set_curve(self):
        """Curve of the current set list: the one of the proposal it came from, else the chosen curve."""
        details = {}
        if self.project is not None:
            details = self.project.step_state("setlist").get("details") or {}
        return details.get("curve") or self.energy_curve_var.get()
```

- [ ] **Step 7 : Overview avec la courbe du set**

Remplacer :
```python
        tracks = self.current_set_list or (self.playlist_manager.tracks if self.playlist_manager else [])
        if not tracks:
            return
        self._clear_frame(self.overview_frame)
        targets = None
        if self.current_set_list:
            values = [PlaylistManager._energy_value(t) for t in tracks]
            targets = PlaylistManager._target_curve(values, self.energy_curve_var.get())
```
par :
```python
        tracks = self.current_set_list or (self.playlist_manager.tracks if self.playlist_manager else [])
        if not tracks:
            self._clear_frame(self.overview_frame, "Analyze the selection and build a set list to see the energy curve and the set map.")
            return
        self._clear_frame(self.overview_frame)
        targets = None
        if self.current_set_list:
            targets = set_proposer.curve_targets(tracks, self._set_curve(), self._mix_bars())
```

- [ ] **Step 8 : lancer la vérification GUI**

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `GUI smoke OK`

- [ ] **Step 9 : commit**

```bash
git add set_builder.py tests/gui_smoke.py
git commit -m "Proposals panel: several variants from the selection, preview, use as set list"
```

---

### Task 11 : Reset project, Clear analysis cache, nouveau projet sans import

**Files :**
- Modify: `set_builder.py`
- Modify: `tests/gui_smoke.py`

**Interfaces :**
- Consumes :
  - `SetProject.reset_preview`, `reset`, `forget_analysis` (Task 4)
  - `AnalysisStore.clear_paths` (Task 3)
  - `rescan_library`, `_refresh_tables`, `_render_overview` (tasks 9 et 10)
  - `_report_error`, `log` (Task 7)
- Produces :
  - `reset_project()` (dialogue) et `_do_reset(delete_imported=False) -> Optional[Dict]`
  - `clear_analysis_cache()` (confirmation) et `_do_clear_analysis_cache(paths) -> int`
  - `_after_cache_cleared()` (appelé aussi par `clear_whole_cache`, Task 8)
  - `import_audio` supprimé

- [ ] **Step 1 : ajouter la vérification GUI (échec attendu)**

Dans `tests/gui_smoke.py`, remplacer :
```python
    # --- checks added by later tasks go above this line ---
```
par :
```python
    open(os.path.join(app.project.exports_dir, "old.m3u"), "w").close()
    result = app._do_reset()
    check(result == {"files_deleted": 1, "bytes_deleted": 0}, f"reset deletes the exports, got {result}")
    check(app.project.selection == [] and app._selection_rows == [] and app.project.set_list == [],
          "reset empties the selection and the set list")
    app.library_tree.selection_set(app.library_tree.get_children())
    app.selection_add()
    from analysis_store import get_store
    first = app.project.selection[0]
    get_store().put(first, "features", {"duration": 2.0, "bpm": 120.0})
    check(app._do_clear_analysis_cache(list(app.project.selection)) == 1, "the selection's cache entries are removed")
    check(get_store().get(first, "features") is None, "the cache entry is gone")
    check(pump(lambda: not app._library_scanning, 10.0), "the library is rescanned after clearing the cache")

    # --- checks added by later tasks go above this line ---
```

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `AttributeError: 'DynaMixGUI' object has no attribute '_do_reset'`

- [ ] **Step 2 : boutons de la barre du haut**

Remplacer :
```python
        ttk.Button(head, text="New project...", command=self.new_project).pack(side=tk.LEFT, padx=4)
        ttk.Button(head, text="Import audio...", command=self.import_audio).pack(side=tk.LEFT, padx=4)
        ttk.Button(head, text="Project summary", command=self.show_project_summary).pack(side=tk.LEFT, padx=4)
```
par :
```python
        ttk.Button(head, text="New project...", command=self.new_project).pack(side=tk.LEFT, padx=4)
        ttk.Button(head, text="Project summary", command=self.show_project_summary).pack(side=tk.LEFT, padx=4)
        ttk.Button(head, text="Reset project...", command=self.reset_project).pack(side=tk.LEFT, padx=(16, 4))
        ttk.Button(head, text="Clear analysis cache...", command=self.clear_analysis_cache).pack(side=tk.LEFT, padx=4)
```

Remplacer `from set_project import SetProject, STEPS, list_projects, audio_files_in` par `from set_project import SetProject, STEPS, list_projects`.

- [ ] **Step 3 : remplacer l'import par reset et cache**

Remplacer le bloc qui va de :
```python
        self.load_project(project.folder)
        self.refresh_project_list()
        if messagebox.askyesno("Import audio", "Import the audio files of a music folder into this project now?"):
            self.import_audio()
```
jusqu'à la fin de la méthode `import_audio`, c'est-à-dire les lignes incluses :
```python
        self.update_status(f"Importing {len(files)} files from {folder} ...")
        threading.Thread(target=work, daemon=True).start()
```
par :
```python
        self.load_project(project.folder)
        self.refresh_project_list()
        if not (self.config.get("library_folder") or "").strip():
            messagebox.showinfo("Music library", "Set your music library folder in the Configuration tab, "
                                                 "then pick the tracks of this set in the Library.")
    
    def reset_project(self):
        if not self._require_project():
            return
        project = self.project
        preview = project.reset_preview()
        outputs, imported = preview["outputs"], preview["imported"]
        win = tk.Toplevel(self.root)
        win.title("Reset project")
        win.transient(self.root)
        win.resizable(False, False)
        text = (f"Reset '{project.name}' to an empty set?\n\n"
                f"Deleted: the selection ({len(project.selection)} tracks), the analysed track list, the proposals, "
                f"the set list, the transitions and pre-master results, and {outputs['files']} files "
                f"({outputs['bytes'] / 1e6:.1f} MB) in premaster/ and exports/.\n\n"
                "Kept: the project name, its options and notes, the analysis cache and your library.")
        ttk.Label(win, text=text, justify=tk.LEFT, wraplength=520).pack(padx=16, pady=(16, 8), anchor="w")
        delete_imported = tk.BooleanVar(value=False)
        if imported["files"]:
            ttk.Checkbutton(win, text=f"Also delete the imported copies in source/ ({imported['files']} files, "
                                      f"{imported['bytes'] / 1e6:.1f} MB)", variable=delete_imported).pack(padx=16, anchor="w")
        buttons = ttk.Frame(win)
        buttons.pack(fill=tk.X, padx=16, pady=16)
        
        def confirm():
            choice = bool(delete_imported.get())
            win.destroy()
            self._do_reset(choice)
        ttk.Button(buttons, text="Reset project", command=confirm).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=6)
        win.grab_set()
    
    def _do_reset(self, delete_imported=False):
        project = self.project
        try:
            result = project.reset(delete_imported=delete_imported)
        except OSError as e:
            self._report_error(f"Reset failed (is a file open in another program?): {e}", e)
            self.load_project(project.folder)
            return None
        message = (f"Project '{project.name}' reset: {result['files_deleted']} files deleted "
                   f"({result['bytes_deleted'] / 1e6:.1f} MB)")
        log.info(message)
        self.load_project(project.folder)
        self.update_status(message)
        return result
    
    def clear_analysis_cache(self):
        if not self._require_project():
            return
        paths = list(self.project.selection)
        if not paths:
            messagebox.showinfo("Clear analysis cache", "The selection is empty: nothing to clear.\n"
                                                        "(The Configuration tab can clear the whole cache.)")
            return
        if not messagebox.askyesno("Clear analysis cache",
                                   f"Forget the analysis results (features, intro/outro, mastering, bands) of the "
                                   f"{len(paths)} selected tracks?\n\nThey will be analysed again. The selection is kept; "
                                   "the set list comes back after 'Analyze selection'.", icon="warning"):
            return
        self._do_clear_analysis_cache(paths)
    
    def _do_clear_analysis_cache(self, paths):
        removed = get_store().clear_paths(paths)
        message = f"Analysis cache: {removed} results removed for {len(paths)} selected tracks"
        log.info(message)
        self._after_cache_cleared()
        self.update_status(message)
        return removed
    
    def _after_cache_cleared(self):
        """Cached analyses are gone: the project must analyse its selection again."""
        if self.project is not None:
            self.project.forget_analysis()
            self.playlist_manager.tracks = []
            self.current_set_list = None
            self.transition_planner = None
            self._save_project()
            self._refresh_tables()
            self._render_overview()
        self.rescan_library()
```

- [ ] **Step 4 : lancer la vérification GUI et toute la suite**

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `GUI smoke OK`

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected : `Ran 98 tests`, `FAILED (failures=2, errors=11)`, uniquement les échecs préexistants.

- [ ] **Step 5 : commit**

```bash
git add set_builder.py tests/gui_smoke.py
git commit -m "Set Builder: reset project, clear the selection's analysis cache, no more audio import"
```

---

### Task 12 : documentation et vérification finale

**Files :**
- Modify: `GUI_README.md` (l.31-51)
- Modify: `README.md` (l.121-135, l.159-163)

- [ ] **Step 1 : `GUI_README.md`**

Remplacer :
```markdown
- **Projects**: a set is a folder under the projects folder (see the
  Configuration tab): `project.json`, `source/` (the audio files imported
  into the project, copies), `premaster/` (corrected copies) and `exports/`
  (M3U, transition sheets, JSON, charts). Your music folders are never
  written to. Use **New project...** then **Import audio...**; the project
  combobox reopens any existing project with everything it contains.
- **Workflow panel**: the six steps with a ✓ / ○ status, the date and key
  figures of each, and a "Next:" hint:
    1. Analyze (BPM, key, energy; cached per file, only new files take time)
    2. Propose a set list (duration, energy curve)
```
par :
```markdown
- **Projects**: a set is a folder under the projects folder (see the
  Configuration tab): `project.json`, `premaster/` (corrected copies) and
  `exports/` (M3U, transition sheets, JSON, charts). The tracks come from your
  **music library**: one folder holding every track you mixed, set in the
  Configuration tab and scanned in place (nothing is copied, the library is
  never written to). The project combobox reopens any existing project.
  **Reset project...** starts the set again from an empty selection (name,
  options, notes and the analysis cache are kept; pre-master and exports are
  deleted). **Clear analysis cache...** forgets the cached analyses of the
  selected tracks so they are analysed again.
- **Workflow panel**: the six steps with a ✓ / ○ status, the date and key
  figures of each, and a "Next:" hint:
    1. Select and analyze (BPM, key, energy; cached per file)
    2. Propose a set list (several variants from the selection; use one)
```

Remplacer :
```markdown
- **Tracks tab**: the **Library** (all analysed tracks, with their position in
  the set) on the left and the **Set list** (playing order) on the right. The
  algorithm's proposal is a starting point: **Add / Remove / Up / Down** edit
  the set list by hand (double-click a library row to add it, a set row to
  remove it); the library never disappears. Select a row to open it in the
  Track tab.
```
par :
```markdown
- **Tracks tab**, three columns:
  **Library** (every track of the library folder, with a filter; double-click
  or **Add to selection →**), **Selection** (the tracks picked for this set,
  their duration and state: analysed / pending / failed / missing; **Analyze
  selection**), and **Proposals + Set list**: choose the duration and the
  energy curve (or `all`), **Propose** computes several variants from the
  analysed selection only (duration with crossfades deducted, score, weakest
  transition). Click a variant to preview it; **Use this proposal** copies it
  into the set list, which **Up / Down / Remove** and **Add to set list ▶**
  then edit by hand. Select a selection or set row to open it in the Track tab.
- **Log tab**: everything DynaMix prints and every error with its traceback,
  filterable by level, also written to `<DynaMix home>/logs/dynamix.log`
  (**Open log folder**). The tab title counts new warnings and errors.
```

- [ ] **Step 2 : `README.md`**

Remplacer :
````markdown
```
<projects folder>/<set name>/
    project.json     options, analysed tracks, set list, step status, results
    source/          the audio files imported (copied) into the project
    premaster/       corrected copies written by the pre-master pass
    exports/         M3U playlists, transition sheets, JSON, charts
```

Your music folders are never written to. The Set Builder tab walks through six steps
(Analyze → Propose → Plan Transitions → Pre-master → Create Playlist → Export to Mixxx) and
shows what is done, when, and what comes next. The proposed order is a starting point: the
Tracks tab keeps the whole library next to the set list, with Add / Remove / Up / Down.
````
par :
````markdown
```
<projects folder>/<set name>/
    project.json     options, selection, analysed tracks, proposals, set list, step status, results
    premaster/       corrected copies written by the pre-master pass
    exports/         M3U playlists, transition sheets, JSON, charts
```

Every track you mixed lives in one **music library folder** (Configuration tab), scanned in
place and never written to (`library.py`). For each set you pick tracks from the library into
the project's **selection**; the Set Builder tab then walks through six steps (Select and
analyze → Propose → Plan Transitions → Pre-master → Create Playlist → Export to Mixxx) and shows
what is done, when, and what comes next. **Propose** computes several variants from the
selection only (`set_proposer.py`); you use one and adjust it with Up / Down / Remove.
**Reset project...** starts a set again from scratch and **Clear analysis cache...** forces the
selected tracks to be analysed again. The **Log** tab shows every message and error
(`app_log.py`, also written to `<DynaMix home>/logs/dynamix.log`). Projects created before
this version keep working: their imported `source/` copies become their selection.
````

Remplacer :
```markdown
Set lists (`create_set_list`, `--playlist`, GUI "Create Set List") first pick tracks that cover
the whole energy range of the folder for the requested duration, then place them along the
chosen curve (`build`, `wave`, `peak_middle`, `constant`) while keeping neighbours within a few
BPM and harmonically compatible (Camelot-wheel logic: same key, relative major/minor, fifth
neighbours).
```
par :
```markdown
Set lists (`set_proposer.propose`, used by the GUI's Propose button and by `create_set_list` /
`--playlist`) come from a beam search over the selected tracks: it fits the requested duration
(crossfade overlaps deducted), follows the chosen curve in time (`build`, `wave`, `peak_middle`,
`constant`) and keeps neighbours within a few BPM and harmonically compatible (Camelot-wheel
logic: same key, relative major/minor, fifth neighbours). The GUI shows the best distinct
variants with their score and weakest transition.
```

- [ ] **Step 3 : vérification finale complète**

Run : `venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected : `Ran 98 tests`, `FAILED (failures=2, errors=11)`, uniquement les échecs préexistants de `test_audio_utils.py` et `test_dj_tools.py`.

Run : `venv/Scripts/python.exe tests/gui_smoke.py`
Expected : `GUI smoke OK`

Run : `venv/Scripts/python.exe -c "import gui, mixxx_export, mastering, mix_enhanced; print('ok')"`
Expected : `ok`

- [ ] **Step 4 : contrôle manuel dans l'application réelle**

Lancer `venv/Scripts/python.exe gui.py` et vérifier, capture d'écran à l'appui :
1. Configuration : définir le dossier bibliothèque, puis Save. La colonne Library se remplit.
2. New project… : Library → Add to selection → Analyze selection. Les états passent à `analysed` et le Log affiche le bilan de l'analyse.
3. Propose (courbe `all`) : 4 variantes. Un clic affiche un aperçu grisé et l'Overview. Use this proposal remplit la set list.
4. Reset project… : le dialogue indique ce qui est supprimé et ce qui est conservé. Après confirmation, tout est vide et les options sont conservées.
5. Clear analysis cache… : la sélection repasse à `pending`.
6. Onglet Log : filtre, Copy et Open log folder fonctionnent.

- [ ] **Step 5 : commit**

```bash
git add README.md GUI_README.md
git commit -m "Docs: music library, selection, proposals, reset and log"
```
