# EasyEdits — Claude Code Context

This is the EasyEdits skill for Claude Code.
Author: kweesbuilds (github.com/kweesbuilds/easyedits)

## One-time setup — add permissions to skip approval prompts

Run this once in your terminal so Claude Code can run the easyedits scripts without asking for approval each time:

**Windows (PowerShell):**
```powershell
$s = Get-Content "$env:USERPROFILE\.claude\settings.json" | ConvertFrom-Json
$newPerms = @(
  "PowerShell(python `"$env:USERPROFILE/.claude/skills/easyedits/scripts/autoedit.py`" *)",
  "PowerShell(python `"$env:USERPROFILE/.claude/skills/easyedits/scripts/xml_builder.py`" *)",
  "PowerShell(Start-Process python -ArgumentList *)",
  "PowerShell(Start-Process `"http://localhost*`")",
  "PowerShell(Get-Content *preview_server.pid*)",
  "PowerShell(Stop-Process -Id * -Force)",
  "PowerShell(Start-Sleep *)",
  "PowerShell(Get-ChildItem *)",
  "PowerShell(Test-Path *)"
)
$existing = $s.permissions.allow
$merged = ($existing + $newPerms) | Select-Object -Unique
$s.permissions.allow = $merged
$s | ConvertTo-Json -Depth 10 | Set-Content "$env:USERPROFILE\.claude\settings.json" -Encoding utf8
```

**macOS / Linux (bash):**
```bash
python3 - <<'EOF'
import json, os
path = os.path.expanduser("~/.claude/settings.json")
s = json.load(open(path)) if os.path.exists(path) else {}
s.setdefault("permissions", {}).setdefault("allow", [])
new = [
  'Bash(python "$USERPROFILE/.claude/skills/easyedits/scripts/autoedit.py" *)',
  'Bash(python "$USERPROFILE/.claude/skills/easyedits/scripts/xml_builder.py" *)',
  'Bash(python "$USERPROFILE/.claude/skills/easyedits/scripts/preview_server.py" *)',
]
s["permissions"]["allow"] = list(dict.fromkeys(s["permissions"]["allow"] + new))
json.dump(s, open(path, "w"), indent=2)
print("Done.")
EOF
```

## Environment

- OS: Windows (primary), macOS/Linux supported
- Python: 3.10+
- FFmpeg: installed via winget, on system PATH
- faster-whisper: installed via pip
- Flask: installed via pip (pip install flask)
- Whisper model: `medium` (CPU, int8)
- DaVinci Resolve: Free version — XML import approach only (no Python API)

## What this skill does

Automates the first-pass edit of talking head / vlog video content:
1. Scans a folder of raw clips
2. Detects clip order from embedded timestamps
3. Transcribes all clips locally with Whisper
4. Identifies silences, filler words, false starts
5. Detects bad takes — phrases repeated after a stumble (fuzzy match, 72% word overlap threshold); cuts the earlier attempt, keeps the retry
6. Detects duplicate clips — clips whose opening content closely matches a later clip; the earlier clip is cut entirely and shown with a ⚠ banner in the preview
7. Shows the user a full transcript preview with proposed cuts marked
8. Accepts plain English adjustments from the user
9. On final approval, outputs edit.xml + captions.srt to an easyedits_output/ subfolder

## Bad take / duplicate take cut types

- `bad_take` — within a single clip; `start` = first word of the failed attempt, `end` = first word of the retry. Everything in between (including "let me try that again" filler) is removed.
- `duplicate_take` — whole-clip cut; `start` = 0.0, `end` = clip duration_sec. The entire clip is removed from the timeline. Shown with a ⚠ banner and orange italic text in the preview left panel.

Both types appear in `preview_state.json → cuts[]` tagged with `"clip"` and `"type"`. The user can override them in plain English (e.g., "clip 3 isn't a duplicate, keep it") — remove the relevant cut from the cuts array and bump `last_modified`.

## Recursive folder support

`mode_scan` and `mode_transcribe` both search recursively using `rglob`. Clips can live in subfolders at any depth — they are still sorted by embedded creation timestamp (or file-mtime fallback) across the whole tree. The clip identifier passed via `--order` is always the bare filename (no subfolder prefix); a lookup dict maps it to the correct full path at transcription time.

## What this skill does NOT do

- Beat-sync / music-driven cutting
- Live DaVinci API control (requires Resolve Studio, which is paid)
- Visual scene analysis (no camera/frame processing)
- Reordering clips after the transcript has been approved (must go back to step 2)

## Script locations

- `scripts/autoedit.py` — scanning, transcription, cut detection; writes preview_state.json
- `scripts/xml_builder.py` — XML and SRT generation; reads broll from preview_state.json
- `scripts/preview_server.py` — Flask server: serves preview.html + video streams
- `scripts/preview.html` — browser frontend: transcript, video player, timeline UI

## Preview server flow

1. After transcription, `autoedit.py` writes `easyedits_output/preview_state.json`
2. Launch `preview_server.py` in background → browser auto-opens at localhost:5000
3. Browser polls `/state` every 2s, updates automatically on each change
4. Claude edits `preview_state.json` in-place for every adjustment (bumps `last_modified`)
5. On "go": run `xml_builder.py` → kill server via PID file

## Output format

- `edit.xml` — FCP7 XML, compatible with DaVinci Resolve free via File → Import Timeline → Import AAF, EDL, XML
- `captions.srt` — standard SRT, import via File → Import Subtitles in DaVinci

## Key flags

autoedit.py:
  --video-type    Type of video (e.g. "food review") — stored in preview_state.json
  --broll-folder  Path to folder containing b-roll clips

xml_builder.py:
  --words-per-caption  Words per SRT caption line (default 3)

## Critical: --cuts file format for --execute

The `--cuts` argument is a path to a JSON file. The file must be a **clip-centric array** — one object per clip, each containing a `cuts` array:

```json
[
  {
    "clip": "clip1.mp4",
    "cuts": [
      {"type": "silence", "start": 0.0, "end": 2.19, "duration": 2.19},
      {"type": "silence", "start": 3.66, "end": 4.63, "duration": 0.97}
    ]
  },
  {
    "clip": "clip2.mp4",
    "cuts": [
      {"type": "silence", "start": 0.0, "end": 1.84, "duration": 1.84}
    ]
  }
]
```

**Never pass a flat list of cut objects.** A flat list causes `mode_execute` to treat every individual cut as a separate clip, producing one full uncut copy of the timeline per cut (e.g. 6 cuts → 6 duplicate uncut sequences in DaVinci).

Always write this file without BOM:
```powershell
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText("<path>", $json, $utf8NoBom)
```

## Default settings (change in autoedit.py if needed)

- Silence threshold: -35dB
- Minimum silence duration: 0.6 seconds
- Padding around cuts: 0.05 seconds each side
- Whisper model: medium
- Words per caption line: 3

## Preview UI layout (preview.html)

Three-panel layout:
- **Left panel (35%)** — transcript with clip headers, cut markers (silence greyed, fillers struck, false starts dimmed), b-roll markers, stats bar showing cut counts
- **Right panel (65%)** — video player (object-fit contain), transport controls (skip back/prev/play/next/skip forward), volume slider, progress bar with seek
- **Bottom panel (full width)** — NLE-style timeline with zoom in/out buttons and horizontal scroll; labeled track sidebar

Timeline track order (top → bottom): **CAP** · V2 b-roll · V1 video · A1 audio

Stats bar shows: `{N} cuts · {N} silences · {N} words removed` — not time saved.

Caption entries use **local clip timestamps** + `clip` field (not global position). The `updateCap` function matches `entry.clip === currentClipName && localTime >= entry.start && localTime <= entry.end`.

### CAP track — caption timeline blocks
- Blocks are **resize-only** — no body drag. Left/right edge handles change start/end times.
- Resizing ripples adjacent captions: expanding right pushes later captions forward; contracting left pulls earlier captions back. Captions never overlap.
- Clicking a block seeks to that caption's start time.
- Direct delta math: `entry.start += dSec` (not `f.localStart + (ng - f.globalStart)`) — correct because local_delta = global_delta within a kept segment.

### Timeline zoom
- `setZoom(level)` sets `#tlc` width to `level × 100%` inside `#tl-scroll` (`overflow-x: auto`)
- Range: 1× (fit panel) → 12×. Playhead auto-scrolls horizontally during playback.

