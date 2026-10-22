"""Limits for a public demo, so a busy day can't run up the model bill or take the show down.

Set GANTRY_PUBLIC=1 when the app is on the internet. Then:
- the four default feeds play only what has been produced ahead of time (no model calls per viewer);
- any other feed (another language, a viewer's own feed) is made live, but only a few at once;
- each address gets a few connections and a question every so often;
- live model work across the whole server stops for the hour once it reaches a ceiling, and the
  show carries on from the production and prepared lines.
"""

from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict, deque

PUBLIC = os.environ.get("GANTRY_PUBLIC") == "1"
MAX_LIVE_SESSIONS = int(os.environ.get("GANTRY_MAX_LIVE", "2"))
MAX_CONNECTIONS_PER_IP = int(os.environ.get("GANTRY_MAX_CONNECTIONS", "4"))
QUESTIONS_PER_IP = (8, 600)          # questions, per this many seconds
LIVE_MOMENTS_PER_HOUR = int(os.environ.get("GANTRY_LIVE_PER_HOUR", "2500"))
MCP_QUESTIONS_PER_HOUR = int(os.environ.get("GANTRY_MCP_QUESTIONS_PER_HOUR", "60"))   # across every MCP client


class Guard:
    def __init__(self):
        self.connections: dict[str, int] = defaultdict(int)
        self.live_sessions = 0
        self.questions: dict[str, deque] = defaultdict(deque)
        self.live_moments: deque = deque()
        self.tickets: dict[str, float] = {}
        self.mcp_questions: deque = deque()

    # ------------------------------------------------------------ connections

    def connect(self, ip: str) -> bool:
        if PUBLIC and self.connections[ip] >= MAX_CONNECTIONS_PER_IP:
            return False
        self.connections[ip] += 1
        return True

    def disconnect(self, ip: str):
        self.connections[ip] = max(0, self.connections[ip] - 1)

    def start_live(self) -> bool:
        """A feed nobody has produced yet: made live, if there is room."""
        if PUBLIC and self.live_sessions >= MAX_LIVE_SESSIONS:
            return False
        self.live_sessions += 1
        return True

    def end_live(self):
        self.live_sessions = max(0, self.live_sessions - 1)

    # ------------------------------------------------------------ questions and model work

    def may_ask(self, ip: str) -> bool:
        if not PUBLIC:
            return True
        n, window = QUESTIONS_PER_IP
        q = self.questions[ip]
        now = time.monotonic()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= n:
            return False
        q.append(now)
        return True

    def may_ask_over_mcp(self, ip: str) -> bool:
        """A question to the crew from an MCP client: the same allowance per address as a viewer, and a ceiling
        across every client for the hour, since MCP needs no page and no connection."""
        if not PUBLIC:
            return True
        now = time.monotonic()
        while self.mcp_questions and now - self.mcp_questions[0] > 3600:
            self.mcp_questions.popleft()
        if len(self.mcp_questions) >= MCP_QUESTIONS_PER_HOUR or not self.may_ask(f"mcp:{ip}"):
            return False
        self.mcp_questions.append(now)
        return True

    def may_produce(self) -> bool:
        """One live moment of model work, if the hour's ceiling hasn't been reached."""
        now = time.monotonic()
        while self.live_moments and now - self.live_moments[0] > 3600:
            self.live_moments.popleft()
        if len(self.live_moments) >= LIVE_MOMENTS_PER_HOUR:
            return False
        self.live_moments.append(now)
        return True

    # ------------------------------------------------------------ speech tokens only for people watching

    def ticket(self) -> str:
        t = secrets.token_urlsafe(18)
        self.tickets[t] = 0.0
        return t

    def drop_ticket(self, t: str):
        self.tickets.pop(t, None)

    def use_ticket(self, t: str | None) -> bool:
        """A speech token at most every 20 seconds, for a viewer who is connected."""
        if not PUBLIC:
            return True
        if not t or t not in self.tickets:
            return False
        now = time.monotonic()
        if now - self.tickets[t] < 20:
            return False
        self.tickets[t] = now
        return True


guard = Guard()
