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

from matplotlib.figure import Figure
import numpy as np

from i18n import tr, tr_text

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


_SCALE = 1.0  # GUI font size / default size: charts are drawn at a higher resolution to match


def set_scale(scale: float) -> None:
    """Draw the next figures `scale` times bigger on screen (text, lines and designed height)."""
    global _SCALE
    _SCALE = max(0.5, float(scale))


def _figure(width: float = 9.0, height: float = 5.0) -> Figure:
    fig = Figure(figsize=(width, height), dpi=100 * _SCALE)
    fig.patch.set_facecolor(SURFACE)
    return fig


def _finish(fig: Figure) -> Figure:
    """Layout that is recomputed at every draw, so labels stay inside when the window resizes."""
    try:
        fig.set_layout_engine("constrained")
        fig.get_layout_engine().set(w_pad=0.08, h_pad=0.08, hspace=0.06, wspace=0.06)
    except Exception:  # older matplotlib
        fig.tight_layout()
    return fig


def pixel_height(fig: Figure) -> int:
    """Height in pixels the figure was designed for (used to size its Tk canvas)."""
    return int(fig.get_size_inches()[1] * fig.dpi)


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
        ax1.plot(x, targets, color=GRAY, linewidth=2, solid_capstyle="round", label=tr("Target curve"))
    ax1.plot(x, energy, color=BLUE, linewidth=2, solid_capstyle="round", solid_joinstyle="round", label=tr("Energy level"))
    ax1.scatter(x, energy, s=70, color=BLUE, edgecolors=SURFACE, linewidths=2, zorder=3)
    if n:
        i_max = int(np.argmax(energy))
        ax1.annotate(f"{energy[i_max]:.1f}", (x[i_max], energy[i_max]), textcoords="offset points",
                     xytext=(0, 9), ha="center", fontsize=8, color=TEXT2)
        ax1.annotate(f"{energy[0]:.1f}", (x[0], energy[0]), textcoords="offset points",
                     xytext=(-8, -3), ha="right", fontsize=8, color=TEXT2)
    ax1.set_ylim(0, 10.5)
    ax1.set_yticks([0, 2, 4, 6, 8, 10])
    ax1.set_ylabel(tr("Energy (1-10)"))
    ax1.set_title(tr("Set energy curve"), loc="left", fontsize=11)
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
    ax2.set_title(tr("Tempo along the set"), loc="left", fontsize=11)
    ax2.set_xticks(x)
    ax2.set_xticklabels(names, rotation=30, ha="right", fontsize=8)
    ax2.set_xlim(0.5, n + 0.5 if n else 1.5)
    return _finish(fig)


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


def set_timeline(profiles: Sequence[Dict], transitions: Optional[Sequence[Dict]] = None,
                 fx_labels: Optional[Dict[int, str]] = None) -> Figure:
    """Where each track plays in the set, with intro/outro sections, transition scores and transition FX."""
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
                ax.text(x, y_bot - height / 2 - 0.08, tr("score {score:.0f}", score=score), ha="center", va="top",
                        fontsize=7, color=TEXT2)
            label = (fx_labels or {}).get(i)
            if label:
                ax.text(x, y_top + height / 2 + 0.06, label, ha="center", va="bottom", fontsize=7, color=BLUE)
    total = starts[-1] + float(profiles[-1].get("duration", 0.0)) if n else 0.0
    ax.set_xlim(0, total * 1.45 if total else 1)
    ax.set_ylim(0.3, n + 0.7)
    ax.set_yticks([])
    if total:
        step = max(60.0, np.ceil(total / 8.0 / 60.0) * 60.0)
        ticks = np.arange(0, total + step, step)
    else:
        ticks = [0]
    ax.set_xticks(ticks)
    ax.set_xticklabels([_fmt_time(v) for v in ticks])
    ax.set_xlabel(tr("Set time (min:sec)"))
    ax.set_title(tr("Set map  (light = intro/outro, blue = body, gray = skipped tail)"), loc="left", fontsize=11)
    return _finish(fig)


