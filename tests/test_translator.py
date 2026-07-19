from bot.discord_bot.translator import (
    DIR_EN_TO_ZH,
    DIR_TO_EN,
    detect_direction,
    looks_chinese,
    looks_english,
    looks_japanese,
    looks_korean,
    should_attempt_translate,
)


def test_chinese_to_english():
    assert looks_chinese("我才刚醒呢")
    assert detect_direction("我才刚醒呢") == DIR_TO_EN
    assert should_attempt_translate("我才刚醒呢")


def test_japanese_to_english():
    assert looks_japanese("おはよう、調子はどう？")
    assert detect_direction("おはよう、調子はどう？") == DIR_TO_EN
    assert should_attempt_translate("おはよう、調子はどう？")


def test_korean_to_english():
    assert looks_korean("방금 일어났어요")
    assert detect_direction("방금 일어났어요") == DIR_TO_EN
    assert should_attempt_translate("방금 일어났어요")


def test_english_to_chinese():
    assert looks_english("I just woke up")
    assert detect_direction("I just woke up") == DIR_EN_TO_ZH
    assert should_attempt_translate("I just woke up")


def test_command_skipped():
    assert not should_attempt_translate("!help")
    assert not should_attempt_translate("/scan AAPL")


def test_url_only_skipped():
    assert not should_attempt_translate("https://discord.com")


def test_short_english_skipped():
    assert detect_direction("ok") is None
    assert detect_direction("hi") is None


def test_short_english_words_translate():
    assert detect_direction("test") == DIR_EN_TO_ZH
    assert detect_direction("tell") == DIR_EN_TO_ZH
    assert detect_direction("testing") == DIR_EN_TO_ZH
