"""Phase 4 — Timeline Evolution tests."""

from bot.news.timeline_evolution import TimelineEvolutionStore


def test_timeline_record_and_format():
    store = TimelineEvolutionStore()
    note = store.record("ABC", "🔴 FDA approval")
    assert note
    store.record("ABC", "🔴 Secondary offering")
    day = store.format_day("ABC")
    assert "FDA" in day or "offering" in day.lower()
