"""Produce a whole match ahead of time, exactly as the crew would cover it live, and keep it.

    uv run python -m gantry.crew.produce --id demo

The viewer's clock in this run never gets closer than 13 seconds to a moment the
crew is still working on, so every moment gets the same head start it has live,
however long the models take. Viewers of a produced match get the full broadcast
instantly and at no extra model cost; their questions are still answered live.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time

from .crew import DELAY_TICKS, Crew
from .feeds import DEFAULT_FEEDS
from .session import CrewSession

SLACK = 20          # ticks: how much of the 15-second head start the clock may eat into

for noisy in ("agent_framework", "httpx", "httpx2", "azure"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


async def main(match_id: str, feeds: list[str], speed: float, start: int, end: int | None, lanes: int):
    from ..server import load

    loaded = load(match_id)
    total = len(loaded.frames)
    end = min(end or total, total)
    crew = Crew()
    await crew.trace()
    lines = 0

    async def send(msg):
        nonlocal lines
        if msg["type"] == "cues":
            lines += sum(1 for c in msg["cues"] if c["kind"] == "line")

    # the crew looks 45 seconds ahead so several moments are worked on at once; the clock still never comes
    # within 13 seconds of a moment that isn't finished, so every call lands as it would live
    session = CrewSession(crew, loaded, feeds, send, lead=450)
    session.in_order = True
    session.seek(start)
    clock = {"t": float(start)}
    began = time.time()
    tasks = [asyncio.create_task(session.watch(lambda: clock["t"])), asyncio.create_task(session.work(lanes=lanes))]
    last_print = 0.0
    while clock["t"] < end or session.pending:
        await asyncio.sleep(0.1)
        target = min(end, clock["t"] + speed)
        if session.pending:
            target = min(target, min(session.pending.values()) - (DELAY_TICKS - SLACK))
        clock["t"] = max(clock["t"], target)
        if time.time() - last_print > 30:
            last_print = time.time()
            m = int(loaded.frames[min(int(clock["t"]), total - 1), 1] // 60)
            print(f"  minute {m}: {lines} lines, {len(session.production.items)} moments kept, "
                  f"{len(session.pending)} in hand, {time.time() - began:.0f}s", flush=True)
        if clock["t"] >= end and not session.pending:
            break
    # the half-time and full-time packages run on their own
    for _ in range(240):
        if not session.tasks:
            break
        await asyncio.sleep(0.5)
    for t in tasks:
        t.cancel()
    try:  # send the last traces before the process ends
        from opentelemetry import trace
        trace.get_tracer_provider().force_flush()
    except Exception:
        pass
    await crew.credential.close()
    print(f"done: {lines} lines, {len(session.production.items)} moments kept in {session.production.dir} "
          f"({time.time() - began:.0f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="demo")
    ap.add_argument("--feeds", default=",".join(DEFAULT_FEEDS))
    ap.add_argument("--speed", type=float, default=8.0, help="ticks per 0.1 s of wall time while nothing is in hand")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    ap.add_argument("--lanes", type=int, default=6)
    a = ap.parse_args()
    asyncio.run(main(a.id, a.feeds.split(","), a.speed, a.start, a.end, a.lanes))
