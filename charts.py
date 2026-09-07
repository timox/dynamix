#!/usr/bin/env python3
"""
Charts for the DynaMix Set Builder (matplotlib figures, embeddable in Tk or
saved as PNG). Every function returns a matplotlib Figure.

Conventions: one series per plot in blue; context (targets, medians,
ceilings) in a recessive gray; before/after as two shades of the same blue;
status colours only where they mean something (clipping, warnings) and always
next to a label; thin marks, hairline solid grid, no dual axes.
"""

import os
from typing import Dict, List, Optional, Sequence

import matplotlib
from matplotlib.figure import Figure
import numpy as np

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT2 = "#52514e"
GRID = "#e6e5e1"
GRAY = "#9a9993"
BLUE = "#2a78d6"
BLUE_LIGHT = "#86b6ef"
BLUE_DARK = "#1c5cab"
RED = "#e34948"
STATUS_CRITICAL = "#d03b3b"
STATUS_WARNING = "#fab219"


def _style(ax, grid_axis: str = "y"):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
        ax.spines[side].set_linewidth(1.0)
    ax.tick_params(colors=TEXT2, labelsize=8, length=0)
    if grid_axis:
        ax.grid(True, axis=grid_axis, color=GRID, linewidth=1.0, linestyle="-")
        ax.set_axisbelow(True)
    ax.title.set_color(TEXT)
    ax.xaxis.label.set_color(TEXT2)
    ax.yaxis.label.set_color(TEXT2)


def _figure(width: float = 9.0, height: float = 5.0) -> Figure:
    fig = Figure(figsize=(width, height), dpi=100)
    fig.patch.set_facecolor(SURFACE)
    return fig


def _short(name: str, n: int = 18) -> str:
    base = os.path.splitext(os.path.basename(name))[0]
    return base if len(base) <= n else base[:n - 1] + "…"


def _fmt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


