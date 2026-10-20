"""Ask your broadcast: a viewer asks a question, the crew answers on their feed.

The question goes to the producer agent, which looks things up with the stats
desk's tools, picks the moment worth showing again, and writes a spoken answer
in the feed's language. The director's replay and the commentator's voice put
it on air, so the answer arrives the way everything else on the feed does.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Literal

from agent_framework import Agent
from pydantic import BaseModel

from .crew import HZ, Cue, MODEL_TIMEOUT

ANGLES = Literal["none", "behind_goal", "high", "follow", "reverse"]


class Answer(BaseModel):
    answer: str
    replay_tick: int | None = None
    replay_angle: ANGLES = "none"
    focus_player: str | None = None


def producer(session) -> Agent:
    booth = session.booth
    desk = booth.desk

    def key_moments() -> list:
        """Goals, big chances, cards and substitutions so far, each with its minute and tick (use the tick to replay it)."""
        now = booth.viewer_tick
        out = []
        for e in desk.events_before(now, now + 1):
            if e["type"] == "goal" or (e["type"] == "shot" and e.get("xg", 0) >= 0.25) or e["type"] in ("yellow_card", "substitution"):
                m = desk._from_event(e)
                if m:
                    out.append({"tick": m.tick, "kind": m.kind, "minute": m.facts.get("minute") or round(e["clock"] / 60),
                                "summary": m.summary, "players": [desk.name(p) for p in m.players]})
        return out[-20:]

    def how_it_happened(tick: int) -> dict:
        """How the attack that ended at `tick` was built: passes, runs, how the ball was won and how fast."""
        now = booth.viewer_tick
        if tick > now:
            return {"error": "that has not happened yet"}
        team = next((e.get("team") for e in desk.events_before(tick, 5) if e.get("team") is not None), 0)
        return desk.build_up(tick, team)

    def right_now() -> dict:
        """What is happening this second: who has the ball, where on the pitch it is, which way they are attacking, the score and the minute."""
        now = booth.viewer_tick
        m = desk.play(now)
        if m is None:
            score = session.loaded.match.score_at(now)
            return {"ball": "loose or out of play", "score": f"Kingsmere {score[0]}-{score[1]} Ashvale"}
        return m.facts

    tools = [*desk.tools(lambda: booth.viewer_tick), key_moments, how_it_happened, right_now]
    return Agent(
        session.crew.smart, name="producer", tools=tools,
        instructions=(
            "You are the producer of a live football broadcast. A viewer has asked their feed a question. Look up what "
            "you need with the tools, then answer the way that feed's commentator would say it on air: spoken, "
            "concrete, at most 45 words (or 70 Chinese characters). Use only numbers from the tools. If a past moment "
            "answers the question best, give its tick in replay_tick and choose a replay angle (behind_goal for a "
            "finish, high for the shape of a move, follow for one player's run, reverse for a fresh look) and the "
            "player to focus on. If the question is about something that has not happened yet, say so kindly."
        ),
    )


# a public demo: questions cost model time, so answer a few at once and not too often per viewer
ANSWERING = asyncio.Semaphore(4)
MIN_GAP_SECONDS = 8.0


async def ask(session, feed_id: str, question: str):
    booth = session.booth
    feed = booth.feeds.get(feed_id)
    if feed is None:
        return
    now_wall = asyncio.get_running_loop().time()
    if session.asking or now_wall - session.last_question < MIN_GAP_SECONDS:
        await session.send({"type": "answer", "feed": feed_id, "question": question,
                            "answer": "One question at a time — ask again in a few seconds."})
        return
    session.asking = True
    session.last_question = now_wall
    try:
        async with ANSWERING:
            await _answer(session, feed, feed_id, question)
    finally:
        session.asking = False


async def _answer(session, feed, feed_id: str, question: str):
    booth = session.booth
    now = booth.viewer_tick
    who = f"Viewer · {feed.name}"
    booth.note(now, who, question, to="Producer", feed=feed_id)
    booth.kinds[now] = "question"
    await session.flush_talk()

    if session.producer is None:
        session.producer = producer(session)
    score = session.loaded.match.score_at(now)
    clock = float(session.loaded.frames[min(now, len(session.loaded.frames) - 1), 1])
    prompt = (f"Feed: {feed.name}. Audience: {feed.audience}\nAnswer in this language: {feed.language}.\n"
              f"Match minute now: {int(clock // 60) + 1}, score Kingsmere {score[0]}-{score[1]} Ashvale.\n"
              f"The viewer asks: {question}")
    try:
        r = await asyncio.wait_for(session.producer.run(prompt, options={"response_format": Answer, "reasoning": {"effort": "low"}}),
                                   MODEL_TIMEOUT * 3)
        ans: Answer = r.value
        source = "ai"
    except Exception:
        zh = feed.language.startswith("zh")
        ans = Answer(answer="这个问题我们稍后在演播室回答。" if zh else "Good question — we'll come back to that in the studio.")
        source = "prepared"
    booth.note(now, "Producer", ans.answer, to=f"Commentator · {feed.name}", feed=feed_id, source=source)

    # air it: a replay of the moment if there is one, with the answer spoken over it
    at = booth.viewer_tick + 12
    if ans.replay_tick is not None and 0 < ans.replay_tick <= booth.viewer_tick:
        desk = booth.desk
        team = next((e.get("team") for e in desk.events_before(ans.replay_tick, 5) if e.get("team") is not None), 0)
        build = desk.build_up(ans.replay_tick, team)
        start = max(ans.replay_tick - 95, ans.replay_tick - int(float(build.get("seconds", 8)) * HZ) - 15)
        angle = ans.replay_angle if ans.replay_angle != "none" else "high"
        focus = desk.player_id(ans.focus_player)
        booth.note(now, "Director", f"replay for the question, {angle.replace('_', ' ')}", to="Replay", feed=feed_id, source=source)
        await session.send({"type": "cues", "cues": [asdict(Cue(f"qr-{feed_id}-{now}", feed_id, at, "replay", "question",
                                                             replay={"from": start, "to": ans.replay_tick + 12, "angle": angle,
                                                                     "focus": focus, "speed": 0.7, "team": team},
                                                             source=source))]})
        at += 8
    try:
        audio, seconds = await booth.voices.say(feed, ans.answer, excited=False)
    except Exception:
        audio, seconds = None, max(2.0, len(ans.answer) / 15)
    at = max(at, booth.viewer_tick + 6)
    booth.on_air_until[feed_id] = at + int(seconds * HZ)
    booth.busy_until[feed_id] = at + int(seconds * HZ)
    await session.send({"type": "cues", "cues": [asdict(Cue(f"qa-{feed_id}-{now}", feed_id, at, "line", "question",
                                                         text=ans.answer, audio=audio, seconds=round(seconds, 2),
                                                         source=source))]})
    await session.send({"type": "answer", "feed": feed_id, "question": question, "answer": ans.answer})
    await session.flush_talk()