# ------------------------------------------------------------------ track detail
def track_detail(profile: Dict, set_median_balance: Optional[Dict[str, float]] = None) -> Figure:
    """Energy envelope with intro/outro sections, plus the tone balance against the set."""
    fig = _figure(9.0, 8.6)
    gs = fig.add_gridspec(3, 1, height_ratios=[1.3, 0.9, 1.0])
    ax1 = fig.add_subplot(gs[0])
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
        ax1.text(float(profile["intro_start"]) + 0.5, -43.5, "intro", fontsize=8, color=TEXT2, ha="left", va="bottom")
    if profile.get("outro_start") is not None:
        ax1.text(float(profile["outro_end"]) - 0.5, -43.5, "outro", fontsize=8, color=TEXT2, ha="right", va="bottom")
    ax1.set_xlim(0, duration or 1)
    ticks = np.arange(0, duration + 1, 60 if duration > 240 else 30) if duration else [0]
    ax1.set_xticks(ticks)
    ax1.set_xticklabels([_fmt_time(v) for v in ticks])
    ax1.set_ylabel(tr("Energy (dB rel. peak)"))
    m = profile.get("mastering") or {}
    head = tr("{name} — {bpm:.1f} BPM · {key} · energy {energy:.1f}/10", name=_short(profile.get('filename', ''), 40),
              bpm=float(profile.get('bpm') or 0), key=profile.get('key') or '-', energy=float(profile.get('energy_level') or 0))
    if m.get("lufs") is not None:
        head += "\n" + tr("{lufs:.1f} LUFS · true peak {true_peak:+.1f} dBTP · PLR {plr:.1f} dB · mastering score {score:.0f}/100",
                          lufs=m['lufs'], true_peak=m['true_peak_db'], plr=m['plr'], score=m['score'])
    ax1.set_title(head, loc="left", fontsize=10)

    sub = gs[1].subgridspec(1, 2, width_ratios=[1.0, 1.0], wspace=0.3)
    ax_phase = fig.add_subplot(sub[0])
    _phase_axes(ax_phase, m)
    ax_bass = fig.add_subplot(sub[1])
    _bass_width_axes(ax_bass, m)

    ax2 = fig.add_subplot(gs[2])
    _mastering_balance_axes(ax2, m, set_median_balance)
    flags = m.get("flags") or []
    if flags:
        ax2.text(0.0, -0.30, "! " + "\n! ".join(tr_text(f) for f in flags[:5]), transform=ax2.transAxes, fontsize=8,
                 color=TEXT2, va="top", ha="left")
    return _finish(fig)


def _bass_width_axes(ax, report: Dict):
    """Side/mid energy per low band: below the mono threshold the bass is effectively mono."""
    _style(ax, grid_axis="y")
    phase = (report or {}).get("phase") or {}
    bands = phase.get("bass_width_bands") or {}
    if not phase.get("stereo") or not bands:
        ax.text(0.5, 0.5, tr("No bass width data"), transform=ax.transAxes, ha="center", color=TEXT2)
        ax.set_xticks([])
        ax.set_yticks([])
        return
    from mastering import MONO_BASS_THRESHOLD_DB
    names = list(bands.keys())
    values = [max(-40.0, float(bands[n])) for n in names]
    x = np.arange(len(names))
    colors = [BLUE if v <= MONO_BASS_THRESHOLD_DB else RED for v in values]
    ax.bar(x, [v + 40 for v in values], bottom=-40, width=0.6, color=colors, linewidth=0)
    ax.axhline(MONO_BASS_THRESHOLD_DB, color=GRAY, linewidth=1)
    ax.set_ylim(-40, 2)
    ax.set_yticks([-40, -30, -20, -10, 0])
    ax.set_yticklabels(["-40", "-30", "-20 mono", "-10", "0"], fontsize=7)
    ax.set_xticks(x)
    ax.set_xticklabels([n.split("-")[0] for n in names], fontsize=7)
    ax.set_xlabel(tr("band start (Hz)"), fontsize=8)
    ax.set_ylabel(tr("side vs mid (dB)"), fontsize=8)
    below = phase.get("mono_below_hz") or 0
    verdict = tr("mono below {hz:.0f} Hz", hz=below) if below else tr("NOT mono")
    ax.set_title(tr("Bass width: {verdict} (red = stereo band)", verdict=verdict), loc="left", fontsize=10)


