# EasyEdits Web Preview — Design Spec
Date: 2026-05-24

## Overview

Add a local web preview UI to the `/easyedits` skill. After transcription, Claude
launches a Flask server at `localhost:5000`. The user opens a browser to see a
two-panel layout: transcript with cuts on the left, a stitched video player with
captions on the right, and an NLE-style timeline below the player. Adjustments
are still made by typing to Claude in the terminal — the browser auto-refreshes
every 2 seconds. When the user says "go", the XML and SRT are saved and the
server stops.

No original files are ever modified. All output goes into `easyedits_output/`.

---

## New files

```
easyedits/
  scripts/
    preview_server.py    ← new: Flask server
    preview.html         ← new: frontend (served by Flask)
    autoedit.py          ← updated: writes preview_state.json after transcription
    xml_builder.py       ← updated: --words-per-caption flag + b-roll V2 track
  docs/
    superpowers/
      specs/
        2026-05-24-web-preview-design.md   ← this file
```

---

## New dependency

```
pip install flask
```

---

## Step 0 — New upfront questions (SKILL.md)

Before scanning, Claude asks:

> "What type of video is this? (e.g. talking head, food review, travel vlog, tutorial)"
> "Will you need b-roll overlays? If yes, what's the path to your b-roll folder?"

- Talking head → skip b-roll question entirely
- Any other type → ask for b-roll folder path
- B-roll folder path stored in `preview_state.json` as `broll_folder`

---

## preview_state.json

Written by `autoedit.py` after transcription. Updated by Claude in-place when
the user makes adjustments. Read by Flask every time the frontend polls `/state`.

```json
{
  "last_modified": 1748131200.0,
  "video_type": "food review",
  "clips": [
    {
      "filename": "clip_007.mp4",
      "path": "C:/Videos/MyVideo/clip_007.mp4",
      "duration_sec": 108.4
    }
  ],
  "cuts": [
    { "clip": "clip_007.mp4", "type": "silence", "start": 4.2,  "end": 6.3  },
    { "clip": "clip_007.mp4", "type": "filler",  "word": "um",  "start": 12.1, "end": 12.4 },
    { "clip": "clip_007.mp4", "type": "false_start", "start": 20.0, "end": 21.5 }
  ],
  "broll": [
    {
      "filename": "broll_cafe.mp4",
      "path": "C:/Videos/Broll/broll_cafe.mp4",
      "at_sec": 32.0,
      "duration": 5.0,
      "muted": true
    }
  ],
  "broll_folder": "C:/Videos/Broll",
  "captions": {
    "words_per_line": 7,
    "entries": [
      { "start": 0.5, "end": 1.8, "text": "Hey guys welcome back" }
    ]
  }
}
```

`at_sec` is a **global timeline position** (seconds from the very start of the
stitched edit, after cuts removed), not a position within a single clip.

---

## preview_server.py

Flask server. Launched by Claude in the background after transcription.

### Routes

| Route | Behaviour |
|---|---|
| `GET /` | Serves `preview.html` |
| `GET /state` | Returns `preview_state.json` as JSON |
| `GET /video/<filename>` | Streams main clip from its source folder (Range header support for seeking) |
| `GET /broll/<filename>` | Streams b-roll clip from `broll_folder` (Range header support) |

### Launch command

```bash
python "%USERPROFILE%\.claude\skills\easyedits\scripts\preview_server.py" --folder "<folder_path>"
```

Runs in the background. On startup, `preview_server.py` writes its PID to
`easyedits_output/preview_server.pid`. Claude reads this file and kills the
process after "go" is executed and files are saved. The PID file is deleted on
server exit.

### Video streaming

Both `/video/` and `/broll/` routes must support HTTP Range requests so the
browser `<video>` element can seek. Use Flask's `send_file` with
`conditional=True` or stream bytes manually with `Range` header parsing.

---

## preview.html — Layout

Three regions, full browser height:

```
┌────────────────────────┬─────────────────────────────────┐
│  TRANSCRIPT            │  PREVIEW                        │
│  ──────────────────    │  ┌─────────────────────────┐    │
│  34 cuts · saves 2m14s │  │                         │    │
│                        │  │   [video playing]       │    │
│  ── clip_007.mp4 ──    │  │   [broll overlay]       │    │
│  Hey guys welcome [uh] │  │   "caption text"        │    │
│  [... 2.1s silence ...] │  └─────────────────────────┘    │
│  basically [you know]  │  ▶  clip_007.mp4  0:32 / 1:48   │
│                        │                                 │
│  ── clip_001.mp4 ──    ├─────────────────────────────────┤
│  ...                   │  TIMELINE                       │
│                        │  ┌─────────────────────────┐    │
│                        │  │ V2 [broll_cafe.mp4──]   │    │
│                        │  │ V1 [clip_007████──][001]│    │
│                        │  │ A1 [clip_007────────][─]│    │
│                        │  │     ▲ playhead          │    │
│                        │  └─────────────────────────┘    │
└────────────────────────┴─────────────────────────────────┘
```

### Left panel — Transcript

- Scrollable, independent of right panel
- Per-clip headers: `── clip_007.mp4 ──`
- Cut rendering:
  - Silence: greyed — `[... 2.1s ...]`
  - Filler: struck through — `[um]`
  - False start: greyed — `[false start]`
- B-roll markers inline at their global position: `▶ broll_cafe.mp4 (5s)`
- Stats bar at top: `34 cuts · saves 2m 14s · output 6m 26s`
- Polls `/state` every 2 seconds; re-renders transcript if state changed
  (compare a `last_modified` timestamp on the JSON to avoid unnecessary redraws)

