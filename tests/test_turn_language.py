from __future__ import annotations

from yumi.core.features.chat.language import build_turn_language_note, detect_prompt_language


def test_detects_japanese_from_kana_even_with_cjk() -> None:
    assert detect_prompt_language("疲れた、めっちゃ眠い") == "Japanese"
    assert "suggests Japanese" in build_turn_language_note("疲れた、めっちゃ眠い")


def test_detects_chinese_when_cjk_has_no_kana() -> None:
    assert detect_prompt_language("嗯嗯，我要睡觉了") == "Chinese"
    assert "suggests Chinese" in build_turn_language_note("嗯嗯，我要睡觉了")


def test_detects_english_as_english_not_generic_latin() -> None:
    note = build_turn_language_note("I'm exhausted and really sleepy")
    assert detect_prompt_language("I'm exhausted and really sleepy") == "English"
    assert "suggests English" in note
    assert "earlier conversation history" in note


def test_latin_script_prompts_keep_specific_language_to_model() -> None:
    note = build_turn_language_note("Estoy agotada y tengo mucho sueño")
    assert detect_prompt_language("Estoy agotada y tengo mucho sueño") == "Latin-script language"
    assert "reply in the language the user uses" in note


def test_ambiguous_prompt_still_says_not_to_follow_history() -> None:
    note = build_turn_language_note("OK")
    assert detect_prompt_language("OK") is None
    assert "Do not infer the response language from earlier conversation history" in note


def test_mixed_language_messages_are_not_forced_by_script_detection():
    for prompt in [
        "Can you explain 这个 API design?",
        "这个 bug 怎么 fix 比较自然？",
        "今日は tired, can we keep it short?",
    ]:
        note = build_turn_language_note(prompt)
        assert "most natural" in note
        assert "weak hint" in note
        assert "MUST be in" not in note
        assert "explicit language" in note
        assert "app interface language" in note


def test_request_language_ignores_foreign_song_titles():
    from yumi.core.features.chat.language import language_scoped_prompt, request_language

    cases = [
        ("我想听夜に駆ける，可以吗？", "Chinese"),
        ("帮我放一下《夜に駆ける》。", "Chinese"),
        ("Can you play 夜に駆ける for me?", "English"),
        ("Hello, how are you?", "English"),
        ("Finish. See you later.", "English"),
        ("夜に駆けるを聞きたい。", "Japanese"),
        ("今日はどうだった？", "Japanese"),
    ]
    for prompt, language in cases:
        assert request_language(prompt) == language
        assert f"Use {language} for your own reply" in build_turn_language_note(prompt)
        assert f"write your own reply in {language}" in language_scoped_prompt(prompt, "auto")
    # Explicit settings and translation requests remain authoritative.
    assert 'saved default response language label is "Japanese"' in build_turn_language_note(
        "Hello, how are you?", "ja"
    )
    assert "explicit request" in language_scoped_prompt("Translate hello into Japanese", "auto")