def _phase_axes(ax, report: Dict):
    """L/R correlation overall, in the bass and in the highs (-1 inverted .. +1 in phase), plus mono loss."""
    _style(ax, grid_axis="x")
    phase = (report or {}).get("phase") or {}
    if not phase:
        ax.text(0.5, 0.5, tr("No phase data (run the mastering check)"), transform=ax.transAxes, ha="center", color=TEXT2)
        ax.set_yticks([])
        return
    if not phase.get("stereo"):
        ax.text(0.5, 0.5, tr("Mono file: no stereo phase to check"), transform=ax.transAxes, ha="center", color=TEXT2)
        ax.set_yticks([])
        ax.set_title(tr("Stereo phase"), loc="left", fontsize=10)
        return
    rows = [(tr("L/R overall"), phase.get("correlation", 1.0)),
            (tr("Bass < 150 Hz"), phase.get("correlation_low", 1.0)),
            (tr("Highs > 1 kHz"), phase.get("correlation_high", 1.0))]
    y = np.arange(len(rows))[::-1]
    values = [float(v) for _, v in rows]
    ax.barh(y, values, height=0.5, color=[BLUE if v >= 0 else RED for v in values], linewidth=0)
    ax.axvline(0, color=GRAY, linewidth=1)
    ax.axvspan(-1.05, 0.3, color=STATUS_WARNING, alpha=0.08, linewidth=0)  # zone where mono compatibility suffers
    for yi, v in zip(y, values):
        if abs(v) > 0.8:  # no room beyond the bar end: label inside, in white
            ax.text(v - (0.03 if v >= 0 else -0.03), yi, f"{v:+.2f}", va="center", ha="right" if v >= 0 else "left",
                    fontsize=8, color=SURFACE)
        else:
            ax.text(v + (0.03 if v >= 0 else -0.03), yi, f"{v:+.2f}", va="center", ha="left" if v >= 0 else "right",
                    fontsize=8, color=TEXT2)
    ax.set_xlim(-1.05, 1.05)
    ax.set_xticks([-1, 0, 1])
    ax.set_xticklabels([tr("-1\ninverted"), "0", tr("+1\nin phase")], fontsize=8)
    ax.set_yticks(y)
    ax.set_yticklabels([label for label, _ in rows], fontsize=8)
    ax.set_xlabel(tr("correlation (shaded: cancels in mono)"), fontsize=8)
    mono = phase.get("mono_loss_db", 0.0)
    comb = phase.get("comb_delay_ms")
    if comb:
        title = tr("Stereo phase (mono fold-down {mono:+.1f} dB, comb ≈ {comb:.2f} ms)", mono=mono, comb=comb)
    else:
        title = tr("Stereo phase (mono fold-down {mono:+.1f} dB)", mono=mono)
    ax.set_title(title, loc="left", fontsize=10)


BAND_LABELS = [("sub", "Sub (20-60 Hz)"), ("low", "Low (60-250)"), ("low_mid", "Low-mid (250-800)"),
               ("mid", "Mid (0.8-2.5 kHz)"), ("high_mid", "High-mid (2.5-6 kHz)"), ("high", "High (6-20 kHz)")]


