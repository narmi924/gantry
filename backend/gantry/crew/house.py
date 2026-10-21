"""House style: how every Gantry commentator talks, in any language, and what may go on air.

The rules go into every commentator's instructions. Before a line is voiced,
`problem()` reads it the way an editor in the gallery would: a name that isn't
part of the moment, a number that isn't in the facts, or a phrase the feed has
banned sends the line back for one rewrite (or, if there is no time, to a
prepared line).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .feeds import Feed, local_club, local_name

LINES = Path(__file__).resolve().parents[2] / "data" / "i18n" / "lines.json"
NUMBER = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)")


@lru_cache(maxsize=1)
def templates() -> dict:
    return json.loads(LINES.read_text(encoding="utf-8"))


GENERAL_RULES = (
    "Use only names and numbers in the material. Never invent a detail: no left or right foot, no header unless the "
    "material says header, no shot height or corner of the net, no rebound unless the material says the ball ran loose. "
    "A player does only what the material says he did. Write complete spoken sentences without parentheses or symbols "
    "such as 30' (say the minute as a word)."
)


def house_rules(feed: Feed) -> str:
    lang = feed.lang
    rules = [
        "Use only names and numbers that appear in the facts, the storyline or the team sheet. Never invent a detail: "
        "no left or right foot, no header unless the facts say header, no shot height or corner of the net, no rebound "
        "unless the facts say the ball ran loose, no weather, no time of day.",
        "Every player belongs to the team the facts and the team sheet give. Never put a player in the other team.",
        "Credit a player only with what the facts say he did: in 'A to B (49 m pass)', the pass is A's, and B received it.",
        "Mention the crowd only for a goal.",
        "When a number covers only part of the match (the last five or ten minutes), say so. Talk only about this "
        "moment; don't retell an earlier one unless the director asks you to.",
        f"Say every number the way it is said aloud in {lang.name}: the minute as a word or an ordinary number "
        "(never 75'), percentages as percentages (never 0.55), speeds in kilometres an hour, distances in metres.",
        "Never repeat one of your recent lines, and never start two lines in a row with the same words.",
        "Write complete spoken sentences: no parentheses, no lists, no notes, and no abbreviations except xG and PPDA.",
        "Talk about the match, not the broadcast: never mention graphics or anything shown on screen.",
        f"Output only the words you say on air, in {lang.name}: no quotation marks, no stage directions, no emojis.",
    ]
    if lang.native_names:
        rules.append(f"Write every player and club name exactly as the team sheet writes it in {lang.name}.")
    else:
        rules.append("Call players by surname, as the on-screen labels do; use the full name for a goal or a first mention.")
    if lang.code != "en":
        rules.append(f"Speak natural, idiomatic {lang.name}, the way a broadcaster in that language would, not a translation.")
    if feed.aud.banned and lang.code == "en":
        rules.append("Never use these words or phrases: " + "; ".join(f'"{b}"' for b in feed.aud.banned) + ".")
    return "House rules:\n- " + "\n- ".join(rules)


def team_sheet(feed: Feed, meta: dict) -> str:
    """Both squads, as this feed's language writes the names."""
    lang = feed.lang
    out = ["Team sheet:"]
    for t in meta["teams"]:
        club = local_club(lang, t["code"], t["short"], full=True, english_full=t["name"])
        kit = "royal blue shirts and shorts, white socks" if t["index"] == 0 else "amber shirts, navy shorts"
        out.append(f"{club} ({kit}), {t['formation']}:")
        starters = set(t["starters"])
        for group, label in ((True, "Starting"), (False, "Bench")):
            row = []
            for p in t["players"]:
                if (p["id"] in starters) != group:
                    continue
                name = local_name(lang, p["id"], p["name"])
                english = f" = {p['name']}" if lang.native_names else ""
                row.append(f"{p['number']} {name}{english} ({p['position']})")
            out.append(f"  {label}: " + "; ".join(row))
    return "\n".join(out)


# ------------------------------------------------------------------ reading a line before it airs


def _numbers(obj, out: set[float]):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
        if 0 < obj < 1:
            out.add(round(obj * 100))
        return
    if isinstance(obj, str):
        for m in NUMBER.finditer(obj):
            out.add(float(m.group(1).replace(",", ".")))
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)


def allowed_numbers(*sources) -> set[float]:
    out: set[float] = {0.0, 1.0, 2.0, 3.0}
    for s in sources:
        _numbers(s, out)
    for n in list(out):
        out.add(round(n))
        if n >= 90:       # 90+3' may be said as 93
            out.add(n)
    return out


