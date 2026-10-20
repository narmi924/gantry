"""The match editor: at half-time and full-time, cuts a highlights package and writes the report.

Every feed watches the same clips at the same time (they share one picture), but
each gets its own camera angle, its own narration in its own language, and its
own report.
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from agent_framework import Agent, Executor, WorkflowContext, handler
from pydantic import BaseModel

from .crew import DEFAULT_REPLAY, HZ, MODEL_TIMEOUT, Booth, Cue, EditorBrief


Angle = Literal["behind_goal", "high", "follow", "reverse"]


class ClipLine(BaseModel):
    feed: str
    line: str
    angle: Angle


class ReelClip(BaseModel):
    tick: int
    why: str
    lines: list[ClipLine]


class FeedReport(BaseModel):
    feed: str
    headline: str
    summary: str
    star_player: str | None = None


class EditorPlan(BaseModel):
    clips: list[ReelClip]
    reports: list[FeedReport]


class EditorExecutor(Executor):
    """Builds the half-time and full-time packages."""

    def __init__(self, booth: Booth, agent: Agent, total_ticks: int):
        super().__init__(id="editor")
        self.booth = booth
        self.agent = agent
        self.total = total_ticks

    def material(self, tick: int) -> dict:
        desk = self.booth.desk
        moments = []
        for e in desk.events_before(tick, tick + 1):
            if e["type"] == "goal" or (e["type"] == "shot" and e.get("xg", 0) >= 0.2) or e["type"] == "substitution":
                m = desk._from_event(e)
                if m:
                    moments.append({"tick": m.tick, "kind": m.kind, "summary": m.summary,
                                    "facts": {k: v for k, v in m.facts.items() if k in ("build_up", "xg", "speed_kmh", "minute", "score")}})
        stats = desk.stats.team_stats(tick)
        players = sorted(desk.stats.players(tick), key=lambda p: (p["goals"] * 3 + p["assists"] * 2 + p["shots"] * 0.3 + p["tackles"] * 0.2 + p["distance_km"] * 0.1), reverse=True)[:6]
        for p in players:
            p["name"] = desk.name(p["player"])
        return {"moments": moments[-14:], "teams": desk._team_facts(stats), "score": desk.match.score_at(tick), "top_players": players}

    @handler
    async def take(self, brief: EditorBrief, ctx: WorkflowContext[None, Cue]) -> None:
        booth, m = self.booth, brief.moment
        when = "half-time" if m.kind == "half_time" else "full-time"
        feeds = list(booth.feeds.values())
        stuff = self.material(m.tick)
        booth.note(m.tick, "Editor", f"cutting the {when} package from {len(stuff['moments'])} moments", to="Director")
        prompt = (
            f"It is {when}. Material from the stats desk:\n{json.dumps(stuff, ensure_ascii=False)}\n"
            f"Feeds: {json.dumps([{'feed': f.id, 'language': f.language, 'audience': f.audience, 'style': f.persona} for f in feeds], ensure_ascii=False)}\n"
            "Cut a highlights package of 3 to 5 clips in match order, always including every goal. For each clip give "
            "its tick, why it is in, and for every feed a narration line in that feed's language (at most 20 words, or "
            "30 Chinese characters; it plays over the clip) and a camera angle (behind_goal, high, follow, reverse). "
            "Then write each feed's report: a headline and a summary of at most 60 words (90 Chinese characters) in "
            "its language and style, and a player of the match. Use only numbers in the material. Keep every player "
            "and team name exactly as written in the material, in English, even in Chinese text."
        )
        try:
            r = await asyncio.wait_for(self.agent.run(prompt, options={"response_format": EditorPlan, "reasoning": {"effort": "low"}}),
                                       MODEL_TIMEOUT * 4)
            plan: EditorPlan = r.value
            source = "ai"
        except Exception:
            plan, source = self.prepared(stuff, feeds, when), "prepared"

        # voice every line of the package at once
        async def voice(feed_id: str, text: str):
            feed = booth.feeds.get(feed_id)
            if not feed:
                return None
            try:
                audio, seconds = await booth.voices.say(feed, text)
                return {"text": text, "audio": audio, "seconds": round(seconds, 2)}
            except Exception:
                return {"text": text, "audio": None, "seconds": max(2.0, len(text) / 15)}

        clips = []
        jobs = []
        for c in sorted(plan.clips, key=lambda c: c.tick)[:5]:
            if not 0 < c.tick <= m.tick:
                continue
            desk = booth.desk
            # the clip is about whoever took the shot, and the move his team built
            near = [e for e in desk.events_before(c.tick + 3, 8) if e["type"] in ("shot", "goal")]
            shot = near[-1] if near else None
            team = shot["team"] if shot else next((e.get("team") for e in desk.events_before(c.tick, 5) if e.get("team") is not None), 0)
            focus = shot.get("player") if shot else None
            build = desk.build_up(c.tick, team)
            start = max(c.tick - 80, c.tick - int(float(build.get("seconds", 6)) * HZ) - 10)
            clip = {"from": start, "to": c.tick + 25, "team": team, "focus": focus, "why": c.why, "angles": {}, "lines": {}}
            for line in c.lines:
                clip["angles"][line.feed] = line.angle
                jobs.append((clip, line.feed, voice(line.feed, line.line)))
            for f in feeds:
                clip["angles"].setdefault(f.id, DEFAULT_REPLAY.get(f.id, "high"))
            clips.append(clip)
        results = await asyncio.gather(*(j[2] for j in jobs))
        for (clip, feed_id, _), res in zip(jobs, results):
            if res:
                clip["lines"][feed_id] = res
        reports = {rep.feed: {"headline": rep.headline, "summary": rep.summary,
                              "star": booth.desk.player_id(rep.star_player)} for rep in plan.reports}
        booth.note(m.tick, "Editor", f"{len(clips)} clips: " + "; ".join(c["why"] for c in clips), to="Crew", source=source)
        # the viewer's picture waits at the whistle for the package, so it goes on air as soon as it is ready
        at = min(m.tick, self.total - 1) - 1
        await ctx.yield_output(Cue(f"reel-{m.id}", "*", at, "reel", m.kind,
                                   reel={"clips": clips, "reports": reports, "when": m.kind}, source=source))

    @staticmethod
    def prepared(stuff: dict, feeds, when: str) -> EditorPlan:
        """If the editor can't answer in time: the goals, with plain lines, and the score."""
        score = stuff["score"]
        clips = []
        for mo in stuff["moments"]:
            if mo["kind"] == "goal":
                lines = [ClipLine(feed=f.id, angle="behind_goal",
                                  line=(mo["summary"] if not f.language.startswith("zh") else "进球回顾。")) for f in feeds]
                clips.append(ReelClip(tick=mo["tick"], why="goal", lines=lines))
        reports = [FeedReport(feed=f.id, headline=f"Kingsmere {score[0]}-{score[1]} Ashvale",
                              summary=f"That's {when}.") for f in feeds]
        return EditorPlan(clips=clips, reports=reports)
