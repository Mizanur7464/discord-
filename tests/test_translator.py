from bot.discord_bot.translator import looks_chinese, should_attempt_translate


def test_chinese_to_english():
    assert looks_chinese("我才刚醒呢")
    assert should_attempt_translate("我才刚醒呢")


def test_english_not_translated():
    assert not should_attempt_translate("I just woke up")
    assert not should_attempt_translate("How is the market today?")


def test_japanese_not_translated():
    assert not should_attempt_translate("おはよう、調子はどう？")


def test_korean_not_translated():
    assert not should_attempt_translate("방금 일어났어요")


def test_command_skipped():
    assert not should_attempt_translate("!help")
    assert not should_attempt_translate("/scan AAPL")


def test_url_only_skipped():
    assert not should_attempt_translate("https://discord.com")
