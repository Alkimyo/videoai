import time
from collections import deque
from typing import Any, Iterable, Optional

from app.config import CONTACT_REPLY_MAXLEN, SESSION_TTL_SECONDS


class TimedDict(dict):
    def __init__(self, *args: Any, ttl_seconds: int = SESSION_TTL_SECONDS, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._ttl_seconds = ttl_seconds
        self._touched_at: dict[Any, float] = {}
        now = time.time()
        for key in self.keys():
            self._touched_at[key] = now

    def touch(self, key: Any) -> None:
        if key in self:
            self._touched_at[key] = time.time()

    def __contains__(self, key: object) -> bool:
        exists = super().__contains__(key)
        if exists:
            self._touched_at[key] = time.time()
        return exists

    def __getitem__(self, key: Any) -> Any:
        value = super().__getitem__(key)
        self._touched_at[key] = time.time()
        return value

    def get(self, key: Any, default: Any = None) -> Any:
        if key in self:
            return self[key]
        return default

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        self._touched_at[key] = time.time()

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key in self:
            return self[key]
        self[key] = default
        return default

    def update(self, other: Optional[dict] = None, **kwargs: Any) -> None:
        if other:
            for key, value in other.items():
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def pop(self, key: Any, default: Any = None) -> Any:
        self._touched_at.pop(key, None)
        return super().pop(key, default)

    def clear(self) -> None:
        self._touched_at.clear()
        super().clear()

    def cleanup_expired(self) -> int:
        if self._ttl_seconds <= 0:
            return 0
        now = time.time()
        expired = [key for key, touched in self._touched_at.items() if now - touched > self._ttl_seconds]
        for key in expired:
            super().pop(key, None)
            self._touched_at.pop(key, None)
        return len(expired)


class TimedSet(set):
    def __init__(self, items: Optional[Iterable[Any]] = None, ttl_seconds: int = SESSION_TTL_SECONDS) -> None:
        super().__init__(items or [])
        self._ttl_seconds = ttl_seconds
        self._touched_at: dict[Any, float] = {}
        now = time.time()
        for item in self:
            self._touched_at[item] = now

    def touch(self, item: Any) -> None:
        if item in self:
            self._touched_at[item] = time.time()

    def __contains__(self, item: object) -> bool:
        exists = super().__contains__(item)
        if exists:
            self._touched_at[item] = time.time()
        return exists

    def add(self, element: Any) -> None:
        super().add(element)
        self._touched_at[element] = time.time()

    def discard(self, element: Any) -> None:
        super().discard(element)
        self._touched_at.pop(element, None)

    def remove(self, element: Any) -> None:
        super().remove(element)
        self._touched_at.pop(element, None)

    def pop(self) -> Any:
        element = super().pop()
        self._touched_at.pop(element, None)
        return element

    def clear(self) -> None:
        self._touched_at.clear()
        super().clear()

    def cleanup_expired(self) -> int:
        if self._ttl_seconds <= 0:
            return 0
        now = time.time()
        expired = [item for item, touched in self._touched_at.items() if now - touched > self._ttl_seconds]
        for item in expired:
            super().discard(item)
            self._touched_at.pop(item, None)
        return len(expired)


# In-memory mutable sessions/caches (previously globals in handlers.py)
LOG_QUERY_ADMINS: TimedSet[int] = TimedSet()
ADMIN_ADD_SESSIONS: TimedDict[int, dict[str, object]] = TimedDict()
RESTORE_DB_SESSIONS: TimedDict[int, dict[str, object]] = TimedDict()
POST_SESSIONS: TimedDict[int, dict[str, object]] = TimedDict()
USER_SEARCH_SESSIONS: TimedSet[int] = TimedSet()
USER_SEARCH_RESULTS: TimedDict[int, list[dict]] = TimedDict()
USER_SERIALS_LIST: TimedDict[int, dict[str, object]] = TimedDict()
VIP_ADD_SESSIONS: TimedDict[int, int] = TimedDict()
VIP_PRICE_SESSIONS: TimedSet[int] = TimedSet()
VIP_MESSAGE_SESSIONS: TimedSet[int] = TimedSet()
VIP_CARD_SESSIONS: TimedSet[int] = TimedSet()
VIP_PAYMENT_SESSIONS: TimedSet[int] = TimedSet()
VIP_REJECT_SESSIONS: TimedDict[int, int] = TimedDict()
CONTACT_ADMIN_SESSIONS: TimedSet[int] = TimedSet()
CONTACT_REPLY_MAP: TimedDict[tuple[int, int], int] = TimedDict(ttl_seconds=86400)
CONTACT_REPLY_ORDER: deque[tuple[int, int]] = deque(maxlen=CONTACT_REPLY_MAXLEN)
BROADCAST_SESSIONS: TimedDict[int, dict[str, object]] = TimedDict()
BROADCAST_TEXT_SESSIONS: TimedSet[int] = TimedSet()
ADMIN_USER_MESSAGE_SESSIONS: TimedDict[int, dict[str, int]] = TimedDict()
VIP_RECEIPT_APPROVED: TimedDict[int, int] = TimedDict()
VIP_RECEIPT_REJECTED: TimedDict[int, int] = TimedDict()
VIP_RECEIPT_MESSAGES: TimedDict[int, list[tuple[int, int]]] = TimedDict()
VIP_EXPIRED_NOTICE_MESSAGE_ID: TimedDict[int, int] = TimedDict(ttl_seconds=86400)
SERIAL_UPLOAD_LOCKS: TimedDict[int, Any] = TimedDict()
SERIAL_UPLOAD_QUEUES: TimedDict[int, Any] = TimedDict()
SERIAL_UPLOAD_TASKS: TimedDict[int, Any] = TimedDict()
SERIAL_UPLOAD_COUNTERS: TimedDict[int, int] = TimedDict()
SERIAL_UPLOAD_NEXT_PART: TimedDict[tuple[int, int], int] = TimedDict()
IMPORT_TASKS: TimedDict[int, Any] = TimedDict()
IMPORT_SESSIONS: TimedDict[int, dict[str, object]] = TimedDict()
SERIAL_RENAME_SESSIONS: TimedDict[int, int] = TimedDict()
SERIAL_BANNER_SESSIONS: TimedDict[int, int] = TimedDict()
PENDING_START_CODES: TimedDict[int, tuple[int, Optional[int], float]] = TimedDict()
GROUP_SPAM_TRACKER: TimedDict[tuple[int, int], deque[float]] = TimedDict(ttl_seconds=3600)


_TIMED_STORES = [
    LOG_QUERY_ADMINS,
    ADMIN_ADD_SESSIONS,
    RESTORE_DB_SESSIONS,
    POST_SESSIONS,
    USER_SEARCH_SESSIONS,
    USER_SEARCH_RESULTS,
    USER_SERIALS_LIST,
    VIP_ADD_SESSIONS,
    VIP_PRICE_SESSIONS,
    VIP_MESSAGE_SESSIONS,
    VIP_CARD_SESSIONS,
    VIP_PAYMENT_SESSIONS,
    VIP_REJECT_SESSIONS,
    CONTACT_ADMIN_SESSIONS,
    CONTACT_REPLY_MAP,
    BROADCAST_SESSIONS,
    BROADCAST_TEXT_SESSIONS,
    ADMIN_USER_MESSAGE_SESSIONS,
    VIP_RECEIPT_APPROVED,
    VIP_RECEIPT_REJECTED,
    VIP_RECEIPT_MESSAGES,
    VIP_EXPIRED_NOTICE_MESSAGE_ID,
    SERIAL_UPLOAD_LOCKS,
    SERIAL_UPLOAD_QUEUES,
    SERIAL_UPLOAD_TASKS,
    SERIAL_UPLOAD_COUNTERS,
    SERIAL_UPLOAD_NEXT_PART,
    IMPORT_TASKS,
    IMPORT_SESSIONS,
    SERIAL_RENAME_SESSIONS,
    SERIAL_BANNER_SESSIONS,
    PENDING_START_CODES,
    GROUP_SPAM_TRACKER,
]


def cleanup_sessions() -> None:
    for store in _TIMED_STORES:
        try:
            store.cleanup_expired()
        except Exception:
            continue

