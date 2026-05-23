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
- Whisper model: `medium` (CPU, int8)
- DaVinci Resolve: Free version — XML import approach only (no Python API)

## What this skill does

Automates the first-pass edit of talking head / vlog video content:
1. Scans a folder of raw clips
2. Detects clip order from embedded timestamps
3. Transcribes all clips locally with Whisper
4. Identifies silences, filler words, false starts
5. Shows the user a full transcript preview with proposed cuts marked
6. Accepts plain English adjustments from the user
7. On final approval, outputs edit.xml + captions.srt to an easyedits_output/ subfolder

## What this skill does NOT do

- Beat-sync / music-driven cutting
- Live DaVinci API control (requires Resolve Studio, which is paid)
- Visual scene analysis (no camera/frame processing)
- Reordering clips after the transcript has been approved (must go back to step 2)

## Script locations

- `scripts/autoedit.py` — scanning, transcription, cut detection
- `scripts/xml_builder.py` — XML and SRT generation

## Output format

- `edit.xml` — FCP7 XML, compatible with DaVinci Resolve free via File → Import Timeline → Import AAF, EDL, XML
- `captions.srt` — standard SRT, import via File → Import Subtitles in DaVinci

## Default settings (change in autoedit.py if needed)

- Silence threshold: -35dB
- Minimum silence duration: 0.6 seconds
- Padding around cuts: 0.05 seconds each side
- Whisper model: medium
- Words per caption line: 7

## Filler words detected by default

um, uh, erm, er, like, you know, you know what i mean, sort of, kind of,
basically, literally, right, okay so, so yeah, i mean, honestly, actually, obviously, and yeah

## Error messages to know

- "ffmpeg is not recognized" → user needs to run `winget install ffmpeg` and reopen terminal
- "No module named faster_whisper" → user needs to run `pip install faster-whisper`
- "No video files found" → check the folder path, must use full Windows path
- "clip not found" in DaVinci → source files have been moved or renamed since running the skill
