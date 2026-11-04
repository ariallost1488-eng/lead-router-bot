import aiosqlite
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
from config import settings

@asynccontextmanager
async def get_db_connection():
    async with aiosqlite.connect(settings.DATABASE_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode = WAL;")
        await conn.execute("PRAGMA busy_timeout = 5000;")
        await conn.execute("PRAGMA foreign_keys = ON;")
        yield conn

async def _init_lead_tables(conn: aiosqlite.Connection) -> None:
    async with conn.execute("PRAGMA table_info(processed_leads)") as cursor:
        columns = {row["name"] for row in await cursor.fetchall()}

    if "manager_id" in columns:
        await conn.execute("ALTER TABLE processed_leads RENAME TO processed_leads_legacy")
        await conn.execute("""
            CREATE TABLE processed_leads (
                agency_id INTEGER NOT NULL,
                lead_id TEXT NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (agency_id, lead_id)
            );
        """)
        await conn.execute("""
            INSERT OR IGNORE INTO processed_leads (agency_id, lead_id, processed_at)
            SELECT agency_id, lead_id, COALESCE(processed_at, CURRENT_TIMESTAMP)
            FROM processed_leads_legacy
        """)
        await conn.execute("DROP TABLE processed_leads_legacy")
    elif not columns:
        await conn.execute("""
            CREATE TABLE processed_leads (
                agency_id INTEGER NOT NULL,
                lead_id TEXT NOT NULL,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (agency_id, lead_id)
            );
        """)
    elif not {"agency_id", "lead_id", "processed_at"}.issubset(columns):
        raise RuntimeError("processed_leads has an unsupported database schema")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS delivered_leads (
            agency_id INTEGER NOT NULL,
            lead_id TEXT NOT NULL,
            manager_id INTEGER NOT NULL,
            object_code TEXT,
            customer_name TEXT,
            contact TEXT,
            ad_title TEXT,
            message_text TEXT,
            delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (agency_id, lead_id)
        );
    """)

async def init_db() -> None:
    async with get_db_connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS agencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                api_key TEXT NOT NULL UNIQUE,
                invite_code TEXT NOT NULL UNIQUE,
                fallback_chat_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS managers (
                telegram_id INTEGER PRIMARY KEY,
                agency_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(agency_id) REFERENCES agencies(id) ON DELETE CASCADE
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agency_id INTEGER NOT NULL,
                manager_id INTEGER NOT NULL,
                object_code TEXT NOT NULL,
                raw_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agency_id, object_code),
                FOREIGN KEY(manager_id) REFERENCES managers(telegram_id) ON DELETE CASCADE,
                FOREIGN KEY(agency_id) REFERENCES agencies(id) ON DELETE CASCADE
            );
        """)
        await _init_lead_tables(conn)
        await conn.commit()

async def create_agency(name: str, api_key: str, invite_code: str, fallback_chat_id: Optional[int] = None) -> int:
    async with get_db_connection() as conn:
        cursor = await conn.execute(
            """
            INSERT INTO agencies (name, api_key, invite_code, fallback_chat_id)
            VALUES (?, ?, ?, ?)
            """,
            (name, api_key, invite_code, fallback_chat_id)
        )
        await conn.commit()
        return cursor.lastrowid

