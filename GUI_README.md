# DynaMix GUI - Quick Start Guide

The GUI of this fork is built around set projects; it replaces the analysis tabs of the original
makalin/dynamix GUI (see "About this fork" in [README.md](README.md)).

## Launching the GUI

To start the DynaMix graphical user interface:

```bash
python gui.py
```

## GUI Tabs Overview

### 1. Set Builder Tab
- **Purpose**: Build a set as a project, step by step, without ever redoing work
- **Projects**: a set is a folder under the projects folder (see the
  Configuration tab): `project.json`, `premaster/` (corrected copies) and
  `exports/` (M3U, transition sheets, JSON, charts). The tracks come from your
  **music library**: one folder holding every track you mixed, set in the
  Configuration tab and scanned in place (nothing is copied, the library is
  never written to). The project combobox reopens any existing project.
  **Reset project...** starts the set again from an empty selection (name,
  options, notes and the analysis cache are kept; pre-master and exports are
  deleted). **Clear analysis cache...** forgets the cached analyses of the
  selected tracks so they are analysed again. **Snapshots...** saves the
  project's settings (selection, set list, transitions, FX settings, options)
  under a name in the project's `snapshots/` folder and restores one later
  (the current state is saved first as "before restore"; steps whose audio
  copies changed since, and the playlist and Mixxx export, are to redo).
- **Which audio is played**: the line under "Next:" says what the FX, the
  playlist and the Mixxx export use (FX copies, pre-mastered copies,
  originals). **Use pre-mastered copies** in *Options for this set* (on by
  default) chooses between the pre-mastered copies and the originals; changing
  it means applying the FX, writing the playlist and exporting again. The FX
  tab shows it per transition ("Plays from: A pre-mastered copy · B original").
