"""The crew members, each an executor in a Microsoft Agent Framework workflow.

    stats desk  ->  director  ->  commentator, one per feed  ->  voice, one per feed

The director reaches the commentators through a multi-selection edge, so the
feeds it asks for are written at the same time, each by its own agent. Every
number and name comes from the stats desk; the director decides what goes on
air, when, and with which picture; the commentators find the words; the voices
book each line into its feed's rundown.
"""

from __future__ import annotations

import asyncio
import json

from agent_framework import Agent, Executor, WorkflowContext, handler

from ..common import HZ
from .booth import Booth
from .feeds import Feed, local_name
from .house import allowed_numbers, names_in, prepared_line, problem
from .messages import Briefing, Cue, Cut, DirectorPlan, FeedReplay, Line, LineRequest, LineRequests, ReplayPlan

MODEL_TIMEOUT = 7.0
REPLAY_KINDS = ("goal", "big_chance")
DEFAULT_REPLAY = {"casual": "behind_goal", "analyst": "high", "home": "follow", "audio": "high"}
SECOND_REPLAY = {"casual": "follow", "analyst": "behind_goal", "home": "behind_goal", "audio": "behind_goal"}
GRAPHIC_EVERY = {"casual": 180, "analyst": 90, "home": 150, "audio": 10**6}
GRAPHIC_WORDS = {"stats": "a panel of both teams' numbers", "momentum": "a chart of which team has been on top, minute by minute",
                 "player": "a card with this player's numbers today", "pitch": "the pitch coloured by which team controls each area",
                 "lineups": "both teams' starting line-ups"}

# how long the air is kept clear around a big moment: (before, after) in ticks
HOLDS = {"goal": (5, 330), "big_chance": (5, 230), "shot": (5, 45), "half_time": (5, 90), "full_time": (5, 120)}


EDITORIAL_KINDS = ("substitution", "card", "kickoff", "press", "spell")
SCORE_EVERY = 180 * HZ       # the audio describer gives the time and score at least this often
# what the audio describer's next open-play line is about, in turn, so ninety minutes never sound the same
AUDIO_FOCUS = (
    "the player on the ball: who, for which team, and where on the pitch",
    "the move so far: the last two or three passes, by name, as a flowing sentence",
    "the shape of the play: where the space is, who is pressing, which side the attack is building down",
    "the player on the ball and what he does next, in a few quick words",
)


def covers(feed: Feed, m) -> bool:
    """Does this feed say something about this goal, change, booking, kick-off or spell of play?"""
    k, a = m.kind, feed.aud.id
    if k in REPLAY_KINDS or k in ("substitution", "card", "kickoff", "spell", "open"):
        return True
    if k == "press":
        return a in ("analyst", "casual") or (a == "home" and m.team == feed.side)
    return False


def replay_window(m) -> tuple[int, int]:
    build = m.facts.get("build_up") or {}
    start = build.get("start_tick", m.tick - 80)
    return max(m.tick - 110, start - 15, 0), m.tick + 12


def opts(model: str, effort: str = "minimal") -> dict:
    """Request options for a model: reasoning models get the least reasoning the job needs."""
    if model.startswith("gpt-5.4") or model.startswith("gpt-5.1") or model.startswith("gpt-5.2"):
        return {"reasoning": {"effort": "none" if effort == "minimal" else effort}}
    if model.startswith("gpt-5") or model.startswith("o"):
        return {"reasoning": {"effort": effort}}
    return {}


# ------------------------------------------------------------------ stats desk


