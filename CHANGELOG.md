# Changelog

All notable changes to EasyEdits will be documented here.

Format: [Semantic Versioning](https://semver.org) — `MAJOR.MINOR.PATCH`

---

## [1.5.3] — 2026-05-30

### Fixed
- **Words cut off mid-syllable at silence boundaries** — `detect_silences` output is now passed through `snap_silence_to_word_boundaries()`: if a silence starts inside a word, its start is pushed to `word.end`; if it ends inside a word, its end is pulled back to `word.start`. Silences that become shorter than `SILENCE_MIN_DURATION` after snapping are dropped. Prevents FFmpeg silence detection from biting into the final syllable of words like "strategy.", "games.", "code.", etc.
- **Caption segments spanning cut boundaries** — `generate_caption_entries` (autoedit.py) and `update_preview_captions` (xml_builder.py) now build keep segments using `max(prev_end, cut.end)` before grouping words into lines. Previously, nested cuts (silences inside bad_takes) reset `prev_end` to a smaller value, creating false keep segments mid-cut and putting wrong words into captions. Words in different keep segments are now always in separate caption entries.
- **Preview: duplicate-take captions and wrong words** — same `max()` fix applied to `buildVirtualTimeline` in `preview.html`, preventing the timeline from showing kept segments inside bad_take cut regions.
- **Preview: bad_take seek clips first word of retry** — `onTimeUpdate` now seeks to exactly `cut.end` (not `cut.end + 0.05`) for `bad_take` cuts, so the first word of the retry plays from its very start. The `+0.05` grace offset is still applied for silence cuts.
- **Preview: stumble word plays before skip fires** — bad_take `cut.start` is now placed slightly before the stumble word (during the preceding pause), giving `onTimeUpdate` a window to seek before the stumble word begins playing, preventing the user from hearing the stumble followed immediately by its retry.

---

## [1.5.2] — 2026-05-30

### Fixed
- **Video not playing in subfolder mode** — `preview_server.py` `/video/<filename>` route now falls back to `rglob` when the file isn't directly in `FOLDER`, so clips stored in scene subfolders are served correctly.
- **Bad take false positives (32+ second cuts)** — `REPEAT_MAX_LOOKAHEAD` reduced from 100 → 40 words; new `REPEAT_MAX_DURATION_SEC = 15.0` constant rejects any candidate whose gap exceeds 15 seconds. Genuine stumble-restarts happen within seconds; the 32.5s false positive in long monologue clips is now prevented.
- **Stray word at bad-take boundary** — `build_marked_transcript` in-cut check now uses `word.start < cut.end` (word-start-based) instead of `word.end <= cut.end + 0.05` (word-end-based). Words that begin inside a cut region but extend fractionally past the cut boundary are now correctly consumed rather than left as isolated keep-words in the transcript.

---

## [1.5.1] — 2026-05-30

### Added
- **Recursive folder scan** — `mode_scan` and `mode_transcribe` now use `rglob` instead of `iterdir`, so clips inside subfolders at any depth are found automatically. Clip ordering is still by embedded creation timestamp (file-mtime fallback). A filename→path lookup dict in `mode_transcribe` maps bare filenames from `--order` to their correct full paths.

---

## [1.5.0] — 2026-05-30

### Added
- **Bad take detection** — `detect_repeated_phrases()` in `autoedit.py` finds phrases said twice after a stumble using an 8-word sliding window with 72% fuzzy word-overlap threshold. The first occurrence (including any "let me try again" filler between attempts) is auto-cut as a `bad_take` type; the retry is kept. Contractions and slang are normalised before comparison (`gonna→going`, `wanna→want`, etc.).
- **Duplicate clip detection** — `detect_duplicate_clips()` compares the opening 20 words of each clip against all later clips. Clips whose opening matches a later clip (72% similarity) are flagged as `duplicate_take` and cut entirely (0.0 → duration_sec).
- **Preview: bad take styling** — bad-take words shown italic orange-struck (`.cbt` CSS class) in the transcript left panel.
- **Preview: duplicate clip banner** — clips flagged as duplicates show an `⚠ duplicate take — full clip cut` banner in orange above the transcript.
- **Preview: stats bar** — now shows `· N bad takes` and `· N duplicate clips` counts alongside existing silence/filler counts.
- **SKILL.md: adjustment language** — added plain-English override examples for bad takes and duplicate clips (e.g., `"clip 3 isn't a duplicate, keep it"`).

### Fixed
- **Stale cut bug** — `build_marked_transcript()` now discards cuts whose end precedes the current word before checking, preventing cut_idx from getting stuck when a large cut (bad_take) subsumes smaller inner cuts (silences, fillers).

---

## [1.4.1] — 2026-05-25

### Bug fixes

- **Fixed: duplicate captions / silences not cut on export** — `--execute` expected a clip-centric cuts file (one object per clip, each with a `cuts` array), but the skill was passing a flat list of cut objects. `xml_builder.py` treated each cut as a separate uncut clip, producing one full uncut copy of the timeline per cut. SKILL.md and CLAUDE.md now document the required format explicitly.
- **Fixed: SRT captions missing words that span a cut boundary** — Words whose audio starts inside a silence region but ends inside the keep segment (e.g. "Hi" clipped at the tail by a leading-silence cut) were excluded from captions. Filter corrected from a start-position check to an overlap check: `w["end"] > clip_in and w["start"] < out_sec`.
- **Fixed: PowerShell `$pid` reserved-variable crash** — `$pid` is a read-only automatic variable in PowerShell 5.1. Stop-server commands updated to use `$serverPid`.

---

## [1.2.3] — 2026-05-24

### Auto-kill stale preview server on new run

- `preview_server.py` now writes a global PID file (`scripts/.preview_server.pid`) on startup
- Any new run kills the old server automatically — no more stale servers holding port 5000
- Preview always opens on port 5000; port bumping to 5001/5002 only happens if something else occupies 5000

---

## [1.2.2] — 2026-05-24

### Caption positioning defaults

- Caption font size reduced to 13px (was 20px) — better fit for vertical/9:16 framing
- Caption position raised to 25% from bottom (was 8%) — sits in the natural subtitle zone for talking head content
- Horizontal margins widened to 20% each side — keeps text in a narrow centred band
- Defaults locked in preview.html and documented in CLAUDE.md; will not be overridden by future sessions

---

## [1.2.1] — 2026-05-24

### Preview UI redesign

- Replaced monospace-everywhere aesthetic with Inter (UI chrome) + JetBrains Mono (transcript text only)
- Full OKLCH CSS custom property token system — near-black base, indigo-purple accent, warm orange b-roll markers
- Transcript panel: clip headers now uppercase labels with border-bottom separator; cut silences and fillers styled distinctly without italic
- Player controls: solid accent-colored play button with hover/focus/active states; tabular-nums timestamps; progress bar is now a 20px invisible click zone wrapping a 3px visible track
- Timeline: taller tracks (32px), subtle border on track backgrounds, 1.5px semi-transparent playhead
- Custom scrollbar styling on transcript panel

---

## [1.2.0] — 2026-05-24

### Browser preview UI

- New `preview_server.py` — Flask server serving preview.html at localhost:5000
- New `preview.html` — two-panel browser UI: marked transcript left, video player right
- NLE-style timeline with V1 (main clips), V2 (b-roll), A1 (audio) tracks + clickable playhead
- Browser polls `/state` every 2 seconds — updates automatically after every Claude adjustment
- B-roll overlay: specify clip, position (global timeline seconds), duration, muted flag
- B-roll audio muted by default; unmutable per clip via plain English instruction
- `--words-per-caption N` flag on `xml_builder.py` (default 7); updates preview captions live
- B-roll V2 track added to FCP7 XML output; audio track included when `muted: false`
- `autoedit.py` gains `--video-type` and `--broll-folder` args; writes `preview_state.json`
- Step 0 in skill flow asks video type upfront; skips b-roll question for talking head videos
- New dependency: `pip install flask`

---

## [1.0.0] — 2025

### Initial release

**Core features**
- Scan folder of raw video clips and detect recording order from embedded timestamps
- Fallback to file-modified time when embedded timestamps are missing, with user warning
- Plain English clip reordering at the order confirmation stage
- Local transcription via faster-whisper (Whisper `medium` model, CPU, no API key)
- Silence detection via FFmpeg `silencedetect` filter (default threshold: 0.5s)
- Filler word detection: um, uh, uh, like, you know, sort of, kind of, basically, literally, honestly, actually, obviously, right, I mean
- False start detection (word sequences followed by restart)
- Full transcript preview with cuts marked inline — silences, fillers, false starts
- Clip order list and full transcript displayed together at preview stage
- Plain English cut adjustments: keep specific instances, skip entire clip, add custom words, adjust threshold
- Final approval required before any files are written
- DaVinci Resolve XML export (FCP7 XML format, compatible with free Resolve)
- SRT caption file export synced to edited timeline
- All output written to `easyedits_output/` subfolder — original files untouched
- Windows support (Python 3.10+, FFmpeg, faster-whisper)

**Known limitations in v1.0.0**
- Single audio track only (stereo clips are mixed to mono for transcription)
- No beat-sync / music-driven cutting (planned for a future Tool B)
- DaVinci Studio live API control not included (requires paid Resolve Studio)
- Whisper `medium` model used by default for improved accuracy
