import os
import tempfile
import unittest

import aiosqlite

from config import settings
from database import (
    create_agency,
    get_lead_by_id,
    get_recent_leads,
    init_db,
    is_lead_processed,
    mark_lead_processed,
    record_delivered_lead,
    register_manager,
)


class DatabaseLeadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database_path = settings.DATABASE_PATH
        settings.DATABASE_PATH = os.path.join(self.temp_dir.name, "test.db")

    async def asyncTearDown(self):
        settings.DATABASE_PATH = self.original_database_path
        self.temp_dir.cleanup()

    async def test_migrates_legacy_rows_to_deduplication_only(self):
        async with aiosqlite.connect(settings.DATABASE_PATH) as conn:
            await conn.execute("""
                CREATE TABLE processed_leads (
                    lead_id TEXT PRIMARY KEY,
                    agency_id INTEGER NOT NULL,
                    manager_id INTEGER,
                    object_code TEXT,
                    customer_name TEXT,
                    contact TEXT,
                    ad_title TEXT,
                    message_text TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute(
                """
                INSERT INTO processed_leads (
                    lead_id, agency_id, manager_id, object_code,
                    customer_name, contact, ad_title, message_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("legacy:1", 1, 42, "123456", "Private Name", "Private Contact", "Title", "Private message"),
            )
            await conn.commit()

        await init_db()

        self.assertTrue(await is_lead_processed(1, "legacy:1"))
        self.assertEqual(await get_recent_leads(), [])

        async with aiosqlite.connect(settings.DATABASE_PATH) as conn:
            async with conn.execute("PRAGMA table_info(processed_leads)") as cursor:
                dedup_columns = {row[1] for row in await cursor.fetchall()}
            async with conn.execute("SELECT COUNT(*) FROM delivered_leads") as cursor:
                delivered_count = (await cursor.fetchone())[0]

        self.assertEqual(dedup_columns, {"agency_id", "lead_id", "processed_at"})
        self.assertEqual(delivered_count, 0)

    async def test_deduplication_markers_are_scoped_to_agency(self):
        await init_db()

        await mark_lead_processed(1, "same-id")
        await mark_lead_processed(2, "same-id")

        self.assertTrue(await is_lead_processed(1, "same-id"))
        self.assertTrue(await is_lead_processed(2, "same-id"))
        self.assertFalse(await is_lead_processed(3, "same-id"))

    async def test_admin_history_contains_only_explicitly_delivered_leads(self):
        await init_db()
        agency_id = await create_agency("Test agency", "test-key", "test-invite")
        await register_manager(42, agency_id, "realtor", "Test Realtor")

        await mark_lead_processed(agency_id, "dedup-only")
        await record_delivered_lead(
            lead_id="delivered",
            agency_id=agency_id,
            manager_id=42,
            object_code="123456",
            customer_name="Test Customer",
            contact="test-contact",
            ad_title="Test Property",
            message_text="Message sent in the realtor's private chat",
        )

        leads = await get_recent_leads()
        self.assertEqual([lead["lead_id"] for lead in leads], ["delivered"])
        self.assertEqual(leads[0]["manager_id"], 42)
        self.assertEqual(leads[0]["message_text"], "Message sent in the realtor's private chat")
        self.assertIsNotNone(await get_lead_by_id("delivered", agency_id))
        self.assertIsNone(await get_lead_by_id("dedup-only", agency_id))


if __name__ == "__main__":
    unittest.main()
