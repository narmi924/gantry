"""The broadcasts Gantry can produce from one match: who each is for, and in which language.

A feed is an audience (new fan, analyst, home fan following a player, audio
description) in one of eight languages. The default production is the four
audiences in English; a viewer can ask for any audience in any language, and
that feed is then entirely in that language: words, voice, names and graphics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "i18n"


@dataclass(frozen=True)
class Audience:
    id: str
    name: str                  # how the page labels this feed
    who: str                   # who is watching, in a sentence
    persona: str               # how the commentator for this audience talks
    graphics: tuple[str, ...]
    quiet_gap: float           # seconds of silence before a line about open play may go out
    story_every: float         # seconds between storyline lines
    max_words: int             # longest ordinary line
    call_words: int            # longest instant call
    follow: str | None = None  # player this feed follows
    side: int | None = None    # team this feed supports
    describes_play: bool = False
    banned: tuple[str, ...] = ()


CASUAL = Audience(
    id="casual", name="New fan",
    who="People new to football. They want to feel why a moment matters, not hear a list of numbers.",
    persona=(
        "You are the lead commentator for people who are new to football. You sound like a warm, clear TV commentator: "
        "short, vivid sentences. Make the viewer feel why a moment matters: who is winning, what just changed, what to "
        "watch for next. Use at most one number in a line, and say what it means. No jargon: never say xG, expected "
        "goals, PPDA, field tilt, low block or half-space; say what they mean in plain words. When a rule or a word "
        "comes up (a corner, a booking, a substitution, offside), explain it in one plain clause now and then. "
        "Lines in your style: \"Kingsmere are camped in Ashvale's half, and that's real pressure.\" \"That's "
        "Sandell's seventh save. He's the reason Ashvale are still in this.\" \"Keep an eye on Aldana: everything good "
        "Kingsmere do goes through him.\""
    ),
    graphics=("stats", "momentum", "player", "lineups"), quiet_gap=11, story_every=38, max_words=20, call_words=12,
    banned=("passing lane", "probing", "probe", "settles it", "steadies", "recycle", "recycling", "outlet", "it matters because",
            "this matters because", "patient", "on screen", "flashes"),
)

ANALYST = Audience(
    id="analyst", name="Analyst",
    who="Data-minded fans and coaches who want the tactical picture and the numbers behind it.",
    persona=(
        "You are the tactical analyst on co-commentary, for data-minded fans and coaches. Be precise, calm and specific. "
        "Each line names a mechanism and backs it with one or two numbers from the facts: how and where the ball was "
        "won, how many passes, how fast, pass difficulty (out of 100), expected goals, possession, the share of "
        "final-third passes, PPDA, how high a defensive line is. Prefer what the picture cannot show. Vary your "
        "vocabulary from line to line. "
        "Lines in your style: \"Kingsmere win it back high again: thirteen times in Ashvale's half in ten minutes.\" "
        "\"Ashvale's back four is sitting eight metres deeper than at the start of the half. That's the press "
        "working.\" \"The hard pass was Varga's, fifty-one out of a hundred for difficulty, and it opened the box.\""
    ),
    graphics=("stats", "momentum", "player", "pitch", "lineups"), quiet_gap=13, story_every=32, max_words=24, call_words=12,
    banned=("passing lane", "lanes", "probing", "probe", "it matters because", "this matters because", "settles it",
            "on screen"),
)

HOME = Audience(
    id="home", name="Following No. 10",
    who="Kingsmere supporters who follow their No. 10, Nico Aldana, wherever he is on the pitch.",
    persona=(
        "You are the Kingsmere fans' own commentator, following their No. 10, Nico Aldana. You are openly on "
        "Kingsmere's side and full of feeling, but you respect the opponent. Speak in short, lively sentences. "
        "Bring Aldana in only when the facts show he is involved (he has the ball, he is close to it, or he just did "
        "something) and not in every line, about one line in three at most; never invent what he is doing. When "
        "anyone scores, name the scorer. "
        "Lines in your style: \"Come on, Kingsmere! They can't get out of their own half!\" \"Aldana again, always "
        "wanting the ball. That's our number ten.\" \"Sandell is keeping them in it, but it's coming.\""
    ),
    graphics=("player", "stats", "lineups"), quiet_gap=9, story_every=36, max_words=20, call_words=12, follow="KSM-10", side=0,
    banned=("passing lane", "probing", "probe", "settles it", "steadies", "steady", "recycle", "recycling", "it matters because",
            "this matters because", "on screen", "for the numbers"),
)

AUDIO = Audience(
    id="audio", name="Audio described",
    who="Blind and partially sighted fans listening without the picture.",
    persona=(
        "You are the audio describer for blind and partially sighted fans, working like a radio commentator: you are "
        "their eyes. In open play keep a steady rhythm of short lines: who has the ball (surname and team), where it "
        "is (which third, which side, roughly how far from goal), which way they are attacking, and what just happened "
        "in the move. Give the time and the score only when the director asks for it. For a big moment say what "
        "happened first, then where. Vary the shape of your sentences and never start two lines the same way. Calm "
        "and clear; warmer and quicker for big moments. "
        "Lines in your style: \"Varga wins it back on the halfway line for Kingsmere.\" \"Okonjo now, wide on the "
        "left, thirty metres out, and he cuts inside.\" \"Ashvale knock it around at the back: Pike, Rusu, back to "
        "Sandell.\" \"Long ball from Whitlock, headed clear at the edge of the Kingsmere box.\""
    ),
    graphics=(), quiet_gap=1.2, story_every=120, max_words=20, call_words=16, describes_play=True,
    banned=("it matters because", "this matters because", "why this mattered", "nil-nil", "one-zero"),
)

AUDIENCES = {a.id: a for a in (CASUAL, ANALYST, HOME, AUDIO)}


@dataclass(frozen=True)
class Language:
    code: str
    name: str                  # in English, as the page shows it
    locale: str                # BCP-47, for the voice and for speech recognition
    voices: dict = field(default_factory=dict)   # audience id -> Azure neural voice
    styles: dict = field(default_factory=dict)   # voice -> (calm style, excited style)
    unit: str = "words"        # what a line's length is counted in
    per_word: float = 1.0      # how many units one English word is worth
    rtl: bool = False
    native_names: bool = False  # names written in this language's own script (from data/i18n/names.json)


LANGUAGES = {lang.code: lang for lang in (
    Language("en", "English", "en-GB",
             voices={"casual": "en-GB-RyanNeural", "analyst": "en-US-AndrewNeural", "home": "en-US-DavisNeural",
                     "audio": "en-GB-SoniaNeural"},
             styles={"en-GB-RyanNeural": (None, "cheerful"), "en-US-DavisNeural": ("chat", "excited")}),
    Language("es", "Spanish", "es-MX",
             voices={"casual": "es-MX-JorgeNeural", "analyst": "es-MX-JorgeNeural", "home": "es-MX-JorgeNeural",
                     "audio": "es-MX-DaliaNeural"},
             styles={"es-MX-JorgeNeural": ("chat", "cheerful")}),
    Language("pt", "Portuguese", "pt-BR",
             voices={"casual": "pt-BR-AntonioNeural", "analyst": "pt-BR-AntonioNeural", "home": "pt-BR-AntonioNeural",
                     "audio": "pt-BR-FranciscaNeural"}),
    Language("fr", "French", "fr-FR",
             voices={"casual": "fr-FR-HenriNeural", "analyst": "fr-FR-HenriNeural", "home": "fr-FR-HenriNeural",
                     "audio": "fr-FR-DeniseNeural"},
             styles={"fr-FR-HenriNeural": (None, "cheerful")}),
    Language("ar", "Arabic", "ar-SA",
             voices={"casual": "ar-SA-HamedNeural", "analyst": "ar-SA-HamedNeural", "home": "ar-SA-HamedNeural",
                     "audio": "ar-SA-ZariyahNeural"},
             rtl=True, native_names=True),
    Language("hi", "Hindi", "hi-IN",
             voices={"casual": "hi-IN-MadhurNeural", "analyst": "hi-IN-MadhurNeural", "home": "hi-IN-MadhurNeural",
                     "audio": "hi-IN-SwaraNeural"},
             native_names=True),
    Language("id", "Indonesian", "id-ID",
             voices={"casual": "id-ID-ArdiNeural", "analyst": "id-ID-ArdiNeural", "home": "id-ID-ArdiNeural",
                     "audio": "id-ID-GadisNeural"}),
    Language("zh", "Chinese", "zh-CN",
             voices={"casual": "zh-CN-YunjianNeural", "analyst": "zh-CN-YunjianNeural", "home": "zh-CN-YunjianNeural",
                     "audio": "zh-CN-XiaoxiaoNeural"},
             styles={"zh-CN-YunjianNeural": ("sports-commentary", "sports-commentary-excited")},
             unit="characters", per_word=1.7, native_names=True),
)}


METRICS = {
    "speed": "pace: top speeds and sprints",
    "distance": "distance covered",
    "passing": "passing: how many, how accurate, how difficult",
    "shots": "shooting: shots and expected goals",
}


@dataclass(frozen=True)
class Feed:
    id: str
    aud: Audience
    lang: Language
    club: int | None = None        # the team this viewer supports, if they chose one
    player: str | None = None      # the player this viewer follows, if they chose one
    metric: str | None = None      # the one number this viewer cares about
    label: str | None = None       # how the page names a viewer's own feed

    @property
    def custom(self) -> bool:
        return self.label is not None

    # the names the rest of the crew uses
    @property
    def name(self) -> str:
        base = self.label or self.aud.name
        return base if self.lang.code == "en" else f"{base} ({self.lang.name})"

    @property
    def language(self) -> str:
        return self.lang.locale

    @property
    def audience(self) -> str:
        return self.aud.who

    @property
    def persona(self) -> str:
        return self.aud.persona

    def persona_for(self, meta: dict) -> str:
        """The commentator's brief, with this viewer's club, player and number in it."""
        if not self.custom:
            return self.aud.persona
        teams = meta["teams"]
        players = {p["id"]: p for t in teams for p in t["players"]}
        club = teams[self.club]["short"] if self.club is not None else None
        p = players.get(self.player) if self.player else None
        if self.aud.id == "home" and club:
            text = (f"You are the {club} fans' own commentator"
                    + (f", following their No. {p['number']}, {p['name']}" if p else "")
                    + f". You are openly on {club}'s side and full of feeling, but you respect the opponent. Speak in "
                      "short, lively sentences. When anyone scores, name the scorer.")
        else:
            text = self.aud.persona
            if club and self.aud.id == "casual":
                text += f" This viewer supports {club}: be warm towards them, and fair to everyone."
        if p:
            text += (f" Bring {p['last']} in only when the facts show he is involved (he has the ball, he is close "
                     "to it, or he just did something), about one line in three at most; never invent what he is doing.")
        if self.metric:
            text += f" This viewer cares most about {METRICS[self.metric]}: when the facts give a new value for it, say it."
        return text

    @property
    def voice(self) -> str:
        return self.lang.voices[self.aud.id]

    @property
    def calm_style(self) -> str | None:
        return self.lang.styles.get(self.voice, (None, None))[0]

    @property
    def excited_style(self) -> str | None:
        return self.lang.styles.get(self.voice, (None, None))[1]

    @property
    def follow(self) -> str | None:
        return self.player if self.custom else self.aud.follow

    @property
    def side(self) -> int | None:
        return self.club if self.custom else self.aud.side

    @property
    def graphics(self) -> tuple[str, ...]:
        return self.aud.graphics

    def words(self, n: int) -> str:
        """A length limit in this language's own unit, e.g. '22 words' or '37 characters'."""
        return f"{round(n * self.lang.per_word)} {self.lang.unit}"


