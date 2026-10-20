"""Match statistics, computed from the tracking frames and events.

Everything a viewer or the AI crew is told as a number comes from here. The
stats desk can be asked about any moment of the match, but only ever sees what
has happened up to that moment.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

import numpy as np

from ..sim.store import StoredMatch

HZ = 10
L, W = 105.0, 68.0
SPRINT_MS = 25 / 3.6          # a sprint is running faster than 25 km/h ...
SPRINT_MIN_TICKS = 10         # ... for at least a second
TAG_SPRINT_KMH = 33.0         # sprints this fast earn an on-screen speed tag
DEFENSIVE_TYPES = {"tackle", "interception", "foul"}


def threat(u, y):
    d = math.hypot(max(L - u, 0.0), abs(y - W / 2) * 1.25)
    return 0.004 + 0.26 * math.exp(-d / 10.0) + 0.016 * (u / L)


@dataclass
class Sprint:
    player: str
    team: int
    start: int
    peak: int
    end: int
    top_kmh: float


class MatchStats:
    def __init__(self, match: StoredMatch):
        self.match = match
        fr = match.frames
        self.n = len(fr)
        self.period = fr[:, 0].astype(int)
        self.owner = fr[:, 5].astype(int)
        self.state = fr[:, 6].astype(int)
        pos = fr[:, 7:].reshape(self.n, 22, 2).astype(np.float64)
        self.pos = pos

        step = np.zeros((self.n, 22))
        step[1:] = np.linalg.norm(np.diff(pos, axis=0), axis=2)
        jump = step > 3.0          # a new half or a substitute appearing
        step[jump] = 0.0
        self.cum_dist = np.cumsum(step, axis=0)

        # speed over half a second, so the number doesn't flicker
        speed = np.zeros((self.n, 22))
        speed[2:-2] = np.linalg.norm(pos[4:] - pos[:-4], axis=2) / 0.4
        bad = np.zeros_like(jump)
        for k in range(-2, 3):
            bad |= np.roll(jump, k, axis=0)
        speed[bad] = 0.0
        self.speed = speed

        self.events = match.events
        self.ticks = [e["tick"] for e in self.events]
        self.names = {p["id"]: p for t in match.meta["teams"] for p in t["players"]}
        self._lineups()
        self.sprints = self._find_sprints()

    # ---------------------------------------------------------------- setup

    def _lineups(self):
        """Which player stood in each slot, tick by tick."""
        meta = self.match.meta
        start = meta["teams"][0]["starters"] + meta["teams"][1]["starters"]
        self.slot_spans: list[list[tuple[int, int, str]]] = [[(0, self.n, pid)] for pid in start]
        for e in self.events:
            if e["type"] == "substitution":
                k = e["slot_index"]
                a, _, pid = self.slot_spans[k][-1]
                self.slot_spans[k][-1] = (a, e["tick"], pid)
                self.slot_spans[k].append((e["tick"], self.n, e["on"]))

    def _find_sprints(self) -> list[Sprint]:
        out = []
        fast = self.speed > SPRINT_MS
        for k in range(22):
            for a, b, pid in self.slot_spans[k]:
                f = fast[a:b, k]
                if not f.any():
                    continue
                edges = np.diff(np.concatenate([[0], f.astype(np.int8), [0]]))
                starts = np.flatnonzero(edges == 1)
                ends = np.flatnonzero(edges == -1)
                for s, e in zip(starts, ends):
                    if e - s < SPRINT_MIN_TICKS:
                        continue
                    seg = self.speed[a + s:a + e, k]
                    peak = int(np.argmax(seg))
                    out.append(Sprint(pid, 0 if k < 11 else 1, int(a + s), int(a + s + peak), int(a + e),
                                      round(float(seg[peak]) * 3.6, 1)))
        out.sort(key=lambda s: s.peak)
        return out

    def sprint_events(self) -> list[dict]:
        """Sprints worth a speed tag on screen, as events the feed can carry."""
        events = []
        for s in self.sprints:
            if s.top_kmh >= TAG_SPRINT_KMH:
                events.append({"tick": s.peak, "type": "sprint", "team": s.team, "player": s.player,
                               "speed_kmh": s.top_kmh, "start_tick": s.start, "end_tick": s.end,
                               "period": int(self.period[s.peak]), "clock": round(float(self.match.frames[s.peak, 1]), 1)})
        return events

    # -------------------------------------------------------------- helpers

    def _past(self, tick: int):
        return self.events[:bisect.bisect_right(self.ticks, tick)]

    def attack_u(self, team: int, period: int, x: float) -> float:
        """Distance from a team's own goal line, given which way it attacks in this half."""
        forward = (team == 0) == (period == 1)
        return x if forward else L - x

    def player_slot(self, pid: str, tick: int):
        for k in range(22):
            for a, b, p in self.slot_spans[k]:
                if p == pid and a <= tick < b:
                    return k
        return None

    def player_distance(self, pid: str, tick: int) -> float:
        total = 0.0
        for k in range(22):
            for a, b, p in self.slot_spans[k]:
                if p == pid and a <= tick:
                    end = min(b - 1, tick)
                    total += self.cum_dist[end, k] - (self.cum_dist[a - 1, k] if a > 0 else 0.0)
        return total

    # --------------------------------------------------------------- views

    def team_stats(self, tick: int, since: int = 0) -> list[dict]:
        tick = int(np.clip(tick, 0, self.n - 1))
        evs = [e for e in self._past(tick) if e["tick"] >= since]
        owned = (self.owner[since:tick + 1] >= 0) & (self.state[since:tick + 1] == 0)
        home_ticks = int(((self.owner[since:tick + 1] < 11) & owned).sum())
        total = max(int(owned.sum()), 1)
        out = []
        for team in (0, 1):
            passes = [e for e in evs if e["type"] == "pass" and e["team"] == team]
            done = [e for e in passes if e["outcome"] == "complete"]
            shots = [e for e in evs if e["type"] == "shot" and e["team"] == team]
            # field tilt: share of the two teams' final-third passes
            final_third = sum(1 for e in passes if self.attack_u(team, e["period"], e["x"]) > 70)
            # PPDA: opponent passes in their own 60% per defensive action of ours there
            opp_passes = sum(1 for e in evs if e["type"] == "pass" and e["team"] == 1 - team
                             and self.attack_u(1 - team, e["period"], e["x"]) < 63)
            def_actions = sum(1 for e in evs if e["type"] in DEFENSIVE_TYPES and e.get("team") == team
                              and self.attack_u(team, e["period"], self._event_x(e)) > 42)
            slots = range(0, 11) if team == 0 else range(11, 22)
            dist = float(self.cum_dist[tick, list(slots)].sum() - (self.cum_dist[since, list(slots)].sum() if since else 0))
            sprints = sum(1 for s in self.sprints if s.team == team and since <= s.start <= tick)
            out.append({
                "possession": round((home_ticks if team == 0 else total - home_ticks) / total, 3),
                "passes": len(passes),
                "completion": round(len(done) / len(passes), 3) if passes else None,
                "difficulty": round(float(np.mean([e["difficulty"] for e in passes])), 1) if passes else None,
                "shots": len(shots),
                "on_target": sum(1 for s in shots if s["outcome"] in ("goal", "saved")),
                "xg": round(sum(s["xg"] for s in shots), 2),
                "final_third_passes": final_third,
                "ppda": round(opp_passes / def_actions, 1) if def_actions else None,
                "distance_km": round(dist / 1000, 1),
                "sprints": sprints,
                "corners": sum(1 for e in evs if e["type"] == "corner" and e["team"] == team),
                "fouls": sum(1 for e in evs if e["type"] == "foul" and e["team"] == team),
            })
        ft = out[0]["final_third_passes"] + out[1]["final_third_passes"]
        for t in out:
            t["field_tilt"] = round(t["final_third_passes"] / ft, 3) if ft else None
        return out

    def _event_x(self, e: dict) -> float:
        if "x" in e:
            return e["x"]
        tick = min(e["tick"], self.n - 1)
        return float(self.match.frames[tick, 2])

    def momentum(self, tick: int, minutes: int = 20) -> list[dict]:
        """Attack momentum per minute: positive for Kingsmere, negative for Ashvale."""
        tick = int(np.clip(tick, 0, self.n - 1))
        clock_now = float(self.match.frames[tick, 1])
        first = max(0, int(clock_now // 60) - minutes + 1)
        buckets: dict[int, list[float]] = {}
        for e in self._past(tick):
            m = int(e["clock"] // 60)
            if m < first:
                continue
            v = 0.0
            if e["type"] == "pass" and e["outcome"] == "complete":
                u = self.attack_u(e["team"], e["period"], e["end_x"])
                if u > 60:
                    v = threat(u, e["end_y"]) * 1.5
            elif e["type"] == "shot":
                v = 0.15 + e["xg"]
            elif e["type"] == "corner":
                v = 0.06
            if v:
                b = buckets.setdefault(m, [0.0, 0.0])
                b[e["team"]] += v
        series = []
        for m in range(first, int(clock_now // 60) + 1):
            h, a = buckets.get(m, [0.0, 0.0])
            series.append({"minute": m + 1, "value": round(math.tanh(3.0 * (h - a)), 3)})
        return series

    def control(self, tick: int, window_min: float = 5) -> dict:
        """Control or chaos: how often the ball changes hands, and how cleanly it is passed."""
        tick = int(np.clip(tick, 0, self.n - 1))
        since = max(0, tick - int(window_min * 60 * HZ))
        evs = [e for e in self._past(tick) if e["tick"] >= since]
        in_play_min = max(float((self.state[since:tick + 1] == 0).sum()) / HZ / 60, 0.5)
        turnovers = sum(1 for e in evs if e["type"] == "possession")
        passes = [e for e in evs if e["type"] == "pass"]
        completion = sum(1 for e in passes if e["outcome"] == "complete") / len(passes) if passes else 1.0
        per_min = turnovers / in_play_min
        chaos = float(np.clip((per_min - 1.5) / 3.5 * 0.7 + (0.9 - completion) * 1.5, 0, 1))
        return {"turnovers_per_min": round(per_min, 2), "completion": round(completion, 3),
                "chaos": round(chaos, 2), "tempo_passes_per_min": round(len(passes) / in_play_min, 1)}

    def players(self, tick: int) -> list[dict]:
        """Every player who has been on the pitch, with their numbers so far."""
        tick = int(np.clip(tick, 0, self.n - 1))
        evs = self._past(tick)
        out = []
        seen = set()
        for k in range(22):
            for a, b, pid in self.slot_spans[k]:
                if a > tick or pid in seen:
                    continue
                seen.add(pid)
                mine = [e for e in evs if e.get("player") == pid]
                passes = [e for e in mine if e["type"] == "pass"]
                on = a <= tick < b
                end = min(b - 1, tick)
                top = float(self.speed[a:end + 1, k].max()) * 3.6 if end >= a else 0.0
                out.append({
                    "player": pid, "team": 0 if k < 11 else 1, "on_pitch": on,
                    "speed_kmh": round(float(self.speed[tick, k]) * 3.6, 1) if on else 0.0,
                    "top_speed_kmh": round(top, 1),
                    "distance_km": round(float(self.player_distance(pid, tick)) / 1000, 2),
                    "sprints": sum(1 for s in self.sprints if s.player == pid and s.start <= tick),
                    "passes": len(passes),
                    "pass_completion": round(sum(1 for e in passes if e["outcome"] == "complete") / len(passes), 2) if passes else None,
                    "shots": sum(1 for e in mine if e["type"] == "shot"),
                    "goals": sum(1 for e in mine if e["type"] == "goal"),
                    "assists": sum(1 for e in evs if e["type"] == "goal" and e.get("assist") == pid),
                    "tackles": sum(1 for e in mine if e["type"] == "tackle"),
                })
        return out

    def snapshot(self, tick: int) -> dict:
        """The compact view the broadcast graphics need, about once a second."""
        return {
            "tick": int(tick),
            "teams": self.team_stats(tick),
            "momentum": self.momentum(tick),
            "control": self.control(tick),
        }

    # -------------------------------------------------------------- space

    def pitch_control(self, tick: int, step: float = 2.5) -> np.ndarray:
        """Which team would reach each patch of grass first. Grid of (rows, cols) in [-1, 1]:
        +1 Kingsmere, -1 Ashvale."""
        tick = int(np.clip(tick, 0, self.n - 1))
        xs = np.arange(step / 2, L, step)
        ys = np.arange(step / 2, W, step)
        gx, gy = np.meshgrid(xs, ys)
        p = self.pos[tick]
        v = (self.pos[min(tick + 2, self.n - 1)] - self.pos[max(tick - 2, 0)]) / 0.4
        # where each player will be in half a second, then time to the patch at 7 m/s
        ahead = p + v * 0.5
        d = np.hypot(gx[..., None] - ahead[:, 0], gy[..., None] - ahead[:, 1])
        t = d / 7.0 + 0.5
        home = t[..., :11].min(axis=-1)
        away = t[..., 11:].min(axis=-1)
        return np.tanh((away - home) * 1.6)
