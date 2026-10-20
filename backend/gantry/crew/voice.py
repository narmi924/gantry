"""Azure AI Speech: turns each commentary line into audio in the feed's own voice."""

from __future__ import annotations

import asyncio
import hashlib
from collections import OrderedDict
from xml.sax.saxutils import escape

import azure.cognitiveservices.speech as speechsdk

from ..ai.azure import speech_config
from .feeds import Feed


class Voices:
    """Synthesises lines and keeps recent audio in memory for the browser to fetch."""

    def __init__(self, keep: int = 600):
        self.audio: OrderedDict[str, bytes] = OrderedDict()
        self._durations: dict[str, float] = {}
        self.keep = keep
        self._config = None

    def _synth(self, ssml: str) -> tuple[bytes, float]:
        if self._config is None:
            cfg = speech_config()
            cfg.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3)
            self._config = cfg
        synth = speechsdk.SpeechSynthesizer(speech_config=self._config, audio_config=None)
        result = synth.speak_ssml_async(ssml).get()
        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            detail = result.cancellation_details.error_details if result.cancellation_details else result.reason
            raise RuntimeError(f"speech failed: {detail}")
        return result.audio_data, result.audio_duration.total_seconds()

    @staticmethod
    def ssml(feed: Feed, text: str, excited: bool) -> str:
        body = escape(text)
        style = feed.excited_style if excited else feed.calm_style
        if style:
            body = f'<mstts:express-as style="{style}">{body}</mstts:express-as>'
        rate, pitch = ("+14%", "+6%") if excited else ("+4%", "+0%")
        return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{feed.language}">'
                f'<voice name="{feed.voice}"><prosody rate="{rate}" pitch="{pitch}">{body}</prosody></voice></speak>')

    async def say(self, feed: Feed, text: str, excited: bool = False) -> tuple[str, float]:
        """Returns (audio id, seconds)."""
        ssml = self.ssml(feed, text, excited)
        key = hashlib.sha1(ssml.encode("utf-8")).hexdigest()[:16]
        if key in self.audio:
            return key, self._durations.get(key, 3.0)
        try:
            # a stalled synthesis must never hold up the show
            data, seconds = await asyncio.wait_for(asyncio.to_thread(self._synth, ssml), 15)
        except Exception:
            self._config = None   # start from a fresh connection next time
            raise
        self.audio[key] = data
        self._durations[key] = seconds
        while len(self.audio) > self.keep:
            old, _ = self.audio.popitem(last=False)
            self._durations.pop(old, None)
        return key, seconds