def _mastering_balance_axes(ax, report: Dict, set_median: Optional[Dict[str, float]]):
    _style(ax, grid_axis="x")
    balance = (report or {}).get("balance_db") or {}
    if not balance:
        ax.text(0.5, 0.5, tr("No mastering data"), transform=ax.transAxes, ha="center", color=TEXT2)
        ax.set_yticks([])
        return
    reference = set_median or balance
    labels, values = [], []
    for key, label in BAND_LABELS:
        labels.append(tr(label))  # the BAND_LABELS texts are in the catalog
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
    ax.set_xlabel(tr("Band level vs. set median (dB)") if set_median else tr("Band level vs. this track's average (dB)"))
    ax.set_title(tr("Tone balance (blue = more than the set, red = less)"), loc="left", fontsize=10)


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
        ax.scatter(before, y, s=70, color=BLUE_LIGHT, edgecolors=SURFACE, linewidths=2, zorder=3, label=tr("Before"))
        ax.scatter(after, y, s=70, color=BLUE_DARK, edgecolors=SURFACE, linewidths=2, zorder=4, label=tr("After"))
        ax.set_xlabel(xlabel)
        ax.set_ylim(-0.7, n - 0.2)

    lufs_b = [float(r["before"]["lufs"] if r["before"]["lufs"] is not None else -70) for r in ok]
    lufs_a = [float(r["after"]["lufs"] if r["after"]["lufs"] is not None else -70) for r in ok]
    dumbbell(ax1, lufs_b, lufs_a, target_lufs, tr("target {lufs:g} LUFS", lufs=target_lufs), tr("Integrated loudness (LUFS)"))
    ax1.set_yticks(y)
    ax1.set_yticklabels(names, fontsize=8)
    ax1.set_title(tr("Loudness: before -> after"), loc="left", fontsize=11)
    ax1.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, frameon=False, fontsize=8, labelcolor=TEXT2)

    tp_b = [float(r["before"]["true_peak_db"]) for r in ok]
    tp_a = [float(r["after"]["true_peak_db"]) for r in ok]
    dumbbell(ax2, tp_b, tp_a, ceiling_db, tr("ceiling {db:g} dBTP", db=ceiling_db), tr("True peak (dBTP)"))
    clipped = [yi for yi, r in zip(y, ok) if r["before"].get("clip_runs", 0) > 0]
    if clipped:
        ax2.scatter([max(tp_b) + 1.2] * len(clipped), clipped, marker="x", s=40, color=STATUS_CRITICAL,
                    linewidths=1.5, label=tr("was clipping"))
        ax2.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, frameon=False, fontsize=8, labelcolor=TEXT2)
    ax2.tick_params(labelleft=False)
    ax2.set_title(tr("True peak: before -> after"), loc="left", fontsize=11)
    return _finish(fig)


def save(fig: Figure, path: str) -> str:
    fig.savefig(path, dpi=110, facecolor=SURFACE)
    return path


