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

from ..common import HZ
from .booth import Booth
from .feeds import local_name
from .house import GENERAL_RULES, allowed_numbers, names_in, problem, reel_goal_line, score_line
from .messages import Cue, EditorBrief
from .roles import DEFAULT_REPLAY, MODEL_TIMEOUT, opts

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

    def __init__(self, booth: Booth, agent: Agent, total_ticks: int, model: str):
        super().__init__(id="editor")
        self.booth = booth
        self.agent = agent
        self.total = total_ticks
        self.model = model

    def material(self, tick: int) -> dict:
        """Every goal, then the biggest chances and the changes, in match order."""
        desk = self.booth.desk
        moments = [m for m in desk.scan(-1, tick) if m.kind in ("goal", "big_chance", "substitution")]
        goals = [m for m in moments if m.kind == "goal"]
        chances = sorted((m for m in moments if m.kind == "big_chance"), key=lambda m: -m.facts["finish"]["xg"])[:8]
        subs = [m for m in moments if m.kind == "substitution"][:4]
        keep = sorted(goals + chances + subs, key=lambda m: m.tick)
        out = [{"tick": m.tick, "kind": m.kind, "summary": m.summary,
                "facts": {k: v for k, v in m.facts.items() if k in ("minute", "build_up", "finish", "result", "score", "score_now", "what_it_means")}}
               for m in keep]
        stats = desk.stats.team_stats(tick)
        players = sorted(desk.stats.players(tick), key=lambda p: (p["goals"] * 3 + p["assists"] * 2 + p["shots"] * 0.3
                                                                   + p["tackles"] * 0.2 + p["distance_km"] * 0.1), reverse=True)[:6]
        top = [{"name": desk.name(p["player"]), "team": desk.short[p["team"]], "goals": p["goals"], "assists": p["assists"],
                "shots": p["shots"], "distance_km": p["distance_km"]} for p in players]
        stuff = {"moments": out, "goals": [m.summary for m in goals], "teams": desk.team_facts(stats),
                 "score": desk.score_text(tick), "top_players": top}
        if desk.match.season:
            # where this leaves the teams in the (fictional) league, and the milestones on the day
            stuff["league"] = {"before": {desk.short[i]: desk.standing(i) for i in (0, 1)},
                               "after_this_result": desk.table_if(desk.match.score_at(tick))}
            stuff["milestones"] = [f"{m.facts['scorer']['name']}: {m.facts['scorer_season']['milestone']}"
                                   for m in goals if (m.facts.get("scorer_season") or {}).get("milestone")]
        return stuff

    def name_sheet(self, feeds, stuff: dict) -> dict:
        """For feeds whose language writes names in its own script: how to write every name in the material."""
        desk = self.booth.desk
        text = json.dumps(stuff, ensure_ascii=False)
        pids = [pid for pid, p in desk.players.items() if p["name"] in text]
        return {f.id: {desk.players[pid]["name"]: local_name(f.lang, pid, desk.players[pid]["name"]) for pid in pids}
                for f in feeds if f.lang.native_names}

    @handler
    async def take(self, brief: EditorBrief, ctx: WorkflowContext[None, Cue]) -> None:
        booth, m = self.booth, brief.moment
        desk = booth.desk
        when = "half-time" if m.kind == "half_time" else "full-time"
        feeds = list(booth.feeds.values())
        stuff = self.material(m.tick)
        booth.note(m.tick, "Editor", f"cutting the {when} package from {len(stuff['moments'])} moments", to="Director")
        sheet = self.name_sheet(feeds, stuff)
        prompt = (
            f"It is {when}. Material from the stats desk:\n{json.dumps(stuff, ensure_ascii=False)}\n"
            f"Feeds: {json.dumps([{'feed': f.id, 'language': f.lang.name, 'audience': f.audience, 'style': f.persona} for f in feeds], ensure_ascii=False)}\n"
            + (f"Names in other scripts, per feed: {json.dumps(sheet, ensure_ascii=False)}\n" if sheet else "")
            + "Cut a highlights package of 3 to 5 clips in match order. Every goal must be a clip. For each clip give its "
              "tick, why it is in, and for every feed a narration line in that feed's language (at most 20 words, or 34 "
              "characters in Chinese; it plays over the clip) and a camera angle (behind_goal, high, follow, reverse). "
              "Then write each feed's report in its language and style: a headline and a summary of at most 60 words "
              "(100 characters in Chinese) that mentions every goal with its scorer (and, at full-time, what the result "
              "means for the league table and any milestone), and a player of the match. Use only "
              "names and numbers in the material, written the way that feed's language writes them. " + GENERAL_RULES
        )
        try:
            r = await asyncio.wait_for(self.agent.run(prompt, options={"response_format": EditorPlan, **opts(self.model, "low")}),
                                       MODEL_TIMEOUT * 5)
            plan: EditorPlan = r.value
            source = "ai"
        except Exception:
            plan, source = self.prepared(stuff, feeds, m.tick), "prepared"
        # every goal is in the package, whatever the plan says
        ticks = {c.tick for c in plan.clips}
        for mo in stuff["moments"]:
            if mo["kind"] == "goal" and not any(abs(t - mo["tick"]) < 30 for t in ticks):
                g = desk.get(f"goal-{mo['tick']}")
                plan.clips.append(ReelClip(tick=mo["tick"], why="goal", lines=[
                    ClipLine(feed=f.id, angle="behind_goal", line=reel_goal_line(f, desk, g.players[0], g.team)) for f in feeds]))

        async def voice(feed_id: str, text: str):
            feed = booth.feeds.get(feed_id)
            if not feed:
                return None
            try:
                audio, seconds = await booth.voices.say(feed, text)
                return {"text": text, "audio": audio, "seconds": round(seconds, 2)}
            except Exception:
                return {"text": text, "audio": None, "seconds": booth.voices.estimate(feed, text)}

        clips, jobs = [], []
        chosen = sorted(plan.clips, key=lambda c: c.tick)
        goals = [c for c in chosen if any(mo["kind"] == "goal" and abs(mo["tick"] - c.tick) < 30 for mo in stuff["moments"])]
        others = [c for c in chosen if c not in goals]
        for c in sorted(goals + others[:max(0, 5 - len(goals))], key=lambda c: c.tick):
            if not 0 < c.tick <= m.tick:
                continue
            # the clip is about whoever took the shot, from the moment his team won the ball
            near = [e for e in desk.events_before(c.tick + 3, 8) if e["type"] in ("shot", "goal")]
            shot = near[-1] if near else None
            team = shot["team"] if shot else next((e.get("team") for e in desk.events_before(c.tick, 5) if e.get("team") is not None), 0)
            focus = shot.get("player") if shot else None
            build = desk.build_up(c.tick, team)
            start = max(c.tick - 150, build.get("start_tick", c.tick - 80) - 20)
            clip = {"from": start, "to": c.tick + 25, "team": team, "focus": focus, "why": c.why, "angles": {}, "lines": {}}
            # every line is read before it goes out, like everything else on air
            mo = next((x for x in desk.scan(c.tick - 30, c.tick + 30) if x.kind in ("goal", "big_chance", "shot")), None)
            allowed = (set(mo.players) | names_in(mo.facts, desk)) if mo else names_in(stuff, desk)
            numbers = allowed_numbers(mo.facts if mo else stuff, stuff["score"])
            for line in c.lines:
                f = booth.feeds.get(line.feed)
                if f is None:
                    continue
                clip["angles"][line.feed] = line.angle
                text = line.line
                if problem(text, f, desk, allowed, numbers, round(24 * f.lang.per_word)) is not None:
                    text = reel_goal_line(f, desk, mo.players[0], mo.team) if mo and mo.kind == "goal" else None
                if text:
                    jobs.append((clip, line.feed, voice(line.feed, text)))
            for f in feeds:
                clip["angles"].setdefault(f.id, DEFAULT_REPLAY.get(f.aud.id, "high"))
            clips.append(clip)
        results = await asyncio.gather(*(j[2] for j in jobs))
        for (clip, feed_id, _), res in zip(jobs, results):
            if res:
                clip["lines"][feed_id] = res
        reports = {rep.feed: {"headline": rep.headline, "summary": rep.summary, "star": desk.player_id(rep.star_player)}
                   for rep in plan.reports if rep.feed in booth.feeds}
        booth.note(m.tick, "Editor", f"{len(clips)} clips: " + "; ".join(c["why"] for c in clips), to="Crew", source=source)
        # the viewer's picture waits at the whistle for the package, so it goes on air as soon as it is ready
        at = min(m.tick, self.total - 1) - 1
        await ctx.yield_output(Cue(f"reel-{m.id}", "*", at, "reel", m.kind,
                                   reel={"clips": clips, "reports": reports, "when": m.kind}, source=source))

    def prepared(self, stuff: dict, feeds, tick: int) -> EditorPlan:
        """If the editor can't answer in time: the goals, with plain lines, and the score."""
        desk = self.booth.desk
        clips = []
        for mo in stuff["moments"]:
            if mo["kind"] == "goal":
                g = desk.get(f"goal-{mo['tick']}")
                clips.append(ReelClip(tick=mo["tick"], why="goal", lines=[
                    ClipLine(feed=f.id, angle="behind_goal", line=reel_goal_line(f, desk, g.players[0], g.team)) for f in feeds]))
        goals = [desk.get(f"goal-{mo['tick']}") for mo in stuff["moments"] if mo["kind"] == "goal"]
        reports = []
        for f in feeds:
            score = score_line(f, desk, tick)
            lines = " ".join(reel_goal_line(f, desk, g.players[0], g.team) for g in goals)
            reports.append(FeedReport(feed=f.id, headline=score, summary=lines or score))
        return EditorPlan(clips=clips, reports=reports)


__all__ = ["EditorExecutor", "HZ"]