# ------------------------------------------------------------------ set overview
def set_overview(tracks: Sequence[Dict], targets: Optional[Sequence[float]] = None) -> Figure:
    """Energy level and BPM along the set order (two stacked panels sharing x)."""
    fig = _figure(9.0, 5.2)
    n = len(tracks)
    x = np.arange(1, n + 1)
    names = [_short(t.get("filename") or t.get("file_path", "")) for t in tracks]
    energy = [float(t.get("energy_level") or 0.0) for t in tracks]
    bpm = [float(t.get("bpm") or 0.0) for t in tracks]

    ax1 = fig.add_subplot(2, 1, 1)
    ax2 = fig.add_subplot(2, 1, 2, sharex=ax1)
    for ax in (ax1, ax2):
        _style(ax)

    if targets is not None and len(targets) == n:
        ax1.plot(x, targets, color=GRAY, linewidth=2, solid_capstyle="round", label="Target curve")
    ax1.plot(x, energy, color=BLUE, linewidth=2, solid_capstyle="round", solid_joinstyle="round", label="Energy level")
    ax1.scatter(x, energy, s=70, color=BLUE, edgecolors=SURFACE, linewidths=2, zorder=3)
    if n:
        i_max = int(np.argmax(energy))
        ax1.annotate(f"{energy[i_max]:.1f}", (x[i_max], energy[i_max]), textcoords="offset points",
                     xytext=(0, 9), ha="center", fontsize=8, color=TEXT2)
        ax1.annotate(f"{energy[0]:.1f}", (x[0], energy[0]), textcoords="offset points",
                     xytext=(-8, -3), ha="right", fontsize=8, color=TEXT2)
    ax1.set_ylim(0, 10.5)
    ax1.set_yticks([0, 2, 4, 6, 8, 10])
    ax1.set_ylabel("Energy (1-10)")
    ax1.set_title("Set energy curve", loc="left", fontsize=11)
    if targets is not None and len(targets) == n:
        ax1.legend(loc="upper left", frameon=False, fontsize=8, labelcolor=TEXT2)
    ax1.tick_params(labelbottom=False)

    ax2.plot(x, bpm, color=BLUE, linewidth=2, solid_capstyle="round", solid_joinstyle="round")
    ax2.scatter(x, bpm, s=70, color=BLUE, edgecolors=SURFACE, linewidths=2, zorder=3)
    if n:
        ax2.annotate(f"{bpm[-1]:.0f}", (x[-1], bpm[-1]), textcoords="offset points",
                     xytext=(8, -3), ha="left", fontsize=8, color=TEXT2)
    valid = [b for b in bpm if b > 0]
    if valid:
        lo, hi = min(valid), max(valid)
        pad = max(3.0, (hi - lo) * 0.25)
        ax2.set_ylim(lo - pad, hi + pad)
    ax2.set_ylabel("BPM")
    ax2.set_title("Tempo along the set", loc="left", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(names, rotation=30, ha="right", fontsize=8)
    ax2.set_xlim(0.5, n + 0.5 if n else 1.5)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ timeline
def set_start_times(profiles: Sequence[Dict], transitions: Optional[Sequence[Dict]] = None) -> List[float]:
    """Absolute start time of every track when Auto DJ follows the intro/outro sections."""
    starts = [0.0]
    for i in range(1, len(profiles)):
        prev, cur = profiles[i - 1], profiles[i]
        exit_time = float(prev.get("outro_start", prev.get("duration", 0.0)))
        entry_time = float(cur.get("intro_start", 0.0))
        starts.append(starts[-1] + exit_time - entry_time)
    return starts


def set_timeline(profiles: Sequence[Dict], transitions: Optional[Sequence[Dict]] = None) -> Figure:
    """Where each track plays in the set, with intro/outro sections and transition scores."""
    n = len(profiles)
    fig = _figure(9.0, max(2.6, 0.55 * n + 1.4))
    ax = fig.add_subplot(1, 1, 1)
    _style(ax, grid_axis="x")
    starts = set_start_times(profiles, transitions)
    height = 0.5
    for i, (p, start) in enumerate(zip(profiles, starts)):
        y = n - i
        duration = float(p.get("duration", 0.0))
        intro_s, intro_e = float(p.get("intro_start", 0.0)), float(p.get("intro_end", 0.0))
        outro_s, outro_e = float(p.get("outro_start", duration)), float(p.get("outro_end", duration))
        # body in blue, intro/outro in the light step of the same hue, 2 px surface gaps
        ax.barh(y, intro_e - intro_s, left=start + intro_s, height=height, color=BLUE_LIGHT, linewidth=0)
        ax.barh(y, max(0.0, outro_s - intro_e), left=start + intro_e, height=height, color=BLUE, linewidth=0)
        ax.barh(y, outro_e - outro_s, left=start + outro_s, height=height, color=BLUE_LIGHT, linewidth=0)
        if outro_e < duration:
            ax.barh(y, duration - outro_e, left=start + outro_e, height=height, color=GRID, linewidth=0)
        ax.text(start + duration + 8, y, f"{_short(p.get('filename', ''), 26)}  ·  {float(p.get('bpm') or 0):.0f} BPM  ·  E{float(p.get('energy_level') or 0):.1f}",
                va="center", ha="left", fontsize=8, color=TEXT)
    # transitions: hairline at the moment the next track starts, score labelled only when it needs attention
    if transitions:
        for i, t in enumerate(transitions):
            if i + 1 >= n:
                break
            x = starts[i + 1]
            y_top, y_bot = n - i, n - i - 1
            ax.plot([x, x], [y_bot - height / 2, y_top + height / 2], color=GRAY, linewidth=1)
            score = float(t.get("score", 100))
            if score < 70:
                ax.text(x, y_bot - height / 2 - 0.08, f"score {score:.0f}", ha="center", va="top",
                        fontsize=7, color=TEXT2)
    total = starts[-1] + float(profiles[-1].get("duration", 0.0)) if n else 0.0
    ax.set_xlim(0, total * 1.45 if total else 1)
    ax.set_ylim(0.3, n + 0.7)
    ax.set_yticks([])
    ticks = np.arange(0, total + 1, 300 if total > 1200 else 60) if total else [0]
    ax.set_xticks(ticks)
    ax.set_xticklabels([_fmt_time(v) for v in ticks])
    ax.set_xlabel("Set time (min:sec)")
    ax.set_title("Set map: light = intro/outro sections, blue = body, gray = skipped tail", loc="left", fontsize=11)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ track detail
def track_detail(profile: Dict, set_median_balance: Optional[Dict[str, float]] = None) -> Figure:
    """Energy envelope with intro/outro sections, plus the tone balance against the set."""
    fig = _figure(9.0, 5.6)
    ax1 = fig.add_subplot(2, 1, 1)
    _style(ax1)
    times = np.asarray(profile.get("envelope_times") or [], dtype=float)
    env = np.asarray(profile.get("envelope") or [], dtype=float)
    duration = float(profile.get("duration", times[-1] if len(times) else 0.0))
    if len(env):
        env_db = 20 * np.log10(np.maximum(env, 1e-6) / max(float(np.max(env)), 1e-6))
        ax1.fill_between(times, env_db, -60, color=BLUE, alpha=0.10, linewidth=0)
        ax1.plot(times, env_db, color=BLUE, linewidth=2, solid_capstyle="round")
        ax1.set_ylim(-45, 3)
    for a, b in ((profile.get("intro_start"), profile.get("intro_end")), (profile.get("outro_start"), profile.get("outro_end"))):
        if a is not None and b is not None:
            ax1.axvspan(float(a), float(b), color=BLUE_LIGHT, alpha=0.35, linewidth=0)
            ax1.axvline(float(a), color=GRAY, linewidth=1)
            ax1.axvline(float(b), color=GRAY, linewidth=1)
    if profile.get("intro_end") is not None:
        ax1.text(float(profile["intro_start"]), 1.5, "intro", fontsize=8, color=TEXT2, ha="left", va="bottom")
    if profile.get("outro_start") is not None:
        ax1.text(float(profile["outro_end"]), 1.5, "outro", fontsize=8, color=TEXT2, ha="right", va="bottom")
    ax1.set_xlim(0, duration or 1)
    ticks = np.arange(0, duration + 1, 60 if duration > 240 else 30) if duration else [0]
    ax1.set_xticks(ticks)
    ax1.set_xticklabels([_fmt_time(v) for v in ticks])
    ax1.set_ylabel("Energy (dB rel. peak)")
    m = profile.get("mastering") or {}
    head = f"{_short(profile.get('filename', ''), 40)} — {float(profile.get('bpm') or 0):.1f} BPM · {profile.get('key') or '-'} · energy {float(profile.get('energy_level') or 0):.1f}/10"
    if m.get("lufs") is not None:
        head += f"\n{m['lufs']:.1f} LUFS · true peak {m['true_peak_db']:+.1f} dBTP · PLR {m['plr']:.1f} dB · mastering score {m['score']:.0f}/100"
    ax1.set_title(head, loc="left", fontsize=10)

    ax2 = fig.add_subplot(2, 1, 2)
    _mastering_balance_axes(ax2, m, set_median_balance)
    flags = m.get("flags") or []
    if flags:
        ax2.text(0.0, -0.32, "! " + "\n! ".join(flags[:4]), transform=ax2.transAxes, fontsize=8,
                 color=TEXT2, va="top", ha="left")
    fig.tight_layout()
    return fig


BAND_LABELS = [("sub", "Sub (20-60 Hz)"), ("low", "Low (60-250)"), ("low_mid", "Low-mid (250-800)"),
               ("mid", "Mid (0.8-2.5 kHz)"), ("high_mid", "High-mid (2.5-6 kHz)"), ("high", "High (6-20 kHz)")]


def _mastering_balance_axes(ax, report: Dict, set_median: Optional[Dict[str, float]]):
    _style(ax, grid_axis="x")
    balance = (report or {}).get("balance_db") or {}
    if not balance:
        ax.text(0.5, 0.5, "No mastering data", transform=ax.transAxes, ha="center", color=TEXT2)
        ax.set_yticks([])
        return
    reference = set_median or balance
    labels, values = [], []
    for key, label in BAND_LABELS:
        labels.append(label)
        values.append(float(balance.get(key, 0.0)) - float(reference.get(key, 0.0)))
    y = np.arange(len(labels))[::-1]
    colors = [BLUE if v >= 0 else RED for v in values]
    ax.barh(y, values, height=0.55, color=colors, linewidth=0)
    ax.axvline(0, color=GRAY, linewidth=1)
    for yi, v in zip(y, values):
        ax.text(v + (0.3 if v >= 0 else -0.3), yi, f"{v:+.1f} dB", va="center",
                ha="left" if v >= 0 else "right", fontsize=8, color=TEXT2)
    lim = max(6.0, max(abs(v) for v in values) * 1.3)
    ax.set_xlim(-lim, lim)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Band level vs. set median (dB)" if set_median else "Band level vs. this track's average (dB)")
    ax.set_title("Tone balance (blue = more than the set, red = less)", loc="left", fontsize=10)


def mastering_balance(report: Dict, set_median: Optional[Dict[str, float]] = None) -> Figure:
    fig = _figure(7.0, 3.2)
    ax = fig.add_subplot(1, 1, 1)
    _mastering_balance_axes(ax, report, set_median)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ pre-master
def premaster_before_after(results: Sequence[Dict], target_lufs: float = -14.0, ceiling_db: float = -1.0) -> Figure:
    """What the pre-master pass did: loudness and true peak before -> after, per track."""
    ok = [r for r in results if "error" not in r]
    n = len(ok)
    fig = _figure(9.0, max(3.0, 0.5 * n + 1.8))
    ax1 = fig.add_subplot(1, 2, 1)
    ax2 = fig.add_subplot(1, 2, 2, sharey=ax1)
    for ax in (ax1, ax2):
        _style(ax, grid_axis="x")
    y = np.arange(n)[::-1]
    names = [_short(os.path.basename(r["output"]), 22) for r in ok]

    def dumbbell(ax, before, after, ref, ref_label, xlabel):
        ax.axvline(ref, color=GRAY, linewidth=1)
        ax.text(ref, n - 0.35, ref_label, fontsize=8, color=TEXT2, ha="center", va="bottom")
        for yi, b, a in zip(y, before, after):
            ax.plot([b, a], [yi, yi], color=GRID, linewidth=2, solid_capstyle="round")
        ax.scatter(before, y, s=70, color=BLUE_LIGHT, edgecolors=SURFACE, linewidths=2, zorder=3, label="Before")
        ax.scatter(after, y, s=70, color=BLUE_DARK, edgecolors=SURFACE, linewidths=2, zorder=4, label="After")
        ax.set_xlabel(xlabel)
        ax.set_ylim(-0.7, n - 0.2)

    lufs_b = [float(r["before"]["lufs"] if r["before"]["lufs"] is not None else -70) for r in ok]
    lufs_a = [float(r["after"]["lufs"] if r["after"]["lufs"] is not None else -70) for r in ok]
    dumbbell(ax1, lufs_b, lufs_a, target_lufs, f"target {target_lufs:g} LUFS", "Integrated loudness (LUFS)")
    ax1.set_yticks(y)
    ax1.set_yticklabels(names, fontsize=8)
    ax1.set_title("Loudness: before -> after", loc="left", fontsize=11)
    ax1.legend(loc="lower left", frameon=False, fontsize=8, labelcolor=TEXT2)

    tp_b = [float(r["before"]["true_peak_db"]) for r in ok]
    tp_a = [float(r["after"]["true_peak_db"]) for r in ok]
    dumbbell(ax2, tp_b, tp_a, ceiling_db, f"ceiling {ceiling_db:g} dBTP", "True peak (dBTP)")
    clipped = [yi for yi, r in zip(y, ok) if r["before"].get("clip_runs", 0) > 0]
    if clipped:
        ax2.scatter([max(tp_b) + 1.2] * len(clipped), clipped, marker="x", s=40, color=STATUS_CRITICAL,
                    linewidths=1.5, label="was clipping")
        ax2.legend(loc="lower left", frameon=False, fontsize=8, labelcolor=TEXT2)
    ax2.tick_params(labelleft=False)
    ax2.set_title("True peak: before -> after", loc="left", fontsize=11)
    fig.tight_layout()
    return fig


def save(fig: Figure, path: str) -> str:
    fig.savefig(path, dpi=110, facecolor=SURFACE)
    return path
