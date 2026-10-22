"""The stats desk: spots the moments worth talking about and gathers the facts.

Detection is plain code over the event stream and the tracking data. Every
moment of the match is found once, in match order, so every viewer session and
the production meet exactly the same moments with the same ids. The stats desk
agent (roles.py) only explains moments; every number and name the crew may say
comes from here.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

import numpy as np

from ..common import HZ, L, W, minute_label
from ..stats.match_stats import MatchStats
from .storylines import Storylines

PRESS_WINDOW = 5 * 60 * HZ
PRESS_SPACING = 120 * HZ
SPELL_EVERY = 4 * 60 * HZ
FILLER_EVERY = 50              # a filler candidate every five seconds of quiet play...
QUIET_AFTER = 6 * HZ           # ... once nothing else has happened for six seconds
BIG_CHANCE_XG = 0.25
ACTIONS = ("pass", "take_on", "shot", "cross", "tackle", "interception", "recovery", "clearance")

POSITIONS = {"GK": "goalkeeper", "RB": "right-back", "LB": "left-back", "CB": "centre-back",
             "DM": "defensive midfielder", "CM": "central midfielder", "AM": "attacking midfielder",
             "RW": "right winger", "LW": "left winger", "ST": "striker"}
KITS = {0: "royal blue shirts and shorts, white socks", 1: "amber shirts, navy shorts"}


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


_MOMENTS: dict[int, list[Moment]] = {}


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
        self.storylines = Storylines(self)
        key = id(stats)
        if key not in _MOMENTS:
            _MOMENTS[key] = self._find_moments()
        self.all = _MOMENTS[key]
        self.all_ticks = [m.tick for m in self.all]

    def reset(self, tick: int):
        """Kept for callers that seek; moments are found once per match, so there is nothing to reset."""

    # ------------------------------------------------------------ naming and places

    def player_id(self, name_or_id: str | None) -> str | None:
        if not name_or_id:
            return None
        if name_or_id in self.players:
            return name_or_id
        low = name_or_id.lower()
        for pid, p in self.players.items():
            if low == p["name"].lower() or low == p["last"].lower():
                return pid
        for pid, p in self.players.items():
            if low in p["name"].lower():
                return pid
        return None

    def name(self, pid: str | None) -> str | None:
        return self.players[pid]["name"] if pid in self.players else None

    def who(self, pid: str | None) -> dict | None:
        """A player as the crew should refer to him: name, team, number and position."""
        p = self.players.get(pid)
        if not p:
            return None
        return {"name": p["name"], "team": self.short[p["team"]], "number": p["number"],
                "position": POSITIONS.get(p["position"], p["position"])}

    def place(self, team: int, period: int, x: float, y: float) -> dict:
        """A spot on the pitch in plain words, from the point of view of the team attacking there."""
        u = self.stats.attack_u(team, period, x)
        forward = (team == 0) == (period == 1)
        side_y = y if forward else W - y
        side = "left" if side_y > W * 0.66 else "right" if side_y < W * 0.34 else "centre"
        if u > L - 16.5 and abs(y - W / 2) < 20.16:
            zone = "inside the box"
        elif u > 70:
            zone = "final third"
        elif u > 35:
            zone = "midfield"
        else:
            zone = "deep in their own half"
        dist = math.hypot(L - u, y - W / 2)
        return {"zone": zone, "side": side, "metres_from_goal": int(round(dist / 5) * 5),
                "attacking": "left to right" if forward else "right to left"}

    def where(self, team: int, period: int, x: float, y: float) -> str:
        p = self.place(team, period, x, y)
        side = "through the middle" if p["side"] == "centre" else f"{p['side']} side"
        return f"{p['zone']}, {side}, about {p['metres_from_goal']} metres from goal"

    def directions(self, period: int) -> dict:
        """Which way each team attacks on the main camera, and what they wear."""
        out = {}
        for team in (0, 1):
            forward = (team == 0) == (period == 1)
            out[self.short[team]] = {"attacking": "left to right" if forward else "right to left", "kit": KITS[team]}
        return out

    def clock(self, tick: int) -> tuple[float, int]:
        tick = min(tick, self.stats.n - 1)
        return float(self.match.frames[tick, 1]), int(self.match.frames[tick, 0])

    def minute(self, tick: int) -> str:
        clock, period = self.clock(tick)
        return minute_label(clock, period)

    def minutes_played(self, tick: int) -> int:
        """Whole minutes on the clock, the way a radio commentator gives the time ("28 minutes gone")."""
        return int(self.clock(tick)[0] // 60)

    def score_text(self, tick: int) -> str:
        s = self.match.score_at(tick)
        return f"{self.short[0]} {s[0]}-{s[1]} {self.short[1]}"

    def game_state(self, team: int, tick: int) -> str:
        s = self.match.score_at(tick)
        mine, theirs = s[team], s[1 - team]
        return "level" if mine == theirs else "leading" if mine > theirs else "trailing"

    # ------------------------------------------------------------ events

    def events_before(self, tick: int, window: int) -> list[dict]:
        lo = bisect.bisect_left(self.ticks, tick - window)
        hi = bisect.bisect_right(self.ticks, tick)
        return self.events[lo:hi]

    def events_until(self, tick: int) -> list[dict]:
        return self.events[:bisect.bisect_right(self.ticks, tick)]

    def events_at(self, tick: int) -> list[dict]:
        lo = bisect.bisect_left(self.ticks, tick)
        hi = bisect.bisect_right(self.ticks, tick)
        return self.events[lo:hi]

    # ------------------------------------------------------------ finding the moments

    def scan(self, start: int, end: int) -> list[Moment]:
        """Moments in (start, end]."""
        lo = bisect.bisect_right(self.all_ticks, start)
        hi = bisect.bisect_right(self.all_ticks, end)
        return self.all[lo:hi]

    def get(self, moment_id: str) -> Moment | None:
        return next((m for m in self.all if m.id == moment_id), None)

    def _find_moments(self) -> list[Moment]:
        out: list[Moment] = [self.opening()]
        state = {"fastest": 0.0, "fastest_by": None, "last_press": {0: -10**9, 1: -10**9}, "corner": None}
        for e in self.events:
            m = self._from_event(e, state)
            if m:
                out.append(m)
        state_col = self.match.frames[:, 6]
        n = self.stats.n
        # a read of the game every few minutes of play, always on the same ticks, never close to a whistle
        ends = [p["end_tick"] for p in self.match.meta["periods"]]
        for t in range(SPELL_EVERY, n, SPELL_EVERY):
            if state_col[t] == 0 and all(not (end - 90 * HZ <= t <= end + 60 * HZ) for end in ends):
                out.append(self.spell(t))
        # filler candidates: quiet play, every five seconds; the director decides who speaks
        out.sort(key=lambda m: m.tick)
        busy = np.zeros(n + 1, dtype=bool)
        for m in out:
            busy[max(0, m.tick - 20):min(n, m.tick + QUIET_AFTER)] = True
        for t in range(FILLER_EVERY, n, FILLER_EVERY):
            if not busy[t] and state_col[t] == 0 and all(not (end - 20 <= t <= end + 20 * HZ) for end in ends):
                m = self.play(t)
                if m:
                    out.append(m)
        out.sort(key=lambda m: (m.tick, -m.priority))
        return out

    def _from_event(self, e: dict, state: dict) -> Moment | None:
        t = e["type"]
        if t == "goal":
            return self.goal(e)
        if t == "shot" and e["outcome"] != "goal":
            return self.shot(e)
        if t in ("tackle", "interception", "recovery"):
            return self.press(e, state)
        if t == "sprint":
            return self.sprint(e, state)
        if t == "corner":
            state["corner"] = e
            return self.corner(e)
        if t in ("cross", "pass") and state.get("corner") is not None:
            c = state["corner"]
            if e.get("team") == c["team"] and 0 < e["tick"] - c["tick"] < 60 * HZ and e.get("x") in (0.0, L):
                state["corner"] = None
                return self.corner_kick(e, c)
            if e["tick"] - c["tick"] >= 60 * HZ:
                state["corner"] = None
        if t == "yellow_card":
            return self.card(e)
        if t == "substitution":
            return self.substitution(e)
        if t == "kick_off" and e.get("team") is not None:
            if any(x["type"] == "goal" and 0 < e["tick"] - x["tick"] < 900 for x in self.events_before(e["tick"], 900)):
                return None
            return self.kickoff(e)
        if t in ("half_time", "full_time"):
            return self.whistle(e)
        return None

    # ------------------------------------------------------------ the moments

    def build_up(self, tick: int, team: int) -> dict:
        """How the attack that ended at `tick` was built, from the events before it."""
        chain = []
        start = None
        for e in reversed(self.events_before(tick, 40 * HZ)):
            if e["tick"] >= tick:          # the shot itself, and what it led to (a save, a corner)
                continue
            if e["type"] == "possession" and e.get("team") == team:
                start = e
                break
            if e.get("team") != team:
                continue
            if e["type"] == "pass" and e["outcome"] == "complete":
                chain.append(f"{self.name(e['player'])} to {self.name(e['to'])} ({e['length']:.0f} m pass, difficulty {e['difficulty']} out of 100)")
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
            secs = (tick - start["tick"]) / HZ
            info["seconds"] = round(secs, 1)
            info["start_tick"] = start["tick"]
            if start["type"] == "possession":
                u = self.stats.attack_u(team, start["period"], self.stats._event_x(start))
                info["won_by"] = self.name(start.get("player"))
                info["won_how"] = start.get("cause")
                info["won_where"] = "in the opponent's half" if u > 52.5 else "in their own half"
                info["counter_attack"] = bool(u < 52.5 and secs < 15)
            else:
                info["started_from"] = start["type"].replace("_", " ")
        return info

    def finish(self, e: dict) -> dict:
        kind = {"open": "shot from open play", "header": "header", "free_kick": "direct free kick"}.get(e.get("shot_type"), "shot")
        return {"type": kind, "distance_m": int(round(e["distance"])), "shot_speed_kmh": e["speed_kmh"], "xg": e["xg"]}

    def shot_place(self, team: int, period: int, x: float, y: float) -> dict:
        """Where a shot was taken from; its distance is in the finish, so it isn't repeated here."""
        p = self.place(team, period, x, y)
        p.pop("metres_from_goal")
        return p

    def shot_result(self, e: dict) -> str:
        after = self.events_at(e["tick"])
        keeper = next((x for x in after if x["type"] == "save"), None)
        gk = self.name(keeper["player"]) if keeper else "the goalkeeper"
        if e["outcome"] == "saved":
            if any(x["type"] == "possession" and x.get("cause") == "save" for x in after):
                return f"saved and held by {gk}"
            if any(x["type"] == "corner_conceded" for x in after):
                return f"saved by {gk}, pushed behind for a corner"
            return f"saved by {gk}, the ball runs loose"
        if e["outcome"] == "blocked":
            blocker = next((x for x in after if x["type"] == "block"), None)
            by = self.who(blocker["player"])["name"] if blocker else "a defender"
            corner = any(x["type"] == "corner" for x in after)
            return f"blocked by {by}" + (", out for a corner" if corner else "")
        return "off target"

    def goal(self, e: dict) -> Moment:
        team = e["team"]
        label = minute_label(e["clock"], e["period"])
        score = e["score"]
        before = (score[0] - (team == 0), score[1] - (team == 1))
        if before[team] < before[1 - team]:
            context = "equaliser" if score[0] == score[1] else "pulls one back"
        elif before[team] == before[1 - team]:
            context = "opening goal" if sum(before) == 0 else "puts them ahead"
        else:
            context = "extends the lead"
        if e["clock"] >= 85 * 60 and score[team] > score[1 - team] and before[team] == before[1 - team]:
            context = "late go-ahead goal"
        build = self.build_up(e["tick"], team)
        facts = {"minute": label, "score_now": f"{self.short[0]} {score[0]}-{score[1]} {self.short[1]}",
                 "what_it_means": context, "scorer": self.who(e["player"]), "assist": self.who(e.get("assist")),
                 "scorer_season": self.season_player(e["player"], e["tick"]),
                 "finish": self.finish(e), "place": self.shot_place(team, e["period"], e["x"], e["y"]),
                 "build_up": build, "scorer_today": self.player_profile(e["player"], e["tick"])}
        how = " on the counter-attack" if build.get("counter_attack") else ""
        assist = self.name(e.get("assist"))
        summary = (f"GOAL for {self.team_names[team]}{how}. {self.name(e['player'])} scores at {label}"
                   f"{f', assisted by {assist}' if assist else ''}. {facts['score_now']} ({context}).")
        return Moment(f"goal-{e['tick']}", e["tick"], "goal", 5, team, summary, facts,
                      [p for p in (e["player"], e.get("assist")) if p])

    def shot(self, e: dict) -> Moment:
        team = e["team"]
        big = e["xg"] >= BIG_CHANCE_XG
        result = self.shot_result(e)
        facts = {"minute": minute_label(e["clock"], e["period"]), "score": self.score_text(e["tick"]),
                 "shooter": self.who(e["player"]), "result": result, "finish": self.finish(e),
                 "place": self.shot_place(team, e["period"], e["x"], e["y"]), "build_up": self.build_up(e["tick"], team)}
        summary = f"{'Big chance' if big else 'Shot'} for {self.short[team]}: {self.name(e['player'])}, {result}."
        return Moment(f"shot-{e['tick']}", e["tick"], "big_chance" if big else "shot", 4 if big else 3, team, summary, facts,
                      [e["player"]])

    def corner(self, e: dict) -> Moment:
        team = e["team"]
        _, period = self.clock(e["tick"])
        why = next((x for x in self.events_at(e["tick"]) if x["type"] in ("save", "block", "clearance")), None)
        facts = {"minute": self.minute(e["tick"]), "score": self.score_text(e["tick"]), "team": self.short[team],
                 "side": self.place(team, period, e["x"], e["y"])["side"],
                 "corners_so_far": sum(1 for x in self.events_until(e["tick"]) if x["type"] == "corner" and x["team"] == team)}
        if why:
            facts["after"] = {"save": "a save", "block": "a block", "clearance": "a clearance"}[why["type"]] + f" by {self.name(why.get('player'))}"
        return Moment(f"corner-{e['tick']}", e["tick"], "corner", 2, team, f"Corner to {self.short[team]}.", facts)

    def corner_kick(self, e: dict, c: dict) -> Moment:
        team = e["team"]
        _, period = self.clock(e["tick"])
        nxt = next((x for x in self.events_at(e["tick"]) if x["type"] in ("clearance", "interception")), None)
        outcome = (f"cleared by {self.name(nxt.get('player'))}" if nxt else
                   f"finds {self.name(e.get('to'))}" if e.get("to") else "into the box")
        facts = {"minute": self.minute(e["tick"]), "score": self.score_text(e["tick"]), "taker": self.who(e.get("player")),
                 "side": self.place(team, period, c["x"], c["y"])["side"], "delivery": outcome}
        players = [p for p in (e.get("player"), e.get("to"), nxt.get("player") if nxt else None) if p]
        return Moment(f"cornerkick-{e['tick']}", e["tick"], "corner_kick", 2, team,
                      f"{self.name(e.get('player'))} takes the corner for {self.short[team]}: {outcome}.", facts, players)

    def card(self, e: dict) -> Moment:
        team, pid = e["team"], e["player"]
        foul = next((x for x in reversed(self.events_before(e["tick"], 30)) if x["type"] == "foul" and x.get("player") == pid), None)
        facts = {"minute": self.minute(e["tick"]), "score": self.score_text(e["tick"]), "player": self.who(pid),
                 "fouls_by_him_today": sum(1 for x in self.events_until(e["tick"]) if x["type"] == "foul" and x.get("player") == pid),
                 "team_yellow_cards": sum(1 for x in self.events_until(e["tick"]) if x["type"] == "yellow_card" and x["team"] == team)}
        players = [pid]
        if foul:
            facts["foul_on"] = self.who(foul.get("on"))
            _, period = self.clock(e["tick"])
            facts["where"] = self.where(team, period, foul["x"], foul["y"])
            if foul.get("on"):
                players.append(foul["on"])
        return Moment(f"card-{e['tick']}-{pid}", e["tick"], "card", 3, team,
                      f"Yellow card for {self.name(pid)} of {self.short[team]}.", facts, players)

    def substitution(self, e: dict) -> Moment:
        team = e["team"]
        off = self.player_profile(e["off"], e["tick"])
        facts = {"minute": minute_label(e["clock"], e["period"]), "score": self.score_text(e["tick"]),
                 "team": self.short[team], "game_state": self.game_state(team, e["tick"]),
                 "on": self.who(e["on"]), "off": self.who(e["off"]),
                 "off_today": {k: off.get(k) for k in ("distance_km", "shots", "passes", "goals", "assists")},
                 "on_this_season": self.season_player(e["on"], e["tick"]),
                 "subs_used": sum(1 for x in self.events_until(e["tick"]) if x["type"] == "substitution" and x["team"] == team)}
        # two changes can happen at once, so the incoming player is part of the id
        return Moment(f"sub-{e['tick']}-{e['on']}", e["tick"], "substitution", 3, team,
                      f"Substitution for {self.short[team]} at {facts['minute']}: {self.name(e['on'])} comes on for {self.name(e['off'])}.",
                      facts, [e["on"], e["off"]])

    # ------------------------------------------------------------ the season

    def standing(self, team: int) -> dict | None:
        s = self.match.season
        if not s:
            return None
        code = self.match.meta["teams"][team]["code"]
        t = next(x for x in s["table"] if x["code"] == code)
        return {"position": t["position"], "points": t["points"], "played": t["played"],
                "record": f"won {t['won']}, drawn {t['drawn']}, lost {t['lost']}", "form_last_five": s["form"][code]}

    def season_player(self, pid: str, tick: int) -> dict | None:
        """A player's season so far, counting what he has done in this match up to `tick`."""
        s = self.match.season
        if not s or pid not in s["players"]:
            return None
        p = s["players"][pid]
        today = sum(1 for e in self.events_until(tick) if e["type"] == "goal" and e.get("player") == pid)
        out = {"league_goals_this_season": p["goals"] + today, "appearances_this_season": p["appearances"] + 1,
               "goals_for_the_club": p["club_goals"] + today}
        if today:
            if p["goals"] == 0 and today == 1:
                out["milestone"] = "his first goal of the season"
            if (p["club_goals"] + today) % 50 == 0:
                out["milestone"] = f"his {p['club_goals'] + today}th goal for the club"
        return out

    def table_if(self, score: list[int]) -> dict | None:
        """Where both teams would stand with this result, the rest of the matchday aside."""
        s = self.match.season
        if not s:
            return None
        teams = self.match.meta["teams"]
        rows = {t["code"]: dict(t) for t in s["table"]}
        for i in (0, 1):
            r = rows[teams[i]["code"]]
            mine, theirs = score[i], score[1 - i]
            r["points"] += 3 if mine > theirs else 1 if mine == theirs else 0
            r["for"] += mine
            r["against"] += theirs
        ranked = sorted(rows.values(), key=lambda t: (-t["points"], -(t["for"] - t["against"]), -t["for"]))
        return {self.short[i]: {"position": next(k for k, t in enumerate(ranked, 1) if t["code"] == teams[i]["code"]),
                                "points": rows[teams[i]["code"]]["points"]} for i in (0, 1)}

    def opening(self) -> Moment:
        """Before kick-off: the two teams, how they line up, what they wear, which way they attack, who to watch."""
        teams = self.match.meta["teams"]
        lineups = {}
        for t in teams:
            lineups[t["short"]] = {"club": t["name"], "formation": t["formation"], "kit": KITS[t["index"]],
                                   "starting": [f"{self.players[pid]['number']} {self.players[pid]['name']} "
                                                f"({POSITIONS.get(self.players[pid]['position'], '')})" for pid in t["starters"]]}
        watch = ["KSM-10", "KSM-9", "ASH-7", "ASH-10"]
        facts = {"score": self.score_text(0), "teams": lineups, "attacking_first_half": self.directions(1),
                 "players_to_watch": [self.who(pid) | ({"season": self.season_player(pid, 0)} if self.match.season else {})
                                      for pid in watch]}
        if self.match.season:
            s = self.match.season
            leader = s["table"][0]
            facts["season"] = {"league": s["league"], "matchday": s["matchday"], "last_meeting": s["last_meeting"]["score"],
                               "leaders": f"{leader['club']}, {leader['points']} points",
                               "standing": {self.short[i]: self.standing(i) for i in (0, 1)},
                               "if_kingsmere_win": self.table_if([1, 0]), "if_ashvale_win": self.table_if([0, 1])}
        return Moment("open-1", 1, "open", 5, None,
                      f"Before kick-off: {teams[0]['name']} against {teams[1]['name']}.", facts, watch)

    def kickoff(self, e: dict) -> Moment:
        period = e["period"]
        facts = {"half": "first half" if period == 1 else "second half", "score": self.score_text(e["tick"]),
                 "kicking_off": self.short[e["team"]], "teams": self.directions(period),
                 "formations": {self.short[i]: self.match.meta["teams"][i]["formation"] for i in (0, 1)}}
        if period == 2:
            facts["first_half"] = self.team_facts(self.stats.team_stats(e["tick"]))
        return Moment(f"kickoff-{e['tick']}", e["tick"], "kickoff", 3, None,
                      f"{facts['half'].capitalize()} under way. {facts['score']}.", facts)

    def whistle(self, e: dict) -> Moment:
        t = e["type"]
        score = e["score"]
        goals = [{"minute": minute_label(x["clock"], x["period"]), "scorer": self.who(x["player"]),
                  "assist": self.name(x.get("assist"))} for x in self.events_until(e["tick"]) if x["type"] == "goal"]
        facts = {"score": f"{self.team_names[0]} {score[0]}-{score[1]} {self.team_names[1]}", "goals": goals,
                 "teams": self.team_facts(self.stats.team_stats(e["tick"]))}
        if t == "full_time" and self.match.season:
            facts["table_now"] = self.table_if(score)
            facts["before_this_match"] = {self.short[i]: self.standing(i) for i in (0, 1)}
        label = "Half-time" if t == "half_time" else "Full-time"
        return Moment(f"{t}-{e['tick']}", e["tick"], t, 5, None,
                      f"{label}: {self.team_names[0]} {score[0]}-{score[1]} {self.team_names[1]}.", facts)

    def press(self, e: dict, state: dict) -> Moment | None:
        team = e.get("team")
        if team is None:
            return None
        if self.stats.attack_u(team, e["period"], self.stats._event_x(e)) < 52.5:
            return None
        wins = [x for x in self.events_before(e["tick"], PRESS_WINDOW)
                if x["type"] in ("tackle", "interception", "recovery") and x.get("team") == team
                and self.stats.attack_u(team, x["period"], self.stats._event_x(x)) >= 52.5]
        if len(wins) < 3 or e["tick"] - state["last_press"][team] < PRESS_SPACING:
            return None
        state["last_press"][team] = e["tick"]
        since = max(0, e["tick"] - 10 * 60 * HZ)
        recent = self.team_facts(self.stats.team_stats(e["tick"], since=since))
        x = self.stats._event_x(e)
        y = e.get("y", float(self.match.frames[min(e["tick"], self.stats.n - 1), 3]))
        facts = {"minute": self.minute(e["tick"]), "score": self.score_text(e["tick"]), "pressing_team": self.short[team],
                 "wins_in_opponent_half_last_5_min": len(wins), "this_one": {"by": self.who(e.get("player")), "how": e["type"],
                 "place": self.place(team, e["period"], x, y)}, "last_10_minutes": recent}
        summary = (f"{self.short[team]} win the ball back in {self.short[1 - team]}'s half again: "
                   f"{len(wins)} times in the last five minutes.")
        return Moment(f"press-{e['tick']}", e["tick"], "press", 3, team, summary, facts,
                      [e["player"]] if e.get("player") else [])

    def sprint(self, e: dict, state: dict) -> Moment:
        fastest = e["speed_kmh"] > state["fastest"]
        before = state["fastest_by"]
        if fastest:
            state["fastest"], state["fastest_by"] = e["speed_kmh"], e["player"]
        pid, team = e["player"], e["team"]
        tick = e["tick"]
        slot = self.stats.player_slot(pid, tick)
        facts = {"minute": self.minute(tick), "score": self.score_text(tick), "runner": self.who(pid),
                 "speed_kmh": e["speed_kmh"], "fastest_of_the_match_so_far": fastest}
        if fastest and before and before != pid:
            facts["previous_fastest"] = self.name(before)
        if slot is not None:
            _, period = self.clock(tick)
            p = self.stats.pos[tick, slot]
            facts["place"] = self.place(team, period, float(p[0]), float(p[1]))
            a = self.stats.pos[max(e["start_tick"], tick - 10), slot]
            du = self.stats.attack_u(team, period, float(p[0])) - self.stats.attack_u(team, period, float(a[0]))
            owner = int(self.match.frames[tick, 5])
            with_ball = owner == slot
            ours = owner >= 0 and (owner < 11) == (team == 0)
            facts["running"] = ("carrying the ball forward" if with_ball and du > 0 else
                                "running in behind" if ours and du > 2 else
                                "tracking back" if not ours and du < -2 else
                                "racing across" if abs(du) <= 2 else "running forward" if du > 0 else "running back")
            facts["team_in_possession"] = (self.short[0] if owner < 11 else self.short[1]) if owner >= 0 else "nobody"
        return Moment(f"sprint-{tick}-{pid}", tick, "sprint", 3 if fastest else 2, team,
                      f"{self.name(pid)} ({self.short[team]}) hits {e['speed_kmh']} km/h"
                      f"{', the fastest sprint of the match so far' if fastest else ''}.", facts, [pid])

    def spell(self, tick: int) -> Moment:
        since = max(0, tick - 10 * 60 * HZ)
        teams = self.team_facts(self.stats.team_stats(tick, since=since))
        mom = self.stats.momentum(tick, minutes=6)
        avg = float(np.mean([m["value"] for m in mom])) if mom else 0.0
        on_top = 0 if avg > 0.15 else 1 if avg < -0.15 else None
        read = "an even spell" if on_top is None else f"{self.short[on_top]} on top"
        c = self.stats.control(tick)
        facts = {"minute": self.minute(tick), "score": self.score_text(tick), "last_10_minutes": teams,
                 "read": read, "control_or_chaos": {"chaos_0_to_1": c["chaos"], "turnovers_per_minute": c["turnovers_per_min"],
                                                    "passes_per_minute": c["tempo_passes_per_min"]}}
        return Moment(f"spell-{tick}", tick, "spell", 2, on_top, f"The last ten minutes: {read}.", facts)

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
        team = 0 if owner < 11 else 1
        pid = lineup[owner]
        in_flight_to = None
        if back < tick:
            # the ball is travelling: describe it from where it was played, and say who it is going to
            fr = self.match.frames[back]
            ahead = next((int(self.match.frames[t, 5]) for t in range(tick, min(tick + 15, self.stats.n))
                          if int(self.match.frames[t, 5]) >= 0), -1)
            if ahead >= 0 and (ahead < 11) == (team == 0) and ahead != owner:
                in_flight_to = self.name(lineup[ahead])
        recent = [e for e in self.events_before(tick, 10 * HZ) if e["type"] in ("pass", "take_on", "tackle", "interception", "cross")]
        seq = []
        for e in recent[-4:]:
            if e["type"] == "pass":
                seq.append(f"{self.name(e['player'])} to {self.name(e.get('to')) or 'nobody'} ({e['outcome']})")
            else:
                seq.append(f"{e['type'].replace('_', ' ')} by {self.name(e.get('player'))} ({self.short[e['team']]})")
        chain = 0
        for e in reversed(self.events_before(tick, 60 * HZ)):
            if e["type"] == "possession":
                break
            if e["type"] == "pass" and e["outcome"] == "complete" and e["team"] == team:
                chain += 1
        won = next((e for e in reversed(self.events_before(tick, 10 * HZ)) if e["type"] == "possession"), None)
        facts = {"minute": minute_label(clock, period), "score": self.score_text(tick), "on_the_ball": self.who(pid),
                 "place": self.place(team, period, float(fr[2]), float(fr[3])), "passes_in_this_move": chain,
                 "recent": seq}
        if won is not None and won.get("team") == team:
            facts["ball_just_won"] = {"by": self.name(won.get("player")), "how": won.get("cause"),
                                      "seconds_ago": int((tick - won["tick"]) / HZ)}
        if in_flight_to:
            facts["pass_on_its_way_to"] = in_flight_to
        summary = f"{self.short[team]} in possession, {self.name(pid)} on the ball."
        return Moment(f"play-{tick}", tick, "play", 1, team, summary, facts, [pid])

    # ------------------------------------------------------------ players

    def team_facts(self, stats: list[dict]) -> dict:
        """Team numbers in the form commentators say them: percentages, not fractions."""
        out = {}
        for i in (0, 1):
            s = stats[i]
            pct = lambda v: None if v is None else round(v * 100)  # noqa: E731
            out[self.short[i]] = {"possession_pct": pct(s["possession"]), "shots": s["shots"], "on_target": s["on_target"],
                                  "xg": s["xg"], "pass_completion_pct": pct(s["completion"]),
                                  "final_third_pass_share_pct": pct(s["field_tilt"]), "ppda": s["ppda"],
                                  "corners": s["corners"], "distance_km": s["distance_km"]}
        return out

    _team_facts = team_facts

    def player_profile(self, pid: str, tick: int) -> dict:
        for p in self.stats.players(tick):
            if p["player"] == pid:
                info = self.players[pid]
                return {"name": info["name"], "team": self.short[info["team"]], "number": info["number"],
                        "position": POSITIONS.get(info["position"], info["position"]),
                        "distance_km": p["distance_km"], "top_speed_kmh": p["top_speed_kmh"], "sprints": p["sprints"],
                        "passes": p["passes"], "pass_completion_pct": None if p["pass_completion"] is None else round(p["pass_completion"] * 100),
                        "shots": p["shots"], "goals": p["goals"], "assists": p["assists"], "tackles": p["tackles"]}
        return {"name": self.name(pid)}

    def player_context(self, pid: str, tick: int) -> dict:
        """Where one player is and what he is doing right now, for a feed that follows him."""
        s = self.stats
        tick = min(tick, s.n - 1)
        slot = s.player_slot(pid, tick)
        info = {"name": self.name(pid)}
        if slot is None:
            return info | {"on_pitch": False}
        team = 0 if slot < 11 else 1
        _, period = self.clock(tick)
        p = s.pos[tick, slot]
        before = s.pos[max(0, tick - 10), slot]
        du = s.attack_u(team, period, float(p[0])) - s.attack_u(team, period, float(before[0]))
        speed = float(s.speed[tick, slot])
        ball = self.match.frames[tick, 2:4]
        dist = float(np.hypot(*(p - ball)))
        owner = int(self.match.frames[tick, 5])
        last = next((e for e in reversed(self.events_before(tick, 90 * HZ)) if e.get("player") == pid and e["type"] in ACTIONS), None)
        touches = sum(1 for e in self.events_before(tick, 60 * HZ) if e.get("player") == pid and e["type"] in ACTIONS)
        moving = ("running forward" if du > 2.5 else "dropping back" if du < -2.5 else
                  "moving across" if speed > 2.0 else "walking or standing")
        info |= {"on_pitch": True, "place": self.place(team, period, float(p[0]), float(p[1])),
                 "distance_to_ball_m": int(round(dist)), "has_the_ball": owner == slot, "moving": moving,
                 "touches_last_minute": touches}
        if last:
            info["last_action"] = {"what": last["type"].replace("_", " "), "seconds_ago": int((tick - last["tick"]) / HZ),
                                   **({"to": self.name(last.get("to"))} if last.get("to") else {}),
                                   **({"outcome": last["outcome"]} if "outcome" in last else {})}
        info["involved"] = bool(owner == slot or dist < 12 or (last and tick - last["tick"] < 8 * HZ))
        return info

    # ------------------------------------------------------------ tools for the stats desk agent

    def tools(self, now):
        """Functions the stats desk agent may call. They only see the match up to `now()`."""
        desk = self

        def team_stats(minutes: int = 10) -> dict:
            """Both teams' numbers over the last `minutes` minutes of play (possession, shots, xG, pass accuracy, share of final-third passes, PPDA, corners, distance)."""
            t = now()
            since = max(0, t - int(minutes) * 60 * HZ)
            return desk.team_facts(desk.stats.team_stats(t, since=since))

        def match_totals() -> dict:
            """Both teams' totals for the match so far, plus the score."""
            t = now()
            return {"score": desk.score_text(t), "teams": desk.team_facts(desk.stats.team_stats(t))}

        def player_stats(name: str) -> dict:
            """One player's numbers so far: team, distance, top speed, sprints, passes, shots, goals, assists, tackles."""
            pid = desk.player_id(name)
            return desk.player_profile(pid, now()) if pid else {"error": f"no player called {name}"}

        def momentum(minutes: int = 10) -> list:
            """Attack momentum per minute: positive values Kingsmere, negative Ashvale."""
            return desk.stats.momentum(now(), minutes=int(minutes))

        def storylines() -> list:
            """Threads of the match so far worth mentioning: saves, shooters without a goal, substitutes, pressing, territory, the defensive line, the fastest sprint."""
            return [{"text": s["text"]} for s in desk.storylines.at(now())]

        return [team_stats, match_totals, player_stats, momentum, storylines]
