#!/usr/bin/env python3
"""
xml_builder.py — EasyEdits XML and SRT generator
github.com/kweesbuilds/easyedits

Reads the cut_plan.json produced by autoedit.py --execute and writes:
  - edit.xml      Final Cut Pro XML (DaVinci Resolve compatible)
  - captions.srt  Subtitle file synced to the edited timeline

Usage:
  python xml_builder.py --plan "C:\\Videos\\MyVideo\\easyedits_output\\cut_plan.json"
"""

import argparse
import json
import os
import subprocess
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom


# ── Helpers ──────────────────────────────────────────────────────────────────

def sec_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format HH:MM:SS,mmm"""
    ms  = int((seconds % 1) * 1000)
    s   = int(seconds) % 60
    m   = int(seconds) // 60 % 60
    h   = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def get_video_dimensions(video_path: Path) -> tuple[int, int, str]:
    """Return (width, height, frame_rate) from ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", str(video_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w   = stream.get("width", 1920)
                h   = stream.get("height", 1080)
                fps = stream.get("r_frame_rate", "30/1")
                return w, h, fps
    except Exception:
        pass
    return 1920, 1080, "30/1"


def fps_to_timebase(fps_str: str) -> tuple[int, int]:
    """Convert '30/1' or '60000/1001' to (numerator, denominator)."""
    try:
        parts = fps_str.split("/")
        return int(parts[0]), int(parts[1])
    except Exception:
        return 30, 1


def sec_to_frames(seconds: float, fps_num: int, fps_den: int) -> int:
    """Convert seconds to frame count."""
    return int(round(seconds * fps_num / fps_den))


def prettify_xml(elem: Element) -> str:
    """Return a pretty-printed XML string."""
    rough = tostring(elem, encoding="unicode")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ")


# ── XML builder ──────────────────────────────────────────────────────────────

def build_fcpxml(plan: dict, output_dir: Path, broll: list = None) -> Path:
    """
    Build a Final Cut Pro 7 XML file compatible with DaVinci Resolve.

    Structure:
      xmeml > project > children > sequence > media > video > track > clipitem(s)
                                                      audio > track > clipitem(s)
    """
    folder = Path(plan["folder"])
    clips  = plan["clips"]

    # Use first clip to get project settings
    first_clip_path = folder / plan["order"][0]
    width, height, fps_str = get_video_dimensions(first_clip_path)
    fps_num, fps_den = fps_to_timebase(fps_str)
    fps_float = fps_num / fps_den

    # Build keep-segments for every clip
    # Each keep_segment = {clip, in_sec, out_sec, timeline_in_sec, timeline_out_sec}
    keep_segments = []
    timeline_cursor = 0.0

    for clip_data in clips:
        clip_name   = clip_data["clip"]
        clip_path   = folder / clip_name
        duration    = clip_data["duration_sec"]
        cuts        = clip_data.get("cuts", [])

        # Sort cuts by start time
        cuts = sorted(cuts, key=lambda x: x["start"])

        # Build keep ranges (inverse of cuts)
        keep_ranges = []
        prev_end = 0.0

        for cut in cuts:
            cut_start = cut["start"]
            cut_end   = cut["end"]
            if cut_start > prev_end + 0.01:
                keep_ranges.append((prev_end, cut_start))
            prev_end = cut_end

        if prev_end < duration - 0.01:
            keep_ranges.append((prev_end, duration))

        for (in_sec, out_sec) in keep_ranges:
            seg_duration = out_sec - in_sec
            if seg_duration < 0.05:
                continue
            keep_segments.append({
                "clip_name":       clip_name,
                "clip_path":       str(clip_path),
                "in_sec":          in_sec,
                "out_sec":         out_sec,
                "duration_sec":    seg_duration,
                "timeline_in_sec": timeline_cursor,
                "timeline_out_sec": timeline_cursor + seg_duration,
                "words":           clip_data.get("words", [])
            })
            timeline_cursor += seg_duration

    total_duration_frames = sec_to_frames(timeline_cursor, fps_num, fps_den)

    # ── XML structure ────────────────────────────────────────────────────────

    xmeml = Element("xmeml", version="5")
    project = SubElement(xmeml, "project")
    SubElement(project, "name").text = "EasyEdits_Timeline"
    children = SubElement(project, "children")

    sequence = SubElement(children, "sequence", id="sequence-1")
    SubElement(sequence, "name").text = "EasyEdits_Timeline"
    SubElement(sequence, "duration").text = str(total_duration_frames)

    rate_el = SubElement(sequence, "rate")
    SubElement(rate_el, "timebase").text = str(int(fps_float))
    SubElement(rate_el, "ntsc").text     = "FALSE"

    media = SubElement(sequence, "media")

    # Video track
    video_el = SubElement(media, "video")
    SubElement(video_el, "format")
    video_track = SubElement(video_el, "track")

    # V2 video track — b-roll overlays (only added when broll entries exist)
    broll = broll or []
    video_track_v2 = SubElement(video_el, "track") if broll else None

    # Audio track
    audio_el = SubElement(media, "audio")
    audio_track_1 = SubElement(audio_el, "track")

    clip_id = 1
    for seg in keep_segments:
        in_frames  = sec_to_frames(seg["in_sec"],          fps_num, fps_den)
        out_frames = sec_to_frames(seg["out_sec"],          fps_num, fps_den)
        tl_in      = sec_to_frames(seg["timeline_in_sec"], fps_num, fps_den)
        tl_out     = sec_to_frames(seg["timeline_out_sec"],fps_num, fps_den)
        dur_frames = out_frames - in_frames

        # Video clipitem
        vi = SubElement(video_track, "clipitem", id=f"clipitem-{clip_id}")
        SubElement(vi, "name").text     = seg["clip_name"]
        SubElement(vi, "duration").text = str(dur_frames)
        vi_rate = SubElement(vi, "rate")
        SubElement(vi_rate, "timebase").text = str(int(fps_float))
        SubElement(vi_rate, "ntsc").text     = "FALSE"
        SubElement(vi, "in").text   = str(in_frames)
        SubElement(vi, "out").text  = str(out_frames)
        SubElement(vi, "start").text = str(tl_in)
        SubElement(vi, "end").text   = str(tl_out)

        file_el = SubElement(vi, "file", id=f"file-{clip_id}")
        SubElement(file_el, "name").text    = seg["clip_name"]
        SubElement(file_el, "pathurl").text = Path(seg["clip_path"]).as_uri()
        f_rate = SubElement(file_el, "rate")
        SubElement(f_rate, "timebase").text = str(int(fps_float))
        SubElement(f_rate, "ntsc").text     = "FALSE"
        SubElement(file_el, "duration").text = str(
            sec_to_frames(seg["out_sec"], fps_num, fps_den)
        )
        media_f = SubElement(file_el, "media")
        SubElement(SubElement(media_f, "video"), "duration").text = str(
            sec_to_frames(seg["out_sec"], fps_num, fps_den)
        )

        # Audio clipitem (mirrors video)
        ai = SubElement(audio_track_1, "clipitem", id=f"clipitem-a{clip_id}")
        SubElement(ai, "name").text      = seg["clip_name"]
        SubElement(ai, "duration").text  = str(dur_frames)
        ai_rate = SubElement(ai, "rate")
        SubElement(ai_rate, "timebase").text = str(int(fps_float))
        SubElement(ai_rate, "ntsc").text     = "FALSE"
        SubElement(ai, "in").text    = str(in_frames)
        SubElement(ai, "out").text   = str(out_frames)
        SubElement(ai, "start").text = str(tl_in)
        SubElement(ai, "end").text   = str(tl_out)
        SubElement(ai, "file").set("id", f"file-{clip_id}")

        clip_id += 1

    # ── B-roll V2 clips ──────────────────────────────────────────────────────
    if broll and video_track_v2 is not None:
        for br_idx, br in enumerate(broll, start=1):
            br_path = Path(br["path"])
            br_in_frames  = 0
            br_out_frames = sec_to_frames(br["duration"], fps_num, fps_den)
            br_tl_in      = sec_to_frames(br["at_sec"],             fps_num, fps_den)
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

    # Write XML
    xml_path = output_dir / "edit.xml"
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
        # Write without the xml declaration (already written above)
        raw = tostring(xmeml, encoding="unicode")
        reparsed = minidom.parseString(raw)
        pretty = reparsed.toprettyxml(indent="  ")
        # Strip the auto-added declaration line
        lines = pretty.split("\n")
        f.write("\n".join(lines[1:]))

    return xml_path, keep_segments