class StatsDeskExecutor(Executor):
    """Explains why a moment matters, using tools over the match statistics."""

    def __init__(self, booth: Booth, agent: Agent, model: str):
        super().__init__(id="stats_desk")
        self.booth = booth
        self.agent = agent
        self.model = model

    async def explain(self, m) -> tuple[str, str]:
        if m.kind in ("kickoff", "open"):
            return m.summary, "rules"
        stories = [s["text"] for s in self.booth.desk.storylines.at(m.tick)][:6] if m.kind in ("press", "spell") else []
        prompt = (f"Moment at {m.facts.get('minute', '')}: {m.summary}\nFacts from the tracking system: "
                  f"{json.dumps(m.facts, ensure_ascii=False)}\n"
                  + (f"Storylines so far: {json.dumps(stories, ensure_ascii=False)}\n" if stories else "")
                  + "In at most two sentences, say why this matters for the match right now. Use only names and "
                    "numbers from the facts, the storylines or your tools.")
        try:
            r = await asyncio.wait_for(self.agent.run(prompt, options=opts(self.model)), MODEL_TIMEOUT)
            return r.text.strip(), "ai"
        except Exception:
            return m.summary, "prepared"

    @handler
    async def take(self, cut: Cut, ctx: WorkflowContext[Briefing]) -> None:
        b, m = self.booth, cut.moment
        b.kinds[m.tick] = m.kind
        if cut.stage == "filler":
            await ctx.send_message(Briefing(m, "filler"))
            return
        if cut.stage == "call":
            b.note(m.tick, "Stats desk", m.summary, to="Director", source="rules")
            await ctx.send_message(Briefing(m, "call"))
            return
        insight, source = await self.explain(m)
        b.note(m.tick, "Stats desk", insight, to="Director", source=source)
        await ctx.send_message(Briefing(m, cut.stage, insight, source))


# ------------------------------------------------------------------ director


