"""The booth: the crew's shared picture of what is on air, feed by feed.

Every line is booked into a slot on its feed. Big moments are held a few
seconds before they happen (the crew sees them 15 seconds early), so nothing
else is booked over a goal, its call, the roar and the replay.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..common import HZ
from .feeds import Feed

GAP = 4                      # ticks of air between two lines


@dataclass
class Slot:
    start: int
    end: int
    moment: str
    soft: bool = False         # kept for a moment still being written; only open-play lines must avoid it
    feeds: tuple = ()          # the feeds it applies to (all, if empty)


class Booth:
    def __init__(self, feeds: dict[str, Feed], desk, voices):
        self.feeds = feeds
        self.desk = desk
        self.voices = voices
        self.lines: dict[str, list[Slot]] = {f: [] for f in feeds}
        self.holds: list[Slot] = []
        self.said: dict[str, deque] = {f: deque(maxlen=20) for f in feeds}
        self.stories: dict[str, dict] = {f: {} for f in feeds}       # story id -> (tick, level)
        self.last_story: dict[str, int] = {f: -10**9 for f in feeds}
        self.last_graphic: dict[str, int] = {f: -10**9 for f in feeds}
        self.last_score: dict[str, int] = {f: -10**9 for f in feeds}
        self.turn: dict[str, int] = {}
        self.claims: dict[str, list[int]] = {f: [] for f in feeds}   # open-play lines asked for but not yet on air
        self.talk: deque = deque(maxlen=600)
        self.kinds: dict[int, str] = {}                              # moment tick -> kind, for grouping talkback
        self.notes = 0
        self.viewer_tick = 0
        self.speed = 1.0

    # ------------------------------------------------------------ air time

    def hold(self, moment: str, start: int, end: int, soft: bool = False, feeds: tuple = ()):
        """Keep [start, end) clear for one moment: on every feed for a big one (hard), or, while an editorial
        moment is still being written, clear of open-play lines on the feeds that will cover it (soft)."""
        self.holds.append(Slot(start, end, moment, soft, tuple(feeds)))
        if len(self.holds) > 300:
            self.holds = self.holds[-300:]

    def release(self, moment: str):
        """The moment is on air (or won't be): its soft hold is no longer needed."""
        self.holds = [h for h in self.holds if not (h.soft and h.moment == moment)]

    def _applies(self, h: Slot, feed: str, owner: str | None, open_play: bool) -> bool:
        return h.moment != owner and (open_play or not h.soft) and (not h.feeds or feed in h.feeds)

    def _clashes(self, feed: str, start: int, end: int, owner: str | None, open_play: bool = False):
        for s in self.lines[feed]:
            if s.start < end + GAP and start < s.end + GAP:
                yield s
        for h in self.holds:
            if self._applies(h, feed, owner, open_play) and h.start < end and start < h.end:
                yield h

    def fit(self, feed: str, earliest: int, seconds: float, owner: str | None = None, latest: int | None = None,
            open_play: bool = False) -> int | None:
        """The first tick from `earliest` where a line this long fits on the feed, or None if not before `latest`."""
        dur = max(1, int(seconds * HZ))
        t = earliest
        for _ in range(60):
            clash = list(self._clashes(feed, t, t + dur, owner, open_play))
            if not clash:
                return t if latest is None or t <= latest else None
            t = max(s.end for s in clash) + GAP
            if latest is not None and t > latest:
                return None
        return None

    def book(self, feed: str, at: int, seconds: float, moment: str) -> Slot:
        slot = Slot(at, at + max(1, int(seconds * HZ)), moment)
        lines = self.lines[feed]
        lines.append(slot)
        lines.sort(key=lambda s: s.start)
        if len(lines) > 400:
            del lines[:100]
        return slot

    def held(self, tick: int, feed: str | None = None, owner: str | None = None) -> bool:
        """Is this tick kept for some other moment (for an open-play line on `feed`)?"""
        return any(h.start <= tick < h.end and h.moment != owner and (not h.feeds or feed in h.feeds) for h in self.holds)

    def quiet_for(self, feed: str, tick: int) -> float:
        """Seconds since the last line on this feed ended, as of `tick` (counting lines booked for later as not quiet)."""
        last_end = -10**9
        for s in self.lines[feed]:
            if s.start <= tick + GAP:
                last_end = max(last_end, s.end)
            if s.start <= tick < s.end:
                return 0.0
        return max(0.0, (tick - last_end) / HZ)

    def next_line(self, feed: str, tick: int) -> int | None:
        nxt = [s.start for s in self.lines[feed] if s.start > tick]
        return min(nxt) if nxt else None

    def claim(self, feed: str, tick: int):
        """An open-play line has been asked for at this tick; the next one waits for it."""
        self.claims[feed] = [t for t in self.claims[feed] if abs(t - tick) < 120] + [tick]

    def claimed(self, feed: str, tick: int) -> bool:
        return any(abs(t - tick) < 80 for t in self.claims[feed])

    # ------------------------------------------------------------ stories and graphics

    def story_fresh(self, feed: str, story: dict, tick: int) -> bool:
        used = self.stories[feed].get(story["id"])
        if used is None:
            return True
        when, level = used
        return tick - when > 10 * 60 * HZ or story.get("level", 0) >= level + 2

    def use_story(self, feed: str, story: dict, tick: int):
        self.stories[feed][story["id"]] = (tick, story.get("level", 0))
        self.last_story[feed] = tick

    # ------------------------------------------------------------ talkback

    def note(self, tick: int, who: str, text: str, to: str | None = None, feed: str | None = None, source: str = "ai"):
        self.talk.append({"tick": tick, "who": who, "to": to, "text": text, "feed": feed, "source": source,
                          "moment": self.kinds.get(tick)})
        self.notes += 1
