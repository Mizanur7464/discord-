import bot.news.benzinga_feed as feed_mod
from bot.news.benzinga import BenzingaArticle
from bot.news.benzinga_feed import BenzingaFeedPoller


def _article(article_id: str, published: str) -> BenzingaArticle:
    return BenzingaArticle(
        article_id=article_id,
        title=f"Headline {article_id}",
        url=f"https://www.benzinga.com/{article_id}",
        symbols=["AAA"],
        published=published,
    )


def _make_poller(tmp_path, monkeypatch, batches):
    monkeypatch.setattr(feed_mod, "STATE_FILE", tmp_path / "state.json")
    calls = {"n": 0}

    def fake_fetch(api_key, *, page_size=25, provider="massive", page=0, published_gte="", sort="published.desc"):
        calls["n"] += 1
        return list(batches.pop(0)) if batches else []

    monkeypatch.setattr(feed_mod, "fetch_recent_news", fake_fetch)
    poller = BenzingaFeedPoller(api_key="k", provider="massive")
    return poller, calls


def test_cold_start_primes_silently(tmp_path, monkeypatch):
    first = [_article("1", "2026-06-25T10:00:00Z"), _article("2", "2026-06-25T10:01:00Z")]
    poller, _ = _make_poller(tmp_path, monkeypatch, [first])
    fresh = poller.poll_new()
    assert fresh == []  # backlog primed, not dumped
    assert "1" in poller._seen_ids and "2" in poller._seen_ids


def test_second_poll_returns_only_new_in_order(tmp_path, monkeypatch):
    first = [_article("1", "2026-06-25T10:00:00Z")]
    second = [
        _article("3", "2026-06-25T10:05:00Z"),
        _article("2", "2026-06-25T10:02:00Z"),
        _article("1", "2026-06-25T10:00:00Z"),
    ]
    poller, _ = _make_poller(tmp_path, monkeypatch, [first, second])
    poller.poll_new()  # cold-start prime
    fresh = poller.poll_new()
    ids = [a.article_id for a in fresh]
    assert ids == ["2", "3"]  # only new, oldest-first


def test_seen_dedup_across_polls(tmp_path, monkeypatch):
    batches = [
        [_article("1", "2026-06-25T10:00:00Z")],
        [_article("2", "2026-06-25T10:02:00Z")],
        [_article("2", "2026-06-25T10:02:00Z")],
    ]
    poller, _ = _make_poller(tmp_path, monkeypatch, batches)
    poller.poll_new()  # prime "1"
    first_new = poller.poll_new()
    second_new = poller.poll_new()
    assert [a.article_id for a in first_new] == ["2"]
    assert second_new == []
