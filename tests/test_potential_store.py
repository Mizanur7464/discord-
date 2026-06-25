from bot.trading.potential_store import PotentialStore


def test_potential_store_hit_flow(tmp_path, monkeypatch):
    store_file = tmp_path / "potential_symbols.json"
    monkeypatch.setattr("bot.trading.potential_store.STORE_FILE", store_file)
    store = PotentialStore(retention_days=5)

    store.add_or_update(
        symbol="SUPX",
        score=72,
        grade="B",
        session_change_pct=8.5,
        reasons=["liquidity expansion"],
    )
    assert store.has_active("SUPX")

    store.attach_news("SUPX", title="SUPX headline", url="https://example.com")
    hit = store.mark_hit("SUPX")
    assert hit is not None
    assert not store.has_active("SUPX")
