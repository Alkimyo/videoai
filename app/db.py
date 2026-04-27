import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
import datetime as dt
from typing import Dict, List, Optional, Tuple

from app.config import (
    AUTO_RESTORE_DB,
    AUTO_RESTORE_ONLY_IF_NEWER,
    BACKUP_DIR,
    DB_PATH,
    OWNER_ID,
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _is_sqlite_db_ok(path: str) -> bool:
    if not path or not os.path.exists(path):
        return False
    try:
        with sqlite3.connect(path) as conn:
            cur = conn.execute("PRAGMA quick_check(1)")
            row = cur.fetchone()
            return bool(row) and row[0] == "ok"
    except sqlite3.DatabaseError:
        return False
    except Exception:
        return False


def _find_latest_backup_file(backup_dir: str) -> Optional[str]:
    if not backup_dir or not os.path.isdir(backup_dir):
        return None
    candidates: list[str] = []
    for name in os.listdir(backup_dir):
        lower = name.lower()
        if not (lower.endswith(".zip") or lower.endswith(".db")):
            continue
        path = os.path.join(backup_dir, name)
        if os.path.isfile(path):
            candidates.append(path)
    if not candidates:
        return None
    try:
        candidates.sort(key=os.path.getmtime, reverse=True)
    except OSError:
        candidates.sort(reverse=True)
    return candidates[0]


def _extract_db_from_zip(zip_path: str, tmp_dir: str) -> Optional[str]:
    expected_name = (os.path.basename(DB_PATH) or "bot.db").lower()
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            candidate = None
            for name in archive.namelist():
                if os.path.basename(name).lower() == expected_name:
                    candidate = name
                    break
            if not candidate:
                for name in archive.namelist():
                    if name.lower().endswith(expected_name):
                        candidate = name
                        break
            if not candidate:
                for name in archive.namelist():
                    if name.lower().endswith(".db"):
                        candidate = name
                        break
            if not candidate:
                return None
            out_path = os.path.join(tmp_dir, os.path.basename(candidate) or "bot.db")
            with archive.open(candidate) as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            return out_path
    except Exception:
        return None


def auto_restore_db_from_latest_backup() -> bool:
    if not AUTO_RESTORE_DB:
        return False

    backup_path = _find_latest_backup_file(BACKUP_DIR)
    if not backup_path:
        return False

    db_exists = os.path.exists(DB_PATH)
    db_ok = _is_sqlite_db_ok(DB_PATH) if db_exists else False

    if db_exists and db_ok and AUTO_RESTORE_ONLY_IF_NEWER:
        try:
            if os.path.getmtime(backup_path) <= os.path.getmtime(DB_PATH):
                return False
        except OSError:
            return False

    timestamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    prev_db_path = None
    if db_exists:
        prev_db_path = os.path.join("/tmp", f"serialbot-prev-{timestamp}.db")
        try:
            shutil.copy2(DB_PATH, prev_db_path)
        except OSError:
            prev_db_path = None

    restore_db_path = None
    try:
        if backup_path.lower().endswith(".db"):
            restore_db_path = backup_path
        else:
            with tempfile.TemporaryDirectory(prefix="serialbot-autorestore-") as tmp_dir:
                extracted = _extract_db_from_zip(backup_path, tmp_dir)
                if not extracted:
                    return False
                restore_db_path = extracted
                _replace_db_file(restore_db_path, timestamp=timestamp)
        if restore_db_path and restore_db_path == backup_path:
            _replace_db_file(restore_db_path, timestamp=timestamp)
    except Exception as exc:
        print(f"[auto-restore] failed: {exc}")
        return False

    if not _is_sqlite_db_ok(DB_PATH):
        if prev_db_path and os.path.exists(prev_db_path):
            try:
                _replace_db_file(prev_db_path, timestamp=f"rollback-{timestamp}")
            except Exception:
                pass
        return False

    print(f"[auto-restore] restored from {backup_path}")
    return True


def _replace_db_file(source_db_path: str, timestamp: str) -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    base = os.path.basename(DB_PATH) or "bot.db"
    tmp_path = os.path.join(db_dir or ".", f".{base}.{timestamp}.tmp")
    shutil.copy2(source_db_path, tmp_path)
    os.replace(tmp_path, DB_PATH)
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            os.remove(f"{DB_PATH}{suffix}")
        except FileNotFoundError:
            pass
        except OSError:
            pass


def init_db() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                can_manage_admins INTEGER NOT NULL DEFAULT 1,
                can_manage_channels INTEGER NOT NULL DEFAULT 1,
                can_manage_vip INTEGER NOT NULL DEFAULT 1,
                can_add_serial INTEGER NOT NULL DEFAULT 1,
                can_add_part INTEGER NOT NULL DEFAULT 1,
                can_broadcast INTEGER NOT NULL DEFAULT 1,
                can_view_lists INTEGER NOT NULL DEFAULT 1,
                can_view_logs INTEGER NOT NULL DEFAULT 1,
                can_view_stats INTEGER NOT NULL DEFAULT 1,
                can_backup INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS channels (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                invite_link TEXT,
                title TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS movies (
                code TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                caption TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS serials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code INTEGER NOT NULL UNIQUE,
                title TEXT NOT NULL COLLATE NOCASE UNIQUE,
                is_vip INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                banner_file_id TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS serial_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                serial_id INTEGER NOT NULL,
                part INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                caption TEXT,
                source_chat_id INTEGER,
                source_message_id INTEGER,
                created_at TEXT,
                UNIQUE(serial_id, part)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_serial_parts_serial_id ON serial_parts (serial_id)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS movie_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                file_type TEXT NOT NULL,
                caption TEXT,
                source_chat_id INTEGER,
                source_message_id INTEGER
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_movie_items_code ON movie_items (code)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS join_requests (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                requested_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS upload_sessions (
                admin_id INTEGER PRIMARY KEY,
                code INTEGER NOT NULL,
                items_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status_message_id INTEGER,
                allow_more INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS serial_sessions (
                admin_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                serial_id INTEGER,
                next_part INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS stats (
                day TEXT NOT NULL,
                code TEXT NOT NULL,
                views INTEGER NOT NULL,
                PRIMARY KEY (day, code)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS serial_stats (
                day TEXT NOT NULL,
                code INTEGER NOT NULL,
                views INTEGER NOT NULL,
                PRIMARY KEY (day, code)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id INTEGER PRIMARY KEY,
                blocked_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS serial_notifications (
                user_id INTEGER NOT NULL,
                serial_id INTEGER NOT NULL,
                muted INTEGER NOT NULL DEFAULT 0,
                notified INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, serial_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS serial_likes (
                user_id INTEGER NOT NULL,
                serial_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, serial_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS serial_ratings (
                user_id INTEGER NOT NULL,
                serial_id INTEGER NOT NULL,
                value INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, serial_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_serial_views (
                user_id INTEGER NOT NULL,
                serial_id INTEGER NOT NULL,
                views INTEGER NOT NULL,
                last_viewed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, serial_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_daily_recommendations (
                day TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                serial_id INTEGER NOT NULL,
                PRIMARY KEY (day, user_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS vip_users (
                user_id INTEGER PRIMARY KEY,
                expires_at TEXT NOT NULL,
                reminded_7d INTEGER NOT NULL DEFAULT 0,
                reminded_2d INTEGER NOT NULL DEFAULT 0,
                reminded_1d INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "channels", "invite_link", "TEXT")
        _ensure_column(conn, "movie_items", "source_chat_id", "INTEGER")
        _ensure_column(conn, "movie_items", "source_message_id", "INTEGER")
        _ensure_column(conn, "upload_sessions", "status_message_id", "INTEGER")
        _ensure_column(conn, "upload_sessions", "allow_more", "INTEGER")
        _ensure_column(conn, "admins", "can_manage_admins", "INTEGER")
        _ensure_column(conn, "admins", "can_manage_channels", "INTEGER")
        _ensure_column(conn, "admins", "can_manage_vip", "INTEGER")
        _ensure_column(conn, "admins", "can_add_serial", "INTEGER")
        _ensure_column(conn, "admins", "can_add_part", "INTEGER")
        _ensure_column(conn, "admins", "can_broadcast", "INTEGER")
        _ensure_column(conn, "admins", "can_view_lists", "INTEGER")
        _ensure_column(conn, "admins", "can_view_logs", "INTEGER")
        _ensure_column(conn, "admins", "can_view_stats", "INTEGER")
        _ensure_column(conn, "admins", "can_backup", "INTEGER")
        _ensure_column(conn, "serials", "is_vip", "INTEGER")
        _ensure_column(conn, "serials", "banner_file_id", "TEXT")
        _ensure_column(conn, "serial_parts", "created_at", "TEXT")
        _ensure_column(conn, "vip_users", "reminded_7d", "INTEGER")
        _fill_null_admin_perms(conn)
        _ensure_column(conn, "users", "username", "TEXT")
        _ensure_column(conn, "users", "full_name", "TEXT")
        _migrate_movies(conn)
        conn.commit()


def ensure_owner() -> None:
    if OWNER_ID:
        add_admin(OWNER_ID)


def add_admin(user_id: int, permissions: Optional[Dict[str, int]] = None) -> None:
    permissions = permissions or {}
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO admins (
                user_id,
                can_manage_admins,
                can_manage_channels,
                can_manage_vip,
                can_add_serial,
                can_add_part,
                can_broadcast,
                can_view_lists,
                can_view_logs,
                can_view_stats,
                can_backup
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                int(permissions.get("can_manage_admins", 1)),
                int(permissions.get("can_manage_channels", 1)),
                int(permissions.get("can_manage_vip", 1)),
                int(permissions.get("can_add_serial", 1)),
                int(permissions.get("can_add_part", 1)),
                int(permissions.get("can_broadcast", 1)),
                int(permissions.get("can_view_lists", 1)),
                int(permissions.get("can_view_logs", 1)),
                int(permissions.get("can_view_stats", 1)),
                int(permissions.get("can_backup", 1)),
            ),
        )
        conn.commit()


def del_admin(user_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()


def get_admins() -> List[int]:
    with _connect() as conn:
        cur = conn.execute("SELECT user_id FROM admins ORDER BY user_id")
        return [row["user_id"] for row in cur.fetchall()]


def is_admin(user_id: int) -> bool:
    if OWNER_ID and user_id == OWNER_ID:
        return True
    with _connect() as conn:
        cur = conn.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
        return cur.fetchone() is not None


def get_admin_permissions(user_id: int) -> Optional[Dict[str, int]]:
    if OWNER_ID and user_id == OWNER_ID:
        return {
            "can_manage_admins": 1,
            "can_manage_channels": 1,
            "can_manage_vip": 1,
            "can_add_serial": 1,
            "can_add_part": 1,
            "can_broadcast": 1,
            "can_view_lists": 1,
            "can_view_logs": 1,
            "can_view_stats": 1,
            "can_backup": 1,
        }
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT
                can_manage_admins,
                can_manage_channels,
                can_manage_vip,
                can_add_serial,
                can_add_part,
                can_broadcast,
                can_view_lists,
                can_view_logs,
                can_view_stats,
                can_backup
            FROM admins
            WHERE user_id = ?
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "can_manage_admins": int(row["can_manage_admins"] if row["can_manage_admins"] is not None else 1),
            "can_manage_channels": int(row["can_manage_channels"] if row["can_manage_channels"] is not None else 1),
            "can_manage_vip": int(row["can_manage_vip"] if row["can_manage_vip"] is not None else 1),
            "can_add_serial": int(row["can_add_serial"] if row["can_add_serial"] is not None else 1),
            "can_add_part": int(row["can_add_part"] if row["can_add_part"] is not None else 1),
            "can_broadcast": int(row["can_broadcast"] if row["can_broadcast"] is not None else 1),
            "can_view_lists": int(row["can_view_lists"] if row["can_view_lists"] is not None else 1),
            "can_view_logs": int(row["can_view_logs"] if row["can_view_logs"] is not None else 1),
            "can_view_stats": int(row["can_view_stats"] if row["can_view_stats"] is not None else 1),
            "can_backup": int(row["can_backup"] if row["can_backup"] is not None else 1),
        }


def set_admin_permissions(user_id: int, permissions: Dict[str, int]) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE admins
            SET
                can_manage_admins = ?,
                can_manage_channels = ?,
                can_manage_vip = ?,
                can_add_serial = ?,
                can_add_part = ?,
                can_broadcast = ?,
                can_view_lists = ?,
                can_view_logs = ?,
                can_view_stats = ?,
                can_backup = ?
            WHERE user_id = ?
            """,
            (
                int(permissions.get("can_manage_admins", 0)),
                int(permissions.get("can_manage_channels", 0)),
                int(permissions.get("can_manage_vip", 0)),
                int(permissions.get("can_add_serial", 0)),
                int(permissions.get("can_add_part", 0)),
                int(permissions.get("can_broadcast", 0)),
                int(permissions.get("can_view_lists", 0)),
                int(permissions.get("can_view_logs", 0)),
                int(permissions.get("can_view_stats", 0)),
                int(permissions.get("can_backup", 0)),
                user_id,
            ),
        )
        conn.commit()


def has_admin_permission(user_id: int, permission: str) -> bool:
    if OWNER_ID and user_id == OWNER_ID:
        return True
    perms = get_admin_permissions(user_id)
    if not perms:
        return False
    return bool(perms.get(permission, 0))


def add_channel(
    chat_id: int, username: Optional[str], title: str, invite_link: str
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO channels (chat_id, username, invite_link, title)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, username or "", invite_link, title),
        )
        conn.commit()


def del_channel(chat_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM channels WHERE chat_id = ?", (chat_id,))
        conn.commit()


def get_channels() -> List[Dict[str, str]]:
    with _connect() as conn:
        cur = conn.execute("SELECT chat_id, username, invite_link, title FROM channels")
        return [dict(row) for row in cur.fetchall()]


def add_movie(
    code: str,
    file_id: str,
    file_type: str,
    caption: str,
    source_chat_id: Optional[int] = None,
    source_message_id: Optional[int] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO movie_items (
                code, file_id, file_type, caption, source_chat_id, source_message_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(code),
                file_id,
                file_type,
                caption,
                source_chat_id,
                source_message_id,
            ),
        )
        conn.commit()


def del_movie(code: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM movie_items WHERE code = ?", (int(code),))
        conn.commit()


def get_next_serial_code() -> int:
    with _connect() as conn:
        cur = conn.execute("SELECT COALESCE(MAX(code), 0) AS max_code FROM serials")
        return int(cur.fetchone()["max_code"]) + 1


def add_serial(title: str, created_at: str) -> Dict[str, object]:
    code = get_next_serial_code()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO serials (code, title, is_vip, created_at)
            VALUES (?, ?, 0, ?)
            """,
            (code, title, created_at),
        )
        cur = conn.execute(
            "SELECT id, code, title, is_vip, created_at FROM serials WHERE code = ?",
            (code,),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row)


def get_serial_by_title(title: str) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, code, title, is_vip, created_at FROM serials WHERE title = ?",
            (title,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_serial_by_code(code: int) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, code, title, is_vip, created_at, banner_file_id FROM serials WHERE code = ?",
            (code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_serial_by_id(serial_id: int) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, code, title, is_vip, created_at, banner_file_id FROM serials WHERE id = ?",
            (serial_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_serials() -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT
                s.id,
                s.code,
                s.title,
                s.is_vip,
                s.created_at,
                s.banner_file_id,
                COALESCE(MAX(p.created_at), s.created_at) AS last_part_at
            FROM serials AS s
            LEFT JOIN serial_parts AS p ON p.serial_id = s.id
            GROUP BY s.id
            ORDER BY s.code ASC
            """
        )
        return [dict(row) for row in cur.fetchall()]


def count_serials() -> int:
    with _connect() as conn:
        cur = conn.execute("SELECT COUNT(1) AS cnt FROM serials")
        return int(cur.fetchone()["cnt"])


def get_serials_page(limit: int, offset: int) -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT
                s.id,
                s.code,
                s.title,
                s.is_vip,
                s.created_at,
                s.banner_file_id,
                COALESCE(MAX(p.created_at), s.created_at) AS last_part_at
            FROM serials AS s
            LEFT JOIN serial_parts AS p ON p.serial_id = s.id
            GROUP BY s.id
            ORDER BY s.code ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]


def count_serials_by_title(query: str, include_vip: bool) -> int:
    like = f"%{query}%"
    with _connect() as conn:
        if include_vip:
            cur = conn.execute(
                "SELECT COUNT(1) AS cnt FROM serials WHERE title LIKE ?",
                (like,),
            )
        else:
            cur = conn.execute(
                "SELECT COUNT(1) AS cnt FROM serials WHERE title LIKE ? AND is_vip = 0",
                (like,),
            )
        return int(cur.fetchone()["cnt"])


def search_serials_by_title(
    query: str,
    include_vip: bool,
    limit: int,
    offset: int,
) -> List[Dict[str, object]]:
    like = f"%{query}%"
    with _connect() as conn:
        if include_vip:
            cur = conn.execute(
                """
                SELECT id, code, title, is_vip, created_at
                FROM serials
                WHERE title LIKE ?
                ORDER BY code ASC
                LIMIT ? OFFSET ?
                """,
                (like, limit, offset),
            )
        else:
            cur = conn.execute(
                """
                SELECT id, code, title, is_vip, created_at
                FROM serials
                WHERE title LIKE ? AND is_vip = 0
                ORDER BY code ASC
                LIMIT ? OFFSET ?
                """,
                (like, limit, offset),
            )
        return [dict(row) for row in cur.fetchall()]


def set_serial_vip(serial_id: int, is_vip: int) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE serials SET is_vip = ? WHERE id = ?",
            (1 if is_vip else 0, serial_id),
        )
        conn.commit()


def rename_serial(serial_id: int, title: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE serials SET title = ? WHERE id = ?",
            (title, serial_id),
        )
        conn.commit()




def add_serial_part(
    serial_id: int,
    part: int,
    file_id: str,
    file_type: str,
    caption: str,
    source_chat_id: Optional[int] = None,
    source_message_id: Optional[int] = None,
    created_at: Optional[str] = None,
) -> None:
    created_at = created_at or dt.datetime.utcnow().isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO serial_parts (
                serial_id,
                part,
                file_id,
                file_type,
                caption,
                source_chat_id,
                source_message_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                serial_id,
                part,
                file_id,
                file_type,
                caption,
                source_chat_id,
                source_message_id,
                created_at,
            ),
        )
        conn.commit()


def del_serial(code: int) -> None:
    with _connect() as conn:
        cur = conn.execute("SELECT id FROM serials WHERE code = ?", (code,))
        row = cur.fetchone()
        if not row:
            return
        serial_id = int(row["id"])
        conn.execute("DELETE FROM serial_parts WHERE serial_id = ?", (serial_id,))
        conn.execute("DELETE FROM serials WHERE id = ?", (serial_id,))
        conn.commit()


def del_serial_part(serial_id: int, part: int) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM serial_parts WHERE serial_id = ? AND part = ?",
            (serial_id, part),
        )
        conn.commit()


def delete_empty_serials() -> list[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT s.id, s.code, s.title
            FROM serials AS s
            LEFT JOIN serial_parts AS p ON p.serial_id = s.id
            WHERE p.serial_id IS NULL
            ORDER BY s.code ASC
            """
        )
        rows = [dict(row) for row in cur.fetchall()]
        if rows:
            conn.execute(
                """
                DELETE FROM serials
                WHERE id IN (
                    SELECT s.id
                    FROM serials AS s
                    LEFT JOIN serial_parts AS p ON p.serial_id = s.id
                    WHERE p.serial_id IS NULL
                )
                """
            )
            conn.commit()
        return rows


def serial_part_exists(serial_id: int, part: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM serial_parts WHERE serial_id = ? AND part = ?",
            (serial_id, part),
        )
        return cur.fetchone() is not None


def serial_part_source_exists(source_chat_id: int, source_message_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT 1
            FROM serial_parts
            WHERE source_chat_id = ? AND source_message_id = ?
            """,
            (source_chat_id, source_message_id),
        )
        return cur.fetchone() is not None


def get_serial_parts(serial_id: int) -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT part, file_id, file_type, caption, source_chat_id, source_message_id, created_at
            FROM serial_parts
            WHERE serial_id = ?
            ORDER BY part ASC, id ASC
            """,
            (serial_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_serial_part(serial_id: int, part: int) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT part, file_id, file_type, caption, source_chat_id, source_message_id, created_at
            FROM serial_parts
            WHERE serial_id = ? AND part = ?
            """,
            (serial_id, part),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def save_serial_session(
    admin_id: int,
    state: str,
    created_at: str,
    serial_id: Optional[int] = None,
    next_part: Optional[int] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO serial_sessions (
                admin_id, state, serial_id, next_part, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (admin_id, state, serial_id, next_part, created_at),
        )
        conn.commit()


def get_serial_session(admin_id: int) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT admin_id, state, serial_id, next_part, created_at
            FROM serial_sessions
            WHERE admin_id = ?
            """,
            (admin_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def clear_serial_session(admin_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM serial_sessions WHERE admin_id = ?", (admin_id,))
        conn.commit()


def get_movie(code: str) -> Optional[Dict[str, str]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT code, file_id, file_type, caption FROM movies WHERE code = ?",
            (code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def movie_exists(code: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("SELECT 1 FROM movie_items WHERE code = ?", (int(code),))
        return cur.fetchone() is not None


def count_movies_for_code(code: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT COUNT(1) AS cnt FROM movie_items WHERE code = ?",
            (int(code),),
        )
        return int(cur.fetchone()["cnt"])


def get_movie_items(code: str) -> List[Dict[str, str]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT id, code, file_id, file_type, caption, source_chat_id, source_message_id
            FROM movie_items
            WHERE code = ?
            ORDER BY id ASC
            """,
            (int(code),),
        )
        return [dict(row) for row in cur.fetchall()]


def get_next_code() -> int:
    with _connect() as conn:
        cur = conn.execute("SELECT COALESCE(MAX(code), 0) AS max_code FROM movie_items")
        return int(cur.fetchone()["max_code"]) + 1


def record_view(day: str, code: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO stats (day, code, views)
            VALUES (?, ?, 1)
            ON CONFLICT(day, code) DO UPDATE SET views = views + 1
            """,
            (day, code),
        )
        conn.commit()


def get_day_stats(day: str) -> Tuple[int, List[Tuple[str, int]]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT COALESCE(SUM(views), 0) AS total FROM stats WHERE day = ?",
            (day,),
        )
        total = cur.fetchone()["total"]
        cur = conn.execute(
            """
            SELECT code, views
            FROM stats
            WHERE day = ?
            ORDER BY views DESC, code ASC
            LIMIT 10
            """,
            (day,),
        )
        top = [(row["code"], row["views"]) for row in cur.fetchall()]
        return total, top


def get_recent_days(limit: int = 7) -> List[Tuple[str, int]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT day, SUM(views) AS total
            FROM stats
            GROUP BY day
            ORDER BY day DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [(row["day"], row["total"]) for row in cur.fetchall()]


def record_serial_view(day: str, code: int) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO serial_stats (day, code, views)
            VALUES (?, ?, 1)
            ON CONFLICT(day, code) DO UPDATE SET views = views + 1
            """,
            (day, code),
        )
        conn.commit()


def get_serial_day_stats(day: str) -> Tuple[int, List[Tuple[str, int]]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT COALESCE(SUM(views), 0) AS total FROM serial_stats WHERE day = ?",
            (day,),
        )
        total = cur.fetchone()["total"]
        cur = conn.execute(
            """
            SELECT code, views
            FROM serial_stats
            WHERE day = ?
            ORDER BY views DESC, code ASC
            LIMIT 10
            """,
            (day,),
        )
        top = [(str(row["code"]), row["views"]) for row in cur.fetchall()]
        return total, top


def get_serial_recent_days(limit: int = 7) -> List[Tuple[str, int]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT day, SUM(views) AS total
            FROM serial_stats
            GROUP BY day
            ORDER BY day DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [(row["day"], row["total"]) for row in cur.fetchall()]


def get_serial_total_views_map(codes: List[int]) -> Dict[int, int]:
    if not codes:
        return {}
    placeholders = ",".join(["?"] * len(codes))
    query = (
        f"SELECT code, COALESCE(SUM(views), 0) AS total FROM serial_stats "
        f"WHERE code IN ({placeholders}) GROUP BY code"
    )
    with _connect() as conn:
        cur = conn.execute(query, codes)
        return {int(row["code"]): int(row["total"]) for row in cur.fetchall()}


def has_serial_like(user_id: int, serial_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM serial_likes WHERE user_id = ? AND serial_id = ?",
            (user_id, serial_id),
        )
        return cur.fetchone() is not None


def like_serial(user_id: int, serial_id: int, created_at: Optional[str] = None) -> None:
    created_at = created_at or dt.datetime.utcnow().isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO serial_likes (user_id, serial_id, created_at)
            VALUES (?, ?, ?)
            """,
            (user_id, serial_id, created_at),
        )
        conn.commit()


def unlike_serial(user_id: int, serial_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM serial_likes WHERE user_id = ? AND serial_id = ?",
            (user_id, serial_id),
        )
        conn.commit()


def get_serial_like_count(serial_id: int) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT COUNT(1) AS cnt FROM serial_likes WHERE serial_id = ?",
            (serial_id,),
        )
        return int(cur.fetchone()["cnt"])


def get_serial_like_counts_map(serial_ids: List[int]) -> Dict[int, int]:
    if not serial_ids:
        return {}
    placeholders = ",".join(["?"] * len(serial_ids))
    query = (
        f"SELECT serial_id, COUNT(1) AS cnt FROM serial_likes "
        f"WHERE serial_id IN ({placeholders}) GROUP BY serial_id"
    )
    with _connect() as conn:
        cur = conn.execute(query, serial_ids)
        return {int(row["serial_id"]): int(row["cnt"]) for row in cur.fetchall()}


def record_user_serial_view(user_id: int, serial_id: int, viewed_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO user_serial_views (user_id, serial_id, views, last_viewed_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id, serial_id) DO UPDATE
            SET views = views + 1, last_viewed_at = excluded.last_viewed_at
            """,
            (user_id, serial_id, viewed_at),
        )
        conn.commit()


def get_user_liked_serial_ids(user_id: int, limit: int = 50) -> List[int]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT serial_id
            FROM serial_ratings
            WHERE user_id = ? AND value = 1
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [int(row["serial_id"]) for row in cur.fetchall()]


def get_user_viewed_serial_ids(user_id: int, limit: int = 50) -> List[int]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT serial_id
            FROM user_serial_views
            WHERE user_id = ?
            ORDER BY last_viewed_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        return [int(row["serial_id"]) for row in cur.fetchall()]


def get_active_user_ids(days: int = 3) -> List[int]:
    cutoff = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT DISTINCT user_id
            FROM user_serial_views
            WHERE last_viewed_at >= ?
            """,
            (cutoff,),
        )
        return [int(row["user_id"]) for row in cur.fetchall()]


def set_user_daily_recommendation(day: str, user_id: int, serial_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO user_daily_recommendations (day, user_id, serial_id)
            VALUES (?, ?, ?)
            """,
            (day, user_id, serial_id),
        )
        conn.commit()


def get_user_daily_recommendations(day: str) -> Dict[int, int]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT user_id, serial_id
            FROM user_daily_recommendations
            WHERE day = ?
            """,
            (day,),
        )
        return {int(row["user_id"]): int(row["serial_id"]) for row in cur.fetchall()}


def get_user_daily_recommendations_for_users(day: str, user_ids: List[int]) -> Dict[int, int]:
    if not user_ids:
        return {}
    placeholders = ",".join(["?"] * len(user_ids))
    with _connect() as conn:
        cur = conn.execute(
            f"""
            SELECT user_id, serial_id
            FROM user_daily_recommendations
            WHERE day = ? AND user_id IN ({placeholders})
            """,
            [day, *user_ids],
        )
        return {int(row["user_id"]): int(row["serial_id"]) for row in cur.fetchall()}


def get_similar_serials_by_likes(user_id: int, limit: int = 10) -> List[int]:
    query = """
        WITH liked AS (
            SELECT serial_id
            FROM serial_ratings
            WHERE user_id = ? AND value = 1
        ),
        seen AS (
            SELECT serial_id FROM user_serial_views WHERE user_id = ?
            UNION
            SELECT serial_id FROM serial_ratings WHERE user_id = ? AND value = 1
        )
        SELECT r2.serial_id, COUNT(*) AS score
        FROM serial_ratings AS r1
        JOIN serial_ratings AS r2
            ON r1.user_id = r2.user_id AND r2.value = 1
        WHERE r1.serial_id IN (SELECT serial_id FROM liked)
          AND r1.value = 1
          AND r2.serial_id NOT IN (SELECT serial_id FROM seen)
        GROUP BY r2.serial_id
        ORDER BY score DESC, r2.serial_id ASC
        LIMIT ?
    """
    with _connect() as conn:
        cur = conn.execute(query, (user_id, user_id, user_id, limit))
        return [int(row["serial_id"]) for row in cur.fetchall()]


def get_similar_serials_by_views(
    user_id: int, limit: int = 10, seed_limit: int = 5
) -> List[int]:
    query = """
        WITH seed AS (
            SELECT serial_id
            FROM user_serial_views
            WHERE user_id = ?
            ORDER BY last_viewed_at DESC
            LIMIT ?
        ),
        seen AS (
            SELECT serial_id FROM user_serial_views WHERE user_id = ?
            UNION
            SELECT serial_id FROM serial_ratings WHERE user_id = ? AND value = 1
        )
        SELECT v2.serial_id, COUNT(*) AS score
        FROM user_serial_views AS v1
        JOIN user_serial_views AS v2
            ON v1.user_id = v2.user_id
        WHERE v1.serial_id IN (SELECT serial_id FROM seed)
          AND v2.serial_id NOT IN (SELECT serial_id FROM seen)
        GROUP BY v2.serial_id
        ORDER BY score DESC, v2.serial_id ASC
        LIMIT ?
    """
    with _connect() as conn:
        cur = conn.execute(query, (user_id, seed_limit, user_id, user_id, limit))
        return [int(row["serial_id"]) for row in cur.fetchall()]


def get_top_liked_serials(limit: int, include_vip: bool) -> List[Dict[str, object]]:
    where = "" if include_vip else "WHERE s.is_vip = 0"
    query = f"""
        SELECT s.id, s.code, s.title, s.is_vip, COUNT(r.user_id) AS likes
        FROM serials AS s
        LEFT JOIN serial_ratings AS r ON r.serial_id = s.id AND r.value = 1
        {where}
        GROUP BY s.id
        ORDER BY likes DESC, s.title ASC
        LIMIT ?
    """
    with _connect() as conn:
        cur = conn.execute(query, (limit,))
        return [dict(row) for row in cur.fetchall()]


def set_serial_rating(user_id: int, serial_id: int, value: int) -> None:
    rating = 1 if value >= 1 else -1
    created_at = dt.datetime.utcnow().isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO serial_ratings (user_id, serial_id, value, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, serial_id, rating, created_at),
        )
        conn.commit()


def get_serial_rating(user_id: int, serial_id: int) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT value FROM serial_ratings WHERE user_id = ? AND serial_id = ?",
            (user_id, serial_id),
        )
        row = cur.fetchone()
        return int(row["value"]) if row else 0


def get_serial_rating_counts(serial_id: int) -> Tuple[int, int]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT value, COUNT(1) AS cnt
            FROM serial_ratings
            WHERE serial_id = ?
            GROUP BY value
            """,
            (serial_id,),
        )
        likes = 0
        dislikes = 0
        for row in cur.fetchall():
            if int(row["value"]) == 1:
                likes = int(row["cnt"])
            elif int(row["value"]) == -1:
                dislikes = int(row["cnt"])
        return likes, dislikes


def get_serial_rating_like_counts_map(serial_ids: List[int]) -> Dict[int, int]:
    if not serial_ids:
        return {}
    placeholders = ",".join(["?"] * len(serial_ids))
    query = (
        f"SELECT serial_id, COUNT(1) AS cnt FROM serial_ratings "
        f"WHERE value = 1 AND serial_id IN ({placeholders}) GROUP BY serial_id"
    )
    with _connect() as conn:
        cur = conn.execute(query, serial_ids)
        return {int(row["serial_id"]): int(row["cnt"]) for row in cur.fetchall()}


def get_expired_vip_serial_parts(cutoff: str, limit: int = 200) -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT
                p.serial_id,
                p.part,
                p.source_chat_id,
                p.source_message_id
            FROM serial_parts AS p
            JOIN serials AS s ON s.id = p.serial_id
            WHERE s.is_vip = 1
                AND p.created_at IS NOT NULL
                AND p.created_at <= ?
            ORDER BY p.created_at ASC
            LIMIT ?
            """,
            (cutoff, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def get_serial_notification_map(serial_id: int) -> Dict[int, Dict[str, int]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT user_id, muted, notified
            FROM serial_notifications
            WHERE serial_id = ?
            """,
            (serial_id,),
        )
        return {
            int(row["user_id"]): {
                "muted": int(row["muted"]),
                "notified": int(row["notified"]),
            }
            for row in cur.fetchall()
        }


def get_serial_notification(user_id: int, serial_id: int) -> Optional[Dict[str, int]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT muted, notified
            FROM serial_notifications
            WHERE user_id = ? AND serial_id = ?
            """,
            (int(user_id), int(serial_id)),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "muted": int(row["muted"]),
            "notified": int(row["notified"]),
        }


def mark_serial_notification_sent(user_id: int, serial_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO serial_notifications (user_id, serial_id, muted, notified)
            VALUES (?, ?, 0, 1)
            ON CONFLICT(user_id, serial_id) DO UPDATE SET notified = 1
            """,
            (user_id, serial_id),
        )
        conn.commit()


def set_serial_notification_muted(user_id: int, serial_id: int, muted: int = 1) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO serial_notifications (user_id, serial_id, muted, notified)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id, serial_id) DO UPDATE SET
                muted = excluded.muted,
                notified = 1
            """,
            (user_id, serial_id, int(bool(muted))),
        )
        conn.commit()


def block_user(user_id: int, blocked_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO blocked_users (user_id, blocked_at)
            VALUES (?, ?)
            """,
            (user_id, blocked_at),
        )
        conn.commit()


def unblock_user(user_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM blocked_users WHERE user_id = ?", (user_id,))
        conn.commit()


def is_blocked_user(user_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("SELECT 1 FROM blocked_users WHERE user_id = ?", (user_id,))
        return cur.fetchone() is not None


def get_blocked_users() -> List[int]:
    with _connect() as conn:
        cur = conn.execute("SELECT user_id FROM blocked_users")
        return [int(row["user_id"]) for row in cur.fetchall()]


def add_user(
    user_id: int,
    username: Optional[str] = None,
    full_name: Optional[str] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
            (user_id, username or "", full_name or ""),
        )
        if username or full_name:
            conn.execute(
                "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
                (username or "", full_name or "", user_id),
            )
        conn.commit()


def get_user_id_by_username(username: str) -> Optional[int]:
    clean = (username or "").strip().lstrip("@")
    if not clean:
        return None
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE username IS NOT NULL
              AND TRIM(username) != ''
              AND LOWER(username) = LOWER(?)
            LIMIT 1
            """,
            (clean,),
        )
        row = cur.fetchone()
        return int(row["user_id"]) if row else None


def get_user_id_by_username(username: str) -> Optional[int]:
    clean = (username or "").strip().lstrip("@")
    if not clean:
        return None
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE username IS NOT NULL
              AND TRIM(username) != ''
              AND LOWER(username) = LOWER(?)
            LIMIT 1
            """,
            (clean,),
        )
        row = cur.fetchone()
        return int(row["user_id"]) if row else None


def set_setting(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()


def get_setting(key: str) -> Optional[str]:
    with _connect() as conn:
        cur = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None


def add_vip_user(user_id: int, expires_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO vip_users (user_id, expires_at, reminded_7d, reminded_2d, reminded_1d)
            VALUES (?, ?, 0, 0, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                expires_at = excluded.expires_at,
                reminded_7d = 0,
                reminded_2d = 0,
                reminded_1d = 0
            """,
            (user_id, expires_at),
        )
        conn.commit()


def remove_vip_user(user_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM vip_users WHERE user_id = ?", (user_id,))
        conn.commit()


def get_vip_user(user_id: int) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT user_id, expires_at, reminded_7d, reminded_2d, reminded_1d FROM vip_users WHERE user_id = ?",
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_vip_users() -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT user_id, expires_at, reminded_7d, reminded_2d, reminded_1d FROM vip_users ORDER BY expires_at ASC"
        )
        return [dict(row) for row in cur.fetchall()]


def count_vip_users() -> int:
    with _connect() as conn:
        cur = conn.execute("SELECT COUNT(1) AS cnt FROM vip_users")
        return int(cur.fetchone()["cnt"])


def get_vip_users_page(limit: int, offset: int) -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT user_id, expires_at, reminded_7d, reminded_2d, reminded_1d
            FROM vip_users
            ORDER BY expires_at ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]


def mark_vip_reminder(user_id: int, days: int) -> None:
    if days == 7:
        column = "reminded_7d"
    elif days == 2:
        column = "reminded_2d"
    else:
        column = "reminded_1d"
    with _connect() as conn:
        conn.execute(
            f"UPDATE vip_users SET {column} = 1 WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()


def get_users() -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT user_id, username, full_name
            FROM users
            ORDER BY
                CASE
                    WHEN username IS NOT NULL AND TRIM(username) != '' THEN 0
                    WHEN full_name IS NOT NULL AND TRIM(full_name) != '' THEN 1
                    ELSE 2
                END,
                LOWER(
                    COALESCE(
                        NULLIF(username, ''),
                        NULLIF(full_name, ''),
                        CAST(user_id AS TEXT)
                    )
                ),
                user_id
            """
        )
        return [dict(row) for row in cur.fetchall()]


def count_users() -> int:
    with _connect() as conn:
        cur = conn.execute("SELECT COUNT(1) AS cnt FROM users")
        return int(cur.fetchone()["cnt"])


def iter_user_ids(batch_size: int = 500):
    with _connect() as conn:
        cur = conn.execute("SELECT user_id FROM users")
        while True:
            rows = cur.fetchmany(batch_size)
            if not rows:
                break
            yield [int(row["user_id"]) for row in rows]


def get_users_page(limit: int, offset: int) -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT user_id, username, full_name
            FROM users
            ORDER BY
                CASE
                    WHEN username IS NOT NULL AND TRIM(username) != '' THEN 0
                    WHEN full_name IS NOT NULL AND TRIM(full_name) != '' THEN 1
                    ELSE 2
                END,
                LOWER(
                    COALESCE(
                        NULLIF(username, ''),
                        NULLIF(full_name, ''),
                        CAST(user_id AS TEXT)
                    )
                ),
                user_id
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [dict(row) for row in cur.fetchall()]


def save_upload_session(
    admin_id: int,
    code: int,
    items: List[Dict[str, str]],
    now: str,
    status_message_id: Optional[int] = None,
    allow_more: int = 1,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO upload_sessions (
                admin_id, code, items_json, created_at, status_message_id, allow_more
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (admin_id, code, json.dumps(items), now, status_message_id, allow_more),
        )
        conn.commit()


def get_upload_session(admin_id: int) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT admin_id, code, items_json, created_at, status_message_id, allow_more
            FROM upload_sessions
            WHERE admin_id = ?
            """,
            (admin_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "admin_id": row["admin_id"],
            "code": row["code"],
            "items": json.loads(row["items_json"]),
            "created_at": row["created_at"],
            "status_message_id": row["status_message_id"],
            "allow_more": row["allow_more"] if row["allow_more"] is not None else 1,
        }


def clear_upload_session(admin_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM upload_sessions WHERE admin_id = ?", (admin_id,))
        conn.commit()


def add_join_request(chat_id: int, user_id: int, requested_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO join_requests (chat_id, user_id, requested_at)
            VALUES (?, ?, ?)
            """,
            (chat_id, user_id, requested_at),
        )
        conn.commit()


def remove_join_request(chat_id: int, user_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM join_requests WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        conn.commit()


def has_join_request(chat_id: int, user_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM join_requests WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )
        return cur.fetchone() is not None


def _migrate_movies(conn: sqlite3.Connection) -> None:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='movies'"
    )
    has_movies = cur.fetchone() is not None
    if not has_movies:
        return
    cur = conn.execute("SELECT COUNT(1) AS cnt FROM movie_items")
    if int(cur.fetchone()["cnt"]) > 0:
        return
    cur = conn.execute("SELECT code, file_id, file_type, caption FROM movies")
    rows = cur.fetchall()
    for row in rows:
        code = row["code"]
        if not str(code).isdigit():
            continue
        conn.execute(
            """
            INSERT INTO movie_items (code, file_id, file_type, caption)
            VALUES (?, ?, ?, ?)
            """,
            (int(code), row["file_id"], row["file_type"], row["caption"]),
        )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    cur = conn.execute(f"PRAGMA table_info({table})")
    columns = {row["name"] for row in cur.fetchall()}
    if column in columns:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


def _fill_null_admin_perms(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE admins
        SET
            can_manage_admins = COALESCE(can_manage_admins, 1),
            can_manage_channels = COALESCE(can_manage_channels, 1),
            can_manage_vip = COALESCE(can_manage_vip, 1),
            can_add_serial = COALESCE(can_add_serial, 1),
            can_add_part = COALESCE(can_add_part, 1),
            can_broadcast = COALESCE(can_broadcast, 1),
            can_view_lists = COALESCE(can_view_lists, 1),
            can_view_logs = COALESCE(can_view_logs, 1),
            can_view_stats = COALESCE(can_view_stats, 1),
            can_backup = COALESCE(can_backup, 1)
        """
    )
