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
    assert "broll.mp4" not in content
