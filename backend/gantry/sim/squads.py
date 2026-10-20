"""The two fictional clubs, their players and formations.

Everything here is invented. Attributes are on a 0..1 scale except `pace`,
which is the player's top speed in metres per second.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Player:
    id: str
    team: int
    number: int
    first: str
    last: str
    position: str
    pace: float
    passing: float
    shooting: float
    dribbling: float
    tackling: float
    stamina: float

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}"


@dataclass(frozen=True)
class Slot:
    """A place in the formation.

    `depth` runs from the back line (0) to the front line (1).
    `width` runs from the team's left touchline (0) to its right (1).
    """

    label: str
    depth: float
    width: float


@dataclass(frozen=True)
class Team:
    index: int
    name: str
    short: str
    code: str
    formation: str
    colors: dict
    slots: tuple[Slot, ...]
    players: tuple[Player, ...]
    starters: tuple[int, ...]
    bench: tuple[int, ...]
    by_number: dict = field(default_factory=dict, compare=False)

    def player(self, number: int) -> Player:
        return next(p for p in self.players if p.number == number)


def _p(team: int, code: str, number: int, first: str, last: str, position: str,
       pace: float, passing: float, shooting: float, dribbling: float,
       tackling: float, stamina: float = 0.75) -> Player:
    return Player(f"{code}-{number}", team, number, first, last, position,
                  pace, passing, shooting, dribbling, tackling, stamina)


FORMATION_433 = (
    Slot("GK", 0.0, 0.5),
    Slot("RB", 0.0, 0.92),
    Slot("RCB", 0.0, 0.64),
    Slot("LCB", 0.0, 0.36),
    Slot("LB", 0.0, 0.08),
    Slot("DM", 0.30, 0.5),
    Slot("RCM", 0.52, 0.70),
    Slot("LCM", 0.52, 0.30),
    Slot("RW", 0.93, 0.90),
    Slot("ST", 1.0, 0.5),
    Slot("LW", 0.93, 0.10),
)

FORMATION_4231 = (
    Slot("GK", 0.0, 0.5),
    Slot("RB", 0.0, 0.92),
    Slot("RCB", 0.0, 0.64),
    Slot("LCB", 0.0, 0.36),
    Slot("LB", 0.0, 0.08),
    Slot("RDM", 0.26, 0.62),
    Slot("LDM", 0.26, 0.38),
    Slot("RAM", 0.70, 0.88),
    Slot("CAM", 0.68, 0.5),
    Slot("LAM", 0.70, 0.12),
    Slot("ST", 1.0, 0.5),
)

K = "KSM"
KINGSMERE_PLAYERS = (
    _p(0, K, 1, "Elias", "Brandt", "GK", 7.4, 0.62, 0.10, 0.30, 0.20),
    _p(0, K, 2, "Kofi", "Mensah-Hale", "RB", 9.1, 0.72, 0.40, 0.66, 0.70, 0.86),
    _p(0, K, 5, "Ruben", "Calado", "CB", 8.3, 0.70, 0.35, 0.45, 0.84),
    _p(0, K, 6, "Marcus", "Oduya", "CB", 8.6, 0.66, 0.30, 0.40, 0.82),
    _p(0, K, 3, "Leo", "Varga", "LB", 9.0, 0.74, 0.38, 0.68, 0.68, 0.84),
    _p(0, K, 4, "Theo", "Lindqvist", "DM", 8.2, 0.84, 0.50, 0.60, 0.80, 0.88),
    _p(0, K, 8, "Sami", "Haddad", "CM", 8.6, 0.82, 0.62, 0.72, 0.66, 0.90),
    _p(0, K, 10, "Nico", "Aldana", "CM", 8.9, 0.92, 0.80, 0.88, 0.48, 0.80),
    _p(0, K, 7, "Kai", "Ferrante", "RW", 9.5, 0.74, 0.72, 0.86, 0.36),
    _p(0, K, 9, "Callum", "Rees", "ST", 9.0, 0.68, 0.86, 0.70, 0.34),
    _p(0, K, 11, "Idris", "Okonjo", "LW", 9.6, 0.72, 0.74, 0.84, 0.36),
    _p(0, K, 12, "Owen", "Pryce", "GK", 7.2, 0.55, 0.10, 0.25, 0.20),
    _p(0, K, 14, "Mateo", "Ibarra", "CM", 8.7, 0.80, 0.66, 0.74, 0.62),
    _p(0, K, 17, "Lucas", "Brennan", "CB", 8.4, 0.64, 0.30, 0.40, 0.80),
    _p(0, K, 19, "Ayo", "Bankole", "ST", 9.3, 0.62, 0.82, 0.74, 0.30),
    _p(0, K, 22, "Finn", "Calloway", "RW", 9.4, 0.70, 0.70, 0.80, 0.34),
)

A = "ASH"
ASHVALE_PLAYERS = (
    _p(1, A, 1, "Viktor", "Sandell", "GK", 7.3, 0.58, 0.10, 0.28, 0.20),
    _p(1, A, 2, "Jonah", "Pike", "RB", 8.9, 0.68, 0.34, 0.60, 0.72, 0.84),
    _p(1, A, 4, "Emeka", "Obi", "CB", 8.5, 0.62, 0.30, 0.38, 0.86),
    _p(1, A, 5, "Stefan", "Rusu", "CB", 8.2, 0.66, 0.28, 0.36, 0.84),
    _p(1, A, 3, "Marco", "Bellandi", "LB", 8.8, 0.70, 0.36, 0.62, 0.70, 0.84),
    _p(1, A, 6, "Aaron", "Whitlock", "DM", 8.1, 0.76, 0.42, 0.52, 0.84, 0.90),
    _p(1, A, 8, "Hugo", "Mercier", "DM", 8.4, 0.80, 0.54, 0.62, 0.74, 0.88),
    _p(1, A, 7, "Tobi", "Adekunle", "RW", 9.3, 0.70, 0.66, 0.80, 0.38),
    _p(1, A, 10, "Rafa", "Olmedo", "AM", 8.6, 0.88, 0.74, 0.84, 0.44),
    _p(1, A, 11, "Sean", "Maddox", "LW", 9.1, 0.68, 0.64, 0.76, 0.40),
    _p(1, A, 9, "Bruno", "Kessler", "ST", 8.8, 0.64, 0.84, 0.66, 0.36),
    _p(1, A, 13, "Pete", "Navarro", "GK", 7.1, 0.55, 0.10, 0.25, 0.20),
    _p(1, A, 15, "Liam", "Achterberg", "CB", 8.3, 0.62, 0.28, 0.36, 0.80),
    _p(1, A, 18, "Dani", "Ferreira-Cole", "CM", 8.6, 0.78, 0.60, 0.70, 0.66),
    _p(1, A, 20, "Kwame", "Osei", "LW", 9.8, 0.66, 0.76, 0.82, 0.32, 0.90),
    _p(1, A, 23, "Oscar", "Lindgren", "ST", 8.9, 0.60, 0.80, 0.62, 0.34),
)


def _team(index, name, short, code, formation, colors, slots, players, starters, bench):
    return Team(index, name, short, code, formation, colors, slots, players,
                tuple(starters), tuple(bench))


KINGSMERE = _team(
    0, "Kingsmere FC", "Kingsmere", "KSM", "4-3-3",
    {"shirt": "#1F4FD1", "shorts": "#1F4FD1", "socks": "#F4F6FB", "text": "#FFFFFF",
     "gk_shirt": "#2BB3A3", "gk_shorts": "#13544D"},
    FORMATION_433, KINGSMERE_PLAYERS,
    starters=(1, 2, 5, 6, 3, 4, 8, 10, 7, 9, 11),
    bench=(12, 14, 17, 19, 22),
)

ASHVALE = _team(
    1, "Ashvale Athletic", "Ashvale", "ASH", "4-2-3-1",
    {"shirt": "#F2A516", "shorts": "#1B2433", "socks": "#F2A516", "text": "#1B2433",
     "gk_shirt": "#B04FD8", "gk_shorts": "#2E1A3B"},
    FORMATION_4231, ASHVALE_PLAYERS,
    starters=(1, 2, 4, 5, 3, 6, 8, 7, 10, 11, 9),
    bench=(13, 15, 18, 20, 23),
)

TEAMS = (KINGSMERE, ASHVALE)
