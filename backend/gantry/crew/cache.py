"""Produce once, serve many.

A broadcaster produces each feed once and sends it to everyone watching that
feed. Gantry does the same: the first time the crew covers a moment, the cues,
voiced lines and crew talkback are kept, and every later viewer of the match
receives that production. Only questions are answered live for each viewer.
The rundown is saved to disk so it survives a restart.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from ..sim.store import DATA_DIR

CACHE_DIR = Path(os.environ.get("GANTRY_PRODUCTIONS", DATA_DIR.parent / "productions"))


class Production:
    _all: dict[str, "Production"] = {}
    _lock = threading.Lock()

    def __init__(self, match_id: str):
        self.dir = CACHE_DIR / match_id
        self.audio_dir = self.dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "rundown.json"
        self.items: dict[str, dict] = {}
        if self.path.exists():
            try:
                self.items = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.items = {}

    @classmethod
    def of(cls, match_id: str) -> "Production":
        with cls._lock:
            if match_id not in cls._all:
                cls._all[match_id] = Production(match_id)
            return cls._all[match_id]

    def get(self, key: str) -> dict | None:
        return self.items.get(key)

    def put(self, key: str, cues: list[dict], talk: list[dict], audio: dict[str, bytes]):
        for audio_id, data in audio.items():
            f = self.audio_dir / f"{audio_id}.mp3"
            if not f.exists():
                f.write_bytes(data)
        self.items[key] = {"cues": cues, "talk": talk}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def audio(self, audio_id: str) -> bytes | None:
        f = self.audio_dir / f"{audio_id}.mp3"
        return f.read_bytes() if f.exists() else None


def audio_from_disk(audio_id: str) -> bytes | None:
    if not CACHE_DIR.exists():
        return None
    for d in CACHE_DIR.iterdir():
        f = d / "audio" / f"{audio_id}.mp3"
        if f.exists():
            return f.read_bytes()
    return None


def collect_audio(cues: list[dict], voices) -> dict[str, bytes]:
    out = {}
    for c in cues:
        ids = [c.get("audio")]
        reel = c.get("reel") or {}
        for clip in reel.get("clips", []):
            ids += [line.get("audio") for line in clip.get("lines", {}).values()]
        for a in ids:
            if a and a in voices.audio:
                out[a] = voices.audio[a]
    return out
