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

from flask import Flask, abort, jsonify, send_file

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