- **Workflow panel**: the six steps with a ✓ / ○ status, the date and key
  figures of each, and a "Next:" hint:
    1. Select and analyze (BPM, key, energy; cached per file)
    2. Propose a set list (several variants from the selection; use one)
    3. Plan Transitions (intro/outro sections; the transition sheet is a
       report in the Log tab, its data goes to exports/transitions.json). Like
       the Track tab and the reports, the sheet's mastering and band figures
       are measured on the files the set plays: after a pre-master (or a
       change of "Use pre-mastered copies") the sheet is measured again, the
       cue positions do not change
    4. Pre-master Set (optional, into the project's premaster folder)
    5. Transition FX (optional, copies with FX into the project's fx folder)
    6. Create Playlist (optional, M3U into exports/)
    7. Export to Mixxx (uses the database set in the Configuration tab)
  Redoing an early step resets the later ones, so the status is always true.
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
- **FX tab** (workflow step 5 opens it). At the top, the **transition chart**
  shows the selected transition on a beat axis (J = junction, thick lines =
  bars): A fading out, B fading in, one lane per effect (freeze captured part
  and repeats, filter sweep, echo and its tail, sample repeats; what runs past
  "A ends" continues in B) and, once a preview has been rendered, the result.
  It is redrawn at every change; drag the separator to make it taller. Then pick a transition, then stack effects on it — **Freeze** (loops the
  last beats of the outgoing track, with a roll such as 4×1 → 2×2 → 1×4, an
  optional loop filter / echo, a fade and a tail), **Filter** (high-pass,
  low-pass or band-pass sweep with resonance, closing the outgoing track or
  opening the incoming one), **Echo** (tempo-synced) and **Sample** (from the
  FX samples folder — click to use, double-click to hear; its BPM is read from
  the file name and the sample is fitted to the track's tempo by *varispeed*
  or *stretch*, or played as it is with *off*; **Repeats** plays a short
  sample several times back to back, up to 64 s —, anchored to end at, start at
  or centre on the junction; it
  may run over into the next track). **▶ Preview (loop)** plays the transition
  in a loop and re-renders it when a setting changes; **Nudge (ms)** shifts the
  junction by ear. **Apply all FX** writes copies into `fx/` (the library and
  the pre-mastered copies are never modified); the playlist and the Mixxx
  export then use those copies, with the cue positions of the rendered files.
  The project's `fx/` (and `premaster/`) folder must be part of the Mixxx
  library (Mixxx music directories) for the export to match the copies.
  The tab follows the open project and its transition plan (it is rebuilt
  after a new plan); leaving the tab stops the looped preview.
- **Overview**: set energy curve against the target, tempo, and the set map
- **Track**: the line at the top says which file is analysed. By default it
  is the file the set plays (the pre-mastered copy when there is one and it is
  used); **Analyse: original | pre-mastered copy** switches between the two
  (judge the mix on the original, the result on the copy). Then: energy
  envelope with intro/outro, loudness figures, stereo
  phase and bass width, tone balance, then the band tracking chart (band
  envelopes over time, low-mid masking map, resonance spectrum with EQ
  suggestions and, when needed, "mix revision recommended"). Each resonance
  shows its nearest note (approximate); blue dots are notes of the track's key,
  which may simply be the key itself, red dots are other notes
- **Band Analysis** button: the same diagnostics as a report for the whole
  set, with the list of tracks that need a mix revision
- **Pre-master**: loudness and true peak before -> after (the actions per
  track are in the Pre-master report of the Log tab)
- **Project summary**, **Mastering Report**, **Band Analysis**: reports, shown
  in the Log tab

### 2. Configuration Tab
- **Display**: the font size (8 to 18 points) of the whole window, the tables
  and the charts, applied and saved at once
- **Paths**: the projects folder, the Mixxx database (Browse / Detect, empty
  = auto-detect), the music library folder, the FX samples folder, and where
  DynaMix keeps its cache and configuration
- **Defaults for new projects**: set duration, energy curve, crossfade
  length, target loudness, tone matching, phase repair, pre-master format
- **Environment**: what DynaMix found on this machine (Python, Tkinter,
  libsndfile with MP3 support, librosa, numba, FFmpeg, Mixxx database,
  analysis cache). Refresh after installing something.

### Status bar and Tasks Tab
- Long operations (library scan, analysis, proposals, transition planning,
  Mastering Report, Band Analysis, pre-master, Apply all FX) run in the
  background. The status bar shows the newest one with a progress bar and
  **■ Stop**; the **Tasks** tab (its title counts the running tasks) lists
  them with their progress and time, **■ Stop selected** and **Clear
  finished**.
- Stop ends a task after the track in progress. A stopped task leaves the
  project unchanged; analyses already done stay in the cache, so running it
  again only does what is missing. The library scan cannot be stopped (it is
  quick).
- A task that ends never switches tab: its report arrives in the Log tab,
  whose title counts the new reports.

### 3. Log Tab
- **Reports** (top): the reports of the open project — Project summary,
  Mastering Report, Band Analysis, Transition Sheet, Pre-master, Mixxx Export.
  Each one is saved as `exports/reports/<date time> <title>.txt` (**Open
  reports folder**), listed with its time; click one to read it. A new report
  opens the Log tab (except the Pre-master one, whose chart stays in view).
  **Reset project** deletes them with the other exports.
- **Log** (bottom): everything DynaMix prints and every error with its
  traceback, also written to `<DynaMix home>/logs/dynamix.log` (**Open log
  folder**). The tab title counts new warnings and errors.
- **Show**: All / Reports (hides the log) / Warnings and errors / Errors.

The Track Analysis, Two-Track Analysis, DJ Tools, Audio Effects and Export
Tools tabs of the original project were removed with their code: the Set
Builder covers the analysis of the set's tracks and its export.

## Usage Tips

1. **Analysis** runs in the background and is cached per file: a track is
   analysed once, whatever the project.
2. **Status bar**: the bottom bar shows the current operation and its progress.
3. **Errors**: the Log tab keeps every warning and error with its traceback;
   copy it from there when reporting a problem.

## Troubleshooting

- **The GUI does not start**: run `python check_install.py`; on Windows,
  Tkinter comes with the "tcl/tk and IDLE" option of the Python installer.
- **The first analysis is slow**: `numba` compiles its code the first time;
  later runs are faster, and analysed tracks come from the cache.
- **A chart stays empty**: analyse the selection and build a set list first;
  the FX tab needs planned transitions (step 3).
- **The Mixxx export misses tracks**: the tracks, and the project's `fx/` and
  `premaster/` folders when copies are used, must be in the Mixxx library;
  close Mixxx during the export.

## System Requirements

- Python 3.11 or 3.12 recommended, with Tkinter
- The dependencies of `requirements.txt`
- 4 GB of RAM or more for FX renders of long sets

