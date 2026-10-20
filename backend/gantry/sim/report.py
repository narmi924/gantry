"""Quick match summary, used while tuning the engine."""

from __future__ import annotations

from collections import Counter

import numpy as np

from .engine import DT, FRAME_HEAD, PLAY


def summarize(engine) -> dict:
    ev = engine.events
    frames = engine.frame_array()
    out = {"score": list(engine.score), "minutes": round(len(frames) * DT / 60, 1)}
    kinds = Counter(e["type"] for e in ev)
    for team in (0, 1):
        passes = [e for e in ev if e["type"] == "pass" and e["team"] == team]
        done = [e for e in passes if e["outcome"] == "complete"]
        shots = [e for e in ev if e["type"] == "shot" and e["team"] == team]
        owner = frames[:, 5]
        owned = owner >= 0
        team_owned = owned & ((owner >= 11) == bool(team))
        pos = frames[:, FRAME_HEAD:].reshape(len(frames), 22, 2)
        step = np.linalg.norm(np.diff(pos, axis=0), axis=2)
        step[step > 3] = 0
        dist = step.sum(axis=0)[team * 11:(team + 1) * 11] / 1000
        speed = step / DT
        out[f"team{team}"] = {
            "passes": len(passes),
            "completion": round(len(done) / max(len(passes), 1), 3),
            "avg_difficulty": round(float(np.mean([e["difficulty"] for e in passes])) if passes else 0, 1),
            "shots": len(shots),
            "on_target": sum(1 for s in shots if s["outcome"] in ("goal", "saved")),
            "xg": round(sum(s["xg"] for s in shots), 2),
            "possession": round(team_owned.sum() / max(owned.sum(), 1), 3),
            "km_outfield_avg": round(float(dist[1:].mean()), 2),
            "top_speed_kmh": round(float(np.percentile(speed[:, team * 11:(team + 1) * 11], 99.9) * 3.6), 1),
        }
    out["in_play"] = round(float((frames[:, 6] == PLAY).mean()), 3)
    out["events"] = dict(kinds.most_common())
    out["goals"] = [(e["clock"] // 60, e["team"], e["player"], e.get("assist")) for e in ev if e["type"] == "goal"]
    return out
