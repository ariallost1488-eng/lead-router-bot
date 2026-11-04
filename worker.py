import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from config import settings
from database import (
    get_agencies,
    find_manager_for_object,
    is_lead_processed,
    mark_lead_processed,
    record_delivered_lead
)
from api_client import DialogiAIClient
from utils import extract_object_code, format_lead_message, format_lead_short, build_lead_keyboard

logger = logging.getLogger(__name__)

async def safe_send_lead(
    bot: Bot,
    chat_id: int,
    lead_details: dict,
    is_unassigned: bool = False,
    agency_name: str = ""
) -> Optional[str]:
    """Безопасная отправка с фолбэком на краткий текст при ошибках длины или парсинга"""
    text = format_lead_message(lead_details, is_unassigned=is_unassigned, agency_name=agency_name)
    kb = build_lead_keyboard(lead_details)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return text
    except TelegramBadRequest as e:
        logger.warning(f"TelegramBadRequest sending lead to {chat_id}: {e}. Retrying with short format...")
        try:
            short_text = format_lead_short(lead_details, is_unassigned=is_unassigned, agency_name=agency_name)
            await bot.send_message(
                chat_id=chat_id,
                text=short_text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return short_text
        except TelegramForbiddenError:
            raise
        except Exception as e2:
            logger.error(f"Failed to send even short format to {chat_id}: {e2}")
            return None
    except TelegramForbiddenError:
        raise
    except Exception as e:
        logger.error(f"Error sending lead to {chat_id}: {e}")
        return None

async def process_agency_leads(agency: dict, bot: Bot):
    agency_id = agency["id"]
    agency_name = agency["name"]
    api_key = agency["api_key"]
    fallback_chat_id = agency.get("fallback_chat_id")

    client = DialogiAIClient(api_key=api_key, base_url=settings.DIALOGIAI_BASE_URL)
    profiles = await client.get_profiles()

    if not profiles:
        return

    for profile in profiles:
        profile_id = profile.get("profile_id")
        if not profile_id or profile.get("status") == "disconnected":
            continue

        leads = await client.get_leads_for_profile(profile_id=profile_id, limit=20)
        for lead_summary in leads:
            lead_id = lead_summary.get("lead_id")
            if not lead_id or await is_lead_processed(agency_id, lead_id):
                continue

            # Получаем полную информацию о лиде
            details = await client.get_lead_details(lead_id)
            if not details:
                # Если детали не получены, не спамим запросами, маркируем или пропускаем
                continue

            # Определяем код объекта: сначала из platform_raw, затем парсингом ссылки ad_url
            raw_meta = details.get("platform_raw") or {}
            object_code = str(raw_meta.get("item_id") or raw_meta.get("offer_id") or "").strip()

            if not object_code:
                ad_url = details.get("ad_url") or ""
                extracted = extract_object_code(ad_url)
                if extracted:
                    object_code = extracted

            manager = None
            if object_code:
                manager = await find_manager_for_object(agency_id, object_code)

            cust_name = details.get("customer_name")
            contact_val = details.get("contact")
            title_val = details.get("ad_title")
            if manager:
                manager_tg_id = manager["telegram_id"]
                try:
                    sent = await safe_send_lead(bot, manager_tg_id, details, is_unassigned=False, agency_name=agency_name)
                    if sent:
                        logger.info(f"Lead {lead_id} sent to manager {manager_tg_id} (code: {object_code})")
                        await record_delivered_lead(
                            lead_id=lead_id,
                            agency_id=agency_id,
                            manager_id=manager_tg_id,
                            object_code=object_code,
                            customer_name=cust_name,
                            contact=contact_val,
                            ad_title=title_val,
                            message_text=sent
                        )
                    else:
                        logger.warning(f"Lead {lead_id} could not be delivered to {manager_tg_id}")
                except TelegramForbiddenError:
                    logger.warning(f"Bot blocked by manager {manager_tg_id}. Falling back to group chat.")
                    if fallback_chat_id:
                        sent = await safe_send_lead(
                            bot,
                            fallback_chat_id,
                            details,
                            is_unassigned=True,
                            agency_name=agency_name
                        )
                        if sent:
                            await mark_lead_processed(agency_id, lead_id)
                    else:
                        await mark_lead_processed(agency_id, lead_id)
            else:
                # Объект НЕ прикреплен ни к одному риелтору:
                # Не засоряем базу — не сохраняем текст переписки и контакты!
                if fallback_chat_id:
                    sent = await safe_send_lead(
                        bot,
                        fallback_chat_id,
                        details,
                        is_unassigned=True,
                        agency_name=agency_name
                    )
                    if sent:
                        logger.info(f"Unassigned lead {lead_id} sent to fallback chat {fallback_chat_id}")
                        await mark_lead_processed(agency_id, lead_id)
                else:
                    logger.info(f"Ignored lead {lead_id} (code {object_code}): not in realtors' objects list")
                    await mark_lead_processed(agency_id, lead_id)

            # Пауза между обработкой лидов
            await asyncio.sleep(0.5)

async def start_lead_polling_worker(bot: Bot):
    logger.info("Starting background lead polling worker...")
    while True:
        try:
            agencies = await get_agencies()
            for agency in agencies:
                try:
                    await process_agency_leads(agency, bot)
                except Exception as e:
                    logger.error(f"Error processing leads for agency {agency.get('name')}: {e}")
                # Пауза между агентствами
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.error(f"Unexpected error in polling worker: {e}")

        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
