"""Storylines: the threads a commentator can pick up when nothing big is happening.

All of them are computed from the events and the tracking data up to a given
tick, so nothing in them is ever ahead of the viewer or made up. Each has a
stable id, so the crew can avoid telling the same story twice in a row.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from ..common import HZ, L


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


class Storylines:
    def __init__(self, desk):
        self.desk = desk
        self.stats = desk.stats

    def at(self, tick: int) -> list[dict]:
        d, s = self.desk, self.stats
        tick = int(np.clip(tick, 0, s.n - 1))
        past = d.events_until(tick)
        out: list[dict] = []
        teams = s.team_stats(tick)
        score = d.match.score_at(tick)

        # goalkeepers who keep being called on
        saves = Counter(e["player"] for e in past if e["type"] == "save")
        for pid, n in saves.items():
            if n >= 3:
                p = d.players[pid]
                out.append({"id": f"saves:{pid}", "level": n, "players": [pid], "team": p["team"],
                            "text": f"{p['name']}, the {d.short[p['team']]} goalkeeper, has made {n} saves."})

        # shooters still waiting for a goal
        shots = Counter(e["player"] for e in past if e["type"] == "shot")
        goals = Counter(e["player"] for e in past if e["type"] == "goal")
        for pid, n in shots.items():
            if n >= 4 and goals[pid] == 0:
                p = d.players[pid]
                out.append({"id": f"no_goal:{pid}", "level": n, "players": [pid], "team": p["team"],
                            "text": f"{p['name']} has had {n} shots without scoring."})
            elif goals[pid] >= 1 and n >= 2:
                p = d.players[pid]
                out.append({"id": f"scorer:{pid}", "level": goals[pid], "players": [pid], "team": p["team"],
                            "text": f"{p['name']} has {goals[pid]} goal{'s' if goals[pid] > 1 else ''} from {n} shots."})

        # substitutes making a difference
        for e in past:
            if e["type"] != "substitution":
                continue
            mins = (tick - e["tick"]) / HZ / 60
            if mins < 6:
                continue
            pid = e["on"]
            mine = [x for x in past if x.get("player") == pid and x["tick"] >= e["tick"]]
            n_shots = sum(1 for x in mine if x["type"] == "shot")
            touches = sum(1 for x in mine if x["type"] in ("pass", "take_on", "shot", "cross", "tackle", "interception"))
            p = d.players[pid]
            if n_shots >= 2 or touches >= 12:
                out.append({"id": f"sub:{pid}", "level": n_shots, "players": [pid], "team": p["team"],
                            "text": f"Since coming on {round(mins)} minutes ago, {p['name']} has had {n_shots} "
                                    f"shot{'s' if n_shots != 1 else ''} and {touches} touches."})

        # a press that keeps winning the ball high
        since = max(0, tick - 10 * 60 * HZ)
        for team in (0, 1):
            wins = [e for e in past if e["tick"] >= since and e["type"] in ("tackle", "interception", "recovery")
                    and e.get("team") == team and s.attack_u(team, e["period"], s._event_x(e)) >= 52.5]
            if len(wins) >= 6:
                out.append({"id": f"press:{team}", "level": len(wins), "players": [], "team": team,
                            "text": f"{d.short[team]} have won the ball back in {d.short[1 - team]}'s half "
                                    f"{len(wins)} times in the last 10 minutes."})

        # one side doing all the shooting
        a, b = teams[0]["shots"], teams[1]["shots"]
        if max(a, b) >= 6 and max(a, b) >= 2 * max(min(a, b), 1):
            lead = 0 if a > b else 1
            out.append({"id": f"shots:{lead}", "level": max(a, b), "players": [], "team": lead,
                        "text": f"Shots: {d.short[0]} {a}, {d.short[1]} {b}. Score: {d.short[0]} {score[0]}-{score[1]} {d.short[1]}."})

        # even possession, lopsided territory
        for team in (0, 1):
            pos, tilt = teams[team]["possession"], teams[team]["field_tilt"]
            if tilt is not None and 0.42 <= pos <= 0.58 and tilt >= 0.65:
                out.append({"id": f"territory:{team}", "level": round(tilt * 10), "players": [], "team": team,
                            "text": f"Possession is close to even ({round(pos * 100)}% for {d.short[team]}), but "
                                    f"{d.short[team]} have {round(tilt * 100)}% of the passes in the final third."})

        # control or chaos over the last five minutes
        c = s.control(tick)
        if c["chaos"] >= 0.6:
            out.append({"id": "chaos", "level": round(c["chaos"] * 10), "players": [], "team": None,
                        "text": f"A scrappy spell: the ball has changed hands {c['turnovers_per_min']} times a minute "
                                f"over the last five minutes."})
        elif c["chaos"] <= 0.2 and c["tempo_passes_per_min"] >= 12:
            out.append({"id": "control", "level": round(c["tempo_passes_per_min"]), "players": [], "team": None,
                        "text": f"A controlled spell: {c['tempo_passes_per_min']} passes a minute, "
                                f"{round(c['completion'] * 100)}% of them completed."})

        # the defensive line, from the tracking data
        for team in (0, 1):
            change = self.line_change(team, tick)
            if change is not None and abs(change["metres"]) >= 5:
                deeper = change["metres"] < 0
                out.append({"id": f"line:{team}:{'deep' if deeper else 'high'}", "level": abs(round(change['metres'])),
                            "players": [], "team": team,
                            "text": f"{d.short[team]}'s back four is holding {abs(round(change['metres']))} metres "
                                    f"{'deeper' if deeper else 'higher'} than earlier in this half, "
                                    f"now about {round(change['now'])} metres from their own goal."})

        # the season: where the teams came in, and the last meeting
        season = self.desk.match.season
        if season:
            for team in (0, 1):
                st = d.standing(team)
                text = (f"{d.short[team]} came into this match {ordinal(st['position'])} in the table with "
                        f"{st['points']} points from {st['played']} games, form {', '.join(st['form_last_five'])}.")
                out.append({"id": f"table:{team}", "level": 1, "players": [], "team": team, "text": text})
            out.append({"id": "last_meeting", "level": 1, "players": [], "team": None,
                        "text": f"The last meeting, {season['last_meeting']['season']}: {season['last_meeting']['score']}."})

        # the fastest player on the pitch
        sprints = [e for e in past if e["type"] == "sprint"]
        if sprints:
            top = max(sprints, key=lambda e: e["speed_kmh"])
            p = d.players[top["player"]]
            out.append({"id": f"fastest:{top['player']}", "level": round(top["speed_kmh"]), "players": [top["player"]],
                        "team": p["team"], "text": f"The fastest sprint of the match: {p['name']} at {top['speed_kmh']} km/h."})
        return out

    def line_height(self, team: int, a: int, b: int) -> float | None:
        """Average distance of a team's four deepest outfield players from their own goal, over ticks [a, b)."""
        s = self.stats
        a, b = max(0, a), min(b, s.n)
        ticks = np.arange(a, b, HZ)
        ticks = ticks[s.state[ticks] == 0] if len(ticks) else ticks
        if len(ticks) < 20:
            return None
        slots = np.arange(1, 11) if team == 0 else np.arange(12, 22)
        x = s.pos[ticks][:, slots, 0]
        forward = (team == 0) == (s.period[ticks] == 1)
        u = np.where(forward[:, None], x, L - x)
        return float(np.sort(u, axis=1)[:, :4].mean())

    def line_change(self, team: int, tick: int) -> dict | None:
        """How the line now (last 3 minutes) compares with the first 15 minutes of this half."""
        s = self.stats
        half_start = 0 if s.period[min(tick, s.n - 1)] == 1 else int(np.argmax(s.period == 2))
        if tick - half_start < 25 * 60 * HZ:
            return None
        now = self.line_height(team, tick - 3 * 60 * HZ, tick)
        then = self.line_height(team, half_start, half_start + 15 * 60 * HZ)
        if now is None or then is None:
            return None
        return {"now": now, "then": then, "metres": now - then}
