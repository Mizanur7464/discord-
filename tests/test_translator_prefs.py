from pathlib import Path

from bot.discord_bot.translator_prefs import TranslatorPrefs


def test_translator_prefs_roundtrip(tmp_path: Path):
    path = tmp_path / "prefs.json"
    prefs = TranslatorPrefs(path=path)
    assert not prefs.is_enabled(111)
    prefs.set_enabled(111, True)
    assert prefs.is_enabled(111)
    prefs2 = TranslatorPrefs(path=path)
    assert prefs2.is_enabled(111)
    prefs2.set_enabled(111, False)
    assert not prefs2.is_enabled(111)
