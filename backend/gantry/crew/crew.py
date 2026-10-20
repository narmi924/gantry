"""The AI production crew, organised like a real broadcast team.

    stats desk  ->  director  ->  commentator(s)  ->  voice

Each role is an executor in a Microsoft Agent Framework workflow. The stats
desk, director and commentators are agents on Microsoft Foundry; the voice is
Azure AI Speech. They share one booth (what has been said, by whom, and when)
and hand work to each other as messages. Every number they use comes from
code (desk.py, match_stats.py).

The crew watches the match a few seconds ahead of the viewers, the way a TV
broadcast runs on a short delay, so lines and graphics land exactly on the
moment. If a model is slow or fails, the show goes on: the director falls back
to its own rules and the commentator to a prepared line.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Literal

from agent_framework import Agent, Executor, WorkflowBuilder, WorkflowContext, handler
from agent_framework.foundry import FoundryChatClient
from azure.identity.aio import DefaultAzureCredential
from pydantic import BaseModel

from ..ai.azure import setting
from .cache import Production, collect_audio
from .desk import Moment, StatsDesk
from .feeds import FEEDS, Feed
from .voice import Voices

HZ = 10
DELAY_TICKS = 150             # the broadcast runs 15 seconds behind the crew
MODEL_TIMEOUT = 7.0
MOMENT_TIMEOUT = 45.0


# ------------------------------------------------------------------ messages


@dataclass
class Briefing:
    """What the stats desk hands the director about a moment."""
    moment: Moment
    stage: Literal["reaction", "analysis", "filler"]
    insight: str | None = None


@dataclass
class EditorBrief:
    """Half-time or full-time: the stats desk hands the editor the moment to package."""
    moment: Moment


@dataclass
class LineRequest:
    """What the director asks one feed's commentator for."""
    feed: str
    briefing: Briefing
    angle: str
    excited: bool
    at: int                   # tick the line should go on air


@dataclass
class LineRequests:
    """The director's calls for one moment, one per feed that should speak."""
    requests: list[LineRequest]


@dataclass
class Lines:
    lines: list[Line]


@dataclass
class Line:
    feed: str
    text: str
    briefing: Briefing
    excited: bool
    at: int
    source: str               # "ai" or "prepared"


@dataclass
class Cue:
    """One entry in the rundown: what a feed shows or says, and when."""
    id: str
    feed: str
    tick: int
    kind: str                 # "line", "graphic", "replay" or "reel"
    moment: str
    text: str | None = None
    audio: str | None = None
    seconds: float | None = None
    excited: bool = False
    graphic: dict | None = None
    replay: dict | None = None
    reel: dict | None = None
    source: str = "ai"


class FeedPlan(BaseModel):
    feed: str
    speak: bool
    angle: str
    graphic: Literal["none", "stats", "momentum", "player", "pitch"]
    player: str | None = None
    replay: Literal["none", "behind_goal", "high", "follow", "reverse"] = "none"


class DirectorPlan(BaseModel):
    feeds: list[FeedPlan]
    talkback: str


REPLAY_KINDS = ("goal", "big_chance")
REPLAY_HINT = ("This moment gets a slow-motion replay on every feed. Pick each feed's replay angle: behind_goal "
               "(from behind the net, best for the finish), high (high and wide, shows the shape of the move), follow "
               "(stays with the scorer's run), reverse (from the opposite stand). Different feeds may take different "
               "angles; choose what that audience would most want to see.\n")
DEFAULT_REPLAY = {"casual_en": "behind_goal", "analyst_en": "high", "home_zh": "follow", "audio_en": "high"}


# ------------------------------------------------------------------ shared booth


@dataclass
class Booth:
    """The crew's shared state for one broadcast."""
    feeds: dict[str, Feed]
    desk: StatsDesk
    voices: Voices
    said: dict[str, deque] = field(default_factory=dict)
    last_line: dict[str, int] = field(default_factory=dict)
    busy_until: dict[str, int] = field(default_factory=dict)
    on_air_until: dict[str, int] = field(default_factory=dict)
    talk: deque = field(default_factory=lambda: deque(maxlen=400))
    kinds: dict = field(default_factory=dict)       # moment tick -> kind, so talkback can be grouped
    notes: int = 0
    viewer_tick: int = 0
    speed: float = 1.0

    def __post_init__(self):
        for f in self.feeds:
            self.said.setdefault(f, deque(maxlen=6))
            self.last_line.setdefault(f, -10**9)
            self.busy_until.setdefault(f, -10**9)
            self.on_air_until.setdefault(f, -10**9)

    def reset(self, tick: int):
        for f in self.feeds:
            self.said[f].clear()
            self.last_line[f] = -10**9
            self.busy_until[f] = -10**9
            self.on_air_until[f] = -10**9
        self.viewer_tick = tick

    def note(self, tick: int, who: str, text: str, to: str | None = None, feed: str | None = None, source: str = "ai"):
        self.talk.append({"tick": tick, "who": who, "to": to, "text": text, "feed": feed, "source": source,
                          "moment": self.kinds.get(tick)})
        self.notes += 1