async def get_agencies() -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.execute("SELECT * FROM agencies") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_agency_by_id(agency_id: int) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.execute("SELECT * FROM agencies WHERE id = ?", (agency_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_agency_by_invite_code(invite_code: str) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.execute("SELECT * FROM agencies WHERE invite_code = ?", (invite_code,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def update_agency_fallback_chat(agency_id: int, chat_id: Optional[int]) -> bool:
    async with get_db_connection() as conn:
        cursor = await conn.execute(
            "UPDATE agencies SET fallback_chat_id = ? WHERE id = ?",
            (chat_id, agency_id)
        )
        await conn.commit()
        return cursor.rowcount > 0

async def register_manager(telegram_id: int, agency_id: int, username: Optional[str], full_name: Optional[str]) -> None:
    async with get_db_connection() as conn:
        # Если менеджер переходит из другого агентства, удаляем его старые привязки объектов
        await conn.execute(
            "DELETE FROM objects WHERE manager_id = ? AND agency_id != ?",
            (telegram_id, agency_id)
        )
        await conn.execute(
            """
            INSERT INTO managers (telegram_id, agency_id, username, full_name, is_active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(telegram_id) DO UPDATE SET
                agency_id = excluded.agency_id,
                username = excluded.username,
                full_name = excluded.full_name,
                is_active = 1
            """,
            (telegram_id, agency_id, username, full_name)
        )
        await conn.commit()

async def get_manager(telegram_id: int) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.execute(
            """
            SELECT m.*, a.name as agency_name, a.invite_code as agency_invite_code
            FROM managers m
            JOIN agencies a ON m.agency_id = a.id
            WHERE m.telegram_id = ?
            """,
            (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def bind_object(agency_id: int, manager_id: int, object_code: str, raw_url: str = "") -> bool:
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO objects (agency_id, manager_id, object_code, raw_url)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(agency_id, object_code) DO UPDATE SET
                manager_id = excluded.manager_id,
                raw_url = excluded.raw_url
            """,
            (agency_id, manager_id, object_code, raw_url)
        )
        await conn.commit()
        return True

async def unbind_object(manager_id: int, object_code: str) -> bool:
    async with get_db_connection() as conn:
        cursor = await conn.execute(
            "DELETE FROM objects WHERE manager_id = ? AND object_code = ?",
            (manager_id, object_code)
        )
        await conn.commit()
        return cursor.rowcount > 0

async def get_manager_objects(manager_id: int) -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.execute(
            "SELECT * FROM objects WHERE manager_id = ? ORDER BY created_at DESC",
            (manager_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def find_manager_for_object(agency_id: int, object_code: str) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.execute(
            """
            SELECT m.*
            FROM objects o
            JOIN managers m ON o.manager_id = m.telegram_id
            WHERE o.agency_id = ?
              AND o.object_code = ?
              AND m.agency_id = o.agency_id
              AND m.is_active = 1
            """,
            (agency_id, object_code)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_agency_managers_with_objects(agency_id: int) -> List[Dict[str, Any]]:
    """Возвращает список риелторов агентства вместе со списком их объектов"""
    async with get_db_connection() as conn:
        async with conn.execute(
            """
            SELECT m.telegram_id, m.username, m.full_name, m.created_at,
                   GROUP_CONCAT(o.object_code, ', ') as object_codes,
                   COUNT(o.id) as objects_count
            FROM managers m
            LEFT JOIN objects o ON m.telegram_id = o.manager_id AND o.agency_id = m.agency_id
            WHERE m.agency_id = ? AND m.is_active = 1
            GROUP BY m.telegram_id
            ORDER BY m.created_at DESC
            """,
            (agency_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_agency_stats(agency_id: int) -> Dict[str, int]:
    async with get_db_connection() as conn:
        async with conn.execute("SELECT COUNT(*) FROM managers WHERE agency_id = ? AND is_active = 1", (agency_id,)) as c:
            managers_count = (await c.fetchone())[0]
        async with conn.execute("SELECT COUNT(*) FROM objects WHERE agency_id = ?", (agency_id,)) as c:
            objects_count = (await c.fetchone())[0]
        async with conn.execute("SELECT COUNT(*) FROM delivered_leads WHERE agency_id = ?", (agency_id,)) as c:
            delivered_leads = (await c.fetchone())[0]
        return {
            "managers_count": managers_count,
            "objects_count": objects_count,
            "delivered_leads": delivered_leads,
        }

async def get_total_stats() -> Dict[str, int]:
    async with get_db_connection() as conn:
        async with conn.execute("SELECT COUNT(*) FROM agencies") as c:
            agencies_count = (await c.fetchone())[0]
        async with conn.execute("SELECT COUNT(*) FROM managers WHERE is_active = 1") as c:
            managers_count = (await c.fetchone())[0]
        async with conn.execute("SELECT COUNT(*) FROM objects") as c:
            objects_count = (await c.fetchone())[0]
        async with conn.execute("SELECT COUNT(*) FROM delivered_leads") as c:
            delivered_count = (await c.fetchone())[0]
        return {
            "agencies_count": agencies_count,
            "managers_count": managers_count,
            "objects_count": objects_count,
            "delivered_count": delivered_count,
        }

async def is_lead_processed(agency_id: int, lead_id: str) -> bool:
    async with get_db_connection() as conn:
        async with conn.execute(
            "SELECT 1 FROM processed_leads WHERE agency_id = ? AND lead_id = ?",
            (agency_id, lead_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row is not None

async def mark_lead_processed(agency_id: int, lead_id: str) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO processed_leads (agency_id, lead_id)
            VALUES (?, ?)
            ON CONFLICT(agency_id, lead_id) DO NOTHING
            """,
            (agency_id, lead_id)
        )
        await conn.commit()

async def record_delivered_lead(
    lead_id: str,
    agency_id: int,
    manager_id: int,
    object_code: Optional[str],
    customer_name: Optional[str],
    contact: Optional[str],
    ad_title: Optional[str],
    message_text: str,
) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO processed_leads (agency_id, lead_id)
            VALUES (?, ?)
            ON CONFLICT(agency_id, lead_id) DO NOTHING
            """,
            (agency_id, lead_id)
        )
        await conn.execute(
            """
            INSERT INTO delivered_leads (
                agency_id, lead_id, manager_id, object_code,
                customer_name, contact, ad_title, message_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agency_id, lead_id) DO NOTHING
            """,
            (agency_id, lead_id, manager_id, object_code, customer_name, contact, ad_title, message_text)
        )
        await conn.commit()

async def get_recent_leads(limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.execute(
            """
            SELECT
                l.*,
                m.full_name as manager_name,
                m.username as manager_username,
                a.name as agency_name
            FROM delivered_leads l
            INNER JOIN managers m ON l.manager_id = m.telegram_id
            INNER JOIN agencies a ON l.agency_id = a.id
            ORDER BY l.delivered_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_lead_by_id(lead_id: str, agency_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.execute(
            """
            SELECT
                l.*,
                m.full_name as manager_name,
                m.username as manager_username,
                a.name as agency_name
            FROM delivered_leads l
            INNER JOIN managers m ON l.manager_id = m.telegram_id
            INNER JOIN agencies a ON l.agency_id = a.id
            WHERE l.lead_id = ?
              AND (? IS NULL OR l.agency_id = ?)
            ORDER BY l.delivered_at DESC
            LIMIT 1
            """,
            (lead_id, agency_id, agency_id)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
