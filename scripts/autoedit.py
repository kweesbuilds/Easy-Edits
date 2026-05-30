#!/usr/bin/env python3
"""
autoedit.py — EasyEdits core processing script
github.com/kweesbuilds/easyedits

Handles:
  --scan        Scan folder for video files, detect order from timestamps
  --transcribe  Run faster-whisper on all clips, return marked transcript
  --execute     Apply approved cut list, prepare segments for XML builder

Usage:
  python autoedit.py --scan --folder "C:\\Videos\\MyVideo"
  python autoedit.py --transcribe --folder "C:\\Videos\\MyVideo" --order "clip1.mp4,clip2.mp4"
  python autoedit.py --execute --folder "C:\\Videos\\MyVideo" --order "clip1.mp4,clip2.mp4" --cuts "cuts.json"
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".mts", ".m4v", ".3gp", ".wmv"}

FILLER_WORDS = [
    "um", "uh", "erm", "er",
    "like", "you know", "you know what i mean",
    "sort of", "kind of", "basically", "literally",
    "right", "okay so", "so yeah", "i mean",
    "honestly", "actually", "obviously",
    "and yeah"
]

SILENCE_THRESHOLD_DB = -35   # audio level below which we call it silence
SILENCE_MIN_DURATION = 0.6   # seconds — shorter silences are kept
PADDING_BEFORE = 0.05        # seconds to keep before a cut resumes
PADDING_AFTER  = 0.05        # seconds to keep after speech ends

# Bad take / duplicate take detection
WORD_NORMALIZATIONS = {
    "gonna": "going", "wanna": "want", "gotta": "got",
    "kinda": "kind",  "sorta": "sort", "outta": "out",
    "tryna": "trying", "hafta": "have", "oughta": "ought",
    "lemme": "let",   "gimme": "give", "dunno": "know",
}
REPEAT_CHECK_WINDOW    = 8    # words compared per phrase window
REPEAT_SIMILARITY      = 0.72 # fraction of words that must match to flag a repeat
REPEAT_MAX_LOOKAHEAD   = 40   # max words ahead to search for a matching phrase
REPEAT_MAX_DURATION_SEC = 15.0 # reject bad takes longer than this (false positives)
DUPE_CLIP_MIN_WORDS  = 20   # words from clip opening used for cross-clip comparison
DUPE_CLIP_SIMILARITY = 0.72 # similarity threshold for duplicate-clip detection


# ── Helpers ──────────────────────────────────────────────────────────────────

def check_dependency(cmd: list[str], name: str) -> bool:
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(f"ERROR: {name} not found. ", end="")
        if name == "FFmpeg":
            if sys.platform == "win32":
                print("Run: winget install ffmpeg")
            elif sys.platform == "darwin":
                print("Run: brew install ffmpeg")
            else:
                print("Run: sudo apt install ffmpeg  (Debian/Ubuntu)  or  sudo dnf install ffmpeg  (Fedora)")
        elif name == "faster-whisper":
            print("Run: pip install faster-whisper")
        return False


def get_video_metadata(path: Path) -> dict:
    """Pull duration and creation time from a video file via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
    except Exception as e:
        return {"error": str(e)}

    meta = {"filename": path.name, "path": str(path)}

    # Duration
    try:
        meta["duration_sec"] = round(float(data["format"]["duration"]), 2)
        d = int(meta["duration_sec"])
        meta["duration_label"] = f"{d // 60}m {d % 60:02d}s"
    except (KeyError, ValueError):
        meta["duration_sec"] = 0
        meta["duration_label"] = "unknown"

    # Creation time
    tags = data.get("format", {}).get("tags", {})
    creation_str = (
        tags.get("creation_time")
        or tags.get("com.apple.quicktime.creationdate")
        or tags.get("date")
    )
    date_source = "embedded"
    created_at = None

    if creation_str:
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d"
        ):
            try:
                created_at = datetime.strptime(creation_str[:26], fmt[:len(creation_str[:26])])
                break
            except ValueError:
                continue

    if created_at is None:
        created_at = datetime.fromtimestamp(os.path.getmtime(path))
        date_source = "file-mtime"

    meta["created_at"] = created_at.isoformat()
    meta["created_label"] = created_at.strftime("%-I:%M%p").lower() if sys.platform != "win32" \
                             else created_at.strftime("%I:%M%p").lstrip("0").lower()
    meta["date_source"] = date_source

    return meta


