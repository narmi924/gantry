"""The things that would ruin the demo if they broke. None of these needs Azure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gantry.crew.booth import Booth
from gantry.crew.desk import StatsDesk
from gantry.crew.feeds import DEFAULT_FEEDS, feed
from gantry.crew.house import allowed_numbers, problem
from gantry.server import load

PRODUCTION = Path(__file__).resolve().parents[1] / "data" / "productions" / f"demo-{'+'.join(sorted(DEFAULT_FEEDS))}" / "rundown.json"


@pytest.fixture(scope="module")
def desk():
    loaded = load("demo")
    return StatsDesk(loaded.stats, loaded.events)


def test_every_moment_has_one_stable_id(desk):
    ids = [m.id for m in desk.all]
    assert len(ids) == len(set(ids))
    again = StatsDesk.__new__(StatsDesk)          # found again from scratch, the same moments come out
    loaded = load("demo")
    again.__init__(loaded.stats, loaded.events)
    assert [m.id for m in again._find_moments()] == ids


def test_every_goal_and_the_opening_are_moments(desk):
    goals = [e["tick"] for e in desk.events if e["type"] == "goal"]
    assert [m.tick for m in desk.all if m.kind == "goal"] == goals
    assert desk.all[0].kind == "open" and desk.all[0].tick == 1


def test_nothing_is_said_after_the_final_whistle(desk):
    end = desk.match.meta["periods"][-1]["end_tick"]
    assert not [m for m in desk.all if m.kind in ("spell", "play") and m.tick > end - 20]


def test_a_big_moment_keeps_its_air(desk):
    booth = Booth({f: feed(f) for f in DEFAULT_FEEDS}, desk, None)
    booth.hold("goal-1000", 995, 1300)
    assert booth.fit("casual_en", 1000, 3.0, owner="play-1000", open_play=True) is None or \
        booth.fit("casual_en", 1000, 3.0, owner="play-1000", open_play=True) >= 1300
    assert booth.fit("casual_en", 1003, 3.0, owner="goal-1000") == 1003


def test_a_moment_being_written_keeps_its_air_from_open_play_only(desk):
    booth = Booth({f: feed(f) for f in DEFAULT_FEEDS}, desk, None)
    booth.hold("card-2000", 1990, 2140, soft=True, feeds=("casual_en",))
    assert booth.fit("casual_en", 2000, 3.0, open_play=True, latest=2100) is None
    assert booth.fit("casual_en", 2000, 3.0, latest=2100) == 2000
    assert booth.fit("analyst_en", 2000, 3.0, open_play=True, latest=2100) == 2000


def test_lines_with_invented_facts_go_back(desk):
    f = feed("casual_en")
    allowed = {"KSM-10", "KSM-3"}
    numbers = allowed_numbers({"minute": "30'", "score": "Kingsmere 1-0 Ashvale", "finish": {"distance_m": 7}})
    assert problem("Aldana scores from seven metres!", f, desk, allowed, numbers, 20) is None
    assert problem("Aldana and Varga combine, 1-0 Kingsmere.", f, desk, allowed, numbers, 20) is None
    assert "not part of this moment" in problem("Sandell can't stop Aldana!", f, desk, allowed, numbers, 20)
    assert "not in the facts" in problem("Aldana scores from 25 metres!", f, desk, allowed, numbers, 20)
    assert "symbol" in problem("Aldana scores at 30'!", f, desk, allowed, numbers, 20)
    assert "never says" in problem("Kingsmere probing again.", f, desk, allowed, numbers, 20)


@pytest.mark.parametrize("fid, ok", [
    ("home_en", True), ("analyst_zh", True), ("home_es.ASH.ASH-7.speed", True), ("casual_fr.-.KSM-9.-", True),
    ("home_en.-.-.-", False), ("casual_xx", False), ("audio_en.KSM.KSM-10.height", False), ("analyst_en.ZZZ.-.-", False),
])
def test_feed_ids(fid, ok):
    assert (feed(fid) is not None) == ok


def test_the_picture_streams_and_seeks():
    from fastapi.testclient import TestClient

    from gantry.server import app

    with TestClient(app) as client, client.websocket_connect("/ws/matches/demo") as ws:
        assert json.loads(ws.receive_text())["type"] == "hello"
        assert json.loads(ws.receive_text())["type"] == "state"
        ws.send_text(json.dumps({"type": "seek", "tick": 17000}))
        ticks = []
        for _ in range(40):
            msg = json.loads(ws.receive_text())
            if msg["type"] == "frames" and msg["frames"]:
                ticks.append(msg["frames"][-1][0])
            if len(ticks) >= 3:
                break
        assert ticks and ticks[-1] >= 17000 and ticks == sorted(ticks)


@pytest.mark.skipif(not PRODUCTION.exists(), reason="the match hasn't been produced on this machine")
def test_the_production_calls_every_goal_on_the_moment(desk):
    rundown = json.loads(PRODUCTION.read_text(encoding="utf-8"))
    for m in (m for m in desk.all if m.kind == "goal"):
        calls = [c for c in rundown[m.id]["cues"] if c["kind"] == "line" and c["id"].endswith("-call")]
        assert {c["feed"] for c in calls} == set(DEFAULT_FEEDS), m.id
        assert all(0 <= c["tick"] - m.tick <= 10 for c in calls), m.id
