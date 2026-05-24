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
