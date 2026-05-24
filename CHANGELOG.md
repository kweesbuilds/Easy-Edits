# Changelog

All notable changes to EasyEdits will be documented here.

Format: [Semantic Versioning](https://semver.org) — `MAJOR.MINOR.PATCH`

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
