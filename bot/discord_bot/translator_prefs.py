"""Per-user translator preferences (on/off)."""

from __future__ import annotations

import json
from pathlib import Path

PREFS_FILE = Path(__file__).resolve().parents[2] / "data" / "translator_prefs.json"


class TranslatorPrefs:
    """User IDs with translator enabled receive private English DMs."""

    def __init__(self, path: Path = PREFS_FILE):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._enabled: set[int] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            ids = raw.get("enabled_user_ids", [])
            self._enabled = {int(uid) for uid in ids}
        except (json.JSONDecodeError, TypeError, ValueError):
            self._enabled = set()

    def _save(self) -> None:
        payload = {"enabled_user_ids": sorted(self._enabled)}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def is_enabled(self, user_id: int) -> bool:
        return user_id in self._enabled

    def set_enabled(self, user_id: int, enabled: bool) -> None:
        if enabled:
            self._enabled.add(user_id)
        else:
            self._enabled.discard(user_id)
        self._save()

    def enabled_ids(self) -> set[int]:
        return set(self._enabled)
