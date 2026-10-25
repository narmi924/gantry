"""Gantry backend: streams a synthetic match live over WebSocket, with the AI crew's broadcast on top.

The match clock lives on the server. Each viewer connection gets frames and
events as the clock reaches them, at the playback speed the viewer picks, and
the cues the crew produces for the feeds the viewer asked for.

    uv run uvicorn gantry.server:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

from .crew.ask import ask
from .crew.cache import CACHE_DIR, Production, audio_from_disk
from .crew.crew import DELAY_TICKS, Crew
from .crew.feeds import DEFAULT_FEEDS, LANGUAGES, feed, friendly, native_names
from .crew.session import CrewSession
from .guard import PUBLIC, guard
from .mcp_server import mcp_app
from .mcp_server import server as mcp_server
from .sim.store import StoredMatch, available
from .stats.match_stats import MatchStats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gantry")
for noisy in ("agent_framework", "httpx", "httpx2", "azure"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
DEV = os.environ.get("GANTRY_DEV") == "1"

# match intelligence for any AI assistant, over MCP
_mcp = mcp_app()


@asynccontextmanager
async def lifespan(_app):
    if not crew().ready:
        log.warning("AZURE_AI_PROJECT_ENDPOINT is not set: playing the produced broadcast only, no live crew")
    await crew().trace()
    async with mcp_server.session_manager.run():
        yield


app = FastAPI(title="Gantry", docs_url="/docs" if DEV else None, redoc_url=None, openapi_url="/openapi.json" if DEV else None,
              lifespan=lifespan)
app.mount("/mcp", _mcp)

SEND_INTERVAL = 0.1     # seconds of wall time between messages
KEY_EVENTS = {"goal", "yellow_card", "substitution", "half_time", "full_time", "period_start"}
STATS_EVERY = 10        # ticks between stats updates: once per match second
MAX_CLIP = 600          # the longest stretch a viewer can ask for again, in ticks


class LoadedMatch:
    """A stored match plus everything the stats desk derives from it."""

    def __init__(self, match_id: str):
        self.match = StoredMatch(match_id)
        self.stats = MatchStats(self.match)
        self.meta = self.match.meta
        self.frames = self.match.frames
        merged = self.match.events + self.stats.sprint_events()
        self.events = sorted(merged, key=lambda e: e["tick"])

    def lineup_at(self, tick: int):
        return self.match.lineup_at(tick)

    def score_at(self, tick: int):
        return self.match.score_at(tick)

    @lru_cache(maxsize=4096)
    def snapshot(self, tick: int) -> dict:
        """The numbers on screen at a tick; the same for every viewer, so worked out once."""
        return self.stats.snapshot(tick)


@lru_cache(maxsize=4)
def load(match_id: str) -> LoadedMatch:
    if match_id not in available():
        raise KeyError(match_id)
    return LoadedMatch(match_id)


def encode_frames(match: LoadedMatch, start: int, end: int) -> list[list[float]]:
    """Frames [start, end) as compact rows: tick first, then the stored columns."""
    rows = np.round(match.frames[start:end].astype(np.float64), 2)
    ticks = np.arange(start, end, dtype=np.float64)[:, None]
    return np.hstack([ticks, rows]).tolist()


def events_between(match: LoadedMatch, start: int, end: int) -> list[dict]:
    return [e for e in match.events if start <= e["tick"] < end]


def chapters(match: LoadedMatch) -> list[dict]:
    """The moments a first-time viewer will want to jump to: kick-off, every goal, the half-time show, full-time."""
    from .common import minute_label

    goals = [e for e in match.events if e["type"] == "goal"]
    final = match.meta["score"]
    out = [{"label": "Kick-off", "tick": 0, "kind": "kickoff"}]
    for i, e in enumerate(goals):
        s, team = e["score"], e["team"]
        if i == 0:
            word = "Opener"
        elif s[0] == s[1]:
            word = "Equaliser"
        elif i == len(goals) - 1 and final[team] > final[1 - team] and s[team] - s[1 - team] == 1:
            word = "Winner"
        else:
            word = "Goal"
        out.append({"label": f"{minute_label(e['clock'], e['period'])} {word}", "tick": max(0, e["tick"] - 150),
                    "kind": "goal", "team": team})
    for e in match.events:
        if e["type"] == "half_time":
            out.append({"label": "Half-time show", "tick": max(0, e["tick"] - 40), "kind": "half_time"})
        elif e["type"] == "full_time":
            out.append({"label": "Full-time", "tick": max(0, e["tick"] - 60), "kind": "full_time"})
    return sorted(out, key=lambda c: c["tick"])


def feed_info(feed_id: str, meta: dict) -> dict:
    f = friendly(feed(feed_id), meta)
    return {"id": f.id, "name": f.name, "audience": f.aud.id, "label": f.aud.name, "language": f.lang.code,
            "language_name": f.lang.name, "locale": f.lang.locale, "rtl": f.lang.rtl, "follow": f.follow,
            "club": f.side, "metric": f.metric, "custom": f.custom}


@app.get("/healthz")
def healthz():
    """For the platform's probes: the match loads and its production is there."""
    produced = bool(Production.of(f"demo-{'+'.join(sorted(DEFAULT_FEEDS))}").items)
    return {"ok": True, "produced": produced, "live_crew": bool(_crew and _crew.ready)}


