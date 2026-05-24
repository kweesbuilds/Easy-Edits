# EasyEdits Web Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a localhost Flask preview UI to `/easyedits` showing a marked transcript on the left and a stitched video player with captions, b-roll overlay, and NLE-style timeline on the right.

**Architecture:** `autoedit.py` writes `preview_state.json` after transcription; `preview_server.py` serves it and the video files; `preview.html` polls `/state` every 2 s and drives a JS virtual timeline that skips cuts, overlays b-roll, and renders captions. `xml_builder.py` gains `--words-per-caption` and reads b-roll from `preview_state.json` to add a V2 XML track.

**Tech Stack:** Python 3.10+, Flask, vanilla JS (no framework), FFmpeg, faster-whisper (existing).

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `scripts/autoedit.py` | Modify | Accept `--video-type` / `--broll-folder`; write `preview_state.json` after transcription |
| `scripts/preview_server.py` | Create | Flask server: `/`, `/state`, `/video/<f>`, `/broll/<f>`; PID file |
| `scripts/preview.html` | Create | Two-panel UI: transcript left, video + timeline right; JS timeline controller |
| `scripts/xml_builder.py` | Modify | `--words-per-caption` flag; `update_preview_captions()`; b-roll V2 XML track |
| `SKILL.md` | Modify | Step 0 (video type), Step 2.5 (launch server), updated Step 3 & 5 |
| `CLAUDE.md` | Modify | Flask dependency, new scripts, updated flow |
| `README.md` | Modify | Features, requirements, new usage section |
| `CHANGELOG.md` | Modify | v1.2.0 entry |
| `tests/test_autoedit_state.py` | Create | Tests for preview_state.json output |
| `tests/test_preview_server.py` | Create | Tests for Flask routes |
| `tests/test_xml_builder_v2.py` | Create | Tests for words-per-caption + b-roll XML track |

---

## Task 1 — `autoedit.py`: preview_state.json

**Files:**
- Modify: `scripts/autoedit.py`
- Create: `tests/test_autoedit_state.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_autoedit_state.py`:

```python
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

def test_preview_state_written(tmp_path):
    """mode_transcribe writes preview_state.json with required top-level keys."""
    from autoedit import mode_transcribe

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")

    mock_meta = {
        "filename": "clip.mp4", "path": str(clip),
        "duration_sec": 10.0, "duration_label": "0m 10s",
        "created_label": "2:00pm", "date_source": "embedded"
    }
    mock_words = [
        {"word": "hello", "start": 0.5, "end": 0.8},
        {"word": "world", "start": 0.9, "end": 1.2}
    ]

    with patch("autoedit.get_video_metadata", return_value=mock_meta), \
         patch("autoedit.extract_audio"), \
         patch("autoedit.transcribe_clip", return_value=mock_words), \
         patch("autoedit.detect_silences", return_value=[]), \
         patch("autoedit.detect_fillers", return_value=[]), \
         patch("autoedit.detect_false_starts", return_value=[]):
        mode_transcribe(
            folder=tmp_path,
            order=["clip.mp4"],
            overrides={},
            video_type="food review",
            broll_folder="C:/broll"
        )

    state_path = tmp_path / "easyedits_output" / "preview_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())

    assert state["video_type"] == "food review"
    assert state["broll_folder"] == "C:/broll"
    assert len(state["clips"]) == 1
    assert state["clips"][0]["filename"] == "clip.mp4"
    assert "words" in state["clips"][0]
    assert "transcript_marked" in state["clips"][0]
    assert "last_modified" in state
    assert isinstance(state["captions"]["entries"], list)
    assert state["broll"] == []


def test_caption_entries_generated(tmp_path):
    """Caption entries group kept words into lines of words_per_line."""
    from autoedit import generate_caption_entries

    words = [{"word": f"w{i}", "start": float(i), "end": float(i) + 0.5} for i in range(14)]
    entries = generate_caption_entries(words, cuts=[], words_per_line=7)

    assert len(entries) == 2
    assert entries[0]["text"] == "w0 w1 w2 w3 w4 w5 w6"
    assert entries[1]["text"] == "w7 w8 w9 w10 w11 w12 w13"
    assert entries[0]["start"] == 0.0
    assert entries[0]["clip"] == ""  # clip name is injected by caller


def test_caption_entries_skip_cuts(tmp_path):
    """Caption entries exclude words that fall inside cuts."""
    from autoedit import generate_caption_entries

    words = [{"word": f"w{i}", "start": float(i), "end": float(i) + 0.5} for i in range(5)]
    cuts = [{"start": 1.0, "end": 2.5}]  # cuts out w1, w2
    entries = generate_caption_entries(words, cuts=cuts, words_per_line=7)

    texts = " ".join(e["text"] for e in entries)
    assert "w1" not in texts
    assert "w2" not in texts
    assert "w0" in texts
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "C:\Users\chris\.claude\skills\easyedits"
python -m pytest tests/test_autoedit_state.py -v
```

Expected: FAIL — `generate_caption_entries` not defined, `mode_transcribe` missing params.

- [ ] **Step 3: Add `generate_caption_entries` to `autoedit.py`**

Add this function after the `detect_fillers` function (around line 240):

```python
def generate_caption_entries(words: list[dict], cuts: list[dict], words_per_line: int = 7, clip_name: str = "") -> list[dict]:
    """Group kept words into caption entries of words_per_line each."""
    cut_ranges = [(c["start"], c["end"]) for c in cuts]
    kept = [
        w for w in words
        if not any(cs <= w["start"] and w["end"] <= ce + 0.05 for cs, ce in cut_ranges)
    ]
    entries = []
    for i in range(0, len(kept), words_per_line):
        chunk = kept[i:i + words_per_line]
        if chunk:
            entries.append({
                "clip": clip_name,
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
                "text": " ".join(w["word"] for w in chunk).strip()
            })
    return entries
```

- [ ] **Step 4: Update `mode_transcribe` signature and add state-writing**

First, add `import time` to the top-level imports in `autoedit.py` (alongside the existing `import sys`, `import os`, etc.):

```python
import time
```

Change the function signature from:
```python
def mode_transcribe(folder: Path, order: list[str], overrides: dict = None):
```
to:
```python
def mode_transcribe(folder: Path, order: list[str], overrides: dict = None,
                    video_type: str = "", broll_folder: str = ""):
```

After the existing `cache_path` write block (around line 450), add:

```python

    # Write preview_state.json for the browser preview
    state_clips = []
    all_caption_entries = []

    for r in results:
        clip_cuts = r.get("cuts", [])
        words = r.get("words", [])
        clip_entries = generate_caption_entries(
            words, cuts=clip_cuts, words_per_line=7, clip_name=r["clip"]
        )
        all_caption_entries.extend(clip_entries)
        state_clips.append({
            "filename": r["clip"],
            "path": str(folder / r["clip"]),
            "duration_sec": r.get("duration_sec", 0),
            "words": words,
            "transcript_marked": r.get("transcript", "")
        })

    all_state_cuts = [
        {**cut, "clip": r["clip"]}
        for r in results
        for cut in r.get("cuts", [])
    ]

    preview_state = {
        "last_modified": time.time(),
        "video_type": video_type,
        "broll_folder": broll_folder,
        "clips": state_clips,
        "cuts": all_state_cuts,
        "broll": [],
        "captions": {
            "words_per_line": 7,
            "entries": all_caption_entries
        }
    }

    state_path = output_dir / "preview_state.json"
    with open(state_path, "w") as f:
        json.dump(preview_state, f, indent=2)
```

- [ ] **Step 5: Update `main()` to pass new args**

In the `main()` function, add two new arguments to the parser:

```python
    parser.add_argument("--video-type",   default="")
    parser.add_argument("--broll-folder", default="")
```

Update the `mode_transcribe` call:

```python
    elif args.transcribe:
        mode_transcribe(folder, order, overrides,
                        video_type=args.video_type,
                        broll_folder=args.broll_folder)
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
python -m pytest tests/test_autoedit_state.py -v
```

Expected: all 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/autoedit.py tests/test_autoedit_state.py
git commit -m "feat: write preview_state.json after transcription"
```

---

## Task 2 — `preview_server.py`: Flask server

**Files:**
- Create: `scripts/preview_server.py`
- Create: `tests/test_preview_server.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_preview_server.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import preview_server

def make_client(tmp_path, state=None):
    output_dir = tmp_path / "easyedits_output"
    output_dir.mkdir(exist_ok=True)
    if state is not None:
        (output_dir / "preview_state.json").write_text(json.dumps(state))
    preview_server.FOLDER = tmp_path
    preview_server.STATE_PATH = output_dir / "preview_state.json"
    return preview_server.app.test_client()


def test_state_returns_json(tmp_path):
    """GET /state returns the contents of preview_state.json."""
    state = {"last_modified": 1234.0, "clips": [], "cuts": [], "broll": []}
    client = make_client(tmp_path, state)
    res = client.get("/state")
    assert res.status_code == 200
    assert json.loads(res.data)["last_modified"] == 1234.0


def test_state_missing_returns_404(tmp_path):
    """GET /state returns 404 when preview_state.json does not exist."""
    client = make_client(tmp_path, state=None)
    res = client.get("/state")
    assert res.status_code == 404


def test_video_missing_returns_404(tmp_path):
    """GET /video/<filename> returns 404 for non-existent clip."""
    client = make_client(tmp_path, state={"broll_folder": ""})
    res = client.get("/video/nonexistent.mp4")
    assert res.status_code == 404


def test_video_path_traversal_blocked(tmp_path):
    """Path traversal in /video/ is blocked — only the basename is used."""
    # Place a file at the root of tmp_path with a safe name
    (tmp_path / "safe.mp4").write_bytes(b"data")
    client = make_client(tmp_path, state={"broll_folder": ""})
    # Traversal attempt — after sanitization it becomes "passwd" which doesn't exist
    res = client.get("/video/../../../etc/passwd")
    assert res.status_code == 404


def test_index_serves_html(tmp_path):
    """GET / returns the preview.html file."""
    # Place a stub preview.html next to the server script
    html_path = Path(__file__).parent.parent / "scripts" / "preview.html"
    assert html_path.exists(), "preview.html must exist before running this test"
    client = make_client(tmp_path)
    res = client.get("/")
    assert res.status_code == 200
    assert b"<!DOCTYPE html>" in res.data.lower() or b"<html" in res.data.lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_preview_server.py -v
```

Expected: FAIL — `preview_server` module does not exist.

- [ ] **Step 3: Create `scripts/preview_server.py`**

```python
#!/usr/bin/env python3
"""
preview_server.py — EasyEdits local preview server
Serves preview.html and streams video files for the browser preview.

Usage:
  python preview_server.py --folder "C:\\Videos\\MyVideo"
"""

import argparse
import json
import os
import socket
import sys
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request, send_file

app = Flask(__name__)
FOLDER: Path = None
STATE_PATH: Path = None
SCRIPT_DIR = Path(__file__).parent


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file(SCRIPT_DIR / "preview.html")


@app.route("/state")
def state():
    if not STATE_PATH or not STATE_PATH.exists():
        return jsonify({"error": "preview_state.json not found"}), 404
    with open(STATE_PATH) as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/video/<filename>")
def video(filename):
    filename = Path(filename).name   # block path traversal
    path = FOLDER / filename
    if not path.exists():
        abort(404)
    return send_file(str(path), conditional=True)


@app.route("/broll/<filename>")
def broll(filename):
    filename = Path(filename).name
    if not STATE_PATH or not STATE_PATH.exists():
        abort(404)
    with open(STATE_PATH) as f:
        state_data = json.load(f)
    broll_folder = state_data.get("broll_folder", "")
    if not broll_folder:
        abort(404)
    path = Path(broll_folder) / filename
    if not path.exists():
        abort(404)
    return send_file(str(path), conditional=True)


# ── PID helpers ───────────────────────────────────────────────────────────────

def _pid_path(output_dir: Path) -> Path:
    return output_dir / "preview_server.pid"


def write_pid(output_dir: Path):
    _pid_path(output_dir).write_text(str(os.getpid()))


def cleanup_pid(output_dir: Path):
    p = _pid_path(output_dir)
    if p.exists():
        p.unlink()


# ── Port helpers ──────────────────────────────────────────────────────────────

def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def find_free_port(start: int = 5000, tries: int = 3) -> int:
    for p in range(start, start + tries):
        if _port_free(p):
            return p
    print(f"ERROR: No free port found in range {start}–{start + tries - 1}.")
    sys.exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    global FOLDER, STATE_PATH

    parser = argparse.ArgumentParser(description="EasyEdits preview server")
    parser.add_argument("--folder", required=True)
    parser.add_argument("--port",   type=int, default=5000)
    args = parser.parse_args()

    FOLDER = Path(args.folder)
    output_dir = FOLDER / "easyedits_output"
    STATE_PATH = output_dir / "preview_state.json"

    output_dir.mkdir(exist_ok=True)
    write_pid(output_dir)

    import atexit
    atexit.register(cleanup_pid, output_dir)

    port = find_free_port(args.port)
    print(f"\nEasyEdits preview running at: http://localhost:{port}")
    print("Open this URL in your browser. Press Ctrl+C to stop.\n")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_preview_server.py -v
```

Expected: `test_index_serves_html` will FAIL (preview.html doesn't exist yet) — all others PASS. That is expected at this stage.

- [ ] **Step 5: Commit**

```bash
git add scripts/preview_server.py tests/test_preview_server.py
git commit -m "feat: add Flask preview server"
```

---

## Task 3 — `preview.html`: complete frontend

**Files:**
- Create: `scripts/preview.html`

No automated tests — browser-verified manually at the end of Task 3.

- [ ] **Step 1: Create `scripts/preview.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>EasyEdits Preview</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #1a1a1a; color: #e0e0e0; font-family: monospace; height: 100vh; overflow: hidden; }
#app { display: flex; height: 100vh; }