class DirectorExecutor(Executor):
    """Decides, feed by feed, what goes on air, when, and with which picture."""

    def __init__(self, booth: Booth, agent: Agent, model: str):
        super().__init__(id="director")
        self.booth = booth
        self.agent = agent
        self.model = model

    # ---------------------------------------------------- helpers

    def feeds(self) -> list[Feed]:
        return list(self.booth.feeds.values())

    def graphic(self, feed: Feed, kind: str, m, player: str | None = None, at: int | None = None) -> dict | None:
        """A graphic payload, if the feed shows this kind and hasn't had one too recently."""
        if kind == "none" or kind not in feed.graphics:
            return None
        at = m.tick if at is None else at
        if kind != "player" and at - self.booth.last_graphic[feed.id] < GRAPHIC_EVERY[feed.aud.id] * HZ:
            return None
        desk = self.booth.desk
        g = {"type": kind, "seconds": 9}
        if kind == "player":
            pid = desk.player_id(player) or (m.players[0] if m.players else None) or feed.follow
            if pid is None:
                return None
            g["player"] = pid
            g["profile"] = desk.player_profile(pid, m.tick)
        elif kind == "stats":
            g["teams"] = desk.stats.team_stats(m.tick)
        return g

    def pick_story(self, feed: Feed, tick: int) -> dict | None:
        desk = self.booth.desk
        stories = [s for s in desk.storylines.at(tick) if self.booth.story_fresh(feed.id, s, tick)]
        aid = feed.aud.id

        def score(s):
            k = s["id"].split(":")[0]
            base = {"casual": {"saves": 3, "no_goal": 3, "sub": 3, "shots": 2, "fastest": 2, "scorer": 3, "press": 1,
                               "table": 2, "last_meeting": 2},
                    "analyst": {"line": 4, "territory": 4, "press": 3, "control": 3, "chaos": 3, "shots": 2, "saves": 1, "sub": 2,
                                "table": 1},
                    "home": {"scorer": 3, "sub": 2, "saves": 2, "no_goal": 2, "press": 2, "shots": 2, "fastest": 1,
                             "table": 2, "last_meeting": 3},
                    "audio": {"shots": 3, "saves": 2, "scorer": 2, "table": 1}}[aid].get(k, 0)
            if feed.side is not None and s.get("team") is not None:
                base += 1 if s["team"] == feed.side else -1
            if feed.follow and feed.follow in s.get("players", []):
                base += 2
            return base
        stories = [s for s in stories if score(s) > 0]
        return max(stories, key=score) if stories else None

    def story_graphic(self, feed: Feed, story: dict, m, at: int) -> dict | None:
        k = story["id"].split(":")[0]
        aid = feed.aud.id
        if aid == "analyst" and k in ("line", "territory", "press", "control", "chaos"):
            return self.graphic(feed, "pitch", m, at=at)
        if aid == "casual" and k in ("press", "shots", "territory"):
            return self.graphic(feed, "momentum", m, at=at)
        if k in ("saves", "no_goal", "sub", "scorer", "fastest") and story.get("players"):
            if aid == "home" or aid == "casual":
                pid = story["players"][0]
                return self.graphic(feed, "player", m, player=pid, at=at)
        if k == "shots":
            return self.graphic(feed, "stats", m, at=at)
        return None

    # ---------------------------------------------------- calls: the instant a big moment happens

    CALLS = {
        "goal": ("Call the goal: the scorer and the feeling, then the score.", 3, 40),
        "big_chance": ("Call the chance as it happens: the shooter and what happened.", 2, 30),
        "shot": ("Call the shot in a few words: who, and what happened to it.", 2, 25),
        "half_time": ("Say that it is half-time and give the score.", 5, 50),
        "full_time": ("Say that it is full-time and give the score, with the feeling of the result.", 5, 60),
        "corner": ("Say who has the corner.", 5, 60),
        "corner_kick": ("Describe the corner as it is taken: who takes it, from which side, and what happens.", 0, 15),
        "sprint": ("Call the burst of pace: who, how fast, and what he is doing.", 0, 25),
    }

    def call_feeds(self, m) -> list[Feed]:
        k = m.kind
        out = []
        for f in self.feeds():
            a = f.aud.id
            if k in ("goal", "big_chance", "shot", "half_time", "full_time"):
                out.append(f)
            elif k == "corner" and (a in ("casual", "audio") or (a == "home" and m.team == f.side)):
                out.append(f)
            elif k == "corner_kick" and a == "audio":
                out.append(f)
            elif k == "sprint":
                running = m.facts.get("running", "")
                if a == "analyst" or (a == "casual" and m.priority >= 3) or \
                   (a == "home" and (f.follow in m.players or m.team == f.side)) or \
                   (a == "audio" and running in ("running in behind", "carrying the ball forward")):
                    out.append(f)
        return out

    def calls(self, b: Briefing) -> list[LineRequest]:
        m = b.moment
        angle, delay, window = self.CALLS[m.kind]
        big = m.kind in ("goal", "big_chance", "half_time", "full_time")
        reqs = []
        for f in self.call_feeds(m):
            if m.kind == "sprint" and self.booth.quiet_for(f.id, m.tick) < 3:
                continue
            reqs.append(LineRequest(f.id, b, "call", angle, m.tick + delay, m.tick + window,
                                    excited=m.kind in ("goal", "big_chance") or (m.kind == "full_time"),
                                    interrupt=big))
        if reqs:
            self.booth.note(m.tick, "Director", f"{m.kind.replace('_', ' ')}: call it now",
                            to="Commentators · " + ", ".join(self.booth.feeds[r.feed].name for r in reqs), source="rules")
        return reqs

    # ---------------------------------------------------- open play

    def fillers(self, b: Briefing) -> list[LineRequest]:
        m = b.moment
        booth = self.booth
        reqs = []
        for f in self.feeds():
            if booth.held(m.tick, feed=f.id) or booth.claimed(f.id, m.tick):
                continue
            quiet = booth.quiet_for(f.id, m.tick)
            if quiet < f.aud.quiet_gap:
                continue
            req = self.open_play(f, b, quiet)
            if req is not None:
                booth.claim(f.id, m.tick)
                if req.story:
                    booth.use_story(f.id, req.story, m.tick)
                reqs.append(req)
        return reqs

    def open_play(self, f: Feed, b: Briefing, quiet: float) -> LineRequest | None:
        """What, if anything, this feed says while nothing in particular is happening."""
        m = b.moment
        booth, desk = self.booth, self.booth.desk
        if f.aud.describes_play:
            due = m.tick - booth.last_score[f.id] >= SCORE_EVERY
            booth.turn[f.id] = booth.turn.get(f.id, 0) + 1
            focus = AUDIO_FOCUS[booth.turn[f.id] % len(AUDIO_FOCUS)]
            return LineRequest(f.id, b, "filler", f"This line is about {focus}.", m.tick, m.tick + 12, say_score=due)
        if m.tick - booth.last_story[f.id] >= f.aud.story_every * HZ:
            story = self.pick_story(f, m.tick)
            if story:
                g = self.story_graphic(f, story, m, m.tick)
                return LineRequest(f.id, b, "story", "Pick up this storyline; don't describe the picture.",
                                   m.tick, m.tick + 25, story=story, graphic=json.dumps(g) if g else None)
        if f.follow and quiet >= f.aud.quiet_gap * 1.5:
            ctx = desk.player_context(f.follow, m.tick)
            last = ctx.get("last_action") or {}
            busy = (ctx.get("has_the_ball") or last.get("seconds_ago", 99) <= 5
                    or (ctx.get("moving") == "running forward" and ctx.get("distance_to_ball_m", 99) < 20))
            if busy:
                return LineRequest(f.id, b, "follow", f"One short line about what {desk.name(f.follow)} is doing "
                                   "right now, from the facts about him.", m.tick, m.tick + 12)
        if quiet >= f.aud.quiet_gap * 2:
            # nobody on air for a while: a short read of the play, in this feed's own way
            angle = {"casual": "Help a new fan read what is happening right now.",
                     "analyst": "A quick tactical read of this phase of play, with one number if the facts give one.",
                     "home": "A short reaction as a fan to what is happening right now."}.get(f.aud.id)
            if angle:
                return LineRequest(f.id, b, "read", angle, m.tick, m.tick + 15)
        return None

    # ---------------------------------------------------- analysis and editorial moments

    async def plan(self, b: Briefing) -> DirectorPlan | None:
        m = b.moment
        booth = self.booth
        feeds = self.feeds()
        stories = [s for s in booth.desk.storylines.at(m.tick)][:8]
        prompt = (
            f"Moment: {m.summary}\nStats desk says: {b.insight}\n"
            f"Feeds on air: {json.dumps([{'feed': f.id, 'audience': f.audience, 'language': f.lang.name, 'graphics': list(f.graphics)} for f in feeds], ensure_ascii=False)}\n"
            f"Recent lines per feed: {json.dumps({f.id: list(booth.said[f.id])[-3:] for f in feeds}, ensure_ascii=False)}\n"
            f"Storylines available (id: text): {json.dumps({s['id']: s['text'] for s in stories}, ensure_ascii=False)}\n"
            "Graphics: stats = both teams' numbers; momentum = who-is-on-top chart; player = one player's card (name "
            "him); pitch = space control on the grass (analyst only); none.\n"
            + (("This moment gets slow-motion replays on every feed. For each feed choose the replay angle and, for a "
                "goal, a second angle: behind_goal (from behind the net, best for the finish), high (high and wide, shows "
                "the shape of the move), follow (stays with the scorer's run), reverse (from the opposite side). Choose what "
                "that audience would most want to see; feeds may differ.\n") if m.kind in REPLAY_KINDS else "")
            + "For each feed decide whether it speaks, what its line should be about (a short direction to the "
              "commentator), which graphic goes with it, and which storyline id it may use (or none). Keep each feed "
              "right for its audience and never cluttered. Then one line of talkback to the crew, in plain spoken "
              "words (no ids or underscores)."
        )
        schema = ReplayPlan if m.kind in REPLAY_KINDS else DirectorPlan
        try:
            r = await asyncio.wait_for(self.agent.run(prompt, options={"response_format": schema, **opts(self.model)}),
                                       MODEL_TIMEOUT)
            return r.value
        except Exception:
            return None

    async def replay(self, m, plan: ReplayPlan | None, ctx) -> int:
        """Book the slow-motion replays on every feed, each from its own angle. Returns when they start."""
        booth = self.booth
        a, b = replay_window(m)
        at = m.tick + (80 if m.kind == "goal" else 50)
        first_len = int((b - a) / 0.7)
        angles = []
        for f in self.feeds():
            choice: FeedReplay | None = next((p for p in plan.replays if p.feed == f.id), None) if plan else None
            angle = choice.angle if choice else DEFAULT_REPLAY[f.aud.id]
            focus = m.players[0] if m.players else None
            await ctx.yield_output(Cue(f"r-{f.id}-{m.id}", f.id, at, "replay", m.kind,
                                       replay={"from": a, "to": b, "angle": angle, "focus": focus, "speed": 0.7, "team": m.team},
                                       source="ai" if choice else "rules"))
            text = angle.replace("_", " ")
            if m.kind == "goal":
                second = (choice.second_angle if choice and choice.second_angle != "none" else SECOND_REPLAY[f.aud.id])
                if second == angle:
                    second = SECOND_REPLAY[f.aud.id] if SECOND_REPLAY[f.aud.id] != angle else "reverse"
                at2 = at + first_len + 6
                await ctx.yield_output(Cue(f"r2-{f.id}-{m.id}", f.id, at2, "replay", m.kind,
                                           replay={"from": m.tick - 45, "to": m.tick + 15, "angle": second, "focus": focus,
                                                   "speed": 0.6, "team": m.team},
                                           source="ai" if choice else "rules"))
                text += f", then {second.replace('_', ' ')}"
            angles.append(f"{f.name}: {text}")
        booth.note(m.tick, "Director", "replays: " + "; ".join(angles), to="Replay", source="ai" if plan else "rules")
        return at

    def editorial_feeds(self, m) -> list[Feed]:
        return [f for f in self.feeds() if covers(f, m)]

    async def coverage(self, b: Briefing, ctx) -> list[LineRequest]:
        m = b.moment
        booth = self.booth
        plan = await self.plan(b) if m.kind != "open" else None
        if plan is not None:
            booth.note(m.tick, "Director", plan.talkback, to="Crew")
        replay_at = await self.replay(m, plan if isinstance(plan, ReplayPlan) else None, ctx) if m.kind in REPLAY_KINDS else None
        reqs = []
        wanted = {f.id for f in self.editorial_feeds(m)}
        for f in self.feeds():
            choice = next((p for p in plan.feeds if p.feed == f.id), None) if plan else None
            if choice is not None and not choice.speak:
                continue
            if choice is None and f.id not in wanted:
                continue
            if m.kind in REPLAY_KINDS:
                kind, at, latest = "analysis", replay_at + 8, replay_at + 120
                default = "The replay is rolling: say why this mattered, from one concrete detail."
            elif m.kind in ("press", "spell"):
                kind, at, latest = "editorial", m.tick, m.tick + 600
                default = "Say what this spell of play tells us, from the stats desk's point."
            elif m.kind == "open":
                kind, at, latest = "open", m.tick, m.tick + 300
                default = OPENING[f.aud.id]
            elif m.kind == "kickoff":
                kind, at, latest = "editorial", m.tick, m.tick + 300
                default = ("Open the half: who is in which colours and which way each team attacks, then the score."
                           if f.aud.describes_play else "Get the half under way: the score and what to watch for.")
            else:
                kind, at, latest = "editorial", m.tick + 15, m.tick + 900
                default = "Tell the viewer what just happened and why it matters right now."
            angle = choice.angle if choice else default
            story = None
            if choice and choice.story:
                story = next((s for s in booth.desk.storylines.at(m.tick) if s["id"] == choice.story), None)
            if story is None and m.kind in ("press", "spell") and f.aud.id != "audio":
                story = self.pick_story(f, m.tick)
            g = None
            if m.kind in REPLAY_KINDS:
                pass                         # the replay is the picture
            elif choice and choice.graphic != "none":
                g = self.graphic(f, choice.graphic, m, player=choice.player, at=at)
            elif m.kind in ("substitution", "card"):
                g = self.graphic(f, "player", m, at=at)
            elif m.kind == "open" and f.graphics:
                g = {"type": "lineups", "seconds": 14}
            elif m.kind == "spell":
                g = self.graphic(f, "pitch" if f.aud.id == "analyst" else "momentum", m, at=at)
            est = booth.fit(f.id, at, 5.0, owner=m.id)
            if est is not None and est - m.tick > 120 and m.kind not in REPLAY_KINDS:
                angle += f" This goes on air about {round((est - m.tick) / HZ)} seconds after it happened, so refer back to it naturally."
            reqs.append(LineRequest(f.id, b, kind, angle, at, latest, story=story, graphic=json.dumps(g) if g else None))
            if g:
                booth.note(m.tick, "Director", f"graphic on air: {g['type']}", to=f"Graphics · {f.name}", feed=f.id,
                           source="ai" if choice else "rules")
        return reqs

    @handler
    async def take(self, b: Briefing, ctx: WorkflowContext[LineRequests, Cue]) -> None:
        if b.stage == "call":
            reqs = self.calls(b)
        elif b.stage == "filler":
            reqs = self.fillers(b)
        else:
            reqs = await self.coverage(b, ctx)
        if reqs:
            await ctx.send_message(LineRequests(reqs))