### Seamless clip transitions (double-buffer video)
- Two `<video>` elements (`video-a`, `video-b`) swap roles; one plays while the other preloads.
- `preloadClip(idx)` hooks `loadedmetadata` to pre-seek to `firstKeptTime(filename)` so the buffer is already at the correct frame before the swap.
- `transitionToNext()` handles the swap; triggered by `onEnded` (clips with no trailing silence) **or** by `onTimeUpdate` when the current cut reaches the clip end (`cut.end >= clip.duration_sec - 0.15`) — this fires before `ended`, eliminating the gap.
- `swapVideos()` pauses the outgoing clip's audio before swapping.
- `firstKeptTime(clipFilename)` walks leading cuts to find the start of the first non-cut segment.

### Cut-aware preview playback
- `onTimeUpdate` skips over every cut region in real time: `if t >= cut.start && t < cut.end - 0.02 → seek to cut.end + 0.05`
- End-of-clip cuts (`cut.end >= clip.duration_sec - 0.15`) call `transitionToNext()` instead of seeking past end.

### Preview state updates
- Server exposes `POST /update-state` — Claude POSTs full state JSON; server writes UTF-8 and bumps `last_modified`.
- Claude may edit `preview_state.json` directly via the Edit tool.
- **Never use PowerShell `ConvertTo-Json | Set-Content`** — writes UTF-16 LE BOM, breaks `json.load()`.

