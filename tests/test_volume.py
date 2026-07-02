from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from bot.trading.volume import _intraday_session_volume, get_daily_volume

_ET = ZoneInfo("America/New_York")


def _bar(volume: int):
    bar = MagicMock()
    bar.volume = volume
    return bar


def test_get_daily_volume_uses_session_when_daily_zero(monkeypatch):
    premarket = datetime(2026, 6, 25, 8, 30, tzinfo=_ET)
    monkeypatch.setattr("bot.trading.volume.is_extended_market_hours", lambda now=None: True)
    monkeypatch.setattr("bot.trading.volume._now_et", lambda now=None: premarket)

    client = MagicMock()

    def fake_bars(request):
        from alpaca.data.timeframe import TimeFrame

        if request.timeframe == TimeFrame.Day:
            return MagicMock(data={"LHAI": [_bar(0)]})
        return MagicMock(data={"LHAI": [_bar(12_000), _bar(8_500), _bar(5_200)]})

    client.get_stock_bars.side_effect = fake_bars
    assert get_daily_volume(client, "LHAI") == 25_700


def test_intraday_session_volume_sums_minute_bars(monkeypatch):
    premarket = datetime(2026, 6, 25, 7, 15, tzinfo=_ET)
    monkeypatch.setattr("bot.trading.volume._now_et", lambda now=None: premarket)

    client = MagicMock()
    client.get_stock_bars.return_value = MagicMock(
        data={"TC": [_bar(1_000), _bar(2_500), _bar(500)]}
    )
    assert _intraday_session_volume(client, "TC") == 4_000
