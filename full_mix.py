"""Render a planned set as one continuous WAV mix."""

import math
import os
import shutil
import tempfile
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np
import soundfile as sf
from scipy import signal

import transition_fx as tfx
from fx_render import render_set, transition_beats
from mastering import load_audio
from i18n import tr


def _active(entry: Optional[Dict]) -> bool:
    return any(fx.get("enabled", True) for fx in (entry or {}).get("effects") or [])


def _write_segment(writer, audio: np.ndarray, source_sr: int, start_s: float, end_s: float,
                   target_sr: int, progress: Optional[Callable], cancel: Optional[Callable], state: List[int],
                   total: int, detail: str) -> None:
    first = max(0, min(len(audio), int(round(start_s * source_sr))))
    last = max(first, min(len(audio), int(round(end_s * source_sr))))
    segment = audio[first:last]
    if not len(segment):
        return
    if source_sr != target_sr:
        divisor = math.gcd(source_sr, target_sr)
        segment = signal.resample_poly(segment, target_sr // divisor, source_sr // divisor, axis=0).astype(np.float32)
    for offset in range(0, len(segment), 65536):
        if cancel:
            cancel()
        chunk = segment[offset:offset + 65536]
        writer.write(chunk)
        state[0] += len(chunk)
        if progress:
            progress(min(state[0], total), total, detail)


def render_full_mix(profiles: Sequence[Dict], playback_profiles: Sequence[Dict],
                    fx_for_pair: Callable[[str, str], Optional[Dict]], bases: Dict[str, str],
                    existing_fx: Dict[str, Dict], output_path: str,
                    sample_rate: int = 44100, bit_depth: int = 24,
                    progress: Optional[Callable[[int, int, str], None]] = None,
                    cancel: Optional[Callable[[], None]] = None) -> Dict:
    """Render ordered transition profiles to an atomic, stereo integer PCM WAV file."""
    profiles = [dict(p) for p in profiles]
    playback_profiles = [dict(p) for p in playback_profiles]
    if len(profiles) < 2:
        raise ValueError(tr("The set needs at least two tracks"))
    if len(playback_profiles) != len(profiles):
        raise ValueError(tr("Playback source list does not match the set list"))
    if sample_rate not in (44100, 48000) or bit_depth not in (16, 24, 32):
        raise ValueError(tr("Unsupported WAV format"))
    input_paths = {p["file_path"] for p in profiles} | {p["file_path"] for p in playback_profiles} | set(bases.values()) | {
        row["output"] for row in existing_fx.values() if row.get("output")}
    target = os.path.normcase(os.path.abspath(output_path))
    if any(target == os.path.normcase(os.path.abspath(path)) or
           (os.path.exists(output_path) and os.path.exists(path) and os.path.samefile(output_path, path))
           for path in input_paths):
        raise ValueError(tr("The mix WAV cannot replace one of its source tracks"))

    active_pairs = [(i, fx_for_pair(profiles[i]["file_path"], profiles[i + 1]["file_path"]) or {})
                    for i in range(len(profiles) - 1)]
    active_pairs = [(i, entry) for i, entry in active_pairs if _active(entry)]
    rendered_fx = dict(existing_fx)
    temp_fx_dir = None
    temp_output = None
    try:
        if any(profiles[i]["file_path"] not in rendered_fx or profiles[i + 1]["file_path"] not in rendered_fx
               for i, _ in active_pairs):
            temp_fx_dir = tempfile.mkdtemp(prefix="dynamix-full-mix-fx-")
            output_names = {p["file_path"]: f"{i:04d}.wav" for i, p in enumerate(profiles)}

            def fx_progress(done, total, detail):
                if cancel:
                    cancel()
                if progress:
                    progress(0, 1, "FX: " + detail)

            results, problems = render_set(
                profiles, fx_for_pair, bases, temp_fx_dir, fmt="wav",
                progress=fx_progress, output_names=output_names)
            required = {profiles[i]["file_path"] for i, _ in active_pairs}
            required.update(profiles[i + 1]["file_path"] for i, _ in active_pairs)
            rendered_fx.update({r["source"]: r for r in results})
            missing = required - set(rendered_fx)
            failed_transitions = [problem for problem in problems if problem.startswith("transition ")]
            if missing or failed_transitions:
                details = "; ".join((failed_transitions or problems)[:3])
                raise RuntimeError(tr("Could not render transition FX for every track: {details}",
                                      details=details or tr("No transition FX copies were created")))

        audio_paths, play_profiles = {}, []
        temp_rendered = {r["source"]: r for r in results} if temp_fx_dir else {}
        for profile, playback in zip(profiles, playback_profiles):
            source = profile["file_path"]
            rendered = temp_rendered.get(source)
            if rendered:
                path = rendered["output"]
                updated = dict(playback, filename=os.path.basename(path))
                for key in ("intro_start", "intro_end", "outro_start", "outro_end", "duration"):
                    if key in rendered:
                        updated[key] = rendered[key]
            else:
                path = playback["file_path"]
                updated = dict(playback, filename=os.path.basename(path))
            audio_paths[source] = path
            play_profiles.append(updated)

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        fd, temp_output = tempfile.mkstemp(prefix=".dynamix-mix-", suffix=".wav", dir=os.path.dirname(os.path.abspath(output_path)))
        os.close(fd)
        bit_subtype = f"PCM_{bit_depth}"
        durations = [float(p.get("duration") or 0.0) for p in play_profiles]
        estimated_total = max(1, int(sum(durations) * sample_rate))
        state = [0]
        profile_a = play_profiles[0]
        audio_a, sr_a = load_audio(audio_paths[profiles[0]["file_path"]])
        audio_a = tfx.to_stereo(audio_a)
        a_pos = 0.0

        with sf.SoundFile(temp_output, mode="w", samplerate=sample_rate, channels=2,
                          format="WAV", subtype=bit_subtype) as writer:
            for i in range(len(profiles) - 1):
                if cancel:
                    cancel()
                original_a, original_b = profiles[i], profiles[i + 1]
                profile_b = play_profiles[i + 1]
                audio_b, sr_b = load_audio(audio_paths[original_b["file_path"]])
                audio_b = tfx.to_stereo(audio_b)
                beats_a, beats_b = transition_beats(original_a, original_b)
                entry = fx_for_pair(original_a["file_path"], original_b["file_path"]) or {}
                # The per-track FX renderer already baked this pair's nudge into its copy and cue positions.
                if _active(entry):
                    a_beat = beats_a[tfx.nearest_beat_index(beats_a, float(profile_a.get("outro_start", 0.0)))]
                    nudge = (float(profile_a.get("outro_start", 0.0)) - float(a_beat)) * 1000.0
                else:
                    nudge = float(entry.get("nudge_ms", 0.0))
                ctx = tfx.make_context(audio_a, sr_a, beats_a,
                                       float(profile_a.get("outro_start", profile_a.get("duration", 0.0))),
                                       float(profile_a.get("outro_end", profile_a.get("duration", 0.0))),
                                       audio_b, sr_b, beats_b,
                                       float(profile_b.get("intro_start", 0.0)), nudge)
                tfx.sync_outgoing_to_incoming(ctx)
                b_intro_end = max(float(profile_b.get("intro_end", 0.0)),
                                  ctx.junction_b + (ctx.a_end - ctx.junction_a))
                clip, clip_sr = tfx.preview_mix(ctx, b_intro_end, "short")
                clip_start = max(ctx.a_beat(-8), ctx.a_offset)
                clip_duration = len(clip) / clip_sr
                if clip_start + 1.0 / sr_a < a_pos:
                    raise RuntimeError(tr("Transition overlaps the previous one on a short track"))
                _write_segment(writer, audio_a, sr_a, a_pos, clip_start, sample_rate, progress, cancel,
                               state, estimated_total, os.path.basename(original_a["file_path"]))
                _write_segment(writer, clip, clip_sr, 0.0, clip_duration, sample_rate, progress, cancel,
                               state, estimated_total, f"{os.path.basename(original_a['file_path'])} → "
                               f"{os.path.basename(original_b['file_path'])}")
                b_pos = max(0.0, clip_start - ctx.junction_a + ctx.junction_b + clip_duration)
                profile_a, audio_a, sr_a, a_pos = profile_b, audio_b, sr_b, b_pos
                del ctx, clip

            _write_segment(writer, audio_a, sr_a, a_pos, len(audio_a) / sr_a, sample_rate, progress, cancel,
                           state, estimated_total, os.path.basename(profiles[-1]["file_path"]))
        if cancel:
            cancel()
        if progress:
            progress(estimated_total, estimated_total, os.path.basename(output_path))
        os.replace(temp_output, output_path)
        temp_output = None
        return {"file": output_path, "sample_rate": sample_rate, "bit_depth": bit_depth,
                "duration": state[0] / sample_rate}
    finally:
        if temp_output and os.path.exists(temp_output):
            os.remove(temp_output)
        if temp_fx_dir:
            shutil.rmtree(temp_fx_dir, ignore_errors=True)