# ------------------------------------------------------------------ band dynamics
def band_dynamics(report: Dict) -> Figure:
    """Band envelopes over time (200-500 Hz emphasised), low-mid masking, and the resonance spectrum."""
    fig = _figure(9.0, 8.0)
    gs = fig.add_gridspec(3, 1, height_ratios=[1.2, 0.8, 1.0])
    chart = report.get("chart") or {}
    times = np.asarray(chart.get("times") or [], dtype=float)
    bands = chart.get("bands") or {}
    duration = float(times[-1]) if len(times) else 1.0

    ax1 = fig.add_subplot(gs[0])
    _style(ax1)
    for name, label in (("low", "60-120 Hz"), ("mid", "0.5-2 kHz")):
        if name in bands:
            ax1.plot(times, bands[name], color=GRAY, linewidth=1.5, solid_capstyle="round", label=label)
    if "mud" in bands:
        ax1.plot(times, bands["mud"], color=BLUE, linewidth=2, solid_capstyle="round", label="200-500 Hz")
    ax1.set_ylabel(tr("band level (dBFS)"))
    ax1.set_xlim(0, duration)
    ticks = np.arange(0, duration + 1, 60 if duration > 240 else 30) if duration else [0]
    ax1.set_xticks(ticks)
    ax1.set_xticklabels([_fmt_time(v) for v in ticks])
    ax1.legend(loc="center right", frameon=False, fontsize=8, labelcolor=TEXT2, ncol=1)
    st = (report.get("stats") or {}).get("mud") or {}
    rel = report.get("release_s")
    if rel:
        title = tr("Band tracking — 200-500 Hz range {range:.1f} dB, pulse {pulse:.2f} (release {release:.0f} ms)",
                   range=st.get('range_db', 0), pulse=st.get('beat_modulation', 0), release=rel * 1000)
    else:
        title = tr("Band tracking — 200-500 Hz range {range:.1f} dB, pulse {pulse:.2f}",
                   range=st.get('range_db', 0), pulse=st.get('beat_modulation', 0))
    ax1.set_title(title, loc="left", fontsize=10)

    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    _style(ax2)
    masking = np.asarray(chart.get("masking") or [], dtype=float)
    mud = report.get("mud") or {}
    if len(masking):
        median = float(mud.get("excess_median_db", np.median(masking)))
        ax2.fill_between(times, masking, median, where=masking > median, color=RED, alpha=0.25, linewidth=0)
        ax2.plot(times, masking, color=BLUE, linewidth=1.5)
        ax2.axhline(median, color=GRAY, linewidth=1)
        ax2.axhline(median + 6, color=GRAY, linewidth=1)
        ax2.text(duration, median + 6.3, tr("build-up (+6 dB)"), fontsize=7, color=TEXT2, ha="right", va="bottom")
    ax2.set_ylabel(tr("200-500 vs neighbours (dB)"))
    ax2.set_title(tr("Low-mid masking — typical {typical:+.0f} dB, worst {worst:+.0f} dB, build-up {share:.0f}%",
                     typical=mud.get('excess_median_db', 0), worst=mud.get('excess_p90_db', 0),
                     share=mud.get('buildup_share', 0) * 100), loc="left", fontsize=10)
    ax2.set_xticks(ticks)
    ax2.set_xticklabels([_fmt_time(v) for v in ticks])

    ax3 = fig.add_subplot(gs[2])
    _style(ax3)
    f = np.asarray(chart.get("spectrum_hz") or [], dtype=float)
    r = np.asarray(chart.get("spectrum_residual_db") or [], dtype=float)
    if len(f):
        ax3.fill_between(f, r, 0, where=r > 0, color=BLUE, alpha=0.10, linewidth=0)
        ax3.plot(f, r, color=BLUE, linewidth=1.5)
        ax3.axhline(0, color=GRAY, linewidth=1)
        ax3.set_xscale("log")
        ax3.set_xlim(100, 800)
        ax3.set_xticks([100, 150, 200, 300, 400, 500, 600, 800])
        ax3.set_xticklabels(["100", "150", "200", "300", "400", "500", "600", "800"])
        ymax = max(8.0, float(np.max(r)) + 3)
        ax3.set_ylim(min(-6.0, float(np.min(r)) - 1), ymax)
        from band_analysis import resonance_note
        key = report.get("key")
        for res in (report.get("resonances") or [])[:4]:
            in_key = resonance_note(res["freq_hz"], key)["in_key"]
            ax3.scatter([res["freq_hz"]], [res["prominence_db"]], s=60, color=BLUE_DARK if in_key else RED,
                        edgecolors=SURFACE, linewidths=2, zorder=3)
        # label only the two strongest to avoid collisions; the others are in the notes
        for res in (report.get("resonances") or [])[:2]:
            n = resonance_note(res["freq_hz"], key)
            ax3.annotate(f"{res['freq_hz']:.0f} Hz ~ {n['note']}" + (f" ({n['degree']})" if n["in_key"] else ""),
                         (res["freq_hz"], res["prominence_db"]), textcoords="offset points", xytext=(6, 4), fontsize=8, color=TEXT2)
    else:
        ax3.text(0.5, 0.5, tr("Track too short for the resonance spectrum"), transform=ax3.transAxes, ha="center", color=TEXT2)
    ax3.set_xlabel("Hz")
    ax3.set_ylabel(tr("above spectral envelope (dB)"))
    n_res = len(report.get("resonances") or [])
    legend = tr("blue = note of {key}, red = other", key=report['key']) if report.get("key") else tr("red dots")
    ax3.set_title(tr("Resonances 100-800 Hz  —  {n} persistent peak(s) ({legend})", n=n_res, legend=legend), loc="left", fontsize=10)
    import textwrap
    lines = ([("! " + tr_text(l)) for l in (report.get("flags") or [])]
             + [tr("EQ: {suggestion}", suggestion=tr_text(sug)) for sug in (report.get("eq_suggestions") or [])])
    if report.get("verdict") == "mix":
        lines.insert(0, tr("MIX REVISION RECOMMENDED (a pre-master pass cannot fix this)"))
    if lines:
        wrapped = "\n".join("\n  ".join(textwrap.wrap(l, 78)) for l in lines[:6])
        ax3.text(0.0, -0.30, wrapped, transform=ax3.transAxes, fontsize=8, color=TEXT2, va="top", ha="left")
    return _finish(fig)


