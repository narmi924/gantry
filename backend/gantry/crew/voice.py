"""Azure AI Speech: turns each commentary line into audio in the feed's own voice."""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

import azure.cognitiveservices.speech as speechsdk

from ..ai.azure import speech_config
from .feeds import Feed

SYNTH_TIMEOUT = 15.0


class Voices:
    """Synthesises lines and keeps recent audio in memory for the browser to fetch.

    Set GANTRY_VOICE=off to write captions only (the crew still times every line as if it were spoken)."""

    def __init__(self, keep: int = 800):
        self.audio: OrderedDict[str, bytes] = OrderedDict()
        self._durations: dict[str, float] = {}
        self.keep = keep
        self.enabled = os.environ.get("GANTRY_VOICE", "on").lower() != "off"
        self._config = None
        self._local = threading.local()
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="speech")

    def _synthesizer(self) -> speechsdk.SpeechSynthesizer:
        # one synthesizer per worker thread, reused line after line
        synth = getattr(self._local, "synth", None)
        if synth is None:
            if self._config is None:
                cfg = speech_config()
                cfg.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3)
                self._config = cfg
            synth = speechsdk.SpeechSynthesizer(speech_config=self._config, audio_config=None)
            self._local.synth = synth
        return synth

    def _synth(self, ssml: str) -> tuple[bytes, float]:
        result = self._synthesizer().speak_ssml_async(ssml).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            self._local.synth = None
            raise RuntimeError("speech synthesis did not complete")
        return result.audio_data, result.audio_duration.total_seconds()

    @staticmethod
    def ssml(feed: Feed, text: str, excited: bool) -> str:
        body = escape(text)
        style = feed.excited_style if excited else feed.calm_style
        if style:
            body = f'<mstts:express-as style="{style}">{body}</mstts:express-as>'
        rate, pitch = ("+12%", "+6%") if excited else ("+3%", "+0%")
        return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{feed.language}">'
                f'<voice name="{feed.voice}"><prosody rate="{rate}" pitch="{pitch}">{body}</prosody></voice></speak>')

    @staticmethod
    def estimate(feed: Feed, text: str) -> float:
        """How long a line takes to say, for captions without audio."""
        per_second = 5.0 if feed.lang.unit == "characters" else 15.0
        return max(1.2, len(text) / per_second)

    async def say(self, feed: Feed, text: str, excited: bool = False) -> tuple[str | None, float]:
        """Returns (audio id, seconds)."""
        if not self.enabled:
            return None, self.estimate(feed, text)
        ssml = self.ssml(feed, text, excited)
        key = hashlib.sha1(ssml.encode("utf-8")).hexdigest()[:16]
        if key in self.audio:
            return key, self._durations.get(key, 3.0)
        loop = asyncio.get_running_loop()
        # a stalled synthesis must never hold up the show
        data, seconds = await asyncio.wait_for(loop.run_in_executor(self._pool, self._synth, ssml), SYNTH_TIMEOUT)
        self.audio[key] = data
        self._durations[key] = seconds
        while len(self.audio) > self.keep:
            old, _ = self.audio.popitem(last=False)
            self._durations.pop(old, None)
        return key, seconds
