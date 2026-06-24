from bot.trading.indicators import Bar
from bot.trading.mosquito_metrics import compute_mosquito_bar_metrics


def test_mosquito_bar_metrics_volumes_and_nhod():
    bars = [
        Bar(1, 1.1, 0.9, 1.0, 10_000),
        Bar(1.0, 1.2, 0.95, 1.15, 20_000),
        Bar(1.15, 1.35, 1.1, 1.3, 30_000),
    ]
    metrics = compute_mosquito_bar_metrics(bars, price=1.3)
    assert metrics.volume_1m == 30_000
    assert metrics.volume_2m == 50_000
    assert metrics.volume_5m == 60_000
    assert metrics.nhod is True
    assert metrics.nlod is False
