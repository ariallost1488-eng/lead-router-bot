import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from database import init_db
from handlers import admin_router, realtor_router
from worker import start_lead_polling_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

async def main():
    if not settings.BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in .env! Please configure .env file.")
        return

    # Инициализация базы данных SQLite
    await init_db()
    logger.info("Database initialized.")

    # Создание экземпляра бота и диспетчера
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # Регистрация роутеров
    dp.include_router(admin_router)
    dp.include_router(realtor_router)

    # Запуск фонового воркера опроса API DialogiAI
    worker_task = asyncio.create_task(start_lead_polling_worker(bot))

    logger.info("Starting Telegram Bot polling...")
    try:
        await dp.start_polling(bot)
    finally:
        worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await worker_task
        from api_client import close_http_session
        await close_http_session()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