# ------------------------------------------------------------------ transition detail (FX tab)
VIOLET = "#7d5bc6"
VIOLET_LIGHT = "#bca9e8"
_BLOCK_COLORS = {"scratch_down": BLUE, "scratch_up": BLUE_DARK, "catchup": BLUE_LIGHT,
                 "source": BLUE_LIGHT, "repeat": BLUE, "tail": GRID, "sweep": BLUE, "hold": BLUE_LIGHT,
                 "release": BLUE_LIGHT, "wet": BLUE, "sample": BLUE}


def _waveform(ax, env: Optional[Dict], shift: float, x0: float, x1: float, color: str,
              gain=None, faint: Optional[str] = None) -> bool:
    """Peak waveform scaled to the view; with `gain` (t -> 0..1) the heard part is drawn over a faint full one."""
    if not env or not len(env.get("peak", [])):
        return False
    peak = np.asarray(env["peak"], dtype=float)
    t = env["t0"] + shift + np.arange(len(peak)) * env["dt"]
    keep = (t >= x0) & (t <= x1)
    if not keep.any():
        return False
    t, y = t[keep], peak[keep] / max(1e-6, float(peak[keep].max()))
    if gain is not None:
        if faint:
            ax.fill_between(t, -y, y, color=faint, linewidth=0)
        y = y * gain(t)
    ax.fill_between(t, -y, y, color=color, linewidth=0)
    return True