# ------------------------------------------------------------------ prepared lines (when a model can't answer in time)


def prepared_line(feed: Feed, b: Briefing) -> str | None:
    """A line the crew can always say, in the feed's language. None means stay quiet."""
    m, f = b.moment, b.moment.facts
    zh = feed.language.startswith("zh")
    if m.kind == "goal":
        return f"进球！{f['scorer']}！比分 {f['score']}！" if zh else f"Goal! {f['scorer']} scores! {f['score']}."
    if m.kind in ("big_chance", "shot"):
        return f"{f['shooter']} 起脚射门！" if zh else f"{f['shooter']} lets fly!"
    if m.kind == "half_time":
        return "上半场结束。" if zh else "That's half-time."
    if m.kind == "full_time":
        return "全场比赛结束！" if zh else "And that's full-time!"
    if m.kind == "substitution":
        return f"换人：{f['on']} 替下 {f['off']}。" if zh else f"A change: {f['on']} on for {f['off']}."
    if m.kind == "play" and "on_the_ball" in f:
        if feed.id == "audio_en":
            return f"{f['team_in_possession']} on the ball, {f['ball_position']}. {f['on_the_ball']} has it."
        return f"{f['on_the_ball']} 拿球。" if zh else f"{f['on_the_ball']} on the ball."
    return None if zh or m.kind == "play" else m.summary


# ------------------------------------------------------------------ crew members


class StatsDeskExecutor(Executor):
    """Explains why a moment matters, using tools over the match statistics."""

    def __init__(self, booth: Booth, agent: Agent):
        super().__init__(id="stats_desk")
        self.booth = booth
        self.agent = agent

    async def explain(self, m: Moment) -> tuple[str, str]:
        prompt = (f"Moment at {m.facts.get('minute', '')}: {m.summary}\nFacts (from the stats system): "
                  f"{json.dumps(m.facts, ensure_ascii=False)}\n\nIn at most two sentences, say why this matters "
                  "for the match. Use only numbers from the facts or your tools.")
        try:
            r = await asyncio.wait_for(self.agent.run(prompt, options={"reasoning": {"effort": "low"}}), MODEL_TIMEOUT)
            return r.text.strip(), "ai"
        except Exception:
            return m.summary, "prepared"

    @handler
    async def take(self, m: Moment, ctx: WorkflowContext[Briefing]) -> None:
        b = self.booth
        b.kinds[m.tick] = m.kind
        if m.priority >= 4 or m.kind in ("half_time", "full_time"):
            b.note(m.tick, "Stats desk", m.summary, to="Director")
            await ctx.send_message(Briefing(m, "reaction"), target_id="director")
            insight, source = await self.explain(m)
            b.note(m.tick, "Stats desk", insight, to="Director", source=source)
            await ctx.send_message(Briefing(m, "analysis", insight), target_id="director")
        elif m.priority == 3 or m.kind == "spell":
            insight, source = await self.explain(m)
            b.note(m.tick, "Stats desk", insight, to="Director", source=source)
            await ctx.send_message(Briefing(m, "analysis", insight), target_id="director")
        else:
            await ctx.send_message(Briefing(m, "filler"), target_id="director")


