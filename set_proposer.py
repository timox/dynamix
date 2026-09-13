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