# ------------------------------------------------------------------ commentators


OPENING = {
    "casual": "Welcome viewers who are new to football: who is playing, in which colours, and the one player to watch.",
    "analyst": "Set up the tactical battle: the two shapes, and the duel that could decide it.",
    "home": "Welcome the Kingsmere fans: the team, and why today is about Aldana.",
    "audio": "Welcome the listeners: who is in which colours, which way each team attacks, and the two shapes.",
}

TASKS = {
    "open": "The broadcast is starting, before kick-off. Open it in two or three short sentences. At most {open}.",
    "call": "Call it live, in the instant it happens: who, and what happened, with feeling. At most {call}.",
    "editorial": "Tell the viewer about this and why it matters now. At most {max}.",
    "story": "Pick up the storyline in one line, in your own words. Do not describe the picture. At most {max}.",
    "follow": "One short line on what he is doing right now, using only the facts about him. At most {half}.",
    "read": "One short spoken sentence about what is happening right now, as the director asks. At most {half}.",
    "describe": ("Describe the play right now in one or two short spoken sentences, the way a radio commentator would: "
                 "the player on the ball and his team, where the ball is, and what just happened (the last pass or two). "
                 "Say which way they are attacking only if the ball has just changed hands. Use a different sentence "
                 "shape from your last lines. {score}At most {max}."),
}
ANALYSIS = {
    "casual": "The replay is rolling. In plain words, say why this mattered, from one concrete detail. At most {max}.",
    "analyst": ("The replay is rolling. Name the mechanism behind it, backed by one or two numbers from the facts or the "
                "stats desk. At most {max}."),
    "home": ("The replay is rolling. As a Kingsmere fan, say how it came about, from one concrete detail (celebrate "
             "it if it's ours). At most {max}."),
    "audio": ("The replay is rolling. Describe how it came about for a listener who cannot see it: how the ball was won, "
              "the passes, and where the finish came from. At most {max}."),
}