@app.get("/api/matches")
def list_matches():
    return [{"id": m, "score": load(m).meta["score"]} for m in available()]


@app.get("/api/matches/{match_id}")
def match_meta(match_id: str):
    try:
        return load(match_id).meta
    except KeyError:
        raise HTTPException(404, f"No match called {match_id}")


@app.get("/api/languages")
def languages():
    return [{"code": lang.code, "name": lang.name, "locale": lang.locale, "rtl": lang.rtl} for lang in LANGUAGES.values()]


@app.get("/api/matches/{match_id}/stats")
def match_stats(match_id: str, tick: int):
    try:
        m = load(match_id)
    except KeyError:
        raise HTTPException(404, f"No match called {match_id}")
    tick = int(np.clip(tick, 0, len(m.frames) - 1))
    return m.snapshot(tick) | {"players": m.stats.players(tick)}


def produced_cues(match_id: str, feeds: list[str]) -> list[dict]:
    """Every produced cue for these feeds, from whichever production made each feed (the default broadcast, or a
    viewer's own feed produced on its own)."""
    wanted, cues, seen = set(feeds), [], set()
    if CACHE_DIR.exists():
        for d in sorted(CACHE_DIR.iterdir()):
            if not d.is_dir() or not d.name.startswith(f"{match_id}-"):
                continue
            if not wanted & set(d.name[len(match_id) + 1:].split("+")):
                continue
            for item in Production.of(d.name).items.values():
                for c in item["cues"]:
                    if c.get("feed") in wanted and c["id"] not in seen:
                        seen.add(c["id"])
                        cues.append(c)
    return sorted(cues, key=lambda c: (c["tick"], c["feed"], c["kind"]))


@app.get("/api/matches/{match_id}/rundown")
def rundown(match_id: str, feeds: str | None = None):
    """The crew's rundown for a produced match: every timed cue (line, graphic, replay, highlights), machine-readable,
    for a graphics or playout system to render in sync with the match. Ticks are tenths of a second of match video."""
    try:
        load(match_id)
    except KeyError:
        raise HTTPException(404, f"No match called {match_id}")
    wanted = [f for f in (feeds.split(",") if feeds else DEFAULT_FEEDS) if feed(f) is not None]
    return {"match": match_id, "hz": 10, "feeds": wanted, "cues": produced_cues(match_id, wanted)}


def vtt_time(tick: float) -> str:
    ms = int(round(tick * 100))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d}.{ms:03d}"


@app.get("/api/matches/{match_id}/captions/{feed_id}.vtt")
def captions(match_id: str, feed_id: str):
    """One feed's commentary as WebVTT captions, timed to the match video."""
    if feed(feed_id) is None:
        raise HTTPException(404, f"No feed called {feed_id}")
    lines = [c for c in produced_cues(match_id, [feed_id]) if c["kind"] == "line"]
    out = ["WEBVTT", ""]
    for i, c in enumerate(lines, 1):
        start = c["tick"]
        end = start + int((c.get("seconds") or 3) * 10)
        out += [str(i), f"{vtt_time(start)} --> {vtt_time(end)}", c["text"], ""]
    return Response("\n".join(out), media_type="text/vtt; charset=utf-8")


