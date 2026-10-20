"""Produce a whole match ahead of time, the way the crew would live, and keep it.

    uv run python -m gantry.crew.produce --id demo --speed 4

Viewers of a produced match get the full broadcast instantly and at no extra
model cost; their questions are still answered live.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from .crew import Crew, CrewSession
from .feeds import FEEDS


async def main(match_id: str, speed: float, start: int, end: int | None):
    from ..server import load

    loaded = load(match_id)
    total = len(loaded.frames)
    end = min(end or total, total)
    crew = Crew()
    lines = 0

    async def send(msg):
        nonlocal lines
        if msg["type"] == "cues":
            lines += sum(1 for c in msg["cues"] if c["kind"] == "line")

    session = CrewSession(crew, loaded, list(FEEDS), send, lead=600)
    session.seek(start)
    clock = {"t": float(start)}
    began = time.time()
    tasks = [asyncio.create_task(session.watch(lambda: clock["t"])), asyncio.create_task(session.work(lanes=4))]
    last_print = 0.0
    while clock["t"] < end:
        await asyncio.sleep(0.25)
        clock["t"] = min(end, start + (time.time() - began) * 10 * speed)
        if time.time() - last_print > 30:
            last_print = time.time()
            m = int(loaded.frames[min(int(clock['t']), total - 1), 1] // 60)
            print(f"  minute {m}: {lines} lines produced, {len(session.production.items)} moments kept", flush=True)
    # let the last moments and the full-time package finish
    for _ in range(120):
        await asyncio.sleep(1)
        if session.queue.empty():
            break
    await asyncio.sleep(25)
    for t in tasks:
        t.cancel()
    print(f"done: {lines} lines, {len(session.production.items)} moments kept in {session.production.dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="demo")
    ap.add_argument("--speed", type=float, default=4.0)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    a = ap.parse_args()
    asyncio.run(main(a.id, a.speed, a.start, a.end))
