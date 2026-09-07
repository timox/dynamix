# Set Workflow Rework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn the Playlist Manager tab into a guided, persistent "Set Builder" workflow: analyses are cached and never redone, the set proposal and every step taken on it are saved with the music folder, and charts show the set energy curve, the transition map, per-track detail and exactly what the pre-master pass changed.

**Architecture:** Two small persistence layers (a per-file analysis cache in SQLite under the user's profile, and a per-folder JSON "set project" recording options, order, step status and results) feed the existing analysis modules and a new `charts.py` (matplotlib, Agg-testable) that the GUI embeds with `FigureCanvasTkAgg`. The GUI tab is rebuilt around a numbered step panel (Folder → Analyze → Set list → Transitions → Pre-master → Export) that reads its state from the project.

**Tech Stack:** Python 3.8+, sqlite3, json, matplotlib (TkAgg / Agg), Tkinter/ttk, existing modules `audio_utils`, `playlist_manager`, `transition_planner`, `mastering`, `mixxx_export`.

**Charts follow the dataviz skill:** one series per plot in slot-1 blue `#2a78d6`; context in de-emphasis gray `#9a9993`; before/after as two shades of the same hue (`#86b6ef` → `#1c5cab`); status colours only for real status (critical `#d03b3b`, warning `#fab219`) and always with a label; 2 px lines, ≥ 8 px markers, hairline solid gridlines, no dual axes (BPM and energy are stacked small multiples sharing x).

---

### Task 1: Analysis cache (`analysis_store.py`)

**Files:**
- Create: `analysis_store.py`
- Test: `tests/test_analysis_store.py`

Key = absolute path + file size + mtime + analyzer version string. Kinds: `features`, `profile:<mix_bars>`, `mastering`. Location: `%LOCALAPPDATA%\DynaMix\analysis.sqlite` on Windows, `~/.dynamix/analysis.sqlite` elsewhere (overridable with `DYNAMIX_HOME`). JSON values, numpy types converted.

Steps: write failing tests (put/get roundtrip, miss when the file changes, `stats()` count) → implement `AnalysisStore` with `get(path, kind)`, `put(path, kind, data)`, `has(path, kind)`, `stats()`, `clear()` → tests pass → commit.

### Task 2: Wire the cache into the analysers

**Files:**
- Modify: `playlist_manager.py` (`analyze_playlist`: look up `features` before creating an `AudioAnalyzer`; report cached/analysed counts through an optional progress callback)
- Modify: `transition_planner.py` (`profile_track`: cache `profile:<mix_bars>` and reuse `mastering`)
- Modify: `mastering.py` (`check_files`: cache `mastering`)
- Test: `tests/test_analysis_store.py` (second run of `analyze_playlist` on the same folder does not instantiate `AudioAnalyzer`; use `unittest.mock.patch`)

Steps: failing test → implementation with a module-level `get_store()` singleton → pass → commit.

### Task 3: Set project (`set_project.py`)

**Files:**
- Create: `set_project.py`
- Test: `tests/test_set_project.py`

`SetProject(folder)` loads/saves `<folder>/.dynamix-set.json`. Fields: `folder`, `created`, `updated`, `options` (set_duration, energy_curve, target_lufs, tone_match, fix_phase, mix_bars), `tracks` (analysed records), `set_list` (ordered file paths), `steps` dict keyed `analyze|setlist|transitions|premaster|playlist|mixxx` → `{done, at, details}`, `transitions` (planner output), `premaster` (results summary), `notes`. Helpers: `mark(step, **details)`, `next_step()` returning the first undone step and a French/English hint, `summary_lines()`.

Steps: failing tests (roundtrip, `next_step` order, `mark` sets timestamp) → implement → pass → commit.

### Task 4: Charts module (`charts.py`)

**Files:**
- Create: `charts.py`
- Test: `tests/test_charts.py` (render each figure to PNG with the Agg backend; assert file size > 0 and no exception; visually inspect the PNGs once)

Functions (each returns a `matplotlib.figure.Figure`):
- `set_overview(profiles_or_tracks, targets=None)`: two stacked axes sharing x (track index); top = energy level line+markers with the target curve in gray; bottom = BPM line. Tick labels = short file names, rotated.
- `set_timeline(profiles)`: horizontal bars per track at their cumulative start time (overlaps by the crossfade), intro/outro sections drawn as lighter segments; a marker on each transition with its score label (selective: only scores < 70 are labelled).
- `track_detail(profile, times, rms, short_term_lufs=None)`: energy envelope over time with intro/outro shaded and beat-aligned markers; a second axis below with short-term loudness and the true-peak / clipping markers when a mastering report is present.
- `mastering_balance(report, set_median)`: diverging horizontal bars of the six bands relative to the set median (blue/red with gray midpoint).
- `premaster_before_after(results, target_lufs)`: dumbbell chart LUFS before → after per track with the target as a vertical hairline; a second panel for true peak with the -1 dBTP ceiling.

Style helper `_style(ax)`: hide top/right spines, hairline gray grid, text in `#0b0b0b`/`#52514e`.

Steps: failing render tests → implement → render PNGs to the scratchpad and look at them → fix collisions → pass → commit.

### Task 5: Rebuild the Playlist Manager tab as "Set Builder"

**Files:**
- Modify: `gui.py` (`create_playlist_tab` and the playlist handlers)

Layout: left column = step panel (six numbered rows: label, status icon ✓/○, timestamp/details, action button) + a "Next:" hint label + Options (duration, curve, target LUFS, match tone, fix phase); right = notebook with tabs "Tracks" (table, row selection updates the Track tab), "Overview" (set_overview + set_timeline), "Track" (track_detail + mastering_balance for the selected row), "Pre-master" (premaster_before_after + actions text).

Behaviour: browsing a folder loads the `SetProject` if present, restores table and step states, renders Overview; every action marks its step, saves the project, refreshes the panel. Analyze shows "cached n / analysed m". Charts are drawn with `FigureCanvasTkAgg`; old canvases are destroyed before redraw.

Steps: implement panel → implement chart embedding → headless smoke test with mocked Tk (as done before) → commit.

### Task 6: CLI parity and docs

**Files:**
- Modify: `mixxx_export.py` (use the project when present: `--project` default on; `--save-charts DIR` writes the PNGs)
- Modify: `mastering.py` (fix: write `premaster` results into the project when run on a project folder)
- Modify: `README.md`, `GUI_README.md`, `INSTALL_WINDOWS.md` (workflow section, where the cache lives, how to clear it)
- Add `.dynamix-set.json` and `*.sqlite` to `.gitignore`

Steps: implement → run the whole flow on the synthetic set → commit → push.

---

## Addendum (same day): project folders, configuration tab, editable set list

### Task 7: Configuration (`config.py`)
`Config` saved as `<DynaMix home>/config.json`: `projects_root` (default `~/DynaMix Projects`), `mixxx_db` (auto-detected, overridable), defaults (`set_duration`, `energy_curve`, `mix_bars`, `target_lufs`, `tone_match`, `fix_phase`, `output_format`). `environment_report()` lists Python, Tkinter, soundfile/libsndfile MP3 support, numba, FFmpeg on PATH, Mixxx database, analysis cache. Tests: roundtrip, defaults, report keys.

### Task 8: Project folders (`set_project.py`)
A project lives in `<projects_root>/<name>/`: `project.json`, `source/` (imported audio copies), `premaster/`, `exports/` (M3U, sheets, JSON, charts). `SetProject.create(root, name, source_folder)`, `SetProject.open(path)`, `list_projects(root)`, `import_audio(files, progress)` (copy, skip identical), `source_files()`. Set-list editing: `add_to_set`, `remove_from_set`, `move_in_set`, `set_order`; every edit invalidates later steps. Tests updated.

### Task 9: GUI
- New **Configuration** tab (paths, Mixxx database with Detect, defaults, environment report, Save).
- Set Builder header: project combobox + New project (name + music folder -> import) + Import audio.
- Tracks tab: Library (all analysed) and Set list (ordered) side by side with Add / Remove / Up / Down / Propose; the library list never disappears.
- Outputs default to the project's folders; Mixxx export uses the configured database without a dialog.

### Task 10: CLI + docs
`mixxx_export.py --project PATH`, `mastering.py fix --project PATH`; README, GUI_README, INSTALL_WINDOWS.
