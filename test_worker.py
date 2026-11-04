import unittest
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from worker import process_agency_leads


class WorkerDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def run_one_lead(
        self,
        *,
        manager,
        send_result="sent text",
        fallback_chat_id=None,
        send_side_effect=None,
    ):
        agency = {
            "id": 7,
            "name": "Test Agency",
            "api_key": "test-key",
            "fallback_chat_id": fallback_chat_id,
        }
        bot = object()
        client = AsyncMock()
        client.get_profiles.return_value = [{"profile_id": "profile-1"}]
        client.get_leads_for_profile.return_value = [{"lead_id": "lead-1"}]
        client.get_lead_details.return_value = {
            "platform_raw": {"item_id": "123456"},
            "customer_name": "Test Customer",
            "contact": "test-contact",
            "ad_title": "Test Property",
        }

        safe_send_mock = (
            AsyncMock(side_effect=send_side_effect)
            if send_side_effect is not None
            else AsyncMock(return_value=send_result)
        )

        with patch("worker.DialogiAIClient", return_value=client), \
                patch("worker.is_lead_processed", new=AsyncMock(return_value=False)), \
                patch("worker.find_manager_for_object", new=AsyncMock(return_value=manager)), \
                patch("worker.record_delivered_lead", new=AsyncMock()) as record_delivered, \
                patch("worker.mark_lead_processed", new=AsyncMock()) as mark_processed, \
                patch("worker.safe_send_lead", new=safe_send_mock) as safe_send, \
                patch("worker.asyncio.sleep", new=AsyncMock()):
            await process_agency_leads(agency, bot)

        return record_delivered, mark_processed, safe_send

    async def test_records_only_successful_private_message_delivery(self):
        manager = {"telegram_id": 42}
        record_delivered, mark_processed, safe_send = await self.run_one_lead(manager=manager)

        safe_send.assert_awaited_once()
        record_delivered.assert_awaited_once()
        self.assertEqual(record_delivered.await_args.kwargs["manager_id"], 42)
        self.assertEqual(record_delivered.await_args.kwargs["lead_id"], "lead-1")
        self.assertEqual(record_delivered.await_args.kwargs["message_text"], "sent text")
        mark_processed.assert_not_awaited()

    async def test_failed_private_message_is_not_recorded_or_marked_processed(self):
        manager = {"telegram_id": 42}
        record_delivered, mark_processed, _ = await self.run_one_lead(
            manager=manager,
            send_result=None,
        )

        record_delivered.assert_not_awaited()
        mark_processed.assert_not_awaited()

    async def test_unassigned_lead_is_only_marked_for_deduplication(self):
        record_delivered, mark_processed, _ = await self.run_one_lead(manager=None)

        record_delivered.assert_not_awaited()
        mark_processed.assert_awaited_once_with(7, "lead-1")

    async def test_blocked_realtor_falls_back_without_entering_admin_history(self):
        forbidden = TelegramForbiddenError(
            SendMessage(chat_id=42, text="lead"),
            "bot was blocked by the user",
        )
        record_delivered, mark_processed, safe_send = await self.run_one_lead(
            manager={"telegram_id": 42},
            fallback_chat_id=-1001234567890,
            send_side_effect=[forbidden, "fallback text"],
        )

        self.assertEqual(safe_send.await_count, 2)
        self.assertEqual(safe_send.await_args_list[1].args[1], -1001234567890)
        record_delivered.assert_not_awaited()
        mark_processed.assert_awaited_once_with(7, "lead-1")


if __name__ == "__main__":
    unittest.main()