/* ── Left panel ── */
#transcript-panel { width: 380px; min-width: 260px; border-right: 1px solid #2d2d2d; display: flex; flex-direction: column; }
#stats-bar { padding: 10px 14px; background: #222; border-bottom: 1px solid #2d2d2d; font-size: 12px; color: #888; }
#transcript-content { flex: 1; overflow-y: auto; padding: 14px; font-size: 13px; line-height: 1.8; }
.clip-header { color: #555; font-size: 11px; margin: 14px 0 6px; text-transform: uppercase; letter-spacing: 0.05em; }
.transcript-text { white-space: pre-wrap; }
.cut-silence { color: #484848; font-style: italic; }
.cut-filler { text-decoration: line-through; color: #555; }
.cut-false-start { color: #484848; font-style: italic; }
.broll-marker { color: #4a9eff; font-size: 11px; display: block; margin: 6px 0; }

/* ── Right panel ── */
#right-panel { flex: 1; display: flex; flex-direction: column; min-width: 0; }

/* ── Video player ── */
#player-section { padding: 14px 16px 10px; flex-shrink: 0; }
#video-container { position: relative; background: #000; width: 100%; aspect-ratio: 16/9; max-height: 52vh; }
#main-video  { width: 100%; height: 100%; object-fit: contain; display: block; }
#broll-video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; display: none; }
#caption-overlay { position: absolute; bottom: 8%; left: 8%; right: 8%; text-align: center; font-size: 20px; font-weight: 700; color: #fff; text-shadow: 0 0 8px #000, 0 2px 4px #000; display: none; pointer-events: none; }
#player-info { display: flex; align-items: center; gap: 10px; padding: 8px 0 5px; font-size: 12px; }
#play-pause  { background: #4a9eff; color: #fff; border: none; border-radius: 4px; padding: 5px 13px; cursor: pointer; font-size: 15px; }
#play-pause:hover { background: #3a8eef; }
#clip-name   { color: #888; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#timestamp   { color: #666; flex-shrink: 0; }
#prog-outer  { height: 3px; background: #2d2d2d; border-radius: 2px; cursor: pointer; }
#prog-inner  { height: 100%; background: #4a9eff; border-radius: 2px; width: 0%; }

/* ── Timeline ── */
#timeline-section { flex: 1; border-top: 1px solid #2d2d2d; padding: 10px 16px; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
#timeline-header  { font-size: 10px; color: #555; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }
#timeline-tracks  { position: relative; flex: 1; }
.track       { display: flex; align-items: center; height: 26px; margin-bottom: 3px; }
.track-label { width: 26px; font-size: 10px; color: #555; flex-shrink: 0; }
.track-content { flex: 1; position: relative; height: 20px; background: #222; border-radius: 2px; overflow: visible; cursor: pointer; }
.clip-block  { position: absolute; height: 100%; border-radius: 2px; opacity: 0.85; cursor: pointer; }
.cut-overlay { position: absolute; height: 100%; background: repeating-linear-gradient(45deg,rgba(0,0,0,0.5),rgba(0,0,0,0.5) 2px,transparent 2px,transparent 5px); border-radius: 2px; }
.broll-block { background: #ff7043 !important; }
#playhead    { position: absolute; top: 0; width: 2px; background: #fff; pointer-events: none; opacity: 0.8; }
</style>
</head>
<body>
<div id="app">
  <div id="transcript-panel">
    <div id="stats-bar">Loading…</div>
    <div id="transcript-content"></div>
  </div>
  <div id="right-panel">
    <div id="player-section">
      <div id="video-container">
        <video id="main-video"  preload="metadata"></video>
        <video id="broll-video" preload="metadata"></video>
        <div  id="caption-overlay"></div>
      </div>
      <div id="player-info">
        <button id="play-pause">▶</button>
        <span   id="clip-name">—</span>
        <span   id="timestamp">0:00 / 0:00</span>
      </div>
      <div id="prog-outer"><div id="prog-inner"></div></div>
    </div>
    <div id="timeline-section">
      <div id="timeline-header">Timeline</div>
      <div id="timeline-tracks">
        <div class="track"><span class="track-label">V2</span><div class="track-content" id="v2-content"></div></div>
        <div class="track"><span class="track-label">V1</span><div class="track-content" id="v1-content"></div></div>
        <div class="track"><span class="track-label">A1</span><div class="track-content" id="a1-content"></div></div>
        <div id="playhead" style="height:78px;top:0;left:0;"></div>
      </div>
    </div>
  </div>
</div>
<script>
// ── State ──────────────────────────────────────────────────────────────────────
let state = null, timeline = [], totalDuration = 0;
let currentClipIdx = 0, globalPosition = 0;
let isPlaying = false, lastModified = 0, activeBroll = null;

const mainVideo  = document.getElementById('main-video');
const brollVideo = document.getElementById('broll-video');
const captionEl  = document.getElementById('caption-overlay');
const playBtn    = document.getElementById('play-pause');
const clipNameEl = document.getElementById('clip-name');
const tsEl       = document.getElementById('timestamp');
const progEl     = document.getElementById('prog-inner');
const playhead   = document.getElementById('playhead');
const v1El = document.getElementById('v1-content');
const v2El = document.getElementById('v2-content');
const a1El = document.getElementById('a1-content');
const COLORS = ['#4a9eff','#ff7043','#66bb6a','#ab47bc','#ffa726'];

function fmt(s) {
  return `${Math.floor(s/60)}:${Math.floor(s%60).toString().padStart(2,'0')}`;
}

// ── State polling ──────────────────────────────────────────────────────────────
async function fetchState() {
  try {
    const data = await fetch('/state').then(r => r.json());
    if (data.last_modified === lastModified) return;
    const clipsChanged = !state ||
      JSON.stringify(state.clips.map(c=>c.filename)) !==
      JSON.stringify(data.clips.map(c=>c.filename));
    lastModified = data.last_modified;
    state = data;
    buildVirtualTimeline();
    renderTranscript();
    renderTimelineUI();
    if (clipsChanged && state.clips.length > 0) { currentClipIdx = 0; loadClip(0, false); }
  } catch (_) {}
}

// ── Virtual timeline ───────────────────────────────────────────────────────────
function buildVirtualTimeline() {
  timeline = []; totalDuration = 0;
  if (!state) return;
  for (const clip of state.clips) {
    const cuts = (state.cuts||[]).filter(c=>c.clip===clip.filename).sort((a,b)=>a.start-b.start);
    const segs = []; let pos = 0;
    for (const cut of cuts) {
      if (cut.start > pos + 0.01) segs.push({start:pos, end:cut.start});
      pos = cut.end;
    }
    if (pos < clip.duration_sec - 0.01) segs.push({start:pos, end:clip.duration_sec});
    if (segs.length === 0) segs.push({start:0, end:clip.duration_sec});
    for (const seg of segs) {
      timeline.push({clip:clip.filename, localStart:seg.start, localEnd:seg.end,
                     globalStart:totalDuration, globalEnd:totalDuration+(seg.end-seg.start)});
      totalDuration += seg.end - seg.start;
    }
  }
}

// ── Clip loading ───────────────────────────────────────────────────────────────
function loadClip(idx, autoPlay=true) {
  if (!state || idx >= state.clips.length) return;
  const clip = state.clips[idx];
  currentClipIdx = idx;
  mainVideo.src = `/video/${encodeURIComponent(clip.filename)}`;
  clipNameEl.textContent = clip.filename;
  if (autoPlay && isPlaying) mainVideo.play().catch(()=>{});
}

// ── Global position ────────────────────────────────────────────────────────────
function getGlobalPos() {
  if (!state || !state.clips[currentClipIdx]) return 0;
  const name = state.clips[currentClipIdx].filename;
  const t = mainVideo.currentTime;
  for (const seg of timeline) {
    if (seg.clip === name && t >= seg.localStart - 0.05 && t <= seg.localEnd + 0.05)
      return seg.globalStart + Math.max(0, t - seg.localStart);
  }
  return 0;
}

// ── Seek to global position ────────────────────────────────────────────────────
function seekToGlobal(target) {
  const seg = timeline.find(s => target >= s.globalStart && target < s.globalEnd);
  if (!seg) return;
  const idx = state.clips.findIndex(c => c.filename === seg.clip);
  const local = seg.localStart + (target - seg.globalStart);
  if (idx !== currentClipIdx) {
    currentClipIdx = idx;
    clipNameEl.textContent = seg.clip;
    mainVideo.src = `/video/${encodeURIComponent(seg.clip)}`;
    mainVideo.addEventListener('loadedmetadata', () => {
      mainVideo.currentTime = local;
      if (isPlaying) mainVideo.play().catch(()=>{});
    }, {once:true});
  } else {
    mainVideo.currentTime = local;
  }
}

// ── timeupdate ─────────────────────────────────────────────────────────────────
mainVideo.addEventListener('timeupdate', () => {
  if (!state || !state.clips[currentClipIdx]) return;
  const name = state.clips[currentClipIdx].filename;
  const t = mainVideo.currentTime;
  // Skip over cuts
  for (const cut of (state.cuts||[]).filter(c=>c.clip===name)) {
    if (t >= cut.start && t < cut.end - 0.02) { mainVideo.currentTime = cut.end + 0.05; return; }
  }
  globalPosition = getGlobalPos();
  updateCaption(); updateBroll(); updateProgress(); updatePlayhead();
});

mainVideo.addEventListener('ended', () => {
  if (state && currentClipIdx + 1 < state.clips.length) {
    currentClipIdx++;
    loadClip(currentClipIdx, true);
    mainVideo.play().catch(()=>{});
  } else { isPlaying=false; playBtn.textContent='▶'; }
});

// ── Play / Pause ───────────────────────────────────────────────────────────────
playBtn.addEventListener('click', () => {
  if (isPlaying) { mainVideo.pause(); } else { mainVideo.play().catch(()=>{}); }
});
mainVideo.addEventListener('play',  () => { isPlaying=true;  playBtn.textContent='⏸'; });
mainVideo.addEventListener('pause', () => { isPlaying=false; playBtn.textContent='▶'; });

// ── B-roll overlay ─────────────────────────────────────────────────────────────
function updateBroll() {
  const broll = (state&&state.broll)||[];
  const cur = broll.find(b => globalPosition>=b.at_sec && globalPosition<b.at_sec+b.duration);
  if (cur && cur!==activeBroll) {
    activeBroll = cur;
    brollVideo.src = `/broll/${encodeURIComponent(cur.filename)}`;
    brollVideo.muted = cur.muted !== false;
    brollVideo.style.display = 'block';
    brollVideo.currentTime = globalPosition - cur.at_sec;
    brollVideo.play().catch(()=>{});
  } else if (!cur && activeBroll) {
    activeBroll = null;
    brollVideo.pause(); brollVideo.style.display='none'; brollVideo.src='';
  }
}

// ── Captions ───────────────────────────────────────────────────────────────────
function updateCaption() {
  if (!state||!state.captions||!state.clips[currentClipIdx]) return;
  const name = state.clips[currentClipIdx].filename;
  const t = mainVideo.currentTime;
  const e = (state.captions.entries||[]).find(e=>e.clip===name&&t>=e.start&&t<=e.end);
  captionEl.textContent = e ? e.text : '';
  captionEl.style.display = e ? 'block' : 'none';
}

// ── Progress bar ───────────────────────────────────────────────────────────────
function updateProgress() {
  const pct = totalDuration>0 ? (globalPosition/totalDuration)*100 : 0;
  progEl.style.width = `${pct}%`;
  tsEl.textContent = `${fmt(globalPosition)} / ${fmt(totalDuration)}`;
}
document.getElementById('prog-outer').addEventListener('click', e => {
  const r = e.currentTarget.getBoundingClientRect();
  seekToGlobal(((e.clientX-r.left)/r.width)*totalDuration);
});

// ── Playhead ───────────────────────────────────────────────────────────────────
function updatePlayhead() {
  const v1r = v1El.getBoundingClientRect();
  const ttr = document.getElementById('timeline-tracks').getBoundingClientRect();
  const pct = totalDuration>0 ? (globalPosition/totalDuration)*100 : 0;
  playhead.style.left = `${(v1r.left-ttr.left)+(pct/100)*v1r.width}px`;
}

// ── Timeline UI ────────────────────────────────────────────────────────────────
function renderTimelineUI() {
  if (!state || totalDuration===0) return;
  [v1El,v2El,a1El].forEach(el=>el.innerHTML='');

  for (let i=0; i<state.clips.length; i++) {
    const clip = state.clips[i];
    const segs = timeline.filter(s=>s.clip===clip.filename);
    if (!segs.length) continue;
    const gStart=segs[0].globalStart, gEnd=segs[segs.length-1].globalEnd;
    const left=`${(gStart/totalDuration)*100}%`, width=`${((gEnd-gStart)/totalDuration)*100}%`;
    const color=COLORS[i%COLORS.length];

    [v1El,a1El].forEach(trackEl => {
      const block=document.createElement('div');
      block.className='clip-block';
      block.style.cssText=`left:${left};width:${width};background:${color};`;
      block.title=`${clip.filename} (${fmt(gEnd-gStart)})`;
      // Cut overlays (approximate visual position within original clip duration)
      for (const cut of (state.cuts||[]).filter(c=>c.clip===clip.filename)) {
        if (clip.duration_sec > 0) {
          const cLeft=`${(cut.start/clip.duration_sec)*100}%`;
          const cWidth=`${((cut.end-cut.start)/clip.duration_sec)*100}%`;
          const ov=document.createElement('div');
          ov.className='cut-overlay'; ov.style.cssText=`left:${cLeft};width:${cWidth};`;
          block.appendChild(ov);
        }
      }
      block.addEventListener('click', e => {
        const r=block.getBoundingClientRect();
        const localFrac=(e.clientX-r.left)/r.width;
        seekToGlobal(gStart+(gEnd-gStart)*localFrac);
        e.stopPropagation();
      });
      trackEl.appendChild(block);
    });
  }

  for (const br of (state.broll||[])) {
    const block=document.createElement('div');
    block.className='clip-block broll-block';
    block.style.cssText=`left:${(br.at_sec/totalDuration)*100}%;width:${(br.duration/totalDuration)*100}%;`;
    block.title=`${br.filename} (${br.duration}s)${br.muted!==false?' [muted]':''}`;
    v2El.appendChild(block);
  }
}

// ── Transcript ─────────────────────────────────────────────────────────────────
function renderTranscript() {
  if (!state) return;
  const totalOrig = state.clips.reduce((s,c)=>s+c.duration_sec,0);
  const cutTime   = (state.cuts||[]).reduce((s,c)=>s+(c.end-c.start),0);
  document.getElementById('stats-bar').textContent =
    `${(state.cuts||[]).length} cuts · saves ${fmt(cutTime)} · output ${fmt(totalOrig-cutTime)}`;

  const content = document.getElementById('transcript-content');
  content.innerHTML = '';

  // Compute per-clip global offsets for b-roll marker placement
  const clipOffsets = {};
  let off = 0;
  for (const clip of state.clips) {
    clipOffsets[clip.filename] = off;
    const clipCutTime=(state.cuts||[]).filter(c=>c.clip===clip.filename).reduce((s,c)=>s+(c.end-c.start),0);
    off += clip.duration_sec - clipCutTime;
  }

  for (const clip of state.clips) {
    const hdr=document.createElement('div'); hdr.className='clip-header';
    hdr.textContent=`── ${clip.filename} ──`; content.appendChild(hdr);

    if (clip.transcript_marked) {
      const pre=document.createElement('pre'); pre.className='transcript-text';
      pre.innerHTML=clip.transcript_marked
        .replace(/\[(\.\.\.[^\]]+)\]/g, m=>`<span class="cut-silence">${m}</span>`)
        .replace(/\[false start\]/g, m=>`<span class="cut-false-start">${m}</span>`)
        .replace(/\[([^\]]+)\]/g, m=>`<span class="cut-filler">${m}</span>`);
      content.appendChild(pre);
    }

    const clipGlobalStart = clipOffsets[clip.filename]||0;
    const clipCutDur=(state.cuts||[]).filter(c=>c.clip===clip.filename).reduce((s,c)=>s+(c.end-c.start),0);
    const clipGlobalEnd=clipGlobalStart+(clip.duration_sec-clipCutDur);

    for (const br of (state.broll||[])) {
      if (br.at_sec>=clipGlobalStart && br.at_sec<clipGlobalEnd) {
        const mk=document.createElement('span'); mk.className='broll-marker';
        mk.textContent=`▶ ${br.filename} (${br.duration}s at ${fmt(br.at_sec)})`;
        content.appendChild(mk);
      }
    }
  }
}

// ── Boot ───────────────────────────────────────────────────────────────────────
fetchState();
setInterval(fetchState, 2000);
</script>
</body>
</html>
```

- [ ] **Step 2: Run the `test_index_serves_html` test that was previously failing**

```bash
python -m pytest tests/test_preview_server.py::test_index_serves_html -v
```

Expected: PASS.

- [ ] **Step 3: Manual browser smoke-test**

Start the server against a real clip folder:

```bash
python scripts/preview_server.py --folder "C:\Users\chris\Videos\TestClips"
```

Open `http://localhost:5000`. Confirm:
- Page loads with two-panel layout (no JS console errors)
- Stats bar shows "Loading…" until `preview_state.json` exists
- Once state exists: transcript renders, video loads

- [ ] **Step 4: Commit**

```bash
git add scripts/preview.html
git commit -m "feat: add browser preview frontend"
```

---

## Task 4 — `xml_builder.py`: `--words-per-caption` + update preview state

**Files:**
- Modify: `scripts/xml_builder.py`
- Create: `tests/test_xml_builder_v2.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_xml_builder_v2.py`:

```python
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def make_segments(words, in_sec=0.0, out_sec=None):
    if out_sec is None:
        out_sec = float(len(words))
    return [{
        "clip_name": "clip.mp4",
        "in_sec": in_sec,
        "out_sec": out_sec,
        "timeline_in_sec": 0.0,
        "timeline_out_sec": out_sec - in_sec,
        "words": words
    }]


def test_words_per_line_default(tmp_path):
    """build_srt groups 14 words into 2 lines of 7 by default."""
    from xml_builder import build_srt
    words = [{"word": f"w{i}", "start": float(i), "end": float(i)+0.5} for i in range(14)]
    srt = build_srt(make_segments(words, out_sec=14.5), tmp_path)
    lines = [l for l in srt.read_text().splitlines() if l and "-->" not in l and not l.isdigit()]
    assert len(lines) == 2
    assert all(len(l.split()) <= 7 for l in lines)


def test_words_per_line_2(tmp_path):
    """build_srt groups 6 words into 3 lines of 2 when words_per_line=2."""
    from xml_builder import build_srt
    words = [{"word": f"w{i}", "start": float(i), "end": float(i)+0.5} for i in range(6)]
    srt = build_srt(make_segments(words, out_sec=6.5), tmp_path, words_per_line=2)
    lines = [l for l in srt.read_text().splitlines() if l and "-->" not in l and not l.isdigit()]
    assert len(lines) == 3
    assert all(len(l.split()) <= 2 for l in lines)


def test_update_preview_captions(tmp_path):
    """update_preview_captions rewrites captions.entries and bumps last_modified."""
    from xml_builder import update_preview_captions
    state = {
        "last_modified": 1000.0,
        "captions": {"words_per_line": 7, "entries": []}
    }
    sp = tmp_path / "preview_state.json"
    sp.write_text(json.dumps(state))

    plan = {"clips": [{
        "clip": "clip.mp4",
        "words": [{"word": f"w{i}", "start": float(i), "end": float(i)+0.5} for i in range(4)],
        "cuts": []
    }]}

    before = time.time()
    update_preview_captions(plan, sp, words_per_line=2)

    updated = json.loads(sp.read_text())
    assert updated["captions"]["words_per_line"] == 2
    assert len(updated["captions"]["entries"]) == 2
    assert updated["captions"]["entries"][0]["text"] == "w0 w1"
    assert updated["last_modified"] >= before
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_xml_builder_v2.py::test_words_per_line_default tests/test_xml_builder_v2.py::test_words_per_line_2 tests/test_xml_builder_v2.py::test_update_preview_captions -v
```

Expected: FAIL — `build_srt` signature mismatch, `update_preview_captions` not defined.

- [ ] **Step 3: Add `words_per_line` parameter to `build_srt`**

In `xml_builder.py`, change line 233:
```python
def build_srt(keep_segments: list[dict], output_dir: Path) -> Path:
```
to:
```python
def build_srt(keep_segments: list[dict], output_dir: Path, words_per_line: int = 7) -> Path:
```

Change the hardcoded constant on line 240:
```python
    WORDS_PER_LINE = 7
```
to:
```python
    WORDS_PER_LINE = words_per_line
```

- [ ] **Step 4: Add `update_preview_captions` function**

Add this function after `build_srt` (before the `# ── Entry point` comment):

```python
def update_preview_captions(plan: dict, state_path: Path, words_per_line: int) -> None:
    """Regenerate captions.entries in preview_state.json with new words_per_line."""
    import time as _time

    with open(state_path) as f:
        state = json.load(f)

    entries = []
    for clip_data in plan["clips"]:
        clip_name = clip_data["clip"]
        words = clip_data.get("words", [])
        cuts  = clip_data.get("cuts", [])
        cut_ranges = [(c["start"], c["end"]) for c in cuts]
        kept = [
            w for w in words
            if not any(cs <= w["start"] and w["end"] <= ce + 0.05 for cs, ce in cut_ranges)
        ]
        for i in range(0, len(kept), words_per_line):
            chunk = kept[i:i + words_per_line]
            if chunk:
                entries.append({
                    "clip":  clip_name,
                    "start": chunk[0]["start"],
                    "end":   chunk[-1]["end"],
                    "text":  " ".join(w["word"] for w in chunk).strip()
                })

    state["captions"]["words_per_line"] = words_per_line
    state["captions"]["entries"]        = entries
    state["last_modified"]              = _time.time()

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)
```

- [ ] **Step 5: Update `main()` in `xml_builder.py`**

Add `--words-per-caption` argument and wire it up:

```python
def main():
    parser = argparse.ArgumentParser(description="EasyEdits — xml_builder.py")
    parser.add_argument("--plan",              required=True)
    parser.add_argument("--words-per-caption", type=int, default=7)
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.exists():
        print(json.dumps({"error": f"Plan file not found: {plan_path}"}))
        return

    with open(plan_path) as f:
        plan = json.load(f)

    output_dir = plan_path.parent
    state_path = output_dir / "preview_state.json"

    print("Building XML timeline...")
    xml_path, keep_segments = build_fcpxml(plan, output_dir)
    print(f"  [ok] edit.xml -> {xml_path}")

    print("Building SRT captions...")
    srt_path = build_srt(keep_segments, output_dir, words_per_line=args.words_per_caption)
    print(f"  [ok] captions.srt -> {srt_path}")

    if state_path.exists():
        update_preview_captions(plan, state_path, args.words_per_caption)
        print(f"  [ok] preview_state.json captions updated")

    print(json.dumps({"status": "ok", "xml": str(xml_path), "srt": str(srt_path)}))
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
python -m pytest tests/test_xml_builder_v2.py -v
```

Expected: all 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/xml_builder.py tests/test_xml_builder_v2.py
git commit -m "feat: add --words-per-caption flag and update_preview_captions"
```

---

## Task 5 — `xml_builder.py`: B-roll V2 XML track

**Files:**
- Modify: `scripts/xml_builder.py`
- Modify: `tests/test_xml_builder_v2.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_xml_builder_v2.py`:

```python
def test_broll_v2_track_in_xml(tmp_path):
    """build_fcpxml includes a second <track> in <video> when broll entries provided."""
    from xml_builder import build_fcpxml
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")
    broll_clip = tmp_path / "broll.mp4"
    broll_clip.write_bytes(b"")

    plan = {
        "folder": str(tmp_path),
        "order": ["clip.mp4"],
        "clips": [{"clip": "clip.mp4", "duration_sec": 30.0, "cuts": [], "words": []}]
    }
    broll = [{"filename": "broll.mp4", "path": str(broll_clip),
              "at_sec": 5.0, "duration": 3.0, "muted": True}]

    with patch("xml_builder.get_video_dimensions", return_value=(1920, 1080, "30/1")):
        xml_path, _ = build_fcpxml(plan, tmp_path, broll=broll)

    content = xml_path.read_text()
    assert content.count("<track>") >= 2     # V1 + V2 video tracks
    assert "broll.mp4" in content


def test_no_broll_single_track(tmp_path):
    """build_fcpxml produces only one video track when no broll provided."""
    from xml_builder import build_fcpxml
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"")

    plan = {
        "folder": str(tmp_path),
        "order": ["clip.mp4"],
        "clips": [{"clip": "clip.mp4", "duration_sec": 30.0, "cuts": [], "words": []}]
    }

    with patch("xml_builder.get_video_dimensions", return_value=(1920, 1080, "30/1")):
        xml_path, _ = build_fcpxml(plan, tmp_path, broll=[])

    content = xml_path.read_text()
    # Video element has exactly 1 track (the main V1 track)
    # Count tracks inside <video> element — audio has its own track too
    # Simplest check: broll.mp4 should NOT appear
    assert "broll.mp4" not in content
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_xml_builder_v2.py::test_broll_v2_track_in_xml tests/test_xml_builder_v2.py::test_no_broll_single_track -v
```

Expected: FAIL — `build_fcpxml` does not accept `broll` keyword.

- [ ] **Step 3: Add `broll` parameter and V2 track to `build_fcpxml`**

Change the function signature from:
```python
def build_fcpxml(plan: dict, output_dir: Path) -> Path:
```
to:
```python
def build_fcpxml(plan: dict, output_dir: Path, broll: list = None) -> Path:
```

After the line `video_track = SubElement(video_el, "track")` (the V1 track), add:

```python
    # V2 video track — b-roll overlays (only added when broll entries exist)
    broll = broll or []
    video_track_v2 = SubElement(video_el, "track") if broll else None
```

After the main `for seg in keep_segments` loop (after `clip_id += 1`), add:

```python
    # ── B-roll V2 clips ──────────────────────────────────────────────────────
    if broll and video_track_v2 is not None:
        for br_idx, br in enumerate(broll, start=1):
            br_path = Path(br["path"])
            br_in_frames  = 0
            br_out_frames = sec_to_frames(br["duration"], fps_num, fps_den)
            br_tl_in      = sec_to_frames(br["at_sec"],            fps_num, fps_den)
            br_tl_out     = sec_to_frames(br["at_sec"] + br["duration"], fps_num, fps_den)
            br_dur_frames = br_out_frames - br_in_frames

            bv = SubElement(video_track_v2, "clipitem", id=f"broll-v{br_idx}")
            SubElement(bv, "name").text     = br["filename"]
            SubElement(bv, "duration").text = str(br_dur_frames)
            bv_rate = SubElement(bv, "rate")
            SubElement(bv_rate, "timebase").text = str(int(fps_float))
            SubElement(bv_rate, "ntsc").text     = "FALSE"
            SubElement(bv, "in").text    = str(br_in_frames)
            SubElement(bv, "out").text   = str(br_out_frames)
            SubElement(bv, "start").text = str(br_tl_in)
            SubElement(bv, "end").text   = str(br_tl_out)

            br_file = SubElement(bv, "file", id=f"broll-file-{br_idx}")
            SubElement(br_file, "name").text    = br["filename"]
            SubElement(br_file, "pathurl").text = br_path.as_uri()
            brf_rate = SubElement(br_file, "rate")
            SubElement(brf_rate, "timebase").text = str(int(fps_float))
            SubElement(brf_rate, "ntsc").text     = "FALSE"
            SubElement(br_file, "duration").text  = str(br_out_frames)

            # Include audio channel only when not muted
            if not br.get("muted", True):
                br_audio_track = SubElement(audio_el, "track")
                ba = SubElement(br_audio_track, "clipitem", id=f"broll-a{br_idx}")
                SubElement(ba, "name").text      = br["filename"]
                SubElement(ba, "duration").text  = str(br_dur_frames)
                ba_rate = SubElement(ba, "rate")
                SubElement(ba_rate, "timebase").text = str(int(fps_float))
                SubElement(ba_rate, "ntsc").text     = "FALSE"
                SubElement(ba, "in").text    = str(br_in_frames)
                SubElement(ba, "out").text   = str(br_out_frames)
                SubElement(ba, "start").text = str(br_tl_in)
                SubElement(ba, "end").text   = str(br_tl_out)
                SubElement(ba, "file").set("id", f"broll-file-{br_idx}")
```

Also update `main()` in `xml_builder.py` to read broll from `preview_state.json` and pass it to `build_fcpxml`:

```python
    # Read broll from preview_state.json if available
    broll = []
    if state_path.exists():
        with open(state_path) as f:
            ps = json.load(f)
        broll = ps.get("broll", [])

    print("Building XML timeline...")
    xml_path, keep_segments = build_fcpxml(plan, output_dir, broll=broll)
```

- [ ] **Step 4: Run all xml_builder tests**

```bash
python -m pytest tests/test_xml_builder_v2.py -v
```

Expected: all 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/xml_builder.py tests/test_xml_builder_v2.py
git commit -m "feat: add b-roll V2 XML track to xml_builder"
```

---

## Task 6 — `SKILL.md`: updated flow

**Files:**
- Modify: `SKILL.md`

- [ ] **Step 1: Replace the entire `SKILL.md` content**

```markdown
---
name: easyedits
description: >
  Auto-edit raw video clips for talking head / vlog content. Use when the user
  wants to cut silences, remove filler words, clean up bad takes, sequence
  multiple clips into one timeline, and generate captions — all before touching
  their NLE. Outputs an XML timeline and SRT caption file compatible with
  DaVinci Resolve, Premiere Pro, and Final Cut Pro. Invoke with /easyedits.
context: fork
disable-model-invocation: true
---

# EasyEdits

You are an AI video editing assistant. Your job is to help the user go from a
folder of raw clips to a clean, ready-to-import timeline with zero manual cutting.
The output XML works with DaVinci Resolve, Premiere Pro, and Final Cut Pro.

Work through the steps below in order. Never skip ahead. Nothing gets written
to disk until the user gives final approval.

---

## Step 0 — Understand the video type

Ask:

> "What type of video is this? (e.g. talking head, food review, travel vlog, tutorial)"

If the answer is **talking head** → skip the next question and set `BROLL_FOLDER=""`.

Otherwise ask:

> "Will you need b-roll overlays? If yes, what's the full path to your b-roll folder?
> (e.g. C:\Videos\Broll) — or say 'no' to skip."

Store answers as `VIDEO_TYPE` and `BROLL_FOLDER` for use in later steps.

---

## Step 1 — Get the folder path

Ask the user:

> "What's the folder path containing your raw clips?"

On Windows this looks like: `C:\Users\Chris\Videos\MyVideo`

Validate the path exists before proceeding. If it doesn't, ask again.

---

## Step 2 — Scan, transcribe, and show the full preview

Run the scanner:

```bash
python "$USERPROFILE/.claude/skills/easyedits/scripts/autoedit.py" --scan --folder "<folder_path>"
```

If any clip used file-mtime for ordering (not embedded metadata), note it with:
"Note: no embedded date info — using file-modified time for order."

Immediately run transcription (include `--video-type` and `--broll-folder` from Step 0):

```bash
python "$USERPROFILE/.claude/skills/easyedits/scripts/autoedit.py" \
  --transcribe \
  --folder "<folder_path>" \
  --order "<comma_separated_filenames>" \
  --video-type "<VIDEO_TYPE>" \
  --broll-folder "<BROLL_FOLDER>"
```

Display the clip order AND full transcript as before.

---

## Step 2.5 — Launch the preview server

After transcription completes, launch the preview server in the background:

```bash
python "$USERPROFILE/.claude/skills/easyedits/scripts/preview_server.py" --folder "<folder_path>"
```

Tell the user:

> "Preview is ready. Open **http://localhost:5000** in your browser to see the
> transcript and a live video preview. The browser updates automatically every
> 2 seconds when you make changes here."

---

## Step 3 — Accept plain English adjustments

The user can adjust cuts, clip order, b-roll, and captions by typing in plain English.
After each change, update `preview_state.json` (`last_modified` must always be bumped)
and tell the user the change is reflected in the browser.

**Cut adjustments (existing):**
- `"keep the first um in clip 3"` — update cuts
- `"don't cut any silences in clip 2"` — update cuts
- `"cut the word honestly everywhere"` — update cuts
- `"lower the silence threshold, too many cuts"` — re-run transcribe with adjusted threshold

**B-roll adjustments:**
- `"put broll_cafe.mp4 at 0:32 for 5 seconds"` → add entry: `{"filename":"broll_cafe.mp4","path":"<BROLL_FOLDER>/broll_cafe.mp4","at_sec":32,"duration":5,"muted":true}`
- `"keep the audio on broll_cafe.mp4 at 0:32"` → set `"muted":false` for that entry
- `"mute the broll at 0:32"` → set `"muted":true`
- `"remove the broll at 0:32"` → delete the entry

**Caption adjustments:**
- `"make captions 2 words per line"` → update `captions.words_per_line` in `preview_state.json`
  and re-run xml_builder with `--words-per-caption 2` to regenerate `captions.entries`
- `"go back to 7 words per caption"` → reset to 7

After every adjustment, update `preview_state.json` with the new state and set
`"last_modified": <current unix timestamp>`.

---

## Step 4 — Final confirmation

Before executing, show a summary:

```
READY TO EXECUTE
──────────────────────────────────────
  Clips:      3
  Cuts:       34
  Time saved: 2m 14s
  B-roll:     2 overlays
  Captions:   2 words per line
  Output:     C:\Users\Chris\Videos\MyVideo\easyedits_output\

  Files to be created:
    edit.xml        → import into DaVinci Resolve, Premiere Pro, or Final Cut Pro
    captions.srt    → import as subtitles in your NLE

  Your original clips will NOT be touched.
──────────────────────────────────────

Type "go" to execute, or keep adjusting.
```

---

## Step 5 — Execute

When the user says go, run execute then xml_builder (pass `--words-per-caption` from
the current `captions.words_per_line` in `preview_state.json`):

```bash
python "$USERPROFILE/.claude/skills/easyedits/scripts/autoedit.py" \
  --execute \
  --folder "<folder_path>" \
  --order "<comma_separated_filenames>" \
  --cuts "<cuts_json>"

python "$USERPROFILE/.claude/skills/easyedits/scripts/xml_builder.py" \
  --plan "<folder_path>/easyedits_output/cut_plan.json" \
  --words-per-caption <words_per_line_from_state>
```

Then stop the preview server by reading its PID and killing the process:

```bash
# Read PID
$pid = Get-Content "<folder_path>\easyedits_output\preview_server.pid"
Stop-Process -Id $pid -Force
```

Tell the user:

> "Done. Your files are in [folder_path]\easyedits_output\
>
> **DaVinci Resolve:** File → Import Timeline → Import AAF, EDL, XML → select edit.xml,
> then File → Import Subtitles → select captions.srt
>
> **Premiere Pro:** File → Import → select edit.xml, then File → Import → select captions.srt
>
> **Final Cut Pro:** File → Import → XML → select edit.xml,
> then File → Import → Captions → select captions.srt"

---

## Error handling

- **FFmpeg not found:** Tell the user to run `winget install ffmpeg` in a terminal and restart Claude Code.
- **faster-whisper not installed:** Tell the user to run `pip install faster-whisper` and retry.
- **Flask not installed:** Tell the user to run `pip install flask` and retry.
- **No video files found in folder:** Ask the user to double-check the path.
- **Port 5000 in use:** The server auto-tries 5001, 5002 — tell the user which port opened.
- **B-roll file not found:** Warn the user, skip that b-roll entry, continue.
- **File timestamps unreliable (file-mtime fallback):** Warn the user at Step 2.
- **Single clip:** Works fine — skip the ordering step.
```

- [ ] **Step 2: Commit**

```bash
git add SKILL.md
git commit -m "feat: update SKILL.md for web preview flow"
```

---

## Task 7 — Docs: `CLAUDE.md`, `README.md`, `CHANGELOG.md`

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update `CLAUDE.md`**

Add `flask` to the environment block:
```markdown
- Flask: installed via pip (pip install flask)
```

Add to the new scripts block:
```markdown
- `scripts/preview_server.py` — Flask server: serves preview.html + video streams
- `scripts/preview.html` — browser frontend: transcript, video player, timeline UI
```

Add to the flow section:
```markdown
2.5. Launch preview_server.py in background → user opens localhost:5000
     Browser polls /state every 2s, updates automatically on each change
```

Add to Key flags:
```markdown
autoedit.py:
  --video-type    Type of video (e.g. "food review")
  --broll-folder  Path to folder containing b-roll clips

xml_builder.py:
  --words-per-caption  Words per SRT caption line (default 7)
```

Add to error states:
```markdown
- "Flask not installed" → user runs `pip install flask`
- "Port already in use" → server auto-tries next port, reports which one opened
```

- [ ] **Step 2: Update `README.md`**

Add `Flask` to the requirements table:
```markdown
| Flask | `pip install flask` — required for browser preview |
```

Add a new **Browser Preview** section before "Skip vision":
```markdown
## Browser preview

After transcription, EasyEdits opens a local preview at `localhost:5000`:

- **Left panel** — transcript with cuts highlighted (silences greyed, fillers struck through)
- **Right panel** — video player that skips cuts in real time, with b-roll overlay and captions
- **Timeline** — V2/V1/A1 tracks, playhead, click to seek

All adjustments are still made by typing to Claude. The browser updates automatically.

### B-roll overlays

Tell Claude where to place b-roll clips:
\`\`\`
put broll_cafe.mp4 at 0:32 for 5 seconds
keep the audio on broll_cafe.mp4 at 0:32
remove the broll at 0:32
\`\`\`

B-roll audio is muted by default (your voiceover plays underneath).

### Caption customisation

\`\`\`
make captions 2 words per line
go back to 7 words per caption
\`\`\`
```

- [ ] **Step 3: Update `CHANGELOG.md`**

Add before the existing `## [1.1.0]` entry:

```markdown
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
```

- [ ] **Step 4: Commit all docs**

```bash
git add CLAUDE.md README.md CHANGELOG.md
git commit -m "docs: update for v1.2.0 web preview feature"
```

---

## Task 8 — Run full test suite and final smoke-test

- [ ] **Step 1: Run all tests**

```bash
cd "C:\Users\chris\.claude\skills\easyedits"
python -m pytest tests/ -v
```

Expected output:
```
tests/test_autoedit_state.py::test_preview_state_written     PASSED
tests/test_autoedit_state.py::test_caption_entries_generated PASSED
tests/test_autoedit_state.py::test_caption_entries_skip_cuts PASSED
tests/test_preview_server.py::test_state_returns_json        PASSED
tests/test_preview_server.py::test_state_missing_returns_404 PASSED
tests/test_preview_server.py::test_video_missing_returns_404 PASSED
tests/test_preview_server.py::test_video_path_traversal_blocked PASSED
tests/test_preview_server.py::test_index_serves_html         PASSED
tests/test_xml_builder_v2.py::test_words_per_line_default    PASSED
tests/test_xml_builder_v2.py::test_words_per_line_2          PASSED
tests/test_xml_builder_v2.py::test_update_preview_captions   PASSED
tests/test_xml_builder_v2.py::test_broll_v2_track_in_xml     PASSED
tests/test_xml_builder_v2.py::test_no_broll_single_track     PASSED
```

- [ ] **Step 2: End-to-end smoke test with real footage**

Run `/easyedits` in Claude Code against a real folder with at least 2 clips.
Verify:
1. Step 0 asks video type and b-roll question
2. Transcription runs and writes `preview_state.json`
3. Server launches and browser opens at `localhost:5000`
4. Transcript renders with cuts marked in left panel
5. Video plays, skips cuts, shows captions
6. Add a b-roll clip via Claude — browser shows it in V2 track within 2 seconds
7. Change caption words to 2 — browser captions update
8. Say "go" — `edit.xml` and `captions.srt` created, server stops

- [ ] **Step 3: Final commit**

```bash
git add .
git commit -m "feat: complete v1.2.0 web preview — all tests passing"
```
