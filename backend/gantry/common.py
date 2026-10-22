"""Constants and small helpers shared by the simulator, the stats and the crew."""

from __future__ import annotations

HZ = 10                  # frames per second of tracking data
L, W = 105.0, 68.0       # pitch length and width in metres


def minute_label(clock: float, period: int) -> str:
    """The minute as broadcasters show it: 29:18 is the 30th minute, 92:10 is 90+3'."""
    base = 45 if period == 1 else 90
    m = int(clock // 60) + 1
    return f"{base}+{m - base}'" if m > base else f"{m}'"


def minute_number(clock: float) -> int:
    return int(clock // 60) + 1
