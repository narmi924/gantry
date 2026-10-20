"""The four broadcasts Gantry produces from one match, and who each is for."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Feed:
    id: str
    name: str
    language: str              # BCP-47 tag, for the voice and the model's output
    audience: str              # who is watching, in a sentence
    persona: str               # how the commentator for this feed talks
    voice: str                 # Azure neural voice
    excited_style: str | None  # SSML speaking style for big moments, if the voice has one
    calm_style: str | None
    min_gap: float             # seconds of match time between ordinary lines
    max_words: int
    follow: str | None = None  # player id this feed follows
    side: int | None = None    # team this feed supports
    graphics: tuple[str, ...] = field(default_factory=tuple)


CASUAL_EN = Feed(
    id="casual_en",
    name="New fan",
    language="en-GB",
    audience="People new to football, watching in English. They want to know why a moment matters, not a list of numbers.",
    persona=(
        "You are the lead TV commentator for fans who are new to football. Speak in short, vivid, natural sentences. "
        "Explain why a moment matters in plain words. Use at most one number in a line, and only numbers given to you. "
        "No jargon such as xG, PPDA or field tilt; say what they mean instead."
    ),
    voice="en-GB-RyanNeural",
    excited_style=None,
    calm_style=None,
    min_gap=11.0,
    max_words=20,
    graphics=("stats", "momentum", "player"),
)

ANALYST_EN = Feed(
    id="analyst_en",
    name="Analyst",
    language="en-US",
    audience="Data-minded fans and coaches who want the tactical picture and the numbers behind it.",
    persona=(
        "You are a tactical analyst on co-commentary. Be precise and calm. Name the mechanism: pressing, space, "
        "overloads, passing lanes. Use the numbers you are given (xG, pass difficulty, speeds, possession, field tilt, "
        "PPDA) and never invent one."
    ),
    voice="en-US-AndrewNeural",
    excited_style=None,
    calm_style=None,
    min_gap=13.0,
    max_words=24,
    graphics=("stats", "momentum", "player", "pitch"),
)

HOME_ZH = Feed(
    id="home_zh",
    name="Kingsmere fans, following No. 10",
    language="zh-CN",
    audience="海外的 Kingsmere 球迷，用中文看球，最关心 10 号 Nico Aldana。",
    persona=(
        "你是 Kingsmere 的主队中文解说，观众是海外的 Kingsmere 球迷，他们最喜欢 10 号 Nico Aldana。"
        "说口语化的中文短句，情绪饱满，明显偏向 Kingsmere，但不说对手坏话。多讲 Aldana 在做什么。"
        "球员名字保留英文。只用给你的数字，不要编。"
    ),
    voice="zh-CN-YunjianNeural",
    excited_style="sports-commentary-excited",
    calm_style="sports-commentary",
    min_gap=10.0,
    max_words=40,
    follow="KSM-10",
    side=0,
    graphics=("player", "stats"),
)

AUDIO_EN = Feed(
    id="audio_en",
    name="Audio description",
    language="en-GB",
    audience="Blind and partially sighted fans listening without the picture.",
    persona=(
        "You describe the match for blind and partially sighted fans, like a radio commentator. Always say where the "
        "ball is (which third, which wing, how far from goal), which team has it and which way they are attacking, "
        "and who is on the ball. Describe movement and space. Plain, steady sentences; calm unless it is a big moment."
    ),
    voice="en-GB-SoniaNeural",
    excited_style=None,
    calm_style=None,
    min_gap=7.0,
    max_words=30,
)

FEEDS = {f.id: f for f in (CASUAL_EN, ANALYST_EN, HOME_ZH, AUDIO_EN)}
