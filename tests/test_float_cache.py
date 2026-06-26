import bot.trading.market_data as md


def _reset_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(md, "_FLOAT_CACHE_FILE", tmp_path / "float_cache.json")
    monkeypatch.setattr(md, "_float_cache", None)


def test_float_cached_and_reused_on_failure(tmp_path, monkeypatch):
    _reset_cache(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_massive(symbol, key):
        calls["n"] += 1
        # First call returns a value; later calls simulate an API failure.
        return 5_000_000.0 if calls["n"] == 1 else None

    monkeypatch.setattr(md, "_shares_from_massive", fake_massive)

    first = md.fetch_float_shares_sync("AAA", "", massive_api_key="k")
    assert first == 5_000_000.0

    # Live source now fails, but the remembered value is returned.
    second = md.fetch_float_shares_sync("AAA", "", massive_api_key="k")
    assert second == 5_000_000.0


def test_float_unknown_symbol_returns_none(tmp_path, monkeypatch):
    _reset_cache(tmp_path, monkeypatch)
    monkeypatch.setattr(md, "_shares_from_massive", lambda s, k: None)
    assert md.fetch_float_shares_sync("ZZZ", "", massive_api_key="k") is None
