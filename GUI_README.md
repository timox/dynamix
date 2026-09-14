# DynaMix GUI - Quick Start Guide

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
  selected tracks so they are analysed again.
- **Workflow panel**: the six steps with a ✓ / ○ status, the date and key
  figures of each, and a "Next:" hint:
    1. Select and analyze (BPM, key, energy; cached per file)
    2. Propose a set list (several variants from the selection; use one)
    3. Plan Transitions (intro/outro sections; the transition sheet is a
       report in the Log tab, its data goes to exports/transitions.json)
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
- **FX tab** (workflow step 5 opens it): pick a transition, then stack effects on it — **Freeze** (loops the
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
- **Track**: energy envelope with intro/outro, loudness figures, stereo
  phase and bass width, tone balance, then the band tracking chart (band
  envelopes over time, low-mid masking map, resonance spectrum with EQ
  suggestions and, when needed, "mix revision recommended")
- **Band Analysis** button: the same diagnostics as a report for the whole
  set, with the list of tracks that need a mix revision
- **Pre-master**: loudness and true peak before -> after (the actions per
  track are in the Pre-master report of the Log tab)
- **Project summary**, **Mastering Report**, **Band Analysis**: reports, shown
  in the Log tab

### 2. Configuration Tab
- **Paths**: the projects folder, the Mixxx database (Browse / Detect, empty
  = auto-detect), the music library folder, the FX samples folder, and where
  DynaMix keeps its cache and configuration
- **Defaults for new projects**: set duration, energy curve, crossfade
  length, target loudness, tone matching, phase repair, pre-master format
- **Environment**: what DynaMix found on this machine (Python, Tkinter,
  libsndfile with MP3 support, librosa, numba, FFmpeg, Mixxx database,
  analysis cache). Refresh after installing something.

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

The former Track Analysis, Two-Track Analysis, DJ Tools, Audio Effects and
Export Tools tabs are gone from the GUI: the Set Builder covers the analysis
of the set's tracks and its export, and the modules remain usable from the
command line (see README.md).

## Usage Tips

1. **Analysis**: analysis runs in the background and is cached per file
2. **Status Bar**: check the bottom status bar for the current operation
3. **Errors**: the Log tab keeps every warning and error with its traceback

## Keyboard Shortcuts

- **Ctrl+O**: Open file (in file selection dialogs)
- **Ctrl+S**: Save (in export dialogs)
- **Esc**: Close dialogs

## Troubleshooting

### GUI Won't Start
- Ensure Python 3.8+ is installed
- Check that all dependencies are installed: `pip install -r requirements.txt`
- Verify tkinter is available (usually included with Python)

### Analysis Takes Too Long
- Large audio files take longer to process
- Use batch analysis for multiple files
- Check the status bar for progress

### No Visualizations Appearing
- Ensure matplotlib is properly installed
- Check that analysis completed successfully
- Try resizing the window

## System Requirements

- Python 3.8 or higher
- All dependencies from requirements.txt
- Tkinter (usually included with Python)
- Sufficient RAM for large playlists (recommended: 4GB+)

## Notes

- The GUI runs analysis in background threads to keep the interface responsive
- Large playlists may take several minutes to analyze
- Export formats are optimized for compatibility with popular DJ software

