from bot.discord_bot.translator import looks_non_english, should_attempt_translate


def test_chinese_needs_translate():
    assert looks_non_english("我才刚醒呢")
    assert should_attempt_translate("我才刚醒呢")


def test_english_skipped():
    assert not looks_non_english("I just woke up")
    assert not should_attempt_translate("I just woke up")


def test_command_skipped():
    assert not should_attempt_translate("!help")
    assert not should_attempt_translate("/scan AAPL")


def test_url_only_skipped():
    assert not should_attempt_translate("https://discord.com")