class DirectorExecutor(Executor):
    """Decides, feed by feed, what goes on air and when."""

    def __init__(self, booth: Booth, agent: Agent):
        super().__init__(id="director")
        self.booth = booth
        self.agent = agent

    def free_at(self, feed: str, tick: int) -> int:
        return max(tick, self.booth.busy_until[feed] + 4)

    def due(self, feed: Feed, m: Moment) -> bool:
        gap = (m.tick - self.booth.last_line[feed.id]) / HZ
        if m.priority >= 4:
            return True
        if m.kind == "play":
            return gap >= feed.min_gap * (1.0 if feed.id == "audio_en" else 1.6)
        return gap >= feed.min_gap

    async def plan(self, b: Briefing) -> DirectorPlan | None:
        m = b.moment
        feeds = [f for f in self.booth.feeds.values()]
        lines = {f.id: list(self.booth.said[f.id])[-3:] for f in feeds}
        prompt = (
            f"Moment: {m.summary}\nStats desk says: {b.insight}\n"
            f"Feeds on air: {json.dumps([{'feed': f.id, 'audience': f.audience, 'graphics': list(f.graphics)} for f in feeds], ensure_ascii=False)}\n"
            f"Recent lines per feed: {json.dumps(lines, ensure_ascii=False)}\n"
            "Graphics: stats = head-to-head numbers panel; momentum = who-is-on-top chart; player = one player's card "
            "(name them in 'player'); pitch = a map drawn on the grass of which team controls which space.\n"
            f"{REPLAY_HINT if m.kind in REPLAY_KINDS else ''}"
            "For each feed decide: speak now or stay quiet, the angle the commentator should take for that audience "
            "(one short phrase), and which graphic to show from that feed's list, or none. Not every moment needs a "
            "graphic. Avoid repeating recent lines. Then give a one-line talkback note to the crew."
        )
        try:
            r = await asyncio.wait_for(
                self.agent.run(prompt, options={"response_format": DirectorPlan, "reasoning": {"effort": "none"}}),
                MODEL_TIMEOUT)
            return r.value
        except Exception:
            return None

    async def replay(self, m: Moment, plan: DirectorPlan | None, ctx) -> None:
        """Book a slow-motion replay of the move on every feed, each from its own angle."""
        booth = self.booth
        build = m.facts.get("build_up") or {}
        seconds = float(build.get("seconds", 8))
        start = max(m.tick - 95, m.tick - int(seconds * HZ) - 15)
        focus = m.players[0] if m.players else None
        at = m.tick + 60
        angles = []
        for feed in booth.feeds.values():
            choice = next((p for p in plan.feeds if p.feed == feed.id), None) if plan else None
            angle = choice.replay if choice and choice.replay != "none" else DEFAULT_REPLAY.get(feed.id, "high")
            angles.append(f"{feed.name}: {angle.replace('_', ' ')}")
            await ctx.yield_output(Cue(f"r-{feed.id}-{m.id}", feed.id, at, "replay", m.kind,
                                       replay={"from": start, "to": m.tick + 12, "angle": angle, "focus": focus,
                                               "speed": 0.7, "team": m.team},
                                       source="ai" if choice else "rules"))
        booth.note(m.tick, "Director", "replay, " + "; ".join(angles), to="Replay", source="ai" if plan else "rules")

    @handler
    async def take(self, b: Briefing, ctx: WorkflowContext[LineRequests, Cue]) -> None:
        booth, m = self.booth, b.moment
        calls: list[LineRequest] = []
        if b.stage == "reaction":
            for feed in booth.feeds.values():
                at = m.tick + 4
                booth.busy_until[feed.id] = at + 30   # hold the feed for the reaction
                booth.note(m.tick, "Director", f"{m.kind.replace('_', ' ')}: react now", to=f"Commentator · {feed.name}", feed=feed.id)
                calls.append(LineRequest(feed.id, b, "react to the moment", True, at))
            await ctx.send_message(LineRequests(calls))
            return

        plan = await self.plan(b) if b.stage == "analysis" else None
        if plan is not None:
            booth.note(m.tick, "Director", plan.talkback, to="Crew")
        if b.stage == "analysis" and m.kind in REPLAY_KINDS:
            await self.replay(m, plan, ctx)
        for feed in booth.feeds.values():
            choice = next((p for p in plan.feeds if p.feed == feed.id), None) if plan else None
            if choice is None:
                speak = self.due(feed, m)
                angle = "describe the play" if b.stage == "filler" else "say why it matters"
                graphic = "none"
                if m.kind in ("spell", "press"):
                    graphic = "pitch" if "pitch" in feed.graphics else "momentum" if "momentum" in feed.graphics else "none"
                player = None
                source = "rules"
            else:
                speak = choice.speak and (self.due(feed, m) or m.priority >= 3)
                angle, graphic, player, source = choice.angle, choice.graphic, choice.player, "ai"
            at = self.free_at(feed.id, m.tick + (60 if b.stage == "analysis" and m.priority >= 4 else 0))
            if graphic != "none" and graphic in feed.graphics:
                g = {"type": graphic, "seconds": 9}
                if graphic == "player":
                    pid = booth.desk.player_id(player) or (m.players[0] if m.players else None) or feed.follow
                    if pid is None:
                        continue
                    g["player"] = pid
                    g["profile"] = booth.desk.player_profile(pid, m.tick)
                elif graphic == "stats":
                    g["teams"] = booth.desk.stats.team_stats(m.tick)
                await ctx.yield_output(Cue(f"g-{feed.id}-{m.id}", feed.id, at, "graphic", m.kind, graphic=g, source=source))
                booth.note(m.tick, "Director", f"graphic on air: {graphic}", to=f"Graphics · {feed.name}", feed=feed.id, source=source)
            if speak:
                booth.busy_until[feed.id] = at + 30
                calls.append(LineRequest(feed.id, b, angle, m.priority >= 4, at))
        if calls:
            await ctx.send_message(LineRequests(calls))