## Caption overlay defaults (preview.html — do not change these)

These are tuned for talking head / vertical video and should not be adjusted:
- Font size: 13px
- Position: bottom 25% of the video frame
- Horizontal margins: 20% left and right (narrow centered band)

## Filler words detected by default

um, uh, erm, er, like, you know, you know what i mean, sort of, kind of,
basically, literally, right, okay so, so yeah, i mean, honestly, actually, obviously, and yeah

## Error messages to know

- "ffmpeg is not recognized" → user needs to run `winget install ffmpeg` and reopen terminal
- "No module named faster_whisper" → user needs to run `pip install faster-whisper`
- "No module named flask" → user needs to run `pip install flask`
- "No video files found" → check the folder path, must use full Windows path
- "clip not found" in DaVinci → source files have been moved or renamed since running the skill
- "Port already in use" → server kills previous EasyEdits server automatically on startup; if 5000 is still blocked by something else it tries 5001, 5002

## Changelog

### v1.4.1 — 2026-05-25
- **Fixed: duplicate captions / silences not cut** — `--cuts` file must be clip-centric (see "Critical: --cuts file format" above); flat cut lists caused one uncut copy per cut
- **Fixed: SRT missing boundary-spanning words** — overlap filter (`w["end"] > clip_in and w["start"] < out_sec`) replaces start-position check so words spanning a cut boundary appear correctly
- **Fixed: PowerShell `$pid` crash** — `$pid` is read-only in PS 5.1; stop-server commands now use `$serverPid`

### v1.4.0 — 2026-05-25
- **CAP timeline track** — captions rendered as draggable blocks in NLE timeline, positioned above V2/V1/A1; click to seek; left/right edge handles only (no body move)
- **Caption ripple** — resizing a caption ripples adjacent ones forward/back so they never overlap; direct delta math for accurate local time updates
- **Timeline zoom** — zoom in/out buttons (1×–12×), `#tlc` scales inside `#tl-scroll` with `overflow-x: auto`; playhead auto-scrolls during playback
- **Seamless clip transitions** — double-buffer swap pre-seeks to `firstKeptTime`; `transitionToNext` fires at entry into end-of-clip silence cut rather than waiting for the `ended` event; outgoing audio paused immediately on swap
- **Cut-aware preview playback** — `onTimeUpdate` skips all cut regions live; `firstKeptTime()` helper used on both preload and `loadClip`
- **`/update-state` POST endpoint** in `preview_server.py` — Claude POSTs state changes instead of requiring a script re-run; writes UTF-8 explicitly
- **Default captions changed to 3 words per line** — better fit for talking head / vertical video short-form content (was 7)
