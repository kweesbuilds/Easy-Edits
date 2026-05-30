---
name: easyedits
description: >
  Auto-edit raw video clips for talking head / vlog content. Use when the user
  wants to cut silences, remove filler words, clean up bad takes, sequence
  multiple clips into one timeline, and generate captions — all before touching
  their NLE. Outputs an XML timeline and SRT caption file compatible with
  DaVinci Resolve, Premiere Pro, and Final Cut Pro. Invoke with /easyedits.
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

The transcript will automatically flag:
- **Bad takes** — phrases the user repeated after stumbling (earlier attempt cut, retry kept). Shown as `[bad take: "first few words..."]` in the transcript.
- **Duplicate clips** — clips whose opening content closely matches a later clip (the earlier clip is cut entirely). Shown with a `⚠ duplicate take` banner in the left panel.

---

## Step 2.5 — Launch the preview server

After transcription completes, launch the preview server in the background then open the browser.

**Windows (PowerShell):**
```powershell
Start-Process python -ArgumentList "`"$env:USERPROFILE/.claude/skills/easyedits/scripts/preview_server.py`" --folder `"<folder_path>`"" -WindowStyle Hidden
Start-Sleep -Seconds 2
Start-Process "http://localhost:5000"
```

**macOS / Linux:**
```bash
nohup python3 "$HOME/.claude/skills/easyedits/scripts/preview_server.py" --folder "<folder_path>" > /dev/null 2>&1 &
sleep 2
open "http://localhost:5000"   # macOS — use xdg-open on Linux
```

Tell the user:

> "Preview is opening in your browser now. The page updates automatically every
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

**Bad take adjustments:**
- `"keep the bad take in clip 2 at 0:34"` — remove that bad_take cut from `preview_state.json`
- `"clip 3 isn't a duplicate, keep it"` — remove the duplicate_take cut from clip 3
- `"that bad take in clip 1 starts too early"` — adjust the start time of the bad_take cut

**B-roll adjustments:**
- `"put broll_cafe.mp4 at 0:32 for 5 seconds"` → add entry: `{"filename":"broll_cafe.mp4","path":"<BROLL_FOLDER>/broll_cafe.mp4","at_sec":32,"duration":5,"muted":true}`
- `"keep the audio on broll_cafe.mp4 at 0:32"` → set `"muted":false` for that entry
- `"mute the broll at 0:32"` → set `"muted":true`
- `"remove the broll at 0:32"` → delete the entry

**Caption adjustments:**
- `"make captions 2 words per line"` → update `captions.words_per_line` in `preview_state.json`
  and re-run xml_builder with `--words-per-caption 2` to regenerate `captions.entries`
- `"go back to 3 words per caption"` → reset to 3

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

When the user says go, first write the approved cuts to a JSON file in **clip-centric format**
(one object per clip, each with a `cuts` array), then run execute and xml_builder.

**CRITICAL — cuts file format.** The `--cuts` argument is a file path. The file must look like:
```json
[
  {
    "clip": "clip1.mp4",
    "cuts": [
      {"type": "silence", "start": 0.0, "end": 2.19, "duration": 2.19}
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
A flat list of cut objects (not grouped by clip) will produce one uncut duplicate per cut in the output.

Write the file without BOM (Windows):
```powershell
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText("<folder_path>\easyedits_output\cuts_input.json", $cutsJson, $utf8NoBom)
```

Then run execute and xml_builder (pass `--words-per-caption` from `captions.words_per_line` in `preview_state.json`):

**Windows (PowerShell):**
```powershell
python "$env:USERPROFILE/.claude/skills/easyedits/scripts/autoedit.py" `
  --execute `
  --folder "<folder_path>" `
  --order "<comma_separated_filenames>" `
  --cuts "<folder_path>\easyedits_output\cuts_input.json"

python "$env:USERPROFILE/.claude/skills/easyedits/scripts/xml_builder.py" `
  --plan "<folder_path>\easyedits_output\cut_plan.json" `
  --words-per-caption <words_per_line_from_state>
```

**macOS / Linux:**
```bash
python "$HOME/.claude/skills/easyedits/scripts/autoedit.py" \
  --execute \
  --folder "<folder_path>" \
  --order "<comma_separated_filenames>" \
  --cuts "<folder_path>/easyedits_output/cuts_input.json"

python "$HOME/.claude/skills/easyedits/scripts/xml_builder.py" \
  --plan "<folder_path>/easyedits_output/cut_plan.json" \
  --words-per-caption <words_per_line_from_state>
```

Then stop the preview server by reading its PID and killing the process.

**Windows (PowerShell):**
```powershell
$serverPid = Get-Content "<folder_path>\easyedits_output\preview_server.pid"
Stop-Process -Id $serverPid -Force
```

**macOS / Linux:**
```bash
kill $(cat "<folder_path>/easyedits_output/preview_server.pid")
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
