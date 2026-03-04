import json
import os
import sqlite3
import datetime as dt
from typing import Dict, List, Optional, Tuple

from app.config import DB_PATH, OWNER_ID


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
                created_at TEXT NOT NULL
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
        _ensure_column(conn, "serial_parts", "created_at", "TEXT")
        _ensure_column(conn, "vip_users", "reminded_7d", "INTEGER")
        _fill_null_admin_perms(conn)
        _ensure_column(conn, "users", "username", "TEXT")
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
            "SELECT id, code, title, is_vip, created_at FROM serials WHERE code = ?",
            (code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_serial_by_id(serial_id: int) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, code, title, is_vip, created_at FROM serials WHERE id = ?",
            (serial_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_serials() -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, code, title, is_vip, created_at FROM serials ORDER BY code ASC"
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


def add_user(user_id: int, username: Optional[str] = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username or ""),
        )
        if username:
            conn.execute(
                "UPDATE users SET username = ? WHERE user_id = ?",
                (username, user_id),
            )
        conn.commit()


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
            "SELECT user_id, username FROM users ORDER BY user_id"
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
