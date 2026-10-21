"""Ask your broadcast: a viewer asks a question, the crew answers on their feed.

The question goes to the producer agent, which looks things up with the stats
desk's tools, picks the moment worth showing again, and writes a spoken answer
in the feed's language. The director's replay and the commentator's voice put
it on air, so the answer arrives the way everything else on the feed does.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Literal

from agent_framework import Agent
from pydantic import BaseModel

from .house import answer_fallback, team_sheet
from .messages import Cue
from .roles import MODEL_TIMEOUT, opts

ANGLES = Literal["none", "behind_goal", "high", "follow", "reverse"]


class Answer(BaseModel):
    answer: str
    replay_tick: int | None = None
    replay_angle: ANGLES = "none"
    focus_player: str | None = None


def producer(session) -> Agent:
    def booth():
        return session.booth

    desk = session.desk

    def key_moments() -> list:
        """Goals, big chances, bookings and substitutions so far, each with its minute and tick (use the tick to replay it)."""
        now = booth().viewer_tick
        out = [{"tick": m.tick, "kind": m.kind, "minute": m.facts.get("minute"), "summary": m.summary,
                "players": [desk.name(p) for p in m.players]}
               for m in desk.scan(-1, now) if m.kind in ("goal", "big_chance", "card", "substitution")]
        return out[-20:]

    def how_it_happened(tick: int) -> dict:
        """How the attack that ended at `tick` was built: passes, runs, how the ball was won and how fast."""
        now = booth().viewer_tick
        if tick > now:
            return {"error": "that has not happened yet"}
        team = next((e.get("team") for e in desk.events_before(tick, 5) if e.get("team") is not None), 0)
        return desk.build_up(tick, team)

    def right_now() -> dict:
        """What is happening this second: who has the ball, where on the pitch it is, which way they are attacking, the score and the minute."""
        now = booth().viewer_tick
        m = desk.play(now)
        if m is None:
            return {"ball": "loose or out of play", "score": desk.score_text(now), "minute": desk.minute(now)}
        return m.facts

    tools = [*desk.tools(lambda: booth().viewer_tick), key_moments, how_it_happened, right_now]
    return Agent(
        session.crew.client("producer"), name="producer", tools=tools,
        instructions=(
            "You are the producer of a live football broadcast. A viewer has asked their feed a question. Look up what "
            "you need with the tools, then answer the way that feed's commentator would say it on air: spoken, "
            "concrete, at most 35 words (or 60 characters in Chinese), in the feed's language. Use only names and "
            "numbers from the tools. If a past moment answers the question best, give its tick in replay_tick, choose "
            "a replay angle (behind_goal for a finish, high for the shape of a move, follow for one player's run, "
            "reverse for a fresh look) and the player to focus on. If the question is about something that has not "
            "happened yet, say so kindly. If it is not about the match, steer back to the match in one sentence."
        ),
    )


# a public demo: questions cost model time, so answer a few at once and not too often per viewer
ANSWERING = asyncio.Semaphore(4)
MIN_GAP_SECONDS = 8.0


async def ask(session, feed_id: str, question: str):
    feed = session.booth.feeds.get(feed_id)
    if feed is None:
        return
    if not session.crew.ready:
        await session.send({"type": "answer", "feed": feed_id, "question": question,
                            "answer": "Questions need the live crew, which isn't set up on this server."})
        return
    now_wall = asyncio.get_running_loop().time()
    if session.asking or now_wall - session.last_question < MIN_GAP_SECONDS:
        await session.send({"type": "answer", "feed": feed_id, "question": question,
                            "answer": "One question at a time. Ask again in a few seconds."})
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
    desk = session.desk
    now = booth.viewer_tick
    booth.kinds[now] = "question"
    booth.note(now, f"Viewer · {feed.name}", question, to="Producer", feed=feed_id)
    await session.flush_talk()

    if session.producer is None:
        session.producer = producer(session)
    sheet = f"\n{team_sheet(feed, desk.match.meta)}" if feed.lang.native_names else ""
    prompt = (f"Feed: {feed.name}. Audience: {feed.audience}\nAnswer in {feed.lang.name}.{sheet}\n"
              f"Match minute now: {desk.minute(now)} (say it as a minute in {feed.lang.name}), score {desk.score_text(now)}.\n"
              f"The viewer asks: {question}")
    try:
        r = await asyncio.wait_for(session.producer.run(prompt, options={"response_format": Answer, **opts(session.crew.models["producer"], "low")}),
                                   MODEL_TIMEOUT * 3)
        ans: Answer = r.value
        source = "ai"
    except Exception:
        ans = Answer(answer=answer_fallback(feed))
        source = "prepared"
    booth.note(now, "Producer", ans.answer, to=f"Commentator · {feed.name}", feed=feed_id, source=source)

    # air it: a replay of the moment if there is one, with the answer spoken over it
    at = booth.viewer_tick + 12
    if ans.replay_tick is not None and 0 < ans.replay_tick <= booth.viewer_tick:
        team = next((e.get("team") for e in desk.events_before(ans.replay_tick, 5) if e.get("team") is not None), 0)
        build = desk.build_up(ans.replay_tick, team)
        start = max(ans.replay_tick - 110, build.get("start_tick", ans.replay_tick - 80) - 15)
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
        audio, seconds = None, booth.voices.estimate(feed, ans.answer)
    at = max(at, booth.viewer_tick + 6)
    booth.book(feed_id, at, seconds, f"question-{now}")
    await session.send({"type": "cues", "cues": [asdict(Cue(f"qa-{feed_id}-{now}", feed_id, at, "line", "question",
                                                         text=ans.answer, audio=audio, seconds=round(seconds, 2),
                                                         interrupt=True, source=source))]})
    await session.send({"type": "answer", "feed": feed_id, "question": question, "answer": ans.answer})
    await session.flush_talk()

