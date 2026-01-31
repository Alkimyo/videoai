import sqlite3
from typing import Dict, List, Optional, Tuple

from app.config import DB_PATH, OWNER_ID


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
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
                username TEXT NOT NULL,
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
                user_id INTEGER PRIMARY KEY
            )
            """
        )
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


def add_channel(chat_id: int, username: str, title: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO channels (chat_id, username, title) VALUES (?, ?, ?)",
            (chat_id, username, title),
        )
        conn.commit()


def del_channel(chat_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM channels WHERE chat_id = ?", (chat_id,))
        conn.commit()


def get_channels() -> List[Dict[str, str]]:
    with _connect() as conn:
        cur = conn.execute("SELECT chat_id, username, title FROM channels")
        return [dict(row) for row in cur.fetchall()]


def add_movie(code: str, file_id: str, file_type: str, caption: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO movies (code, file_id, file_type, caption) VALUES (?, ?, ?, ?)",
            (code, file_id, file_type, caption),
        )
        conn.commit()


def del_movie(code: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM movies WHERE code = ?", (code,))
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
        cur = conn.execute("SELECT 1 FROM movies WHERE code = ?", (code,))
        return cur.fetchone() is not None


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


def add_user(user_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )
        conn.commit()


def get_users() -> List[int]:
    with _connect() as conn:
        cur = conn.execute("SELECT user_id FROM users ORDER BY user_id")
        return [row["user_id"] for row in cur.fetchall()]
