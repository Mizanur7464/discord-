"""Per-user translator preference (on/off)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "translator_prefs.json"


class TranslatorPrefs:
    """Users who opted in receive private translations (default: off)."""

    def __init__(self, path: Path = STORE_PATH) -> None:
        self.path = path
        self._enabled: set[int] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            ids = raw.get("enabled_user_ids", [])
            self._enabled = {int(x) for x in ids}
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Translator prefs load failed: %s", exc)
            self._enabled = set()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
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

    def enabled_user_ids(self) -> list[int]:
        return list(self._enabled)
