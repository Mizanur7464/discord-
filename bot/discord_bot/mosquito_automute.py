"""SPM-style auto-mute when #mosquito gets too noisy."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class MosquitoAutoMute:
    """Pause mosquito posts when alert rate exceeds a rolling window."""

    window_seconds: int = 90
    max_alerts_in_window: int = 8
    mute_seconds: int = 180
    _sent_at: list[float] = field(default_factory=list)
    _muted_until: float = 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._sent_at = [ts for ts in self._sent_at if ts >= cutoff]

    @property
    def is_muted(self) -> bool:
        return time.time() < self._muted_until

    @property
    def muted_seconds_remaining(self) -> int:
        remaining = self._muted_until - time.time()
        return max(0, int(remaining))

    def can_send(self) -> bool:
        self._prune(time.time())
        return not self.is_muted

    def record_send(self) -> None:
        now = time.time()
        self._prune(now)
        self._sent_at.append(now)
        if len(self._sent_at) >= self.max_alerts_in_window:
            self._muted_until = now + self.mute_seconds
            self._sent_at.clear()


ChannelAutoMute = MosquitoAutoMute  # same SPM-style gate for #watchlist-monitor
