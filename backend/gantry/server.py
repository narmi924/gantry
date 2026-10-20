"""Gantry backend: streams a synthetic match live over WebSocket.

The match clock lives on the server. Each viewer connection gets frames and
events as the clock reaches them, at the playback speed the viewer picks.

    uv run uvicorn gantry.server:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .crew.ask import ask
from .crew.cache import audio_from_disk
from .crew.crew import DELAY_TICKS, Crew, CrewSession

from .sim.store import StoredMatch, available
from .stats.match_stats import MatchStats

app = FastAPI(title="Gantry")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SEND_INTERVAL = 0.1     # seconds of wall time between messages
KEY_EVENTS = {"goal", "yellow_card", "substitution", "half_time", "full_time", "period_start"}
STATS_EVERY = 10        # ticks between stats updates: once per match second


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


@app.get("/api/matches")
def list_matches():
    return [{"id": m, "score": load(m).meta["score"]} for m in available()]


@app.get("/api/matches/{match_id}")
def match_meta(match_id: str):
    try:
        return load(match_id).meta
    except KeyError:
        raise HTTPException(404, f"No match called {match_id}")


@app.get("/api/matches/{match_id}/stats")
def match_stats(match_id: str, tick: int):
    try:
        m = load(match_id)
    except KeyError:
        raise HTTPException(404, f"No match called {match_id}")
    return m.stats.snapshot(tick) | {"players": m.stats.players(tick)}


@app.get("/api/audio/{audio_id}")
def audio(audio_id: str):
    data = crew().voices.audio.get(audio_id) if _crew else None
    if data is None:
        data = audio_from_disk(audio_id)
    if data is None:
        raise HTTPException(404, "No such line")
    return Response(content=data, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/speech-token")
async def speech_token():
    """A ten-minute, speech-only token so the browser can listen to a viewer's spoken question.

    The server signs in with Microsoft Entra ID and exchanges that for a short Speech token, so no key
    and no broader credential ever reaches the browser."""
    import aiohttp

    from .ai.azure import setting

    aad = await crew().credential.get_token("https://cognitiveservices.azure.com/.default")
    url = setting("AZURE_AI_ENDPOINT").rstrip("/") + "/sts/v1.0/issueToken"
    async with aiohttp.ClientSession() as http:
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


@app.websocket("/ws/matches/{match_id}")
async def stream(ws: WebSocket, match_id: str):
    await ws.accept()
    try:
        match = load(match_id)
    except KeyError:
        await ws.close(code=4404)
        return

    total = len(match.frames)
    state = {"head": 0.0, "speed": 1.0, "playing": True, "sent": 0}
    lock = asyncio.Lock()

    async def send(msg: dict):
        async with lock:
            await ws.send_text(json.dumps(msg, ensure_ascii=False))

    feeds = [f for f in (ws.query_params.get("feeds") or "").split(",") if f]
    session = CrewSession(crew(), match, feeds, send) if feeds else None

    async def send_state(tick: int):
        past = [e for e in match.events if e["tick"] <= tick]
        await send({
            "type": "state",
            "tick": tick,
            "score": match.score_at(tick),
            "lineup": match.lineup_at(tick),
            "events": [e for e in past if e["type"] in KEY_EVENTS] + past[-20:],
            "stats": match.stats.snapshot(tick),
        })

    await send({"type": "hello", "meta": match.meta, "feeds": feeds, "delay_ticks": DELAY_TICKS})
    await send_state(0)

    async def receive():
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("type") == "control":
                if "speed" in msg:
                    state["speed"] = float(np.clip(msg["speed"], 0.25, 32))
                    if session:
                        session.booth.speed = state["speed"]
                if "playing" in msg:
                    state["playing"] = bool(msg["playing"])
            elif msg.get("type") == "ask" and session:
                question = str(msg.get("question", "")).strip()[:300]
                if question:
                    asyncio.create_task(ask(session, str(msg.get("feed", "")), question))
            elif msg.get("type") == "clip":
                # a stretch of the match the viewer has already seen, for a replay
                a = int(np.clip(msg.get("from", 0), 0, total - 1))
                b = int(np.clip(msg.get("to", 0), a + 1, total))
                await send({"type": "clip", "frames": encode_frames(match, a, b)})
            elif msg.get("type") == "seek":
                tick = int(np.clip(msg.get("tick", 0), 0, total - 1))
                state["head"] = float(tick)
                state["sent"] = tick
                if session:
                    session.seek(tick)
                await send_state(tick)

    async def pump():
        while True:
            await asyncio.sleep(SEND_INTERVAL)
            if state["playing"]:
                state["head"] = min(state["head"] + state["speed"] * SEND_INTERVAL * 10, total)
            end = int(state["head"]) + 1
            start = state["sent"]
            if end > start:
                end = min(end, total)
                stats = []
                for t in range(start - start % STATS_EVERY, end, STATS_EVERY):
                    if t >= start:
                        stats.append(match.stats.snapshot(t))
                await send({
                    "type": "frames",
                    "frames": encode_frames(match, start, end),
                    "events": events_between(match, start, end),
                    "stats": stats,
                    "speed": state["speed"],
                    "playing": state["playing"],
                })
                state["sent"] = end

    tasks = [asyncio.create_task(receive()), asyncio.create_task(pump())]
    if session:
        tasks += [asyncio.create_task(session.watch(lambda: state["head"])), asyncio.create_task(session.work())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in done:
            t.result()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for t in tasks:
            t.cancel()


# In production the same server hands out the built frontend, so the page, its API and the
# live WebSocket share one origin.
STATIC_DIR = Path(os.environ.get("GANTRY_STATIC", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="site")
