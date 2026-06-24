import time

from bot.discord_bot.mosquito_automute import MosquitoAutoMute


def test_automute_triggers_after_burst(monkeypatch):
    clock = {"t": 1000.0}

    def fake_time() -> float:
        return clock["t"]

    monkeypatch.setattr(time, "time", fake_time)
    gate = MosquitoAutoMute(window_seconds=60, max_alerts_in_window=3, mute_seconds=120)

    assert gate.can_send()
    gate.record_send()
    gate.record_send()
    assert gate.can_send()
    gate.record_send()
    assert gate.is_muted
    assert not gate.can_send()

    clock["t"] += 60
    assert not gate.can_send()

    clock["t"] = 1121
    assert gate.can_send()
    assert not gate.is_muted