def extract_audio(video_path: Path, out_wav: Path):
    """Extract mono 16kHz WAV from video — format Whisper expects."""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-ac", "1", "-ar", "16000",
        "-vn", str(out_wav)
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def transcribe_clip(wav_path: Path) -> list[dict]:
    """Run faster-whisper on a WAV file, return word-level segments."""
    from faster_whisper import WhisperModel

    model = WhisperModel("medium", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(wav_path),
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300}
    )

    words = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                words.append({
                    "word": w.word.strip(),
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                })
    return words


def detect_silences(wav_path: Path, duration_sec: float) -> list[dict]:
    """Use FFmpeg silencedetect filter to find gaps in audio."""
    cmd = [
        "ffmpeg", "-i", str(wav_path),
        "-af", f"silencedetect=noise={SILENCE_THRESHOLD_DB}dB:d={SILENCE_MIN_DURATION}",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stderr

    silences = []
    starts = re.findall(r"silence_start: (\d+\.?\d*)", output)
    ends   = re.findall(r"silence_end: (\d+\.?\d*)", output)

    for s, e in zip(starts, ends):
        start = float(s)
        end   = float(e)
        if end - start >= SILENCE_MIN_DURATION:
            silences.append({
                "type": "silence",
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(end - start, 2)
            })

    return silences


def detect_false_starts(words: list[dict]) -> list[dict]:
    """
    Detect false starts — word sequences followed by em dash pause or
    immediate repetition of same phrase.
    """
    false_starts = []
    text = " ".join(w["word"] for w in words).lower()

    # Pattern: word(s) followed by — or ... and then repeat
    dash_pattern = re.finditer(r"(\b\w+(?:\s+\w+){0,4})\s*[—–]\s*\1", text)
    for match in dash_pattern:
        # Find the word time range for this match
        char_start = match.start()
        char_end   = match.end()
        # Approximate to word timestamps
        cumulative = 0
        fs_start = fs_end = None
        for w in words:
            wlen = len(w["word"]) + 1
            if cumulative >= char_start and fs_start is None:
                fs_start = w["start"]
            if cumulative >= char_end:
                fs_end = w["end"]
                break
            cumulative += wlen
        if fs_start and fs_end:
            false_starts.append({
                "type": "false_start",
                "start": fs_start,
                "end": fs_end,
                "text": match.group(0)
            })

    return false_starts


def detect_fillers(words: list[dict], filler_list: list[str]) -> list[dict]:
    """Find filler words/phrases in the word list."""
    cuts = []
    i = 0
    while i < len(words):
        for filler in sorted(filler_list, key=len, reverse=True):
            filler_words = filler.lower().split()
            n = len(filler_words)
            if i + n <= len(words):
                chunk = [w["word"].lower().strip(".,!?") for w in words[i:i+n]]
                if chunk == filler_words:
                    cuts.append({
                        "type": "filler",
                        "word": filler,
                        "start": words[i]["start"],
                        "end": words[i+n-1]["end"]
                    })
                    i += n
                    break
        else:
            i += 1
    return cuts


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


def normalize_word(w: str) -> str:
    """Lowercase, strip punctuation, expand common slang contractions."""
    w = re.sub(r"[.,!?;:\"'—\-]+", "", w.lower().strip())
    return WORD_NORMALIZATIONS.get(w, w)


def phrase_similarity(a: list[str], b: list[str]) -> float:
    """Fraction of the shorter phrase's tokens that appear in the other phrase."""
    if not a or not b:
        return 0.0
    ca, cb = Counter(a), Counter(b)
    matches = sum(min(ca[tok], cb[tok]) for tok in ca)
    return matches / min(len(a), len(b))


def detect_repeated_phrases(words: list[dict]) -> list[dict]:
    """
    Find phrases the speaker said twice — the first occurrence is the bad take.
    The resulting cut spans from words[i].start to words[j].start, removing
    everything (including 'let me try that again' filler) up to the retry.
    """
    n = len(words)
    if n < REPEAT_CHECK_WINDOW * 2:
        return []

    norm = [normalize_word(w["word"]) for w in words]
    bad_takes = []
    i = 0

    while i < n - REPEAT_CHECK_WINDOW:
        phrase_i = norm[i:i + REPEAT_CHECK_WINDOW]
        best_j, best_sim = None, 0.0

        limit = min(n - REPEAT_CHECK_WINDOW + 1, i + REPEAT_MAX_LOOKAHEAD)
        for j in range(i + REPEAT_CHECK_WINDOW, limit):
            sim = phrase_similarity(phrase_i, norm[j:j + REPEAT_CHECK_WINDOW])
            if sim >= REPEAT_SIMILARITY and sim > best_sim:
                best_j, best_sim = j, sim

        if best_j is not None:
            gap_sec = words[best_j]["start"] - words[i]["start"]
            if gap_sec > REPEAT_MAX_DURATION_SEC:
                # Too long to be a genuine stumble-restart — skip
                i += 1
                continue
            preview_words = min(8, REPEAT_CHECK_WINDOW)
            bad_takes.append({
                "type": "bad_take",
                "start": round(words[i]["start"], 3),
                "end": round(words[best_j]["start"], 3),
                "duration": round(gap_sec, 2),
                "text": " ".join(w["word"] for w in words[i:i + preview_words]),
                "similarity": round(best_sim, 2),
            })
            i = best_j  # resume from the kept take
        else:
            i += 1

    return bad_takes


def detect_duplicate_clips(clip_results: list[dict]) -> set:
    """
    Compare each clip's opening words against all later clips.
    Returns names of clips that are earlier duplicate takes (keep the last one).
    """
    duplicates = set()

    for i in range(len(clip_results) - 1):
        if clip_results[i]["clip"] in duplicates:
            continue

        words_i = clip_results[i].get("words", [])[:DUPE_CLIP_MIN_WORDS]
        if len(words_i) < DUPE_CLIP_MIN_WORDS // 2:
            continue

        norm_i = [normalize_word(w["word"]) for w in words_i]

        for j in range(i + 1, len(clip_results)):
            words_j = clip_results[j].get("words", [])[:DUPE_CLIP_MIN_WORDS]
            if len(words_j) < DUPE_CLIP_MIN_WORDS // 2:
                continue

            norm_j = [normalize_word(w["word"]) for w in words_j]
            if phrase_similarity(norm_i, norm_j) >= DUPE_CLIP_SIMILARITY:
                duplicates.add(clip_results[i]["clip"])
                break

    return duplicates


def build_marked_transcript(
    words: list[dict],
    silences: list[dict],
    fillers: list[dict],
    false_starts: list[dict],
    bad_takes: list[dict] = None,
    overrides: dict = None
) -> tuple[str, list[dict]]:
    """
    Combine words, silences, fillers, false starts into a marked transcript
    string and a final cut list.

    overrides = {
        "keep": [{"type": "filler", "word": "um", "clip": 3, "occurrence": 1}],
        "cut":  [{"word": "honestly", "all_clips": True}],
        "skip_silences": [2],       # clip indices
        "skip_fillers": [1],
        "silence_threshold_override": 1.0
    }
    """
    if overrides is None:
        overrides = {}
    if bad_takes is None:
        bad_takes = []

    all_cuts = silences + fillers + false_starts + bad_takes
    all_cuts.sort(key=lambda x: x["start"])

    # Apply overrides
    keep_first_filler = overrides.get("keep_first_filler", {})  # {word: True}
    skip_silences = overrides.get("skip_silences", False)
    skip_fillers = overrides.get("skip_fillers", False)
    extra_cuts = overrides.get("extra_cut_words", [])
    filler_occurrence_count = {}

    filtered_cuts = []
    for cut in all_cuts:
        if skip_silences and cut["type"] == "silence":
            continue
        if skip_fillers and cut["type"] == "filler":
            continue

        if cut["type"] == "filler":
            w = cut.get("word", "")
            filler_occurrence_count[w] = filler_occurrence_count.get(w, 0) + 1
            if keep_first_filler.get(w) and filler_occurrence_count[w] == 1:
                continue

        filtered_cuts.append(cut)

    # Add extra user-requested cuts
    for word in extra_cuts:
        for w in words:
            if w["word"].lower().strip(".,!?") == word.lower():
                filtered_cuts.append({
                    "type": "filler",
                    "word": word,
                    "start": w["start"],
                    "end": w["end"]
                })

    filtered_cuts.sort(key=lambda x: x["start"])

    # Build readable transcript string
    lines = []
    word_idx = 0
    cut_idx  = 0
    current_line = []

    def flush_line():
        if current_line:
            lines.append(" ".join(current_line))
            current_line.clear()

    while word_idx < len(words):
        word = words[word_idx]

        # Discard cuts whose end is already behind the current word
        while cut_idx < len(filtered_cuts) and filtered_cuts[cut_idx]["end"] + 0.05 < word["start"]:
            cut_idx += 1

        # Check if this word falls inside a cut (use word start, not end, to
        # handle words that begin inside a cut but extend fractionally past it)
        in_cut = False
        if cut_idx < len(filtered_cuts):
            cut = filtered_cuts[cut_idx]
            if word["start"] >= cut["start"] and word["start"] < cut["end"]:
                in_cut = True
                if cut["type"] == "silence":
                    current_line.append(f"[... {cut['duration']}s silence ...]")
                elif cut["type"] == "filler":
                    current_line.append(f"[{word['word']}]")
                elif cut["type"] == "false_start":
                    current_line.append(f"[false start]")
                elif cut["type"] == "bad_take":
                    preview = cut.get("text", "")[:40]
                    current_line.append(f'[bad take: "{preview}"]')
                elif cut["type"] == "duplicate_take":
                    current_line.append("[duplicate take — full clip cut]")

                # Advance past all words whose start falls within this cut
                while word_idx < len(words) and words[word_idx]["start"] < cut["end"]:
                    word_idx += 1
                cut_idx += 1
                continue

        if not in_cut:
            current_line.append(word["word"])
            # Wrap lines at ~80 chars
            if len(" ".join(current_line)) > 75:
                flush_line()

        word_idx += 1

    flush_line()
    transcript = "\n".join(lines)

    return transcript, filtered_cuts


# ── CLI modes ────────────────────────────────────────────────────────────────

def mode_scan(folder: Path):
    """Scan folder (recursively) for clips, detect timestamps, print JSON."""
    files = sorted([
        f for f in folder.rglob("*")
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    ])

    if not files:
        print(json.dumps({"error": "No video files found in folder."}))
        sys.exit(1)

    clips = []
    warned_mtime = False
    for f in files:
        meta = get_video_metadata(f)
        if meta.get("date_source") == "file-mtime" and not warned_mtime:
            meta["mtime_warning"] = True
            warned_mtime = True
        clips.append(meta)

    # Sort by creation time
    clips.sort(key=lambda x: x.get("created_at", ""))
    for i, c in enumerate(clips):
        c["order"] = i + 1

    print(json.dumps(clips, indent=2))


def mode_transcribe(folder: Path, order: list[str], overrides: dict = None,
                    video_type: str = "", broll_folder: str = ""):
    """Transcribe clips in given order, return marked transcript JSON."""
    if not check_dependency(["ffmpeg", "-version"], "FFmpeg"):
        sys.exit(1)

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("ERROR: faster-whisper not installed. Run: pip install faster-whisper")
        sys.exit(1)

    results = []
    total_original = 0
    total_cut = 0

    # Build filename → full path lookup so clips in subfolders are found correctly
    clip_lookup = {
        f.name: f
        for f in folder.rglob("*")
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        for clip_name in order:
            clip_path = clip_lookup.get(clip_name, folder / clip_name)
            if not clip_path.exists():
                results.append({"clip": clip_name, "error": "file not found"})
                continue

            meta = get_video_metadata(clip_path)
            total_original += meta.get("duration_sec", 0)

            wav_path = Path(tmpdir) / (clip_path.stem + ".wav")
            extract_audio(clip_path, wav_path)

            words        = transcribe_clip(wav_path)
            silences     = detect_silences(wav_path, meta.get("duration_sec", 0))
            fillers      = detect_fillers(words, FILLER_WORDS)
            false_starts = detect_false_starts(words)
            bad_takes    = detect_repeated_phrases(words)

            transcript_str, cuts = build_marked_transcript(
                words, silences, fillers, false_starts,
                bad_takes=bad_takes,
                overrides=overrides or {}
            )

            cut_time = sum(
                c["end"] - c["start"]
                for c in cuts
            )
            total_cut += cut_time

            results.append({
                "clip": clip_name,
                "path": str(clip_path),
                "duration_sec": meta.get("duration_sec", 0),
                "duration_label": meta.get("duration_label", ""),
                "created_label": meta.get("created_label", ""),
                "transcript": transcript_str,
                "words": words,
                "cuts": cuts,
                "cuts_count": len(cuts),
                "time_saved_sec": round(cut_time, 1)
            })

    # Cross-clip duplicate take detection (runs after all clips are transcribed)
    duplicate_clip_names = detect_duplicate_clips(results)
    for r in results:
        if r["clip"] in duplicate_clip_names:
            dur = r.get("duration_sec", 0)
            dupe_cut = {
                "type": "duplicate_take",
                "start": 0.0,
                "end": dur,
                "duration": round(dur, 2),
                "text": "Duplicate take — full clip cut",
            }
            r["cuts"].insert(0, dupe_cut)
            r["cuts_count"] = len(r["cuts"])
            cut_time = sum(c["end"] - c["start"] for c in r["cuts"])
            r["time_saved_sec"] = round(cut_time, 1)
            total_cut += dur  # count the whole clip as cut time

    output_sec  = total_original - total_cut
    result = {
        "clips": results,
        "total_original_sec": round(total_original, 1),
        "total_output_sec": round(output_sec, 1),
        "total_cuts": sum(r["cuts_count"] for r in results if "cuts_count" in r),
        "total_time_saved_sec": round(total_cut, 1)
    }

    # Cache transcript (including word timestamps) so --execute can build SRT
    output_dir = folder / "easyedits_output"
    output_dir.mkdir(exist_ok=True)
    cache_path = output_dir / "transcript_cache.json"
    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)

    # Write preview_state.json for the browser preview
    state_clips = []
    all_caption_entries = []

    for r in results:
        clip_cuts = r.get("cuts", [])
        words = r.get("words", [])
        clip_entries = generate_caption_entries(
            words, cuts=clip_cuts, words_per_line=3, clip_name=r["clip"]
        )
        all_caption_entries.extend(clip_entries)
        state_clips.append({
            "filename": r["clip"],
            "path": r.get("path", str(folder / r["clip"])),
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
            "words_per_line": 3,
            "entries": all_caption_entries
        }
    }

    state_path = output_dir / "preview_state.json"
    with open(state_path, "w") as f:
        json.dump(preview_state, f, indent=2)

    print(json.dumps(result, indent=2))


def mode_execute(folder: Path, order: list[str], cuts_file: str):
    """
    Write the approved cut data to a JSON file that xml_builder.py reads.
    Does not modify original files.
    """
    output_dir = folder / "easyedits_output"
    output_dir.mkdir(exist_ok=True)

    with open(cuts_file) as f:
        cuts_data = json.load(f)

    # Load cached transcript so word timestamps are available for SRT generation
    words_by_clip = {}
    cache_path = output_dir / "transcript_cache.json"
    if cache_path.exists():
        with open(cache_path) as f:
            cache = json.load(f)
        for clip_result in cache.get("clips", []):
            words_by_clip[clip_result["clip"]] = clip_result.get("words", [])

    # Enrich each clip entry with duration_sec and words so xml_builder has what it needs
    for clip_entry in cuts_data:
        if "duration_sec" not in clip_entry:
            clip_path = folder / clip_entry["clip"]
            meta = get_video_metadata(clip_path)
            clip_entry["duration_sec"] = meta.get("duration_sec", 0)
        if "words" not in clip_entry:
            clip_entry["words"] = words_by_clip.get(clip_entry["clip"], [])

    # Write resolved cut plan for xml_builder
    plan_path = output_dir / "cut_plan.json"
    with open(plan_path, "w") as f:
        json.dump({
            "folder": str(folder),
            "order": order,
            "clips": cuts_data
        }, f, indent=2)

    print(json.dumps({"status": "ok", "plan": str(plan_path)}))


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="EasyEdits — autoedit.py")
    parser.add_argument("--scan",         action="store_true")
    parser.add_argument("--transcribe",   action="store_true")
    parser.add_argument("--execute",      action="store_true")
    parser.add_argument("--folder",       required=True)
    parser.add_argument("--order",        default="")
    parser.add_argument("--cuts",         default="")
    parser.add_argument("--overrides",    default="{}")
    parser.add_argument("--video-type",   default="")
    parser.add_argument("--broll-folder", default="")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(json.dumps({"error": f"Folder not found: {folder}"}))
        sys.exit(1)

    order     = [f.strip() for f in args.order.split(",") if f.strip()]
    overrides = json.loads(args.overrides)

    if args.scan:
        mode_scan(folder)
    elif args.transcribe:
        mode_transcribe(folder, order, overrides,
                        video_type=args.video_type,
                        broll_folder=args.broll_folder)
    elif args.execute:
        mode_execute(folder, order, args.cuts)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