class CommentatorExecutor(Executor):
    """Writes the line for one feed, in that feed's language and voice."""

    def __init__(self, booth: Booth, agents: dict[str, Agent]):
        super().__init__(id="commentators")
        self.booth = booth
        self.agents = agents

    @handler
    async def take(self, batch: LineRequests, ctx: WorkflowContext[Lines]) -> None:
        lines = await asyncio.gather(*(self.write(r) for r in batch.requests))
        lines = [x for x in lines if x is not None]
        if lines:
            await ctx.send_message(Lines(lines))

    async def write(self, req: LineRequest) -> Line | None:
        booth = self.booth
        feed = booth.feeds[req.feed]
        b, m = req.briefing, req.briefing.moment
        recent = list(booth.said[feed.id])[-4:]
        zh = feed.language.startswith("zh")
        unit = "个汉字" if zh else "words"
        if b.stage == "reaction":
            task = (f"React live, in the instant it happens: the player and the emotion. "
                    f"At most {18 if zh else 12} {unit}. No analysis yet.")
        elif b.stage == "analysis":
            task = (f"You have already reacted to this moment. Now tell the viewer why it matters, built on one "
                    f"concrete detail from the stats desk. At most {feed.max_words} {unit}.")
        else:
            task = f"Describe what is happening right now, briefly. At most {max(10, feed.max_words // 2)} {unit}."
        prompt = (
            f"Moment: {m.summary}\n"
            f"Facts: {json.dumps(m.facts, ensure_ascii=False)}\n"
            f"Stats desk: {b.insight or '-'}\nDirector's angle: {req.angle}\n"
            f"Your last lines: {json.dumps(recent, ensure_ascii=False)}\n"
            f"{task} Say something new. Output only the spoken words."
        )
        text, source = None, "ai"
        try:
            r = await asyncio.wait_for(self.agents[feed.id].run(prompt, options={"reasoning": {"effort": "none"}}), MODEL_TIMEOUT)
            text = r.text.strip().strip('"')
        except Exception:
            text = None
        if not text:
            text, source = prepared_line(feed, b), "prepared"
            if text is None:
                booth.busy_until[feed.id] = booth.last_line[feed.id]
                return None
        booth.note(m.tick, f"Commentator · {feed.name}", text, to="Voice", feed=feed.id, source=source)
        return Line(feed.id, text, b, req.excited, req.at, source)


class VoiceExecutor(Executor):
    """Azure AI Speech reads the line in the feed's voice and books it into the rundown."""

    def __init__(self, booth: Booth):
        super().__init__(id="voice")
        self.booth = booth

    @handler
    async def take(self, batch: Lines, ctx: WorkflowContext[None, Cue]) -> None:
        async def one(line: Line):
            cue = await self.speak(line)
            if cue is not None:
                await ctx.yield_output(cue)
        await asyncio.gather(*(one(x) for x in batch.lines))

    async def speak(self, line: Line) -> Cue | None:
        booth = self.booth
        feed = booth.feeds[line.feed]
        m = line.briefing.moment
        try:
            audio, seconds = await booth.voices.say(feed, line.text, excited=line.excited)
        except Exception as e:
            audio, seconds = None, max(2.0, len(line.text) / 15)
            booth.note(m.tick, "Voice", f"no audio, captions only ({e})", feed=feed.id, source="prepared")
        # never talk over the line already booked on this feed
        at = max(line.at, booth.viewer_tick + 4, booth.on_air_until[feed.id] + 6)
        if at - m.tick > 60 and m.priority < 4:
            booth.note(m.tick, "Director", "line dropped: the moment has passed", feed=feed.id, source="rules")
            return None
        booth.busy_until[feed.id] = at + int(seconds * HZ)
        booth.on_air_until[feed.id] = at + int(seconds * HZ)
        booth.last_line[feed.id] = at
        booth.said[feed.id].append(line.text)
        return Cue(f"l-{feed.id}-{m.id}-{line.briefing.stage}", feed.id, at, "line", m.kind,
                   text=line.text, audio=audio, seconds=round(seconds, 2),
                   excited=line.excited, source=line.source)


