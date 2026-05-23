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

Immediately run transcription without waiting for user input:

```bash
python "$USERPROFILE/.claude/skills/easyedits/scripts/autoedit.py" --transcribe --folder "<folder_path>" --order "<comma_separated_filenames>"
```

Display the clip order AND full transcript together:

```
CLIP ORDER
──────────────────────────────────────
  1. clip_007.mp4   (1m 48s, 2:41pm)
  2. clip_001.mp4   (2m 05s, 2:58pm)
  3. clip_004.mp4   (3m 12s, 2:34pm)
──────────────────────────────────────

FULL TRANSCRIPT
──────────────────────────────────────────────────────────────────────

── [1] clip_007.mp4 ──

"Hey guys welcome back so [uh] today we're gonna be talking about
[... 2.1s silence ...] something I've been wanting to cover for a
while [um] basically [you know] the whole idea is that you can
actually automate this entire thing."

── [2] clip_001.mp4 ──

"So the first thing you wanna do— [false start] the first thing
is just open up the folder [uh] drop your clips in
[... 3.2s silence ...] and then you just run the command."

── [3] clip_004.mp4 ──

"That's pretty much it honestly [um] if you have any questions
[... 1.1s silence ...] drop them in the comments below."

──────────────────────────────────────────────────────────────────────
Cuts marked:  [ ] = filler word   [... Xs ...] = silence   [false start] = restart

34 cuts total — saves 2m 14s
Original: 8m 40s  →  Output: 6m 26s

Happy with this? You can adjust anything in plain English, or say go.
```

---

## Step 3 — Accept plain English adjustments

The user can adjust cuts or clip order in plain English. Examples:

- "keep the first um in clip 3"
- "don't cut any silences in clip 2"
- "cut the word honestly everywhere"
- "keep everything in clip 1, just cut silences"
- "that false start in clip 1 — keep it"
- "lower the silence threshold, too many cuts"
- "remove you know everywhere except clip 3"
- "swap clip 1 and clip 2" (reordering is still allowed here — re-transcribe if order changes)

After each adjustment, re-render only the affected section of the transcript
preview with the change clearly marked. The rest stays the same. Ask if there
are any more changes or if they're ready to go.

---

## Step 4 — Final confirmation

Before executing, show a summary:

```
READY TO EXECUTE
──────────────────────────────────────
  Clips:     3
  Cuts:      34
  Time saved: 2m 14s
  Output:    C:\Users\Chris\Videos\MyVideo\easyedits_output\

  Files to be created:
    edit.xml        → import into DaVinci Resolve, Premiere Pro, or Final Cut Pro
    captions.srt    → import as subtitles in your NLE

  Your original clips will NOT be touched.
──────────────────────────────────────

Type "go" to execute, or keep adjusting.
```

---

## Step 5 — Execute

When the user says go, run:

```bash
python "$USERPROFILE/.claude/skills/easyedits/scripts/autoedit.py" --execute --folder "<folder_path>" --order "<comma_separated_filenames>" --cuts "<cuts_json>"
python "$USERPROFILE/.claude/skills/easyedits/scripts/xml_builder.py" --folder "<folder_path>" --cuts "<cuts_json>" --order "<comma_separated_filenames>"
```

Output files go into a subfolder called `easyedits_output` inside the user's
clip folder so originals are never mixed with outputs.

Tell the user:

> "Done. Your files are in [folder_path]\easyedits_output\
>
> **DaVinci Resolve:** File → Import Timeline → Import AAF, EDL, XML → select edit.xml, then File → Import Subtitles → select captions.srt
>
> **Premiere Pro:** File → Import → select edit.xml, then File → Import → select captions.srt
>
> **Final Cut Pro:** File → Import → XML → select edit.xml, then File → Import → Captions → select captions.srt"

---

## Error handling

- **FFmpeg not found:** Tell the user to run `winget install ffmpeg` in a terminal and restart Claude Code.
- **faster-whisper not installed:** Tell the user to run `pip install faster-whisper` and retry.
- **No video files found in folder:** Ask the user to double-check the path.
- **File timestamps unreliable (file-mtime fallback):** Warn the user at Step 2 — "Some clips don't have embedded date info so I'm using file-modified time, which may be less accurate. Double-check the order looks right."
- **Single clip:** Works fine — skip the ordering step and go straight to transcription.
