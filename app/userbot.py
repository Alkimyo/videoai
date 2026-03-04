import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import USERBOT_API_HASH, USERBOT_API_ID, USERBOT_SESSION, USERBOT_IDLE_TIMEOUT
from app.db import get_setting, set_setting

USERBOT_SESSION_KEY = "userbot_session"
USERBOT_API_ID_KEY = "userbot_api_id"
USERBOT_API_HASH_KEY = "userbot_api_hash"
_CLIENT: TelegramClient | None = None
_CLIENT_LOCK = asyncio.Lock()
_CLIENT_SESSION: str | None = None
_IDLE_TASK: asyncio.Task | None = None


class UserbotError(RuntimeError):
    pass


def _get_session_value() -> str:
    override = get_setting(USERBOT_SESSION_KEY)
    if override and override.strip():
        return override.strip()
    return USERBOT_SESSION


def _get_api_id() -> int:
    override = get_setting(USERBOT_API_ID_KEY)
    if override and override.strip():
        try:
            return int(override.strip())
        except ValueError:
            return 0
    return USERBOT_API_ID


def _get_api_hash() -> str:
    override = get_setting(USERBOT_API_HASH_KEY)
    if override and override.strip():
        return override.strip()
    return USERBOT_API_HASH


async def _disconnect_client() -> None:
    global _CLIENT, _CLIENT_SESSION
    if _CLIENT is None:
        _CLIENT_SESSION = None
        return
    try:
        await _CLIENT.disconnect()
    except Exception:
        pass
    _CLIENT = None
    _CLIENT_SESSION = None


def _schedule_idle_disconnect() -> None:
    global _IDLE_TASK
    if USERBOT_IDLE_TIMEOUT <= 0:
        return
    if _IDLE_TASK and not _IDLE_TASK.done():
        _IDLE_TASK.cancel()
    async def _idle() -> None:
        try:
            await asyncio.sleep(USERBOT_IDLE_TIMEOUT)
            async with _CLIENT_LOCK:
                await _disconnect_client()
        except asyncio.CancelledError:
            return
    _IDLE_TASK = asyncio.create_task(_idle())


async def reset_userbot_client() -> None:
    async with _CLIENT_LOCK:
        await _disconnect_client()


def set_userbot_session(value: str) -> None:
    set_setting(USERBOT_SESSION_KEY, value.strip())


def set_userbot_api_id(value: str) -> None:
    set_setting(USERBOT_API_ID_KEY, value.strip())


def set_userbot_api_hash(value: str) -> None:
    set_setting(USERBOT_API_HASH_KEY, value.strip())


async def get_userbot_client() -> TelegramClient:
    api_id = _get_api_id()
    api_hash = _get_api_hash()
    if not api_id or not api_hash:
        raise UserbotError("USERBOT_API_ID yoki USERBOT_API_HASH sozlanmagan.")
    async with _CLIENT_LOCK:
        global _CLIENT
        global _CLIENT_SESSION
        session_value = _get_session_value()
        if _CLIENT is not None and _CLIENT_SESSION != session_value:
            await _disconnect_client()
        if _CLIENT is None:
            if session_value:
                session = StringSession(session_value)
            else:
                session = "data/userbot"
            _CLIENT = TelegramClient(session, api_id, api_hash)
            _CLIENT_SESSION = session_value
            await _CLIENT.connect()
            if not await _CLIENT.is_user_authorized():
                await _disconnect_client()
                raise UserbotError("USERBOT_SESSION sozlanmagan yoki sessiya eskirgan.")
        _schedule_idle_disconnect()
    return _CLIENT
