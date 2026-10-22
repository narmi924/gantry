"""The season around the demo match: a fictional league, nine matchdays played before this one.

All of it is synthetic. Results come from a simple goals model using each club's
strength; Kingsmere and Ashvale's players get season numbers from their own
ratings. The crew uses it for what a real broadcast would bring to a match: where
the teams stand, their form, the last meeting, and milestones.

    uv run python -m gantry.sim.season --id demo
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from .store import DATA_DIR

OTHERS = [
    ("Brackwater FC", "BRK"), ("Selwyn Park", "SEL"), ("Northcliffe United", "NCU"), ("Greymoor Athletic", "GRA"),
    ("Larkspur City", "LKC"), ("Duncairn Rovers", "DUN"), ("Hollowfield Town", "HOL"), ("Westmarch United", "WMU"),
    ("Carrowmere", "CAR"), ("Oakhurst Town", "OAK"), ("Bellmont Forge", "BEL"), ("Halverton", "HAL"),
    ("Kestrel Vale", "KES"), ("Pellingham", "PEL"), ("Wexcombe City", "WEX"), ("Thornfield City", "THO"),
    ("Marlowe Bay", "MAR"), ("Cedarbrook United", "CED"),
]
PLAYED = 9                     # matchdays before the demo match, which is matchday 10
ROLE = {"ST": 1.0, "RW": 0.7, "LW": 0.7, "AM": 0.6, "CM": 0.35, "DM": 0.15, "RB": 0.1, "LB": 0.1, "CB": 0.12, "GK": 0.0}


def rounds(codes: list[str]) -> list[list[tuple[str, str]]]:
    """A round-robin, by the circle method: every club plays every other once."""
    teams = list(codes)
    out = []
    for r in range(len(teams) - 1):
        pairs = []
        for i in range(len(teams) // 2):
            a, b = teams[i], teams[-1 - i]
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        out.append(pairs)
        teams = [teams[0], teams[-1]] + teams[1:-1]
    return out


def make(meta: dict, seed: int = 60) -> dict:
    rng = np.random.default_rng(seed)
    home, away = meta["teams"]
    clubs = [(home["name"], home["code"]), (away["name"], away["code"])] + OTHERS
    codes = [c for _, c in clubs]
    names = dict((c, n) for n, c in clubs)
    strength = {c: float(rng.uniform(0.85, 1.3)) for c in codes}
    strength[home["code"]], strength[away["code"]] = 1.42, 1.28

    sched = rounds(codes)
    # this match is matchday 10, at Kingsmere
    i = next(k for k, r in enumerate(sched) if any({home["code"], away["code"]} == set(p) for p in r))
    sched.insert(PLAYED, sched.pop(i))
    sched[PLAYED] = [(home["code"], away["code"]) if {home["code"], away["code"]} == set(p) else p for p in sched[PLAYED]]

    table = {c: {"club": names[c], "code": c, "played": 0, "won": 0, "drawn": 0, "lost": 0, "for": 0, "against": 0, "points": 0}
             for c in codes}
    form = {c: [] for c in codes}
    goals_for = {c: [] for c in codes}
    for md in range(PLAYED):
        for h, a in sched[md]:
            gh = int(rng.poisson(1.35 * strength[h] / strength[a] * 1.12))
            ga = int(rng.poisson(1.35 * strength[a] / strength[h] * 0.92))
            for c, f, g in ((h, gh, ga), (a, ga, gh)):
                t = table[c]
                t["played"] += 1
                t["for"] += f
                t["against"] += g
                res = "W" if f > g else "D" if f == g else "L"
                t[{"W": "won", "D": "drawn", "L": "lost"}[res]] += 1
                t["points"] += {"W": 3, "D": 1, "L": 0}[res]
                form[c].append(res)
                goals_for[c].append(f)
    ranked = sorted(table.values(), key=lambda t: (-t["points"], -(t["for"] - t["against"]), -t["for"], t["club"]))
    for pos, t in enumerate(ranked, 1):
        t["position"] = pos

    players = {}
    for team in (home, away):
        total = table[team["code"]]["for"]
        squad = team["players"]
        starters = set(team["starters"])
        w = np.array([ROLE.get(p["position"], 0.2) * (0.3 + p["shooting"]) ** 2 for p in squad])
        goals = rng.multinomial(total, w / w.sum()) if total else np.zeros(len(squad), dtype=int)
        wa = np.array([0.0 if p["position"] == "GK" else (0.2 + p["passing"]) ** 2 * (1.2 if p["position"] in ("AM", "CM", "RW", "LW") else 0.6)
                       for p in squad])
        assists = rng.multinomial(int(total * 0.7), wa / wa.sum()) if total else np.zeros(len(squad), dtype=int)
        for p, g, a in zip(squad, goals, assists):
            apps = int(rng.integers(7, PLAYED + 1)) if p["id"] in starters else int(rng.integers(1, 6))
            club_apps = apps + int(rng.integers(20, 160))
            players[p["id"]] = {"appearances": apps, "goals": int(g), "assists": int(a),
                                "club_appearances": club_apps, "club_goals": int(g) + int(rng.integers(0, 25) * ROLE.get(p["position"], 0.2))}

    # the threads a broadcaster would have ready: a milestone within reach, a substitute still waiting
    if "KSM-10" in players:
        players["KSM-10"]["club_goals"] = 49           # one more is his fiftieth for the club
    if "KSM-19" in players:
        players["KSM-19"].update(goals=0, appearances=6)

    last = {"season": "last season", "venue": names[away["code"]], "score": f"{names[away['code']]} 2-1 {names[home['code']]}",
            "winner": away["code"]}
    return {"league": "a fictional league of 20 clubs", "matchday": PLAYED + 1, "table": ranked,
            "form": {c: "".join(form[c][-5:]) for c in codes}, "players": players, "last_meeting": last}


def main(match_id: str, seed: int):
    path = DATA_DIR / match_id
    meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    season = make(meta, seed)
    (path / "season.json").write_text(json.dumps(season, ensure_ascii=False, indent=1), encoding="utf-8")
    for t in season["table"][:8]:
        print(f"{t['position']:2d} {t['club']:20s} {t['played']} {t['won']}-{t['drawn']}-{t['lost']} {t['for']}:{t['against']} {t['points']}")
    print("form", {c: season["form"][c] for c in ("KSM", "ASH")})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="demo")
    ap.add_argument("--seed", type=int, default=60)
    a = ap.parse_args()
    main(a.id, a.seed)
