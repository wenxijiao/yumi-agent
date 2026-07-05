from __future__ import annotations

from yumi.core.features.chat.language import build_turn_language_note, detect_prompt_language


def test_detects_japanese_from_kana_even_with_cjk() -> None:
    assert detect_prompt_language("疲れた、めっちゃ眠い") == "Japanese"
    assert "MUST be in Japanese" in build_turn_language_note("疲れた、めっちゃ眠い")


def test_detects_chinese_when_cjk_has_no_kana() -> None:
    assert detect_prompt_language("嗯嗯，我要睡觉了") == "Chinese"
    assert "MUST be in Chinese" in build_turn_language_note("嗯嗯，我要睡觉了")


def test_detects_english_as_english_not_generic_latin() -> None:
    note = build_turn_language_note("I'm exhausted and really sleepy")
    assert detect_prompt_language("I'm exhausted and really sleepy") == "English"
    assert "MUST be in English" in note
    assert "earlier conversation history" in note


def test_latin_script_prompts_keep_specific_language_to_model() -> None:
    note = build_turn_language_note("Estoy agotada y tengo mucho sueño")
    assert detect_prompt_language("Estoy agotada y tengo mucho sueño") == "Latin-script language"
    assert "MUST use that same natural language" in note


def test_ambiguous_prompt_still_says_not_to_follow_history() -> None:
    note = build_turn_language_note("OK")
    assert detect_prompt_language("OK") is None
    assert "Do not infer the response language from earlier conversation history" in note