def transition_detail(layout: Dict, a_env: Optional[Dict] = None, b_env: Optional[Dict] = None,
                      result_env: Optional[Dict] = None) -> Figure:
    """
    One transition on a beat axis: A with its fade-out, B with its fade-in, one lane per effect (freeze repeats,
    filter sweep, echo and its tail, sample repeats) and the rendered result when there is one.
    layout: transition_fx.transition_layout; envelopes: transition_fx.peak_envelope (A and result in A seconds,
    B in B seconds, shifted by layout['b_shift']).
    """
    lanes = layout["lanes"]
    heights = [1.0, 1.0] + [0.42] * len(lanes) + ([1.0] if result_env else [])
    fig = _figure(9.0, 0.9 + 0.95 * sum(heights))
    gs = fig.add_gridspec(len(heights), 1, height_ratios=heights)
    axes = []
    for i in range(len(heights)):
        ax = fig.add_subplot(gs[i], sharex=axes[0] if axes else None)
        _style(ax, grid_axis="")
        ax.set_yticks([])
        axes.append(ax)
    j, a_end, fade = layout["junction"], layout["a_end"], layout["fade_len"]
    x0, x1 = layout["view"]
    span = max(1e-6, x1 - x0)
    def a_gain(tt):
        g = np.where(tt < j, 1.0, np.cos(np.clip((tt - j) / fade, 0.0, 1.0) * np.pi / 2))
        return np.where(tt >= a_end, 0.0, g)

    def b_gain(tt):
        return np.where(tt < j, 0.0, np.sin(np.clip((tt - j) / fade, 0.0, 1.0) * np.pi / 2))

    t = np.linspace(x0, x1, 400)
    for ax, env, shift, wave_color, faint, line_color, gain, name, note in (
            (axes[0], a_env, 0.0, BLUE_LIGHT, "#e4eefa", BLUE_DARK, a_gain, tr("A  (out)"), tr("A fades out")),
            (axes[1], b_env, layout["b_shift"], VIOLET_LIGHT, "#eee8f8", VIOLET, b_gain, tr("B  (in)"), tr("B fades in"))):
        if not _waveform(ax, env, shift, x0, x1, wave_color, gain=gain, faint=faint):
            ax.text(x0 + span * 0.01, 0.0, tr("waveform loading ..."), fontsize=8, color=TEXT2, va="center")
        ax.plot(t, gain(t), color=line_color, linewidth=1.5)
        ax.set_ylim(-1.05, 1.2)
        ax.set_ylabel(name, rotation=0, ha="right", va="center", fontsize=9)
        ax.text(min(x1 - span * 0.1, j + span * 0.01), 0.85, note, fontsize=8, color=line_color, ha="left", va="center")

    for n_lane, (ax, lane) in enumerate(zip(axes[2:], lanes)):
        ax.set_ylim(-0.5, 0.5)
        ax.set_ylabel(tr(lane["label"]), rotation=0, ha="right", va="center", fontsize=8)
        for n, blk in enumerate(lane["blocks"]):
            kind = blk["kind"]
            color = BLUE_DARK if kind in ("repeat", "sample") and n % 2 else _BLOCK_COLORS.get(kind, BLUE)
            width = max(0.0, blk["end"] - blk["start"])
            ax.barh(0.0, width, left=blk["start"], height=0.7, color=color, linewidth=0,
                    hatch="///" if kind == "tail" else None, edgecolor=GRAY if kind == "tail" else color)
            if blk.get("label") and width > span / 30:
                dark = color in (BLUE, BLUE_DARK)
                # fixed words of transition_fx ("captured", "tail", "held", ...) are in the catalog; a sample shows its file name
                text = blk["label"] if kind == "sample" else tr(blk["label"])
                ax.text(max(blk["start"], x0) + min(width, x1 - max(blk["start"], x0)) / 2, 0.0, text,
                        fontsize=7, color="white" if dark else TEXT, ha="center", va="center", clip_on=True)
        if lane.get("note"):
            ax.text(x0 + span * 0.01, 0.0, tr(lane["note"]), fontsize=8, color=TEXT2, va="center")

    if result_env:
        ax = axes[-1]
        _waveform(ax, result_env, 0.0, x0, x1, BLUE)
        ax.set_ylim(-1.05, 1.05)
        ax.set_ylabel(tr("Result"), rotation=0, ha="right", va="center", fontsize=9)

    for ax in axes:
        for tb, k in layout["beat_times"]:
            if x0 <= tb <= x1:
                ax.axvline(tb, color=GRID, linewidth=1.6 if k % 4 == 0 else 0.8, zorder=0)
        ax.axvline(j, color=TEXT, linewidth=1.3)
        if a_end > j + 1e-3:
            ax.axvline(a_end, color=GRAY, linewidth=1.0, linestyle="--")
        if abs(layout["planned_junction"] - j) > 1e-3:
            ax.axvline(layout["planned_junction"], color=GRAY, linewidth=1.0, linestyle=":")
        ax.set_xlim(x0, x1)
    for ax in axes[:-1]:
        ax.tick_params(labelbottom=False)
    top = axes[0]
    top.text(j, 1.22, tr("junction"), ha="center", va="bottom", fontsize=8, color=TEXT)
    if a_end > j + span * 0.06:
        top.text(a_end, 1.22, tr("A ends"), ha="center", va="bottom", fontsize=8, color=TEXT2)
    planned = layout["planned_junction"]
    if abs(planned - j) > 1e-3:
        near_a_end = a_end > j + span * 0.06 and abs(planned - a_end) < span * 0.12
        # written on the side away from the "A ends" label when the two lines are close
        top.text(planned, 1.22, tr("planned") + "  " if near_a_end and planned < a_end else "  " + tr("planned"),
                 ha="right" if near_a_end and planned < a_end else "left", va="bottom", fontsize=8, color=TEXT2)
    bars = [(tb, k) for tb, k in layout["beat_times"] if k % 4 == 0 and x0 <= tb <= x1]
    axes[-1].set_xticks([tb for tb, _ in bars])
    axes[-1].set_xticklabels(["J" if k == 0 else f"{k:+d}" for _, k in bars])
    axes[-1].set_xlabel(tr("Beats from the junction (1 beat = {period:.2f} s; thick lines = bars)", period=layout['period']))
    warnings = layout.get("warnings") or []
    top.set_title(tr("Transition") + (f"   ⚠ {tr_text(warnings[0])}" if warnings else ""), loc="left", fontsize=10,
                  color=STATUS_CRITICAL if warnings else TEXT, pad=14)
    return _finish(fig)