DEFAULT_FEEDS = ("casual_en", "analyst_en", "home_en", "audio_en")


CLUBS = {"KSM": 0, "ASH": 1}
METRIC_WORDS = {"speed": "pace", "distance": "distance", "passing": "passing", "shots": "shooting"}


def friendly(f: Feed, meta: dict) -> Feed:
    """A viewer's own feed, named the way they built it: 'Ashvale fan, following Adekunle, pace'."""
    if not f.custom:
        return f
    from dataclasses import replace

    teams = meta["teams"]
    players = {p["id"]: p for t in teams for p in t["players"]}
    who = {"home": "Fan", "casual": "New fan", "analyst": "Analyst", "audio": "Audio described"}[f.aud.id]
    if f.aud.id == "home" and f.club is not None:
        who = f"{teams[f.club]['short']} fan"
    parts = [who] + ([f"following {players[f.player]['last']}"] if f.player in players else [])         + ([METRIC_WORDS[f.metric]] if f.metric else [])
    return replace(f, label=", ".join(parts))


@lru_cache(maxsize=256)
def feed(feed_id: str) -> Feed | None:
    """Any audience in any language, e.g. 'home_es'; or a viewer's own feed, 'home_es.ASH.ASH-7.speed'
    (club, player to follow and number, each '-' for none). None if there is no such feed."""
    base, *extra = feed_id.split(".")
    aud, _, code = base.partition("_")
    if aud not in AUDIENCES or code not in LANGUAGES:
        return None
    if not extra:
        return Feed(feed_id, AUDIENCES[aud], LANGUAGES[code])
    if len(extra) != 3:
        return None
    club_code, player, metric = extra
    club = CLUBS.get(club_code) if club_code != "-" else None
    if (club_code != "-" and club is None) or (metric != "-" and metric not in METRICS):
        return None
    if player != "-" and not (player[:3] in CLUBS and player[3:4] == "-" and player[4:].isdigit()):
        return None
    if aud == "home" and club is None:
        return None
    player = None if player == "-" else player
    who = {"home": f"{club_code} fan" if club is not None else "Fan", "casual": "New fan", "analyst": "Analyst",
           "audio": "Audio described"}[aud]
    label = who + (f", following {player}" if player else "") + (f", {metric}" if metric != "-" else "")
    return Feed(feed_id, AUDIENCES[aud], LANGUAGES[code], club, player, None if metric == "-" else metric, label)


@lru_cache(maxsize=1)
def native_names() -> dict:
    path = DATA / "names.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def local_name(lang: Language, pid: str, english: str, short: bool = False) -> str:
    """A player's name as this language writes it."""
    if not lang.native_names:
        return english.split(" ")[-1] if short else english
    entry = native_names().get(lang.code, {}).get("players", {}).get(pid)
    if not entry:
        return english
    return entry["short"] if short else entry["full"]


def local_club(lang: Language, code: str, english_short: str, full: bool = False, english_full: str | None = None) -> str:
    if not lang.native_names:
        return (english_full or english_short) if full else english_short
    entry = native_names().get(lang.code, {}).get("clubs", {}).get(code)
    if not entry:
        return english_short
    return entry["full"] if full else entry["short"]