@app.get("/api/audio/{audio_id}")
def audio(audio_id: str):
    data = _crew.voices.audio.get(audio_id) if _crew else None
    if data is None:
        data = audio_from_disk(audio_id)
    if data is None:
        raise HTTPException(404, "No such line")
    return Response(content=data, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/speech-token")
async def speech_token(ticket: str | None = None):
    """A ten-minute Speech token so the browser can listen to a viewer's spoken question.

    The server signs in with Microsoft Entra ID and exchanges that for a short Speech token, so no key
    and no longer-lived credential ever reaches the browser."""
    import aiohttp

    from .ai.azure import setting

    if not guard.use_ticket(ticket):
        raise HTTPException(429, "Ask again in a few seconds")
    aad = await crew().credential.get_token("https://cognitiveservices.azure.com/.default")
    url = setting("AZURE_AI_ENDPOINT").rstrip("/") + "/sts/v1.0/issueToken"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as http:
        async with http.post(url, headers={"Authorization": f"Bearer {aad.token}", "Content-Length": "0"}) as r:
            if r.status != 200:
                raise HTTPException(502, "Speech token unavailable")
            token = await r.text()
    return {"token": token, "region": setting("AZURE_SPEECH_REGION")}


_crew: Crew | None = None


def crew() -> Crew:
    global _crew
    if _crew is None:
        _crew = Crew()
    return _crew


def number(value, default: float) -> float:
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def client_ip(ws: WebSocket) -> str:
    forwarded = ws.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (ws.client.host if ws.client else "?")


ORIGINS = {o.strip() for o in os.environ.get("GANTRY_ORIGINS", "").split(",") if o.strip()}


@app.websocket("/ws/matches/{match_id}")
async def stream(ws: WebSocket, match_id: str):
    origin = ws.headers.get("origin", "")
    if PUBLIC and ORIGINS and origin not in ORIGINS:
        await ws.close(code=4403)
        return
    ip = client_ip(ws)
    if not guard.connect(ip):
        await ws.close(code=4429)
        return
    try:
        await _stream(ws, match_id, ip)
    finally:
        guard.disconnect(ip)


async def _stream(ws: WebSocket, match_id: str, ip: str):
    await ws.accept()
    try:
        match = load(match_id)
    except KeyError:
        await ws.close(code=4404)
        return

    total = len(match.frames)
    # a reconnect, or a feed added mid-match, opens where the viewer is rather than at kick-off
    start = int(np.clip(number(ws.query_params.get("from"), 0), 0, total - 1))
    # film: when a recording drives the page frame by frame, the clock never runs more than 4 s ahead of its picture
    state = {"head": float(start), "speed": 1.0, "playing": True, "sent": start, "film": None}
    lock = asyncio.Lock()

    async def send(msg: dict):
        async with lock:
            # once the viewer has gone, whatever the crew still had to say goes nowhere
            if ws.client_state != WebSocketState.CONNECTED or ws.application_state != WebSocketState.CONNECTED:
                return
            await ws.send_text(json.dumps(msg, ensure_ascii=False))

    asked = [f for f in (ws.query_params.get("feeds") or "").split(",") if f]
    feeds = [f for f in dict.fromkeys(asked) if feed(f) is not None][:6]
    # the standard feeds share one crew (and one production); a viewer's own feed gets a crew of its own
    standard = [f for f in feeds if not feed(f).custom]
    own = [f for f in feeds if feed(f).custom]
    sessions: list[CrewSession] = []
    live_count = 0
    for group in (standard, own):
        if not group:
            continue
        s = CrewSession(crew(), match, group, send)
        if not s.crew.ready or (PUBLIC and sorted(s.feeds) == sorted(DEFAULT_FEEDS) and s.production.items):
            s.live = False          # the default broadcast plays from its production (or no models are set up)
        else:
            s.live = guard.start_live()
            live_count += s.live
        if start:
            s.seek(start)
        sessions.append(s)
    ticket = guard.ticket()

    def owner(feed_id: str) -> CrewSession | None:
        return next((s for s in sessions if feed_id in s.feeds), None)

    async def send_state(tick: int):
        past = [e for e in match.events if e["tick"] <= tick]
        await send({
            "type": "state",
            "tick": tick,
            "score": match.score_at(tick),
            "lineup": match.lineup_at(tick),
            "events": [e for e in past if e["type"] in KEY_EVENTS] + past[-20:],
            "stats": match.snapshot(tick),
        })

    # names written in another script, for the feeds whose language needs them
    langs = {feed(f).lang.code for f in feeds}
    names = {c: native_names()[c] for c in langs if LANGUAGES[c].native_names and c in native_names()}
    await send({"type": "hello", "meta": match.meta, "feeds": [feed_info(f, match.meta) for f in feeds], "names": names,
                "chapters": chapters(match), "delay_ticks": DELAY_TICKS, "ticket": ticket,
                "live": {f: owner(f).live for f in feeds}})
    await send_state(start)

    async def receive():
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            kind = msg.get("type")
            if kind == "control":
                if "speed" in msg:
                    state["speed"] = float(np.clip(number(msg["speed"], state["speed"]), 0.25, 32))
                    for s in sessions:
                        s.booth.speed = state["speed"]
                if "playing" in msg:
                    state["playing"] = bool(msg["playing"])
            elif kind == "ask" and owner(str(msg.get("feed", ""))):
                question = str(msg.get("question", "")).strip()[:300]
                s = owner(str(msg.get("feed", "")))
                if question and guard.may_ask(ip):
                    s.spawn(ask(s, str(msg.get("feed", "")), question))
                elif question:
                    await send({"type": "answer", "feed": str(msg.get("feed", "")), "question": question,
                                "answer": "That's a lot of questions. Ask again in a few minutes."})
            elif kind == "clip":
                # a stretch of the match the viewer has already seen, for a replay
                head = int(state["head"])
                a = int(np.clip(number(msg.get("from"), 0), 0, max(head - 1, 0)))
                b = int(np.clip(number(msg.get("to"), 0), a + 1, min(head + 1, a + MAX_CLIP, total)))
                await send({"type": "clip", "frames": encode_frames(match, a, b)})
            elif kind == "film":
                state["film"] = number(msg.get("tick"), 0)
            elif kind == "seek":
                tick = int(np.clip(number(msg.get("tick"), 0), 0, total - 1))
                state["head"] = float(tick)
                state["sent"] = tick
                for s in sessions:
                    s.seek(tick)
                await send_state(tick)

    async def pump():
        while True:
            await asyncio.sleep(SEND_INTERVAL)
            if state["playing"]:
                state["head"] = min(state["head"] + state["speed"] * SEND_INTERVAL * 10, total)
            if state["film"] is not None:
                state["head"] = min(state["head"], state["film"] + 40)
            end = min(int(state["head"]) + 1, total)
            start = state["sent"]
            if end <= start:
                continue
            # claimed before sending, so a seek that arrives meanwhile isn't overwritten
            state["sent"] = end
            stats = [match.snapshot(t) for t in range(start - start % STATS_EVERY, end, STATS_EVERY) if t >= start]
            await send({
                "type": "frames",
                "frames": encode_frames(match, start, end),
                "events": events_between(match, start, end),
                "stats": stats,
                "speed": state["speed"],
                "playing": state["playing"],
            })

    async def crew_work(session: CrewSession):
        """The crew is not allowed to take the picture down with it: if it fails, the match keeps streaming."""
        try:
            await asyncio.gather(session.watch(lambda: state["head"]), session.work())
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("crew stopped for this viewer")

    tasks = [asyncio.create_task(receive()), asyncio.create_task(pump())]
    for s in sessions:
        tasks.append(asyncio.create_task(crew_work(s)))
    try:
        done, _ = await asyncio.wait(tasks[:2], return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            t.result()
    except WebSocketDisconnect:
        pass
    except RuntimeError as e:
        log.info("viewer connection ended: %s", e)
    except Exception:
        log.exception("viewer connection failed")
    finally:
        for t in tasks:
            t.cancel()
        for s in sessions:
            s.close()
        for _ in range(live_count):
            guard.end_live()
        guard.drop_ticket(ticket)


# In production the same server hands out the built frontend, so the page, its API and the
# live WebSocket share one origin.
STATIC_DIR = Path(os.environ.get("GANTRY_STATIC", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="site")


__all__ = ["app", "load", "DEFAULT_FEEDS"]