# ------------------------------------------------------------------ building the crew


class Crew:
    """Agents are created once per server and shared by every broadcast session."""

    def __init__(self):
        self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        endpoint = setting("AZURE_AI_PROJECT_ENDPOINT")
        fast = os.environ.get("GANTRY_MODEL_FAST", "gpt-5.4-mini")
        smart = os.environ.get("GANTRY_MODEL_SMART", fast)
        self.fast = FoundryChatClient(project_endpoint=endpoint, model=fast, credential=self.credential)
        self.smart = FoundryChatClient(project_endpoint=endpoint, model=smart, credential=self.credential)
        self.voices = Voices()

    def agents(self, booth: Booth) -> dict:
        desk_agent = Agent(
            self.smart, name="stats_desk", tools=booth.desk.tools(lambda: booth.viewer_tick + DELAY_TICKS),
            instructions=("You are the stats desk of a live football broadcast. You receive a moment with facts from "
                          "the tracking system. Explain briefly why it matters for the match. You may call a tool or "
                          "two for context. Never state a number that did not come from the facts or a tool."))
        director = Agent(
            self.smart, name="director",
            instructions=("You are the director in the gallery of a live football broadcast that produces several "
                          "personalised feeds at once. You decide what each feed puts on air, keeping each one right "
                          "for its audience and never cluttered."))
        commentators = {
            f.id: Agent(self.fast, name=f"commentator_{f.id}",
                        instructions=f"{f.persona}\nAudience: {f.audience}\nYou are live on air. Output only the words you say.")
            for f in booth.feeds.values()
        }
        editor = Agent(
            self.smart, name="editor",
            instructions=("You are the match editor of a live football broadcast. At half-time and full-time you cut the "
                          "highlights package and write the report for each personalised feed, in its language and style."))
        return {"desk": desk_agent, "director": director, "commentators": commentators, "editor": editor}

    @staticmethod
    def workflow(booth: Booth, agents: dict):
        desk = StatsDeskExecutor(booth, agents["desk"])
        direc = DirectorExecutor(booth, agents["director"])
        comm = CommentatorExecutor(booth, agents["commentators"])
        voice = VoiceExecutor(booth)
        return (WorkflowBuilder(name="gantry-crew", start_executor=desk)
                .add_edge(desk, direc).add_edge(direc, comm).add_edge(comm, voice).build())

    @staticmethod
    def editor_workflow(booth: Booth, agents: dict, total_ticks: int):
        """The editor works in its own workflow, alongside the live crew, so a long edit never holds up the show."""
        from .editor import EditorExecutor
        editor = EditorExecutor(booth, agents["editor"], total_ticks)
        return WorkflowBuilder(name="gantry-editor", start_executor=editor).build()

    @staticmethod
    async def warm_up(agents: dict):
        """One tiny call per agent, so the first real moment isn't slowed by cold connections."""
        everyone = [agents["desk"], agents["director"], agents["editor"], *agents["commentators"].values()]

        async def ping(a):
            try:
                await asyncio.wait_for(a.run("Reply with OK.", options={"reasoning": {"effort": "none"}}), 20)
            except Exception:
                pass
        await asyncio.gather(*(ping(a) for a in everyone))