# ── SRT builder ──────────────────────────────────────────────────────────────

def build_srt(keep_segments: list[dict], output_dir: Path, words_per_line: int = 7) -> Path:
    """
    Build an SRT caption file from the word timestamps in keep segments.
    Groups words into subtitle lines of ~6-8 words, synced to timeline time.
    """
    entries = []
    entry_idx = 1
    WORDS_PER_LINE = words_per_line

    for seg in keep_segments:
        words      = seg.get("words", [])
        tl_offset  = seg["timeline_in_sec"]
        clip_in    = seg["in_sec"]

        # Filter words that overlap with this keep segment
        seg_words = [
            w for w in words
            if w["end"] > clip_in - 0.05 and w["start"] < seg["out_sec"] + 0.05
        ]

        if not seg_words:
            continue

        # Group into lines
        for i in range(0, len(seg_words), WORDS_PER_LINE):
            chunk = seg_words[i:i + WORDS_PER_LINE]
            if not chunk:
                continue

            # Map timestamps to timeline
            line_start = tl_offset + (chunk[0]["start"] - clip_in)
            line_end   = tl_offset + (chunk[-1]["end"]   - clip_in)

            # Clamp to segment bounds
            line_start = max(line_start, tl_offset)
            line_end   = min(line_end,   seg["timeline_out_sec"])

            if line_end <= line_start:
                continue

            text = " ".join(w["word"] for w in chunk).strip()
            if not text:
                continue

            entries.append((entry_idx, line_start, line_end, text))
            entry_idx += 1

    srt_path = output_dir / "captions.srt"
    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, start, end, text in entries:
            f.write(f"{idx}\n")
            f.write(f"{sec_to_srt_time(start)} --> {sec_to_srt_time(end)}\n")
            f.write(f"{text}\n\n")

    return srt_path


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


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="EasyEdits — xml_builder.py")
    parser.add_argument("--plan",              required=True, help="Path to cut_plan.json")
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

    # Read broll from preview_state.json if available
    broll = []
    if state_path.exists():
        with open(state_path) as f:
            ps = json.load(f)
        broll = ps.get("broll", [])

    print("Building XML timeline...")
    xml_path, keep_segments = build_fcpxml(plan, output_dir, broll=broll)
    print(f"  [ok] edit.xml -> {xml_path}")

    print("Building SRT captions...")
    srt_path = build_srt(keep_segments, output_dir, words_per_line=args.words_per_caption)
    print(f"  [ok] captions.srt -> {srt_path}")

    if state_path.exists():
        update_preview_captions(plan, state_path, args.words_per_caption)
        print(f"  [ok] preview_state.json captions updated")

    print(json.dumps({"status": "ok", "xml": str(xml_path), "srt": str(srt_path)}))


if __name__ == "__main__":
    main()