class CommentatorExecutor(Executor):
    """Writes the line for one feed, in that feed's language and voice."""

    def __init__(self, booth: Booth, feed_id: str, call_agent: Agent, line_agent: Agent, models: tuple[str, str]):
        super().__init__(id=f"commentator_{feed_id}")
        self.booth = booth
        self.feed_id = feed_id
        self.call_agent = call_agent
        self.line_agent = line_agent
        self.models = models

    @handler
    async def take(self, batch: LineRequests, ctx: WorkflowContext[Line]) -> None:
        for req in batch.requests:
            if req.feed != self.feed_id:
                continue
            line = await self.write(req)
            if line is not None:
                await ctx.send_message(line)

    def prompt(self, req: LineRequest, feed: Feed, note: str | None = None) -> str:
        booth, desk = self.booth, self.booth.desk
        b, m = req.briefing, req.briefing.moment
        kind = "describe" if req.kind == "filler" and feed.aud.describes_play else req.kind
        lengths = dict(call=feed.words(feed.aud.call_words), max=feed.words(feed.aud.max_words),
                       half=feed.words(max(10, feed.aud.max_words // 2)), open=feed.words(45))
        if kind == "analysis":
            task = ANALYSIS[feed.aud.id].format(**lengths)
        elif kind == "describe":
            score = (f"Start with the time ({desk.minutes_played(m.tick)} minutes played) and the score. "
                     if req.say_score else "Do not give the time or the score this time. ")
            task = TASKS["describe"].format(score=score, **lengths)
        else:
            task = TASKS.get(kind, TASKS["editorial"]).format(**lengths)
        parts = [task, f"Moment: {m.summary}", f"Facts: {json.dumps(m.facts, ensure_ascii=False)}"]
        if b.insight and req.kind in ("analysis", "editorial"):
            parts.append(f"Stats desk: {b.insight}")
        if req.story:
            parts.append(f"Storyline: {req.story['text']}")
        if feed.follow and req.kind != "call":
            ctx = desk.player_context(feed.follow, m.tick)
            parts.append(f"{desk.name(feed.follow)} right now: {json.dumps(ctx, ensure_ascii=False)}")
        if req.graphic:
            g = json.loads(req.graphic)
            parts.append(f"(For your information, on screen with your line: {GRAPHIC_WORDS.get(g['type'], g['type'])}"
                         + (f" for {desk.name(g['player'])}" if g.get("player") else "") + ". Don't mention it.)")
        parts.append(f"Director: {req.angle}")
        parts.append(f"Your recent lines, oldest first: {json.dumps(list(booth.said[feed.id])[-12:], ensure_ascii=False)}")
        if feed.side is not None and m.team is not None and m.team != feed.side and m.kind in ("goal", "big_chance", "shot"):
            club = booth.desk.short[feed.side]
            parts.append(f"You support {club}, and this went against them: you are gutted, and it shows in how you say it "
                         "(a groan, a sigh, 'oh no'), while still saying what happened.")
        if note:
            parts.append(f"The director sent your first try back: {note}. Write it again.")
        parts.append(f"Write the line in {feed.lang.name}.")
        return "\n".join(parts)

    async def write(self, req: LineRequest) -> Line | None:
        booth, desk = self.booth, self.booth.desk
        feed = booth.feeds[req.feed]
        b, m = req.briefing, req.briefing.moment
        call = req.kind == "call"
        agent, model = (self.call_agent, self.models[0]) if call else (self.line_agent, self.models[1])
        loop = asyncio.get_running_loop()
        started = loop.time()
        # a call must be written and voiced before the viewer sees the moment
        budget = max(1.5, min(7.0, (req.at - booth.viewer_tick) / HZ - 2.0)) if call else MODEL_TIMEOUT
        allowed = set(m.players) | names_in(m.facts, desk) | names_in(b.insight or "", desk)
        if req.story:
            allowed |= set(req.story.get("players", [])) | names_in(req.story["text"], desk)
        if feed.follow:
            allowed.add(feed.follow)
        numbers = allowed_numbers(m.facts, b.insight or "", req.story["text"] if req.story else "",
                                  desk.player_context(feed.follow, m.tick) if feed.follow else {},
                                  json.loads(req.graphic) if req.graphic else {})
        limit = round((feed.aud.call_words if call else 45 if req.kind == "open" else feed.aud.max_words) * feed.lang.per_word)
        text, source, note = None, "ai", None
        for attempt in (0, 1):
            remaining = budget - (loop.time() - started)
            if remaining < (1.0 if call else 2.5):
                break
            try:
                r = await asyncio.wait_for(agent.run(self.prompt(req, feed, note), options=opts(model)), remaining)
                text = r.text.strip().strip('"“”«»')
            except Exception:
                text = None
                break
            if not text:
                break
            note = problem(text, feed, desk, allowed, numbers, limit)
            if note is None:
                break
            booth.note(m.tick, "Director", f"back to you: {note}", to=f"Commentator · {feed.name}", feed=feed.id, source="rules")
            text = None
            if call:
                break
        if not text:
            text, source = prepared_line(feed, req.kind, m, desk), "prepared"
            if text is None:
                return None
        booth.note(m.tick, f"Commentator · {feed.name}", text, to="Voice", feed=feed.id, source=source)
        return Line(feed.id, text, req, source)


# ------------------------------------------------------------------ voices


class VoiceExecutor(Executor):
    """Azure AI Speech reads the line in the feed's voice and books it into the feed's rundown."""

    def __init__(self, booth: Booth, feed_id: str):
        super().__init__(id=f"voice_{feed_id}")
        self.booth = booth
        self.feed_id = feed_id

    @handler
    async def take(self, line: Line, ctx: WorkflowContext[None, Cue]) -> None:
        booth = self.booth
        feed = booth.feeds[line.feed]
        req = line.request
        m = req.briefing.moment
        try:
            audio, seconds = await booth.voices.say(feed, line.text, excited=req.excited)
        except Exception:
            audio, seconds = None, booth.voices.estimate(feed, line.text)
            booth.note(m.tick, "Voice", "no audio for this line, captions only", feed=feed.id, source="rules")
        if req.kind == "call":
            at = max(req.at, booth.viewer_tick + 4)
            if at > req.latest:
                at = None
        elif req.kind == "open":
            at = req.at                        # said before kick-off while the picture waits
        else:
            at = booth.fit(feed.id, max(req.at, booth.viewer_tick + 4), seconds, owner=m.id, latest=req.latest,
                           open_play=req.kind in ("filler", "story", "follow", "read"))
        if at is None:
            if req.kind in ("analysis", "editorial"):
                booth.note(m.tick, "Director", "no room on air for that line, dropped", feed=feed.id, source="rules")
            return
        if req.kind != "open":                # the opening is said while the picture waits, so it takes no match time
            booth.book(feed.id, at, seconds, m.id)
        booth.said[feed.id].append(line.text)
        if req.say_score or (req.kind == "call" and m.kind in ("goal", "half_time", "full_time")) or m.kind == "kickoff":
            booth.last_score[feed.id] = at
        if req.story:
            booth.use_story(feed.id, req.story, at)
        stage = req.briefing.stage
        if req.graphic:
            g = json.loads(req.graphic)
            booth.last_graphic[feed.id] = at
            await ctx.yield_output(Cue(f"g-{feed.id}-{m.id}-{stage}", feed.id, at, "graphic", m.kind, graphic=g, source=line.source))
        await ctx.yield_output(Cue(f"l-{feed.id}-{m.id}-{stage}", feed.id, at, "line", m.kind, text=line.text, audio=audio,
                                   seconds=round(seconds, 2), excited=req.excited, interrupt=req.interrupt, source=line.source))


def player_name(feed: Feed, desk, pid: str) -> str:
    return local_name(feed.lang, pid, desk.players[pid]["name"])