class CrewSession:
    """Runs the crew for one viewer's broadcast, a few seconds ahead of the picture."""

    def __init__(self, crew: Crew, loaded, feed_ids: list[str], send, lead: int = DELAY_TICKS):
        self.crew = crew
        self.loaded = loaded
        self.send = send
        desk = StatsDesk(loaded.stats, loaded.events)
        self.booth = Booth({f: FEEDS[f] for f in feed_ids if f in FEEDS}, desk, crew.voices)
        self.scanned = 0
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.generation = 0
        self.talk_sent = 0
        self.agents = crew.agents(self.booth)
        self.producer = None
        self.lead = lead
        self.asking = False
        self.last_question = -1e9
        self.seq = 0
        # productions are shared only between sessions carrying the same set of feeds
        self.production = Production.of(f"{loaded.match.id}-{'+'.join(sorted(self.booth.feeds))}")

    def seek(self, tick: int):
        self.generation += 1
        self.scanned = tick
        self.booth.reset(tick)
        self.booth.desk.reset(tick)
        while not self.queue.empty():
            self.queue.get_nowait()

    async def watch(self, head):
        """Scans the match ahead of the viewer and queues the moments."""
        total = len(self.loaded.frames)
        while True:
            await asyncio.sleep(0.2)
            viewer = int(head())
            self.booth.viewer_tick = viewer
            live = min(viewer + self.lead, total - 1)
            if live <= self.scanned:
                continue
            try:
                for m in self.booth.desk.scan(self.scanned, live):
                    # the sequence number keeps the queue from ever comparing two moments directly
                    self.seq += 1
                    await self.queue.put((-m.priority, m.tick, self.seq, m))
            except Exception as e:  # a bad moment must never stop the match reaching the viewer
                self.booth.note(live, "Gallery", f"stats desk skipped a stretch ({type(e).__name__})", source="rules")
            self.scanned = live

    async def work(self, lanes: int = 3):
        """Big moments go first, and up to `lanes` moments are produced at once."""
        await self.crew.warm_up(self.agents)
        await asyncio.gather(*(self._lane() for _ in range(lanes)))

    async def _lane(self):
        while True:
            *_, m = await self.queue.get()
            gen = self.generation
            booth = self.booth
            # skip what the viewer has already seen, and small things when playback is fast
            if m.tick < booth.viewer_tick - 20 and m.priority < 5:
                continue
            if booth.speed > 1.5 and m.priority < 3 or booth.speed > 3 and m.priority < 4:
                continue
            started = time.perf_counter()
            if m.kind in ("half_time", "full_time"):
                asyncio.create_task(self._edit(m, gen))
            if await self.replay_production(m.id, gen):
                continue
            workflow = self.crew.workflow(booth, self.agents)
            produced: list[dict] = []
            failed = False
            try:
                # no single moment may hold a lane for long, whatever gets stuck inside it
                async with asyncio.timeout(MOMENT_TIMEOUT):
                    async for event in workflow.run(m, stream=True):
                        if event.type == "output":
                            cue = asdict(event.data)
                            produced.append(cue)
                            if gen == self.generation:
                                await self.send({"type": "cues", "cues": [cue]})
            except Exception as e:  # the show goes on
                failed = True
                booth.note(m.tick, "Gallery", f"{m.kind}: crew error, skipped ({type(e).__name__})", source="rules")
            booth.note(m.tick, "Gallery", f"{m.kind} produced in {time.perf_counter() - started:.1f}s", source="rules")
            if not failed:
                self.keep(m.id, m.tick, produced)
            await self.flush_talk()

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
                end = c["tick"] + int((c.get("seconds") or 3) * HZ)
                booth.on_air_until[c["feed"]] = max(booth.on_air_until[c["feed"]], end)
                booth.busy_until[c["feed"]] = max(booth.busy_until[c["feed"]], end)
                booth.last_line[c["feed"]] = max(booth.last_line[c["feed"]], c["tick"])
                if c.get("text"):
                    booth.said[c["feed"]].append(c["text"])
        if gen == self.generation and hit["cues"]:
            await self.send({"type": "cues", "cues": hit["cues"]})
        await self.flush_talk()
        return True

    async def _edit(self, m: Moment, gen: int):
        key = f"{m.id}-edit"
        if await self.replay_production(key, gen):
            return
        self.booth.note(m.tick, "Stats desk", m.summary, to="Editor")
        workflow = self.crew.editor_workflow(self.booth, self.agents, len(self.loaded.frames))
        produced: list[dict] = []
        try:
            async for event in workflow.run(EditorBrief(m), stream=True):
                if event.type == "output":
                    cue = asdict(event.data)
                    produced.append(cue)
                    if gen == self.generation:
                        await self.send({"type": "cues", "cues": [cue]})
            if produced:
                talk = [n for n in self.booth.talk if n["tick"] == m.tick and n["who"] in ("Editor", "Stats desk")]
                self.production.put(key, produced, talk, collect_audio(produced, self.booth.voices))
        except Exception as e:
            self.booth.note(m.tick, "Gallery", f"editor error, no package ({type(e).__name__})", source="rules")
        await self.flush_talk()

    async def flush_talk(self):
        new = min(self.booth.notes - self.talk_sent, len(self.booth.talk))
        self.talk_sent = self.booth.notes
        if new > 0:
            await self.send({"type": "talkback", "items": list(self.booth.talk)[-new:]})
