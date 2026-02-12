import json
import os
import sqlite3
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
                user_id INTEGER PRIMARY KEY
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
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT
            )
            """
        )
        _ensure_column(conn, "channels", "invite_link", "TEXT")
        _ensure_column(conn, "movie_items", "source_chat_id", "INTEGER")
        _ensure_column(conn, "movie_items", "source_message_id", "INTEGER")
        _ensure_column(conn, "upload_sessions", "status_message_id", "INTEGER")
        _ensure_column(conn, "upload_sessions", "allow_more", "INTEGER")
        _ensure_column(conn, "users", "username", "TEXT")
        _migrate_movies(conn)
        conn.commit()


def ensure_owner() -> None:
    if OWNER_ID:
        add_admin(OWNER_ID)


def add_admin(user_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admins (user_id) VALUES (?)",
            (user_id,),
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
            INSERT INTO serials (code, title, created_at)
            VALUES (?, ?, ?)
            """,
            (code, title, created_at),
        )
        cur = conn.execute(
            "SELECT id, code, title, created_at FROM serials WHERE code = ?",
            (code,),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row)


def get_serial_by_title(title: str) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, code, title, created_at FROM serials WHERE title = ?",
            (title,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_serial_by_code(code: int) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, code, title, created_at FROM serials WHERE code = ?",
            (code,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_serial_by_id(serial_id: int) -> Optional[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, code, title, created_at FROM serials WHERE id = ?",
            (serial_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_serials() -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT id, code, title, created_at FROM serials ORDER BY code ASC"
        )
        return [dict(row) for row in cur.fetchall()]


def add_serial_part(
    serial_id: int,
    part: int,
    file_id: str,
    file_type: str,
    caption: str,
    source_chat_id: Optional[int] = None,
    source_message_id: Optional[int] = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO serial_parts (
                serial_id, part, file_id, file_type, caption, source_chat_id, source_message_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                serial_id,
                part,
                file_id,
                file_type,
                caption,
                source_chat_id,
                source_message_id,
            ),
        )
        conn.commit()


def serial_part_exists(serial_id: int, part: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM serial_parts WHERE serial_id = ? AND part = ?",
            (serial_id, part),
        )
        return cur.fetchone() is not None


def get_serial_parts(serial_id: int) -> List[Dict[str, object]]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT part, file_id, file_type, caption, source_chat_id, source_message_id
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
            SELECT part, file_id, file_type, caption, source_chat_id, source_message_id
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
