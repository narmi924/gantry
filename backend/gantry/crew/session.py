"""One viewer's broadcast: the gallery that runs the crew a few seconds ahead of the picture."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict

from opentelemetry import trace

from ..common import HZ
from .booth import Booth
from .cache import Production, collect_audio
from .crew import DELAY_TICKS, Crew
from .desk import StatsDesk
from .feeds import feed, friendly
from .messages import Cut, EditorBrief
from ..guard import guard
from .roles import EDITORIAL_KINDS, HOLDS, covers

log = logging.getLogger("gantry.crew")
tracer = trace.get_tracer("gantry")
MOMENT_TIMEOUT = 45.0

STAGES = {
    "goal": ("call", "analysis"), "big_chance": ("call", "analysis"), "shot": ("call",),
    "half_time": ("call",), "full_time": ("call",), "corner": ("call",), "corner_kick": ("call",), "sprint": ("call",),
    "substitution": ("editorial",), "card": ("editorial",), "kickoff": ("editorial",), "press": ("editorial",),
    "spell": ("editorial",), "play": ("filler",), "open": ("editorial",),
}


class CrewSession:
    """Runs the crew for one viewer's broadcast, a few seconds ahead of the picture."""

    def __init__(self, crew: Crew, loaded, feed_ids, send, lead: int = DELAY_TICKS):
        self.crew = crew
        self.loaded = loaded
        self.send = send
        self.lead = lead
        self.feeds = {f: friendly(feed(f), loaded.meta) for f in dict.fromkeys(feed_ids) if feed(f) is not None}
        self.desk = StatsDesk(loaded.stats, loaded.events)
        self.booth = Booth(self.feeds, self.desk, crew.voices)
        self._agents = None                     # made the first time the crew has live work
        self.big: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.rest: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.pending: dict[str, int] = {}       # moments queued or being produced, by id
        self.scanned = 0
        self.generation = 0
        self.seq = 0
        self.talk_sent = 0
        self.producer = None
        self.asking = False
        self.last_question = -1e9
        self.tasks: set[asyncio.Task] = set()
        self.live = crew.ready                  # may the crew make what isn't produced yet?
        self.in_order = False                   # producing ahead of time: take moments in match order
        # productions are shared only between sessions carrying the same set of feeds
        self.production = Production.of(f"{loaded.match.id}-{'+'.join(sorted(self.feeds))}")

    # ------------------------------------------------------------ housekeeping

    @property
    def agents(self) -> dict:
        if self._agents is None:
            self._agents = self.crew.agents(self.booth, self.loaded.meta)
        return self._agents

    def spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)
        return t

    def close(self):
        for t in list(self.tasks):
            t.cancel()

    def seek(self, tick: int):
        """A jump in the match: a fresh booth, so work still in flight for the old position can't touch the new one."""
        self.generation += 1
        self.scanned = tick
        self.booth = Booth(self.feeds, self.desk, self.crew.voices)
        self.booth.viewer_tick = tick
        self._agents = None
        self.producer = None
        self.talk_sent = 0
        self.pending.clear()
        for q in (self.big, self.rest):
            while not q.empty():
                q.get_nowait()

    # ------------------------------------------------------------ watching ahead

    async def watch(self, head):
        """Scans the match ahead of the viewer, keeps the air clear for big moments and queues every moment."""
        total = len(self.loaded.frames)
        while True:
            await asyncio.sleep(0.1)
            viewer = int(head())
            self.booth.viewer_tick = viewer
            live = min(viewer + self.lead, total - 1)
            if live <= self.scanned:
                continue
            try:
                for m in self.desk.scan(self.scanned, live):
                    if m.kind in HOLDS:
                        before, after = HOLDS[m.kind]
                        self.booth.hold(m.id, m.tick - before, m.tick + after)
                    elif m.kind in EDITORIAL_KINDS:
                        on = tuple(f for f, fd in self.feeds.items() if covers(fd, m))
                        if on:
                            self.booth.hold(m.id, m.tick - 10, m.tick + 140, soft=True, feeds=on)
                    self.seq += 1
                    self.pending[m.id] = m.tick
                    q = self.big if m.priority >= 4 else self.rest
                    # live, the biggest moment goes first; ahead of time, the earliest, so the clock never waits
                    rank = (m.tick, 0) if self.in_order and q is self.rest else (-m.priority, m.tick)
                    await q.put((*rank, self.seq, m))
            except Exception:  # a bad moment must never stop the match reaching the viewer
                log.exception("scan failed at %s", live)
                self.booth.note(live, "Gallery", "stats desk skipped a stretch", source="rules")
            self.scanned = live

    async def work(self, lanes: int = 3):
        """One lane is kept for big moments; the others take everything else, the most important first."""
        await asyncio.gather(self._lane(self.big), *(self._lane(self.rest) for _ in range(lanes)))

    # ------------------------------------------------------------ producing a moment

    async def _lane(self, queue: asyncio.PriorityQueue):
        while True:
            *_, m = await queue.get()
            gen, booth = self.generation, self.booth
            try:
                # skip what the viewer has already seen, and small things when playback is fast
                if m.tick < booth.viewer_tick - 20 and m.priority < 5:
                    continue
                if booth.speed > 1.5 and m.priority < 3 or booth.speed > 3 and m.priority < 4:
                    continue
                if m.kind in ("half_time", "full_time"):
                    self.spawn(self._edit(m, gen))
                if await self.replay_production(m.id, gen):
                    continue
                if not self.live or not guard.may_produce():
                    continue
                await self.crew.warm_up()
                await self._produce(m, gen, booth)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("moment %s failed", m.id)
            finally:
                self.pending.pop(m.id, None)
                booth.release(m.id)
                await self.flush_talk()

    async def _produce(self, m, gen: int, booth: Booth):
        started = time.perf_counter()
        produced: list[dict] = []
        agents = self.agents

        async def run(stage: str):
            workflow = self.crew.workflow(booth, agents)
            async for event in workflow.run(Cut(m, stage), stream=True):
                if event.type == "output":
                    cue = asdict(event.data)
                    produced.append(cue)
                    if gen == self.generation:
                        await self.send({"type": "cues", "cues": [cue]})

        failed = False
        stages = STAGES.get(m.kind, ("filler",))
        with tracer.start_as_current_span(f"moment {m.kind}", attributes={
                "gantry.moment": m.id, "gantry.kind": m.kind, "gantry.minute": m.facts.get("minute", ""),
                "gantry.stages": ",".join(stages), "gantry.feeds": ",".join(booth.feeds)}) as span:
            try:
                # no single moment may hold a lane for long, whatever gets stuck inside it
                async with asyncio.timeout(MOMENT_TIMEOUT):
                    results = await asyncio.gather(*(run(s) for s in stages), return_exceptions=True)
                for r in results:
                    if isinstance(r, Exception):
                        failed = True
                        log.warning("moment %s: %s", m.id, r)
            except TimeoutError:
                failed = True
            span.set_attribute("gantry.cues", len(produced))
            span.set_attribute("gantry.lines", sum(1 for c in produced if c["kind"] == "line"))
            span.set_attribute("gantry.complete", not failed)
        booth.note(m.tick, "Gallery", f"{m.kind.replace('_', ' ')} produced in {time.perf_counter() - started:.1f}s", source="rules")
        if failed:
            booth.note(m.tick, "Gallery", f"{m.kind.replace('_', ' ')}: part of the crew missed it; the show went on", source="rules")
        if gen == self.generation and not failed:
            self.keep(m.id, m.tick, produced)

    def keep(self, key: str, tick: int, cues: list[dict]):
        """Store what the crew made for this moment, so the next viewer gets the same production."""
        talk = [n for n in self.booth.talk if n["tick"] == tick and n["who"] != "Gallery"]
        self.production.put(key, cues, talk, collect_audio(cues, self.booth.voices))

    async def replay_production(self, key: str, gen: int) -> bool:
        """Send an earlier production of this moment, if there is one."""
        hit = self.production.get(key)
        if hit is None:
            return False
        booth = self.booth
        for n in hit["talk"]:
            booth.talk.append(n)
            booth.notes += 1
        for c in hit["cues"]:
            if c["kind"] == "line" and c["feed"] in booth.feeds:
                booth.book(c["feed"], c["tick"], c.get("seconds") or 3.0, c["moment"])
                if c.get("text"):
                    booth.said[c["feed"]].append(c["text"])
        if gen == self.generation and hit["cues"]:
            await self.send({"type": "cues", "cues": hit["cues"]})
        return True

    async def _edit(self, m, gen: int):
        key = f"{m.id}-edit"
        try:
            if await self.replay_production(key, gen):
                return
            if not self.live:
                return
            await self.crew.warm_up()
            booth = self.booth
            booth.note(m.tick, "Stats desk", m.summary, to="Editor", source="rules")
            workflow = self.crew.editor_workflow(booth, self.agents, len(self.loaded.frames))
            produced: list[dict] = []
            async for event in workflow.run(EditorBrief(m), stream=True):
                if event.type == "output":
                    cue = asdict(event.data)
                    produced.append(cue)
                    if gen == self.generation:
                        await self.send({"type": "cues", "cues": [cue]})
            if produced and gen == self.generation:
                talk = [n for n in booth.talk if n["tick"] == m.tick and n["who"] in ("Editor", "Stats desk")]
                self.production.put(key, produced, talk, collect_audio(produced, booth.voices))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("editor failed for %s", m.id)
            self.booth.note(m.tick, "Gallery", "the editor missed this package", source="rules")
        await self.flush_talk()

    async def flush_talk(self):
        new = min(self.booth.notes - self.talk_sent, len(self.booth.talk))
        self.talk_sent = self.booth.notes
        if new > 0:
            await self.send({"type": "talkback", "items": list(self.booth.talk)[-new:]})


__all__ = ["CrewSession", "DELAY_TICKS", "HZ"]
