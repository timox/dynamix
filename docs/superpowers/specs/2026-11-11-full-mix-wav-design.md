# Full Mix WAV Export

## Intent

Add a final Set Builder action that renders the planned set as one continuous WAV file. This lets a user listen to or share the complete mix without assembling tracks in a separate application.

## Goals

- Render the project's set list in its current order as one stereo, continuous mix.
- Apply the project's planned transition timing, including per-pair nudge, A-end markers, and configured transition effects.
- Use the same playback source selection as the existing workflow, including the existing “Use pre-mastered copies” option.
- Offer PCM WAV output at 44.1 or 48 kHz and 16, 24, or 32 bits. Defaults: 44.1 kHz and 24 bits.
- Put the result in the project's `exports/` directory, with a file picker so the user can choose the output path/name.
- Run rendering as a cancellable background task with progress, using the existing task system. Cancellation or failure must not leave a partial final WAV or change the project settings.

## Non-goals

- No new choice for pre-mastered audio; use the existing project option.
- No changes to the M3U or Mixxx export behavior.
- No extra mastering, loudness target, or user-editable fade curves in this feature.
- No batch export or command-line interface in this change.

## User flow

Add a “Create full mix WAV” action as the final workflow step after Mixxx export. The user chooses the WAV destination, sample rate (44.1/48 kHz), and bit depth (16/24/32); the bit depth defaults to 24. The action requires a valid set list and transition plan. It renders in the background and reports progress in the Tasks tab/status area. On success it reports the saved path and output settings. If the chosen destination already exists, ask before replacing it.

## Audio behavior

- Render the tracks in set-list order and use the transition plan's cue positions and Mixxx “Full Intro + Outro” equal-power fades. Keep the existing transition junction, nudge, A-end marker, and FX settings in sync with the transition preview and rendered track copies.
- Include configured FX whether or not “Apply all FX” has previously produced per-track FX copies. Reuse valid rendered copies; if FX are pending, render temporary copies with the existing FX renderer, then build the full mix from those copies. Do not apply the same FX twice.
- Respect the existing playback source priority and `use_premaster` setting through the same project source-selection helper used by playlist and Mixxx exports. Temporary FX copies must be based on that selected source.
- Resample tracks as needed to the selected output sample rate. Write stereo integer PCM using the selected 16-, 24-, or 32-bit subtype.
- Render long sets incrementally so memory use does not grow with the full output duration. Write to a temporary file and only replace/move it into the chosen destination after successful completion.

## Constraints and affected areas

- Follow the Set Builder workflow and `TaskManager` background-task patterns.
- Extend workflow step state/invalidation so upstream changes make the full-mix export stale in the same way as the M3U and Mixxx exports.
- Reuse existing transition FX and playback-source logic; avoid duplicating project selection rules.
- Add English and French UI strings using the existing localization approach.
- WAV size can be large for long sets; show a useful error if there is insufficient space or an audio source cannot be read, and leave no partial final output.

## Open implementation choices

- Exact progress granularity and the smallest practical chunk size are implementation details.
- Keep the output default name as `<project name>.wav`; the save dialog lets the user change it.
