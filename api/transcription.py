"""Speech-to-text via OpenAI's audio transcription API.

Default model is `gpt-4o-mini-transcribe` — cheaper than legacy `whisper-1`
($0.003/min vs $0.006/min) and more accurate on Italian + regulatory
vocabulary because it benefits from GPT-4o's language model context.

Domain vocabulary is biased through the `prompt` parameter so high-value
proper nouns (TIAD, SAPR, SOGL, GSE, ARERA) and Italian regulatory phrasing
(\"paragrafo\", \"comma\", \"articolo Nbis\") survive transcription intact.
"""

import io
import os
from typing import Optional

from openai import OpenAI


# Default model is the latest gpt-4o-mini-transcribe alias. The dated
# snapshot `gpt-4o-mini-transcribe-2025-12-15` shipped a ~90% reduction in
# silence-driven hallucinations vs Whisper v2 and ~70% vs earlier gpt-4o
# transcribe versions, which fixes the failure mode we hit. The alias
# resolves to that snapshot today; pin explicitly via env if you don't want
# to inherit future versions.
TRANSCRIBE_MODEL = os.getenv("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
TRANSCRIBE_LANGUAGE = os.getenv("TRANSCRIBE_LANGUAGE", "it")


# `prompt` parameter — DELIBERATELY EMPTY by default.
#
# Vocabulary-biasing prompts cause prompt-leakage on this model family: when
# the audio is short, quiet, or low-confidence, the model regurgitates
# individual tokens from the prompt. We saw `", comma 1."` come back from a
# 3-second recording because the prompt listed "comma" and "Articolo" as
# vocabulary hints. Empty prompt + `language=it` gives clean output.
#
# If you ever need to bias for a specific session (long, clean recordings,
# rare terms), set TRANSCRIBE_PROMPT in the environment. A reported anti-
# hallucination prompt is: "The sentence may be cut off or empty, do not
# make up words to fill in the rest of the sentence." Results are mixed.
TRANSCRIBE_PROMPT = os.getenv("TRANSCRIBE_PROMPT", "").strip()


# Accepted MIME types. webm/Opus is what MediaRecorder produces by default
# in Chromium-based browsers; the rest are common alternates from Safari/FF
# and from manual file uploads if we ever add that path.
ACCEPTED_MIME_TYPES = frozenset({
    "audio/webm",
    "audio/ogg",
    "audio/mp4",
    "audio/mpeg",
    "audio/m4a",
    "audio/wav",
    "audio/x-wav",
})


class TranscriptionError(Exception):
    """Raised when OpenAI returns an error or we can't decode the response."""


def transcribe_audio(
    client: OpenAI,
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    language: Optional[str] = None,
) -> dict:
    """Send audio to OpenAI for transcription.

    Returns `{"text": "...", "language": "it"}`. Raises `TranscriptionError`
    on any failure — the endpoint translates that into a 502.
    """
    if not audio_bytes:
        raise TranscriptionError("empty audio")

    # The SDK accepts a (filename, fileobj, content_type) tuple in lieu of
    # an actual file path. BytesIO wraps the bytes; no temp file needed.
    file_tuple = (filename, io.BytesIO(audio_bytes), content_type)

    kwargs = {
        "model": TRANSCRIBE_MODEL,
        "file": file_tuple,
        # `gpt-4o-*` transcribe models only support "json" and "text";
        # whisper-1 supports those plus verbose_json/vtt/srt. We only need
        # plain text either way.
        "response_format": "json",
    }
    # Only pass `prompt` if explicitly configured — empty prompt is better
    # than a vocabulary list when the audio is short or quiet.
    if TRANSCRIBE_PROMPT:
        kwargs["prompt"] = TRANSCRIBE_PROMPT
    # `language` is a hint — when set, the model knows what language to
    # decode (improves Italian + numeric/acronym accuracy noticeably).
    lang = language or TRANSCRIBE_LANGUAGE
    if lang:
        kwargs["language"] = lang

    try:
        response = client.audio.transcriptions.create(**kwargs)
    except Exception as e:
        # Re-raise as our own type so the endpoint doesn't leak provider
        # details into the user-facing error.
        raise TranscriptionError(str(e)) from e

    text = (getattr(response, "text", None) or "").strip()
    return {"text": text, "language": lang}
