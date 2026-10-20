"""The match script.

A real broadcast gets the match it gets. For the demo we want a match with a
shape: Kingsmere on top early, Ashvale changing their plan after an hour and
hitting back on the break, and a late winner. The director only nudges team
tactics and finishing; every pass, tackle and shot is still played out by the
engine.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tactics:
    press: float      # how high and hard the team presses, 0..1
    line: float       # how high the defensive line sits, 0..1
    risk: float       # appetite for forward, risky passes, 0..1
    counter: float    # urgency to go forward straight after winning the ball, 0..1
    composure: float = 0.6  # how well the side plays through pressure, 0..1


@dataclass(frozen=True)
class Phase:
    start: float      # match clock, seconds
    home: Tactics
    away: Tactics


@dataclass(frozen=True)
class GoalBeat:
    team: int
    start: float
    end: float


@dataclass(frozen=True)
class Substitution:
    after: float
    team: int
    off_number: int
    on_number: int


MIN = 60.0

DEMO_PHASES = (
    Phase(0, Tactics(0.75, 0.70, 0.50, 0.45, 0.70), Tactics(0.35, 0.35, 0.55, 0.55, 0.65)),
    Phase(46 * MIN, Tactics(0.60, 0.60, 0.50, 0.45, 0.65), Tactics(0.55, 0.50, 0.60, 0.65, 0.80)),
    Phase(60 * MIN, Tactics(0.50, 0.85, 0.60, 0.40, 0.55), Tactics(0.35, 0.25, 0.65, 0.95, 0.95)),
    Phase(84 * MIN, Tactics(0.90, 0.90, 0.85, 0.60, 0.60), Tactics(0.25, 0.15, 0.35, 0.80, 0.80)),
)

DEMO_GOALS = (
    GoalBeat(0, 24 * MIN, 41 * MIN),
    GoalBeat(1, 66 * MIN, 80 * MIN),
    GoalBeat(0, 90 * MIN + 20, 93 * MIN + 40),
)

DEMO_SUBS = (
    Substitution(59 * MIN, 1, 11, 20),
    Substitution(59 * MIN, 1, 6, 18),
    Substitution(74 * MIN, 0, 9, 19),
    Substitution(83 * MIN, 0, 7, 22),
)


class Director:
    def __init__(self, phases=DEMO_PHASES, goals=DEMO_GOALS, subs=DEMO_SUBS,
                 stoppage=(2 * MIN, 4 * MIN)):
        self.phases = phases
        self.goals = list(goals)
        self.subs = list(subs)
        self.stoppage = stoppage
        self.scored = [False] * len(self.goals)

    def tactics(self, team: int, clock: float) -> Tactics:
        current = self.phases[0]
        for phase in self.phases:
            if clock >= phase.start:
                current = phase
        return current.home if team == 0 else current.away

    def _open_beat(self, team: int, clock: float) -> int | None:
        for i, beat in enumerate(self.goals):
            if not self.scored[i] and beat.team == team and beat.start <= clock <= beat.end:
                return i
        return None

    def finishing(self, team: int, clock: float) -> float:
        """Multiplier on the chance that a shot goes in."""
        return 2.6 if self._open_beat(team, clock) is not None else 0.0

    def attacking_boost(self, team: int, clock: float) -> float:
        return 0.15 if self._open_beat(team, clock) is not None else 0.0

    def record_goal(self, team: int, clock: float) -> None:
        beat = self._open_beat(team, clock)
        if beat is not None:
            self.scored[beat] = True

    def missed_beats(self, clock: float) -> list[int]:
        return [i for i, b in enumerate(self.goals) if not self.scored[i] and clock > b.end]

    def due_subs(self, clock: float) -> list[Substitution]:
        due = [s for s in self.subs if clock >= s.after]
        for s in due:
            self.subs.remove(s)
        return due
