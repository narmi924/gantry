"""The stats desk: spots the moments worth talking about and gathers the facts.

Detection is plain code over the event stream and the statistics. The stats
desk agent (see crew.py) only explains moments; every number it uses comes
from here.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

import numpy as np

from ..stats.match_stats import MatchStats

L, W = 105.0, 68.0
HZ = 10
PRESS_WINDOW = 5 * 60 * HZ
SPELL_EVERY = 4 * 60 * HZ
QUIET_AFTER = 9 * HZ


@dataclass
class Moment:
    id: str
    tick: int
    kind: str
    priority: int                 # 1 small .. 5 huge
    team: int | None
    summary: str                  # one factual line, built by code
    facts: dict = field(default_factory=dict)
    players: list[str] = field(default_factory=list)


def minute_label(clock: float, period: int) -> str:
    base = 45 if period == 1 else 90
    m = int(clock // 60) + 1
    return f"{base}+{m - base}'" if m > base else f"{m}'"


class StatsDesk:
    def __init__(self, stats: MatchStats, events: list[dict]):
        self.stats = stats
        self.match = stats.match
        self.events = events                     # match events plus derived ones, sorted by tick
        self.ticks = [e["tick"] for e in events]
        teams = self.match.meta["teams"]
        self.team_names = [t["name"] for t in teams]
        self.short = [t["short"] for t in teams]
        self.players = {p["id"]: p for t in teams for p in t["players"]}
        self.reset(0)

    def reset(self, tick: int):
        self.last_spell = tick
        self.last_moment = tick
        self.last_press = {0: -10**9, 1: -10**9}
        self.fastest = 0.0
        for e in self.events[:bisect.bisect_right(self.ticks, tick)]:
            if e["type"] == "sprint":
                self.fastest = max(self.fastest, e["speed_kmh"])

    # ------------------------------------------------------------ naming

    def player_id(self, name_or_id: str | None) -> str | None:
        if not name_or_id:
            return None
        if name_or_id in self.players:
            return name_or_id
        for pid, p in self.players.items():
            if name_or_id.lower() in p["name"].lower():
                return pid
        return None

    def name(self, pid: str | None) -> str | None:
        return self.players[pid]["name"] if pid in self.players else None

    def where(self, team: int, period: int, x: float, y: float) -> str:
        """Plain words for a spot on the pitch, from the attacking team's point of view."""
        u = self.stats.attack_u(team, period, x)
        forward = (team == 0) == (period == 1)
        # left/right as the attacking team sees it
        side_y = y if forward else W - y
        lateral = "left wing" if side_y > W * 0.7 else "right wing" if side_y < W * 0.3 else "middle"
        if u > L - 16.5 and abs(y - W / 2) < 20.16:
            zone = "inside the box"
        elif u > 70:
            zone = "in the final third"
        elif u > 35:
            zone = "in midfield"
        else:
            zone = "deep in their own half"
        dist = math.hypot(L - u, y - W / 2)
        return f"{zone}, {lateral}, about {round(dist / 5) * 5:.0f} metres from goal"

    def clock(self, tick: int) -> tuple[float, int]:
        tick = min(tick, self.stats.n - 1)
        return float(self.match.frames[tick, 1]), int(self.match.frames[tick, 0])

    def _id(self, kind: str, tick: int) -> str:
        return f"{kind}-{tick}"

    # ------------------------------------------------------------ scanning

    def scan(self, start: int, end: int) -> list[Moment]:
        """Moments in (start, end]."""
        out: list[Moment] = []
        lo = bisect.bisect_right(self.ticks, start)
        hi = bisect.bisect_right(self.ticks, end)
        for e in self.events[lo:hi]:
            m = self._from_event(e)
            if m:
                out.append(m)
        # a read of the game every few minutes of play, always on the same ticks, so every viewer
        # session finds the same moments (and can share one production of them)
        spell_at = end - end % SPELL_EVERY
        if spell_at > self.last_spell and spell_at > start and self.match.frames[min(spell_at, self.stats.n - 1), 6] == 0:
            self.last_spell = spell_at
            out.append(self.spell(spell_at))
        if out:
            self.last_moment = max(m.tick for m in out)
        else:
            quiet_at = end - end % 50
            if quiet_at - self.last_moment >= QUIET_AFTER and quiet_at > start and self.match.frames[min(quiet_at, self.stats.n - 1), 6] == 0:
                m = self.play(quiet_at)
                if m:
                    self.last_moment = quiet_at
                    out.append(m)
        return out

    def _from_event(self, e: dict) -> Moment | None:
        t = e["type"]
        if t == "goal":
            return self.goal(e)
        if t == "shot" and e["outcome"] != "goal":
            return self.shot(e)
        if t in ("tackle", "interception", "recovery"):
            return self.press(e)
        if t == "sprint":
            return self.sprint(e)
        if t == "corner":
            return Moment(self._id("corner", e["tick"]), e["tick"], "corner", 2, e["team"],
                          f"Corner to {self.short[e['team']]}.")
        if t == "yellow_card":
            n = self.name(e.get("player"))
            return Moment(f"card-{e['tick']}-{e.get('player')}", e["tick"], "card", 3, e["team"],
                          f"Yellow card for {n} of {self.short[e['team']]}.", players=[e["player"]])
        if t == "substitution":
            on, off = self.name(e["on"]), self.name(e["off"])
            clock, period = e["clock"], e["period"]
            # two changes can happen at once, so the incoming player is part of the id
            return Moment(f"sub-{e['tick']}-{e['on']}", e["tick"], "substitution", 3, e["team"],
                          f"Substitution for {self.short[e['team']]} at {minute_label(clock, period)}: {on} comes on for {off}.",
                          facts={"on": on, "off": off, "on_profile": self.player_profile(e["on"], e["tick"])},
                          players=[e["on"], e["off"]])
        if t == "kick_off" and e.get("team") is not None:
            if any(x["type"] == "goal" and 0 < e["tick"] - x["tick"] < 900 for x in self.events_before(e["tick"], 900)):
                return None
            half = "First half" if e["period"] == 1 else "Second half"
            score = self.match.score_at(e["tick"])
            return Moment(self._id("kickoff", e["tick"]), e["tick"], "kickoff", 3, None,
                          f"{half} under way. {self.short[0]} {score[0]}-{score[1]} {self.short[1]}.",
                          facts={"score": score, "period": e["period"]})
        if t in ("half_time", "full_time"):
            score = e["score"]
            stats = self.stats.team_stats(e["tick"])
            return Moment(self._id(t, e["tick"]), e["tick"], t, 5, None,
                          f"{'Half-time' if t == 'half_time' else 'Full-time'}: {self.team_names[0]} {score[0]}-{score[1]} {self.team_names[1]}.",
                          facts={"score": score, "teams": self._team_facts(stats)})
        return None

    def events_before(self, tick: int, window: int) -> list[dict]:
        lo = bisect.bisect_left(self.ticks, tick - window)
        hi = bisect.bisect_right(self.ticks, tick)
        return self.events[lo:hi]

    # ------------------------------------------------------------ moments

    def build_up(self, goal_tick: int, team: int) -> dict:
        """How the attack that led to a goal or shot was built, from the events."""
        chain = []
        start = None
        for e in reversed(self.events_before(goal_tick, 40 * HZ)):
            if e["type"] == "possession" and e.get("team") == team:
                start = e
                break
            if e.get("team") != team:
                continue
            if e["type"] == "pass" and e["outcome"] == "complete":
                chain.append(f"{self.name(e['player'])} to {self.name(e['to'])} ({e['length']:.0f} m, difficulty {e['difficulty']})")
            elif e["type"] == "take_on":
                chain.append(f"{self.name(e['player'])} beats {self.name(e.get('beat'))}")
            elif e["type"] == "sprint":
                chain.append(f"{self.name(e['player'])} sprints at {e['speed_kmh']} km/h")
            elif e["type"] == "cross":
                chain.append(f"cross from {self.name(e['player'])}")
            elif e["type"] in ("corner", "free_kick", "throw_in", "goal_kick", "kick_off"):
                start = e
                break
        chain.reverse()
        info = {"sequence": chain[-6:], "passes": sum(1 for c in chain if " to " in c)}
        if start is not None:
            secs = (goal_tick - start["tick"]) / HZ
            info["seconds"] = round(secs, 1)
            if start["type"] == "possession":
                period = start["period"]
                x = self.stats._event_x(start)
                u = self.stats.attack_u(team, period, x)
                info["won_by"] = self.name(start.get("player"))
                info["won_how"] = start.get("cause")
                info["won_where"] = "in the opponent's half" if u > 52.5 else "in their own half"
                info["counter_attack"] = bool(u < 52.5 and secs < 15)
            else:
                info["started_from"] = start["type"].replace("_", " ")
        return info

    def goal(self, e: dict) -> Moment:
        team = e["team"]
        scorer, assist = self.name(e["player"]), self.name(e.get("assist"))
        label = minute_label(e["clock"], e["period"])
        score = e["score"]
        build = self.build_up(e["tick"], team)
        facts = {"scorer": scorer, "assist": assist, "minute": label, "score": f"{self.short[0]} {score[0]}-{score[1]} {self.short[1]}",
                 "shot_speed_kmh": e["speed_kmh"], "xg": e["xg"], "distance_m": round(e["distance"]),
                 "build_up": build, "scorer_profile": self.player_profile(e["player"], e["tick"])}
        how = " on the counter-attack" if build.get("counter_attack") else ""
        summary = (f"GOAL for {self.team_names[team]}{how}. {scorer} scores at {label}"
                   f"{f', assisted by {assist}' if assist else ''}. {facts['score']}.")
        return Moment(self._id("goal", e["tick"]), e["tick"], "goal", 5, team, summary, facts,
                      [p for p in (e["player"], e.get("assist")) if p])

    def shot(self, e: dict) -> Moment:
        team = e["team"]
        shooter = self.name(e["player"])
        big = e["xg"] >= 0.25
        outcome = {"saved": "saved by the goalkeeper", "off_target": "off target", "blocked": "blocked"}[e["outcome"]]
        facts = {"shooter": shooter, "outcome": e["outcome"], "xg": e["xg"], "speed_kmh": e["speed_kmh"],
                 "distance_m": round(e["distance"]), "type": e["shot_type"],
                 "where": self.where(team, e["period"], e["x"], e["y"])}
        if big:
            facts["build_up"] = self.build_up(e["tick"], team)
        summary = f"{'Big chance' if big else 'Shot'} for {self.short[team]}: {shooter}, {outcome}."
        return Moment(self._id("shot", e["tick"]), e["tick"], "big_chance" if big else "shot",
                      4 if big else 3 if e["outcome"] == "saved" else 2, team, summary, facts, [e["player"]])

    def press(self, e: dict) -> Moment | None:
        team = e.get("team")
        if team is None:
            return None
        x = self.stats._event_x(e)
        if self.stats.attack_u(team, e["period"], x) < 52.5:
            return None
        wins = [x for x in self.events_before(e["tick"], PRESS_WINDOW)
                if x["type"] in ("tackle", "interception", "recovery") and x.get("team") == team
                and self.stats.attack_u(team, x["period"], self.stats._event_x(x)) >= 52.5]
        if len(wins) < 3 or e["tick"] - self.last_press[team] < 120 * HZ:
            return None
        self.last_press[team] = e["tick"]
        recent = self._team_facts(self.stats.team_stats(e["tick"], since=max(0, e["tick"] - 10 * 60 * HZ)))
        summary = (f"{self.short[team]} win the ball back in {self.short[1 - team]}'s half again: "
                   f"{len(wins)} times in the last five minutes.")
        return Moment(self._id("press", e["tick"]), e["tick"], "press", 3, team, summary,
                      {"wins_in_opponent_half_last_5_min": len(wins), "won_by": self.name(e.get("player")),
                       "last_10_minutes": recent}, [e["player"]] if e.get("player") else [])

    def sprint(self, e: dict) -> Moment:
        fastest = e["speed_kmh"] > self.fastest
        self.fastest = max(self.fastest, e["speed_kmh"])
        n = self.name(e["player"])
        summary = f"{n} hits {e['speed_kmh']} km/h{' — the fastest sprint of the match so far' if fastest else ''}."
        return Moment(f"sprint-{e['tick']}-{e['player']}", e["tick"], "sprint", 3 if fastest else 2, e["team"], summary,
                      {"player": n, "speed_kmh": e["speed_kmh"], "fastest_so_far": fastest,
                       "profile": self.player_profile(e["player"], e["tick"])}, [e["player"]])

    def spell(self, tick: int) -> Moment:
        since = max(0, tick - 10 * 60 * HZ)
        teams = self._team_facts(self.stats.team_stats(tick, since=since))
        mom = self.stats.momentum(tick, minutes=6)
        avg = float(np.mean([m["value"] for m in mom])) if mom else 0.0
        on_top = 0 if avg > 0.15 else 1 if avg < -0.15 else None
        control = self.stats.control(tick)
        if on_top is None:
            read = "an even spell"
        else:
            read = f"{self.short[on_top]} on top"
        summary = f"State of play over the last ten minutes: {read}."
        return Moment(self._id("spell", tick), tick, "spell", 2, on_top, summary,
                      {"last_10_minutes": teams, "momentum_last_6_min": round(avg, 2), "control": control,
                       "score": self.match.score_at(tick)})

    def play(self, tick: int) -> Moment | None:
        """What is happening right now, for a line when nothing else is going on."""
        tick = min(tick, self.stats.n - 1)
        fr = self.match.frames[tick]
        clock, period = float(fr[1]), int(fr[0])
        owner = int(fr[5])
        back = tick
        while owner < 0 and back > tick - 20:     # the ball may be between two players
            back -= 1
            owner = int(self.match.frames[back, 5])
        if owner < 0:
            return None
        lineup = self.match.lineup_at(tick)
        recent = [e for e in self.events_before(tick, 8 * HZ) if e["type"] in ("pass", "take_on", "tackle", "interception", "cross")]
        seq = []
        for e in recent[-4:]:
            if e["type"] == "pass":
                seq.append(f"{self.name(e['player'])} to {self.name(e.get('to')) or 'nobody'} ({e['outcome']})")
            else:
                seq.append(f"{e['type'].replace('_', ' ')} by {self.name(e.get('player'))}")
        facts = {"recent": seq, "score": self.match.score_at(tick), "minute": minute_label(clock, period)}
        team = None
        if owner >= 0:
            team = 0 if owner < 11 else 1
            pid = lineup[owner]
            facts["on_the_ball"] = self.name(pid)
            facts["team_in_possession"] = self.short[team]
            facts["ball_position"] = self.where(team, period, float(fr[2]), float(fr[3]))
            facts["attacking_towards"] = "the right" if (team == 0) == (period == 1) else "the left"
        summary = (f"{facts.get('team_in_possession', 'Nobody')} in possession"
                   f"{', ' + facts['on_the_ball'] + ' on the ball' if 'on_the_ball' in facts else ''}.")
        return Moment(self._id("play", tick), tick, "play", 1, team, summary, facts,
                      [lineup[owner]] if owner >= 0 else [])

    # ------------------------------------------------------------ helpers

    def _team_facts(self, stats: list[dict]) -> dict:
        keys = ("possession", "shots", "on_target", "xg", "completion", "field_tilt", "ppda", "corners", "distance_km")
        return {self.short[i]: {k: stats[i][k] for k in keys} for i in (0, 1)}

    def player_profile(self, pid: str, tick: int) -> dict:
        for p in self.stats.players(tick):
            if p["player"] == pid:
                info = self.players[pid]
                return {"name": info["name"], "number": info["number"], "position": info["position"],
                        "distance_km": p["distance_km"], "top_speed_kmh": p["top_speed_kmh"], "sprints": p["sprints"],
                        "passes": p["passes"], "pass_completion": p["pass_completion"], "shots": p["shots"],
                        "goals": p["goals"], "assists": p["assists"], "tackles": p["tackles"]}
        return {"name": self.name(pid)}

    # ------------------------------------------------------------ tools for the stats desk agent

    def tools(self, now: callable):
        """Functions the stats desk agent may call. They only see the match up to `now()`."""
        desk = self

        def team_stats(minutes: int = 10) -> dict:
            """Both teams' numbers over the last `minutes` minutes of play (possession, shots, xG, pass accuracy, field tilt, PPDA, corners, distance)."""
            t = now()
            since = max(0, t - int(minutes) * 60 * HZ)
            return desk._team_facts(desk.stats.team_stats(t, since=since))

        def match_totals() -> dict:
            """Both teams' totals for the match so far, plus the score."""
            t = now()
            return {"score": desk.match.score_at(t), "teams": desk._team_facts(desk.stats.team_stats(t))}

        def player_stats(name: str) -> dict:
            """One player's numbers so far: distance, top speed, sprints, passes, shots, goals, assists, tackles."""
            t = now()
            for pid, p in desk.players.items():
                if name.lower() in p["name"].lower():
                    return desk.player_profile(pid, t)
            return {"error": f"no player called {name}"}

        def momentum(minutes: int = 10) -> list:
            """Attack momentum per minute: positive values Kingsmere, negative Ashvale."""
            return desk.stats.momentum(now(), minutes=int(minutes))

        return [team_stats, match_totals, player_stats, momentum]
