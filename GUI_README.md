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
- **Purpose**: Build a set from a music folder, step by step, without ever
  redoing work
- **How it works**:
  - Choose the music folder. If a set was already started there, its project
    (`.dynamix-set.json` in the folder) is reloaded: analysed tracks, proposed
    order, transitions, pre-master results and the status of every step
  - The **Workflow** panel lists the six steps with a ✓ / ○ status, the date and
    key figures of each, and a "Next:" hint telling you what to do now:
    1. Analyze (BPM, key, energy; every file is cached, only new files take time)
    2. Create Set List (duration, energy curve)
    3. Plan Transitions (intro/outro sections, transition sheet)
    4. Pre-master Set (optional, corrected copies in another folder)
    5. Create Playlist (optional, M3U)
    6. Export to Mixxx (intro/outro cues + playlist for Auto DJ)
  - Redoing an early step (new analysis with different files, new set list)
    resets the later ones, so the status is always truthful
- **Tabs on the right**:
  - **Tracks**: the analysed tracks or the proposed order, with BPM, key,
    duration, energy level, mastering score and flags. Select a row to open it
    in the Track tab
  - **Overview**: energy curve of the set against the target curve, tempo
    along the set, and the set map (where each track plays, its intro/outro
    sections, and transitions that need attention)
  - **Track**: energy envelope over time with intro/outro marked, loudness /
    true peak / PLR, and the tone balance of the track against the set median
  - **Pre-master**: loudness and true peak before -> after for every track,
    with the list of actions taken (gain, tone, polarity, mono bass)
- **Project summary** button: text summary of the project and its steps
- **Analysis cache**: shown at the bottom of the panel (files, results, path)

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

