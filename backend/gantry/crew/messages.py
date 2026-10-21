"""What the crew hands each other, and what it puts on air."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from .desk import Moment

Stage = Literal["call", "analysis", "editorial", "filler"]
Angle = Literal["behind_goal", "high", "follow", "reverse"]
GraphicKind = Literal["none", "stats", "momentum", "player", "pitch"]


@dataclass
class Cut:
    """The gallery hands the crew one moment, for one part of its coverage."""
    moment: Moment
    stage: Stage


@dataclass
class Briefing:
    """What the stats desk tells the director about a moment."""
    moment: Moment
    stage: Stage
    insight: str | None = None
    insight_source: str = "ai"


@dataclass
class LineRequest:
    """What the director asks one feed's commentator for."""
    feed: str
    briefing: Briefing
    kind: str                  # call, analysis, editorial, story or filler
    angle: str                 # the director's direction for this line
    at: int                    # tick the line should go on air
    latest: int                # last tick it may still go on air
    excited: bool = False
    interrupt: bool = False    # a call cuts in over whatever is being said
    story: dict | None = None
    graphic: str | None = None  # what is on screen with the line
    say_score: bool = False     # this line should give the time and the score


@dataclass
class LineRequests:
    requests: list[LineRequest]


@dataclass
class Line:
    feed: str
    text: str
    request: LineRequest
    source: str                # "ai" or "prepared"


@dataclass
class EditorBrief:
    """Half-time or full-time: the moment the editor packages."""
    moment: Moment


@dataclass
class Cue:
    """One entry in the rundown: what a feed shows or says, and when."""
    id: str
    feed: str
    tick: int
    kind: str                  # "line", "graphic", "replay" or "reel"
    moment: str
    text: str | None = None
    audio: str | None = None
    seconds: float | None = None
    excited: bool = False
    interrupt: bool = False
    graphic: dict | None = None
    replay: dict | None = None
    reel: dict | None = None
    source: str = "ai"


class FeedPlan(BaseModel):
    feed: str
    speak: bool
    angle: str
    graphic: GraphicKind = "none"
    player: str | None = None
    story: str | None = None


class DirectorPlan(BaseModel):
    feeds: list[FeedPlan]
    talkback: str


class FeedReplay(BaseModel):
    feed: str
    angle: Angle
    second_angle: Literal["none", "behind_goal", "high", "follow", "reverse"] = "none"


class ReplayPlan(DirectorPlan):
    replays: list[FeedReplay]
