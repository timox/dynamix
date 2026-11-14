# Full Mix WAV Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a final Set Builder action that creates a continuous mix as WAV.

**Architecture:** Add a focused renderer that lays planned tracks on a shared timeline, applies existing FX rendering and Mixxx-style equal-power transition fades, then writes bounded chunks to a temporary WAV and atomically publishes it. Integrate it as a workflow step using the existing project source-selection and background task patterns.

**Tech Stack:** Python, NumPy, SoundFile, existing `fx_render.py`, `transition_fx.py`, Tkinter, `TaskManager`.

**Spec:** `docs/superpowers/specs/2026-11-11-full-mix-wav-design.md`

## Global Constraints

- Output is stereo integer PCM WAV at 44.1 or 48 kHz, 16/24/32 bits; default 44.1 kHz and 24 bits.
- Preserve planned order, Mixxx “Full Intro + Outro” equal-power fades, nudge, A-end markers, and configured transition FX.
- Reuse valid FX copies; if FX are pending, create temporary copies with the existing FX renderer without applying FX twice.
- Follow the existing `use_premaster` and playback source selection rules.
- Rendering runs in a cancellable background task, reports progress, streams output, and does not leave partial final files.
- No new dependencies, mastering controls, command-line mode, or changes to playlist/Mixxx export behavior.

## Review Focus

- Different source sample rates and stereo/mono input: resample and write valid stereo output.
- FX already rendered versus pending FX: each configured effect is audible once.
- Cancellation or write failure: no partial final file remains and an existing target is preserved until success.
- Long set: output memory use must not grow with total duration.
- A-end/nudge and short or missing source audio: timeline must follow the transition plan or fail with a useful error.

---

### Task 1: Continuous mix renderer

**Files:**
- Create: `full_mix.py`
- Modify: `fx_render.py` to let this export give temporary FX copies collision-safe output names.

**Interfaces:**
- Consumes: `SetProject.rendered_profiles`, `fx_render.render_set`, transition profiles and FX settings, `transition_fx` cue/fade behavior.
- Produces: `render_full_mix(profiles, playback_profiles, fx_for_pair, bases, existing_fx, output_path, sample_rate, bit_depth, progress, cancel) -> dict`, returning output metadata; write only to a sibling temporary file and publish after success.

- [x] Add the smallest core implementation that renders a project timeline incrementally, mixes overlapping tracks with the planned equal-power fades, applies the selected PCM subtype, reports progress, checks cancellation between chunks, and cleans temporary audio on failure.
- [x] Reuse existing per-track FX copies; use a temporary directory and `fx_render.render_set` only when configured FX are pending.
- [x] Inspect the renderer and its call sites for format, cancellation, cleanup, and memory lifetime consistency with the spec.

### Task 2: Final workflow action

**Files:**
- Modify: `set_project.py` (append the optional full-mix workflow state after Mixxx export).
- Modify: `set_builder.py` (output options, destination dialog, task launch, progress, report/status, stale-state handling).
- Modify: `tasks.py` and `tasks_tab.py` (describe cooperative stop points as tracks or audio chunks).
- Modify: `locales/fr/set_builder.json` and `locales/fr/tabs.json` (French strings for the new control and output options).
- Modify: `GUI_README.md` and `README.md` (briefly document the action and output settings).

**Interfaces:**
- Consumes: `full_mix.render_full_mix(...)` from Task 1 and `TaskManager` progress/cancellation.
- Produces: final workflow step “Create full mix WAV”, offering 44.1/48 kHz and 16/24/32 bits, defaulting to 44.1 kHz/24 bits.

- [x] Add the step after `mixxx` so existing `invalidate_from()` rules mark it stale when earlier project inputs change.
- [x] Add the save dialog with default `<project name>.wav` under `exports/`, confirm replacement, then run rendering as a cancellable background task.
- [x] On success mark the step with the file and format and report the path; on cancellation/failure preserve project step state and surface the existing task error/status.
- [x] Update French strings and user documentation, then inspect all changed files for consistency with the approved spec.
