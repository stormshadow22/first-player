"""Bounded, locked TTL duplicate storage; batch callers supply event time."""

import hashlib
import re
import threading
import time
from collections import Counter
from datetime import datetime
from math import sqrt

from app.schemas import TriageRequest


class Deduplicator:
    def __init__(self, *, event_time: bool = False, max_entries: int = 10000):
        self.event_time = event_time
        self.max_entries = max_entries
        self._items: list[tuple[float, str, Counter]] = []
        self._lock = threading.Lock()
        self._watermark = 0.0

    def check(self, req: TriageRequest, text: str, category: str) -> bool:
        now = time.time()
        if self.event_time and req.created_at:
            now = datetime.fromisoformat(req.created_at.replace("Z", "+00:00")).timestamp()
        words = Counter(re.findall(r"\w+", text.lower()[:64000]))
        if not words:
            return False
        identity = (req.reporter_hash or "") + ":" + (req.reported_hash or "")
        if not req.reporter_hash:
            identity = hashlib.sha256(text.lower().strip().encode()).hexdigest()
        key = identity + ":" + category
        norm = sqrt(sum(v * v for v in words.values()))
        with self._lock:
            self._watermark = max(self._watermark, now)
            self._items = [row for row in self._items if row[0] >= self._watermark - 3600]
            duplicate = any(
                k == key
                and 0 <= now - ts <= 3600
                and sum(v * old.get(w, 0) for w, v in words.items())
                / (norm * sqrt(sum(v * v for v in old.values())))
                >= 0.85
                for ts, k, old in self._items
            )
            self._items.append((now, key, words))
            self._items = self._items[-self.max_entries :]
        return duplicate
