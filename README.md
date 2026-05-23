# EasyEdits

**AI-powered auto-editor for talking head and vlog content.**

Drop in your raw clips. EasyEdits transcribes everything, cuts silences and filler words across all clips, sequences them into one timeline, and outputs an XML timeline and SRT caption file ready to import into DaVinci Resolve, Premiere Pro, or Final Cut Pro — before you touch a single edit point.

Built as a Claude Code skill. Runs 100% locally. No API costs, no cloud uploads, no subscriptions beyond Claude Code.

---

## What it does

- Scans a folder of raw clips and detects recording order from file timestamps
- Lets you reorder clips in plain English before anything is processed
- Transcribes every clip locally using Whisper (faster-whisper)
- Shows you the full transcript with every proposed cut marked — silences, filler words, false starts
- Lets you adjust cuts in plain English ("keep the first um in clip 3", "don't cut silences in clip 2")
- Outputs a single `edit.xml` covering all clips sequenced on one timeline — compatible with DaVinci Resolve, Premiere Pro, and Final Cut Pro
- Outputs a `captions.srt` synced to the edited timeline
- Never touches your original files

---

## Requirements

| Requirement | Version | Install |
|-------------|---------|---------|
| Windows | 10 or 11 | — |
| Python | 3.10+ | [python.org](https://python.org) |
| FFmpeg | Any recent | `winget install ffmpeg` |
| faster-whisper | Latest | `pip install faster-whisper` |
| Claude Code | Latest | [code.claude.com](https://code.claude.com) |
| NLE | DaVinci Resolve (free works), Premiere Pro, or Final Cut Pro | — |

---

## Installation

**1. Install dependencies**

```
winget install ffmpeg
pip install faster-whisper
```

**2. Copy skill to Claude Code**

Open PowerShell and run:

```powershell
Copy-Item -Recurse easyedits "$env:USERPROFILE\.claude\skills\easyedits"
```

**3. Verify**

Open a terminal and run:

```
python --version
ffmpeg -version
```

Both should print version numbers. If either says "not recognized", FFmpeg or Python isn't on your PATH — reinstall and tick "Add to PATH" during setup.

**4. Open Claude Code**

```
claude
```

Type `/easyedits` to invoke the skill.

---

## Usage

**1. Prepare your clips**

Put your raw video files in one folder. Any format works: `.mp4`, `.mov`, `.avi`, `.mkv`, `.mts`, `.m4v`.

No need to rename them — EasyEdits reads the recording timestamps embedded in the files and sorts them automatically.

**2. Run the skill**

In Claude Code:

```
/easyedits
```

Claude will ask for your folder path, then walk you through:

- Clip order confirmation (reorder in plain English if needed)
- Full transcript preview with all proposed cuts marked
- Plain English adjustments ("keep the first um in clip 3")
- Final approval before anything is written

**3. Import into your NLE**

Once you approve, EasyEdits writes two files to a subfolder called `easyedits_output` inside your clip folder:

```
YourFolder/
  easyedits_output/
    edit.xml        ← your edited timeline
    captions.srt    ← your captions
```

**DaVinci Resolve (free version):**
1. Create a new project
2. **File → Import Timeline → Import AAF, EDL, XML** → select `edit.xml`
3. **File → Import Subtitles** → select `captions.srt`

**Premiere Pro:**
1. **File → Import** → select `edit.xml`
2. Drag the imported sequence into the timeline
3. **File → Import** → select `captions.srt` to add captions

**Final Cut Pro:**
1. **File → Import → XML** → select `edit.xml`
2. **File → Import → Captions** → select `captions.srt`

Your full edited timeline appears with all clips in sequence and all cuts already made. Polish from there.

---

## Plain English adjustments — examples

During the transcript preview you can type anything like:

```
keep the first um in clip 3
don't cut any silences in clip 2
cut the word honestly everywhere
keep everything in clip 1 as is
that false start in clip 1 — keep it
lower the silence threshold, too many cuts
remove you know everywhere except clip 3
swap clip 1 and clip 2
```

---

## First run note

The first time you run `/easyedits` and it transcribes a clip, faster-whisper downloads the Whisper model weights in the background (~1.5GB for the `medium` model). This only happens once. After that, transcription is instant.

---

## Troubleshooting

**"ffmpeg is not recognized"**
Run `winget install ffmpeg`, then close and reopen your terminal.

**"No module named faster_whisper"**
Run `pip install faster-whisper`.

**"No video files found in folder"**
Check the folder path — on Windows use backslashes: `C:\Users\YourName\Videos\MyClips`

**Wrong clip order detected**
Some cameras don't embed creation timestamps (some GoPro models, older Android devices). EasyEdits warns you when it falls back to file-modified time. Just reorder manually at the prompt.

**"Clip not found" error on XML import (DaVinci / Premiere / FCP)**
Make sure your original clip files are still in the same folder — the XML references them by path. Don't move or rename your source clips after running the skill.

---

## License

MIT — see `LICENSE.md`

---

## Author

[kweesbuilds](https://github.com/kweesbuilds/easyedits)