def names_in(obj, desk) -> set[str]:
    """Players whose full name appears anywhere in some facts."""
    text = json.dumps(obj, ensure_ascii=False)
    return {pid for pid, p in desk.players.items() if p["name"] in text}


def name_forms(feed: Feed, desk) -> dict[str, list[str]]:
    forms = {}
    for pid, p in desk.players.items():
        if feed.lang.native_names:
            forms[pid] = [local_name(feed.lang, pid, p["name"]), local_name(feed.lang, pid, p["name"], short=True)]
        else:
            forms[pid] = [p["name"], p["last"], p["first"]]
    return forms


def problem(text: str, feed: Feed, desk, allowed: set[str], numbers: set[float], max_units: int) -> str | None:
    """Why a line can't go on air as written, or None if it can."""
    low = text.lower()
    if re.search(r"\d+\s*['’]", text):
        return "it writes a minute as a symbol; say it as a word"
    for b in (feed.aud.banned if feed.lang.code == "en" else ()):
        if b in low:
            return f'it uses "{b}", which this feed never says'
    for pid, forms in name_forms(feed, desk).items():
        if pid in allowed:
            continue
        for f in forms:
            if len(f) < 3:
                continue
            hit = (f in text) if feed.lang.native_names else re.search(rf"\b{re.escape(f)}\b", text)
            if hit:
                return f"{f} is not part of this moment"
    for m in NUMBER.finditer(text):
        n = float(m.group(1).replace(",", "."))
        if not any(abs(n - a) <= max(0.51, 0.03 * a) for a in numbers):
            return f"the number {m.group(1)} is not in the facts"
    units = len(text) if feed.lang.unit == "characters" else len(text.split())
    if units > max_units * 1.6:
        return f"it is too long ({units} {feed.lang.unit}; keep it under {max_units})"
    return None


# ------------------------------------------------------------------ prepared lines


def prepared_line(feed: Feed, kind: str, m, desk) -> str | None:
    """A line the crew can always say, in the feed's language. None means stay quiet."""
    t = templates()[feed.lang.code]
    lang = feed.lang
    teams = desk.match.meta["teams"]

    def nm(pid):
        return local_name(lang, pid, desk.players[pid]["name"], short=False) if pid in desk.players else ""

    def club(i):
        return local_club(lang, teams[i]["code"], teams[i]["short"])

    def score(tick):
        s = desk.match.score_at(tick)
        return t["score"].format(home=club(0), a=s[0], b=s[1], away=club(1))

    k = m.kind
    if kind == "call":
        if k == "goal":
            return t["goal"].format(scorer=nm(m.players[0]), team=club(m.team), score=score(m.tick))
        if k in ("big_chance", "shot"):
            return t["shot"].format(shooter=nm(m.players[0]))
        if k in ("half_time", "full_time"):
            return t[k].format(score=score(m.tick))
        if k == "corner":
            return t["corner"].format(team=club(m.team))
        return None
    if kind == "editorial":
        if k == "substitution":
            return t["substitution"].format(team=club(m.team), on=nm(m.players[0]), off=nm(m.players[1]))
        if k == "card":
            return t["card"].format(player=nm(m.players[0]))
        if k == "kickoff":
            return t["kickoff_1" if m.facts.get("half") == "first half" else "kickoff_2"].format(score=score(m.tick))
        return None
    if kind == "filler" and feed.aud.describes_play and m.players:
        return t["play"].format(team=club(m.team), player=nm(m.players[0]))
    return None


def score_line(feed: Feed, desk, tick: int) -> str:
    t = templates()[feed.lang.code]
    teams = desk.match.meta["teams"]
    s = desk.match.score_at(tick)
    club = [local_club(feed.lang, teams[i]["code"], teams[i]["short"]) for i in (0, 1)]
    return t["score"].format(home=club[0], a=s[0], b=s[1], away=club[1])


def answer_fallback(feed: Feed) -> str:
    return templates()[feed.lang.code]["answer"]


def reel_goal_line(feed: Feed, desk, pid: str, team: int) -> str:
    t = templates()[feed.lang.code]
    teams = desk.match.meta["teams"]
    return t["reel_goal"].format(scorer=local_name(feed.lang, pid, desk.players[pid]["name"]),
                                 team=local_club(feed.lang, teams[team]["code"], teams[team]["short"]))