### Right panel — Video player

**Elements (all positioned relative to a container div):**

1. Main `<video>` — full size, plays current clip
2. B-roll `<video>` — absolutely positioned, full size overlay, hidden by default,
   `muted` attribute toggled from state
3. Caption `<div>` — absolutely positioned at bottom centre, 80% width,
   semi-transparent background, large white text
4. Progress bar + timestamp + clip name below the video container
5. Play/Pause button

### Timeline

- Horizontal axis = total edit duration (after cuts removed)
- Track rows (top to bottom): V2 (b-roll), V1 (main clips), A1 (audio)
- V1 clip blocks: coloured by clip, cut regions shown as dark hatched overlay
- V2 b-roll blocks: positioned at `at_sec`, width proportional to `duration`
- Playhead: vertical line, moves on `timeupdate`, clicking seeks
- Hovering a block shows tooltip: filename + duration

---

## JS Timeline Controller

All logic runs in `preview.html` as vanilla JS (no framework).

### Virtual timeline

On state load, build a `timeline` array mapping every clip's kept segments to
global positions:

```
clip_007.mp4  duration 108s  cuts: [4.2-6.3, 12.1-12.4]
  → kept segments: [0-4.2, 6.3-12.1, 12.4-108]
  → global offsets: 0, 4.2, 10.0
  → total clip contribution: 105.9s

clip_001.mp4  duration 125s  no cuts
  → global offset: 105.9
  → total clip contribution: 125s
```

### Playback control

- `timeupdate` event: check if `video.currentTime` falls inside any cut for the
  current clip → if yes, `video.currentTime = cut.end + PADDING`
- `ended` event: advance to next clip — set `video.src`, call `video.play()`
- Playhead: `globalPosition = clipGlobalOffset + video.currentTime`

### B-roll overlay

- On each `timeupdate`: check if `globalPosition` is within any b-roll range
- If entering b-roll range: show overlay video, set `src` if not already set,
  call `play()`, apply `muted` from state
- If leaving b-roll range: pause overlay, hide it, reset `src`

### Captions

- On each `timeupdate`: find `captions.entries` entry where
  `start <= globalPosition <= end` → set caption div text
- Empty caption div when no entry matches

### Auto-refresh

- Poll `/state` every 2000ms
- Compare `state.last_modified` (a Unix timestamp written by Claude on each edit)
- If changed: rebuild virtual timeline, re-render transcript, update timeline UI
- Do not interrupt currently playing video unless the clips list itself changed

---

## xml_builder.py changes

### `--words-per-caption N` flag

- Default: 7 (existing behaviour unchanged)
- Splits transcript words into lines of N words max when generating SRT entries
- Also updates `captions.entries` in `preview_state.json` so preview reflects it

### B-roll track (V2)

Add a second `<track>` element to the FCP7 XML for b-roll clips:

- V1 track: existing main clip sequence (unchanged)
- V2 track: one `<clipitem>` per b-roll entry
  - `start` / `end` = global timeline position in frames (at clip framerate)
  - `in` / `out` = 0 to `duration` in frames
  - Audio channels: included if `muted: false`, omitted if `muted: true`

---

## autoedit.py changes

After `mode_transcribe()` completes, write `preview_state.json`:

```python
state = {
  "last_modified": time.time(),
  "video_type": video_type,
  "clips": [...],
  "cuts": [...],
  "broll": [],
  "broll_folder": broll_folder or "",
  "captions": {
    "words_per_line": 7,
    "entries": [...]
  }
}
with open(output_dir / "preview_state.json", "w") as f:
    json.dump(state, f, indent=2)
```

`last_modified` is updated every time Claude modifies the file so the frontend
knows to re-render.

---

## Plain English adjustment examples (SKILL.md)

**B-roll:**
- `"put broll_cafe.mp4 at 0:32 for 5 seconds"` → add/update broll entry, `muted: true`
- `"keep the audio on broll_cafe.mp4 at 0:32"` → set `muted: false`
- `"mute the broll at 0:32"` → set `muted: true`
- `"remove the broll at 0:32"` → delete broll entry

**Captions:**
- `"make captions 2 words per line"` → set `words_per_line: 2`, re-run caption generation
- `"go back to 7 words per caption"` → reset to default

**Cuts (existing, unchanged):**
- `"keep the first um in clip 3"`
- `"don't cut any silences in clip 2"`
- `"lower the silence threshold"`

---

## Error handling

| Error | Response |
|---|---|
| Flask not installed | Tell user: `pip install flask` |
| Port 5000 already in use | Try 5001, 5002 — tell user which port opened |
| B-roll file not found | Warn user, skip that entry, continue |
| B-roll folder not found | Ask user to re-check path |
| Browser can't seek video | Confirm Range header support in `/video/` route |

---

## Files changed / created summary

| File | Change |
|---|---|
| `scripts/preview_server.py` | New — Flask server |
| `scripts/preview.html` | New — frontend |
| `scripts/autoedit.py` | Write `preview_state.json` after transcription |
| `scripts/xml_builder.py` | `--words-per-caption` flag + V2 b-roll XML track |
| `SKILL.md` | Step 0 (video type + b-roll), Step 2.5 (launch server), updated Step 3 |
| `CLAUDE.md` | New dependency (flask), new scripts, updated flow |
| `README.md` | Updated features section, new flask requirement, new usage section |
| `CHANGELOG.md` | v1.2.0 entry |
