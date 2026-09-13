# DynaMix GUI - Quick Start Guide

## Launching the GUI

To start the DynaMix graphical user interface:

```bash
python gui.py
```

## GUI Tabs Overview

### 1. Track Analysis Tab
- **Purpose**: Analyze individual audio tracks
- **Features**:
  - Browse and select audio files
  - View comprehensive track analysis (BPM, key, energy, sections, etc.)
  - Visualize energy profiles and beat grids
  - Export analysis results

### 2. Two-Track Analysis Tab
- **Purpose**: Compare and analyze compatibility between two tracks
- **Features**:
  - Select two tracks for comparison
  - View compatibility scores (BPM, key, energy)
  - Get mix recommendations
  - See optimal exit/entry points

### 3. Set Builder Tab
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
    3. Plan Transitions (intro/outro sections, transition sheet)
    4. Pre-master Set (optional, into the project's premaster folder)
    5. Create Playlist (optional, M3U into exports/)
    6. Export to Mixxx (uses the database set in the Configuration tab)
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
- **Log tab**: everything DynaMix prints and every error with its traceback,
  filterable by level, also written to `<DynaMix home>/logs/dynamix.log`
  (**Open log folder**). The tab title counts new warnings and errors.
- **Overview**: set energy curve against the target, tempo, and the set map
- **Track**: energy envelope with intro/outro, loudness figures, stereo
  phase and bass width, tone balance, then the band tracking chart (band
  envelopes over time, low-mid masking map, resonance spectrum with EQ
  suggestions and, when needed, "mix revision recommended")
- **Band Analysis** button: the same diagnostics as a text report for the
  whole set, with the list of tracks that need a mix revision
- **Pre-master**: loudness and true peak before -> after, actions per track
- **Project summary** button: text summary of the project and its steps

### 3 bis. Configuration Tab
- **Paths**: the projects folder, the Mixxx database (Browse / Detect, empty
  = auto-detect), and where DynaMix keeps its cache and configuration
- **Defaults for new projects**: set duration, energy curve, crossfade
  length, target loudness, tone matching, phase repair, pre-master format
- **Environment**: what DynaMix found on this machine (Python, Tkinter,
  libsndfile with MP3 support, librosa, numba, FFmpeg, Mixxx database,
  analysis cache). Refresh after installing something.

### 4. DJ Tools Tab
- **Purpose**: Access DJ performance tools
- **Features**:
  - Detect cue points
  - Suggest loops
  - Analyze performance zones
  - Generate DJ notes
  - Batch analyze directories

### 5. Audio Effects Tab
- **Purpose**: Advanced audio effects analysis
- **Features**:
  - Analyze dynamics (compression, dynamic range)
  - Frequency spectrum analysis
  - Transient response analysis
  - Detect clipping and phasing issues

### 6. Export Tools Tab
- **Purpose**: Export analysis results in various formats
- **Features**:
  - Export to JSON, CSV, M3U
  - Export to Rekordbox XML
  - Export to Traktor NML
  - Export text reports
  - View export log

## Usage Tips

1. **File Selection**: Use the "Browse" buttons to select audio files or directories
2. **Analysis**: Click "Analyze" buttons to start processing (may take time for large files)
3. **Visualizations**: Charts and graphs appear automatically after analysis
4. **Export**: Use the Export Tools tab to save results in your preferred format
5. **Status Bar**: Check the bottom status bar for current operation status

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

