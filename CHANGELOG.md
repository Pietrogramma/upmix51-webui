# Changelog

## 1.4.1
- Copy and move from the ⋮ menu can now replace an existing file when "Allow replacing existing files" is on, after a confirmation dialog.
- Replaced files are always backed up, now inside the output folder (`<output>/upmix_originali/<folder>/...`) so that media servers never see duplicates in the library. This also applies to conversions.

## 1.4
- Library folders are now **locked by default** and can be unlocked one by one from the settings, with a warning dialog (protection managed by the program; `:ro` still available for system-level protection).
- New `:out` flag in `ROOTS` for the output folder.
- The ⋮ menu (rename, copy, move, delete) is available only in the output folder; library files can never be renamed or deleted from Upmix51. Unlocked folders can only receive files.

## 1.3.1
- Settings: clearer wording for the "replace existing files" switch (it never unlocks protected folders).
- Settings: list of folders with their real status (read-only / writable) and how to make a folder writable.

## 1.3
- File actions menu (⋮) in writable folders: rename, copy, move, delete.
- Copy and move run in the background with progress in the job list; nothing is ever overwritten.
- Read-only folders stay untouchable: no actions are shown there and the server refuses any change.

## 1.2
- Legal notices in the interface (cover art copyright, licence, trademarks).
- `UA_CONTACT` setting to identify the application to MusicBrainz.
- Top-down 5.1 room view with live per-speaker levels and a video frame on the TV.
- Warning dialog when enabling file overwriting.

## 1.1
- Settings panel: theme (auto/light/dark), language (EN, IT, FR, ES, DE), optional overwriting with confirmation and backup.
- Cover art search (iTunes, Deezer, MusicBrainz/Cover Art Archive, optional TMDB) and upload; embedded in MKV/MP4; existing covers preserved.
- Previous upmix tracks are no longer duplicated when a file is processed again.

## 1.0
- First version: per-channel sliders, presets, 30-second preview with level meters, job queue, read-only library support.
