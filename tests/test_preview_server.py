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
    (tmp_path / "safe.mp4").write_bytes(b"data")
    client = make_client(tmp_path, state={"broll_folder": ""})
    # Traversal attempt — after sanitization it becomes "passwd" which doesn't exist
    res = client.get("/video/../../../etc/passwd")
    assert res.status_code == 404


def test_index_serves_html(tmp_path):
    """GET / returns the preview.html file."""
    html_path = Path(__file__).parent.parent / "scripts" / "preview.html"
    assert html_path.exists(), "preview.html must exist before running this test"
    client = make_client(tmp_path)
    res = client.get("/")
    assert res.status_code == 200
    assert b"<!DOCTYPE html>" in res.data.lower() or b"<html" in res.data.lower()
