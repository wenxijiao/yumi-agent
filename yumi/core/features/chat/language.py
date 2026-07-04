"""Per-turn response language guidance."""

from __future__ import annotations

import re

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+")

_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
_ARABIC_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
_HEBREW_RE = re.compile(r"[\u0590-\u05ff]")
_THAI_RE = re.compile(r"[\u0e00-\u0e7f]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _text_for_language_detection(prompt: str) -> str:
    text = _CODE_FENCE_RE.sub(" ", prompt)
    text = _INLINE_CODE_RE.sub(" ", text)
    text = _URL_RE.sub(" ", text)
    return text.strip()


def detect_prompt_language(prompt: str) -> str | None:
    """Best-effort language label for the latest user prompt.

    This intentionally favors high-signal script checks over broad language
    guessing. The model can infer Spanish/French/etc. from a Latin-script prompt,
    but it needs a stronger nudge when Japanese and Chinese compete in history.
    """
    text = _text_for_language_detection(prompt)
    if not text:
        return None

    kana = len(_KANA_RE.findall(text))
    hangul = len(_HANGUL_RE.findall(text))
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))

    if kana:
        return "Japanese"
    if hangul >= 2:
        return "Korean"
    if len(_THAI_RE.findall(text)) >= 2:
        return "Thai"
    if len(_ARABIC_RE.findall(text)) >= 2:
        return "Arabic"
    if len(_HEBREW_RE.findall(text)) >= 2:
        return "Hebrew"
    if len(_CYRILLIC_RE.findall(text)) >= 2:
        return "Cyrillic-script language"
    if cjk >= 2:
        return "Chinese"
    if latin >= 3 and not cjk:
        return "Latin-script language"
    return None


def build_turn_language_note(prompt: str) -> str:
    """Build an ephemeral system note that keeps response language turn-local."""
    language = detect_prompt_language(prompt)
    if language == "Latin-script language":
        detected_line = (
            "The latest user message is primarily in a Latin-script language; "
            "reply in that same natural language."
        )
    elif language == "Cyrillic-script language":
        detected_line = (
            "The latest user message is primarily in a Cyrillic-script language; "
            "reply in that same natural language."
        )
    elif language:
        detected_line = f"The latest user message appears to be in {language}; reply in {language}."
    else:
        detected_line = (
            "The latest user message is language-ambiguous; mirror its wording or language mix instead of "
            "defaulting to the language of earlier turns."
        )

    return (
        "[Turn language]\n"
        "Choose the response language for this turn from the latest user message, not from earlier conversation "
        "history.\n"
        f"{detected_line}\n"
        "Follow an explicit language, translation, or mixed-language request in the latest user message if it "
        "conflicts with this detection.\n"
        "Keep proper nouns, code, commands, URLs, and quoted/source text in their original language when appropriate."
    )
