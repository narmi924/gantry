"""Gantry's match intelligence as an MCP server, so any AI assistant can plug into the match.

A studio analyst's assistant, a partner's app or GitHub Copilot in VS Code can ask
what the score is at any minute, what the key moments were, how a player is doing,
which storylines are running, what a feed said, or ask the production crew itself.

    MCP endpoint: http://localhost:8000/mcp   (streamable HTTP)
"""

from __future__ import annotations

import asyncio
import os
import re

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .crew.desk import StatsDesk
from .crew.feeds import DEFAULT_FEEDS, feed

MATCH = "demo"

server = FastMCP(
    "Gantry",
    instructions=("Live match intelligence for a synthetic football match, Kingsmere FC v Ashvale Athletic, from "
                  "Gantry's AI production crew. Every tool takes the match minute to look from (for example 30, or "
                  "'45+2' or '90+3' for added time); nothing after that minute is revealed. Numbers come from the "
                  "tracking data, never from a model."),
)

_desk: StatsDesk | None = None


def desk() -> StatsDesk:
    global _desk
    if _desk is None:
        from .server import load

        loaded = load(MATCH)
        _desk = StatsDesk(loaded.stats, loaded.events)
    return _desk


def tick_at(minute: str | float | None) -> int:
    """The tick for a match minute such as 30, 74.5, '45+2' or '90+3'. None means full-time."""
    d = desk()
    frames = d.match.frames
    n = len(frames)
    if minute is None or str(minute).strip() == "":
        return n - 1
    text = str(minute).replace("'", "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\+(\d+(?:\.\d+)?))?", text)
    if not m:
        return n - 1
    base, extra = float(m.group(1)), float(m.group(2) or 0)
    period = 1 if base <= 45 else 2          # '45+2' is first-half added time, '90+3' second-half
    clock = (base + extra) * 60
    p = d.match.meta["periods"][period - 1]
    for t in range(p["start_tick"], p["end_tick"]):
        if frames[t, 1] >= clock:
            return t
    return p["end_tick"] - 1


@server.tool()
def match_state(minute: str | None = None) -> dict:
    """The score, the minute and both teams' numbers (possession, shots, xG, pass accuracy, final-third passes, PPDA, corners, distance) at a match minute."""
    d = desk()
    t = tick_at(minute)
    c = d.stats.control(t)
    return {"minute": d.minute(t), "score": d.score_text(t), "teams": d.team_facts(d.stats.team_stats(t)),
            "last_10_minutes": d.team_facts(d.stats.team_stats(t, since=max(0, t - 6000))),
            "control_or_chaos": {"chaos_0_to_1": c["chaos"], "turnovers_per_minute": c["turnovers_per_min"],
                                 "passes_per_minute": c["tempo_passes_per_min"]}}


@server.tool()
def key_moments(up_to_minute: str | None = None) -> list:
    """Goals, big chances, bookings and substitutions up to a match minute, with the minute and what happened."""
    d = desk()
    t = tick_at(up_to_minute)
    return [{"minute": m.facts.get("minute") or d.minute(m.tick), "kind": m.kind, "what": m.summary}
            for m in d.scan(-1, t) if m.kind in ("goal", "big_chance", "card", "substitution")]


@server.tool()
def player_stats(name: str, minute: str | None = None) -> dict:
    """One player's numbers at a match minute: team, position, distance, top speed, sprints, passes, shots, goals, assists, tackles."""
    d = desk()
    pid = d.player_id(name)
    if pid is None:
        return {"error": f"No player called {name}. The squads are on the team sheet: try a surname."}
    return d.player_profile(pid, tick_at(minute))


@server.tool()
def storylines(minute: str | None = None) -> list:
    """The threads of the match at a minute: keepers' saves, shooters without a goal, substitutes, pressing, territory, the defensive line, the fastest sprint."""
    return [s["text"] for s in desk().storylines.at(tick_at(minute))]


@server.tool()
def what_the_crew_said(feed_id: str = "analyst_en", from_minute: str | None = "0", to_minute: str | None = None) -> list:
    """What one broadcast said on air between two minutes. Feeds: casual_en (new fan), analyst_en, home_en (following No. 10), audio_en (audio described)."""
    from .server import produced_cues

    if feed(feed_id) is None:
        return [{"error": f"No feed called {feed_id}"}]
    a, b = tick_at(from_minute), tick_at(to_minute)
    d = desk()
    lines = [c for c in produced_cues(MATCH, list(DEFAULT_FEEDS)) if c["feed"] == feed_id and c["kind"] == "line"]
    return [{"minute": d.minute(c["tick"]), "said": c["text"]} for c in lines if a <= c["tick"] <= b][:80]


class _Viewer:
    """Just enough of a viewer's session for the producer to answer at a given minute."""

    def __init__(self, crew, loaded, feed_id: str, tick: int):
        from .crew.booth import Booth

        self.crew = crew
        self.loaded = loaded
        self.desk = desk()
        f = feed(feed_id)
        self.booth = Booth({feed_id: f}, self.desk, crew.voices)
        self.booth.viewer_tick = tick


ASKING = asyncio.Semaphore(2)


@server.tool()
async def ask_the_crew(question: str, minute: str | None = None, feed_id: str = "analyst_en") -> str:
    """Ask Gantry's production crew a question about the match, as of a minute. The producer agent looks it up with the stats desk's tools and answers in that feed's voice."""
    from .crew.ask import Answer, producer
    from .crew.roles import MODEL_TIMEOUT, opts
    from .server import crew, load

    if os.environ.get("GANTRY_PUBLIC") == "1" and ASKING.locked():
        return "The crew is busy with other questions. Try again in a moment."
    f = feed(feed_id) or feed("analyst_en")
    async with ASKING:
        viewer = _Viewer(crew(), load(MATCH), f.id, tick_at(minute))
        agent = producer(viewer)
        d = viewer.desk
        t = viewer.booth.viewer_tick
        prompt = (f"Feed: {f.name}. Audience: {f.audience}\nAnswer in {f.lang.name}.\n"
                  f"Match minute now: {d.minute(t)}, score {d.score_text(t)}.\nThe question: {question}")
        try:
            r = await asyncio.wait_for(agent.run(prompt, options={"response_format": Answer, **opts(viewer.crew.models["producer"], "low")}),
                                       MODEL_TIMEOUT * 3)
            return r.value.answer
        except Exception:
            return "The crew couldn't answer that just now."


def mcp_app():
    """The MCP endpoint as an ASGI app, to mount at /mcp."""
    hosts = [h.strip() for h in os.environ.get("GANTRY_HOSTS", "").split(",") if h.strip()]
    server.settings.streamable_http_path = "/"
    server.settings.stateless_http = True
    server.settings.json_response = True
    server.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(hosts), allowed_hosts=hosts, allowed_origins=[f"https://{h}" for h in hosts])
    return server.streamable_http_app()
