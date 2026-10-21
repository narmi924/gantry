"""Save and load generated matches."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .engine import FRAME_COLS, FRAME_HEAD, HZ, L, W
from .squads import TEAMS

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "matches"


def team_meta(team) -> dict:
    return {
        "index": team.index, "name": team.name, "short": team.short, "code": team.code,
        "formation": team.formation, "colors": team.colors,
        "players": [asdict(p) | {"name": p.name} for p in team.players],
        "starters": [f"{team.code}-{n}" for n in team.starters],
        "slots": [s.label for s in team.slots],
    }


def save(engine, match_id: str) -> Path:
    out = DATA_DIR / match_id
    out.mkdir(parents=True, exist_ok=True)
    frames = engine.frame_array()
    np.save(out / "frames.npy", frames)
    (out / "events.json").write_text(json.dumps(engine.events), encoding="utf-8")
    meta = {
        "id": match_id,
        "seed": engine.seed,
        "hz": HZ,
        "pitch": {"length": L, "width": W},
        "frame_columns": FRAME_COLS,
        "frame_head": ["period", "clock", "ball_x", "ball_y", "ball_z", "owner", "state"],
        "player_offset": FRAME_HEAD,
        "frames": int(len(frames)),
        "periods": engine.periods,
        "score": engine.score,
        "teams": [team_meta(t) for t in TEAMS],
        "kickoff_attack": [1, -1],
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return out


class StoredMatch:
    def __init__(self, match_id: str):
        root = DATA_DIR / match_id
        self.id = match_id
        self.meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
        self.events = json.loads((root / "events.json").read_text(encoding="utf-8"))
        self.frames = np.load(root / "frames.npy")
        # the fictional season around this match, if one was made (gantry.sim.season)
        season = root / "season.json"
        self.season = json.loads(season.read_text(encoding="utf-8")) if season.exists() else None

    def lineup_at(self, tick: int) -> list[str]:
        lineup = self.meta["teams"][0]["starters"] + self.meta["teams"][1]["starters"]
        for ev in self.events:
            if ev["tick"] > tick:
                break
            if ev["type"] == "substitution":
                lineup[ev["slot_index"]] = ev["on"]
        return lineup

    def score_at(self, tick: int) -> list[int]:
        score = [0, 0]
        for ev in self.events:
            if ev["tick"] > tick:
                break
            if ev["type"] == "goal":
                score = list(ev["score"])
        return score


def available() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted(p.name for p in DATA_DIR.iterdir() if (p / "meta.json").exists())
