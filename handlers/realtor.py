import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command, CommandObject

from config import settings
from database import (
    get_manager,
    register_manager,
    get_agency_by_invite_code,
    bind_object,
    unbind_object,
    get_manager_objects
)
from utils import extract_all_object_codes, is_valid_url

realtor_router = Router()

def is_admin(telegram_id: int) -> bool:
    if not settings.admin_ids:
        return False
    return telegram_id in settings.admin_ids

@realtor_router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    telegram_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    args = command.args

    # Если зашел админ без инвайта — перенаправляем в админ-панель
    if is_admin(telegram_id) and not (args and args.startswith("agency_")):
        from handlers.admin import show_admin_panel
        await show_admin_panel(message)
        return

    # Проверяем, пришел ли пользователь по инвайт-ссылке агентства (?start=agency_XXX)
    if args and args.startswith("agency_"):
        invite_code = args.replace("agency_", "").strip()
        agency = await get_agency_by_invite_code(invite_code)

        if not agency:
            await message.answer("❌ Недействительная ссылка приглашения или агентство не найдено.")
            return

        await register_manager(telegram_id, agency["id"], username, full_name)
        await message.answer(
            f"🤝 <b>Вы успешно подключены к агентству «{html.escape(agency['name'])}»!</b>\n\n"
            f"Теперь отправьте мне ссылки на ваши объявления с <b>Циан</b> или <b>Авито</b> (можно несколько сообщений или списком).\n\n"
            f"Я автоматически привяжу их к вам, и все новые лиды по этим объектам будут приходить прямо сюда в ЛС.\n\n"
            f"Команды:\n"
            f"/my — Список моих закрепленных объектов"
        )
        return

    # Если зашел без аргументов обычный пользователь
    manager = await get_manager(telegram_id)
    if not manager:
        await message.answer(
            "👋 Привет! Этот бот персонально доставляет лиды риелторам в личные сообщения.\n\n"
            "⚠️ Вы пока не прикреплены ни к одному агентству.\n"
            "Попросите вашего руководителя прислать вам специальную <b>инвайт-ссылку</b> для подключения."
        )
        return

    await message.answer(
        f"👋 С возвращением! Вы работаете в агентстве «<b>{html.escape(manager['agency_name'])}</b>».\n\n"
        f"📩 Чтобы закрепить за собой объект, просто отправьте ссылку на него (Циан или Авито) или его ID в этот чат.\n\n"
        f"Команды:\n"
        f"/my — Посмотреть мои объекты и отвязать ненужные"
    )

@realtor_router.message(Command("my"))
async def cmd_my_objects(message: Message):
    telegram_id = message.from_user.id
    manager = await get_manager(telegram_id)

    if not manager:
        await message.answer("Сначала подключитесь к агентству по инвайт-ссылке.")
        return

    agency_name = manager.get("agency_name") or "Не указано"
    full_name = manager.get("full_name") or "Риелтор"

    objects = await get_manager_objects(telegram_id)
    if not objects:
        await message.answer(
            f"🏢 <b>Агентство:</b> «{html.escape(agency_name)}»\n"
            f"👤 <b>Риелтор:</b> {html.escape(full_name)}\n\n"
            "📭 У вас пока нет закрепленных объектов.\n\n"
            "Отправьте мне ссылку на объявление (Циан или Авито), чтобы привязать его к себе."
        )
        return

    text = (
        f"🏢 <b>Агентство:</b> «{html.escape(agency_name)}»\n"
        f"👤 <b>Риелтор:</b> {html.escape(full_name)}\n\n"
        f"📋 <b>Ваши закрепленные объекты ({len(objects)} шт.):</b>\n\n"
    )
    keyboard_buttons = []

    for obj in objects:
        code = html.escape(str(obj["object_code"]))
        raw_url = (obj.get("raw_url") or "").strip()
        display = f"Код: <code>{code}</code>"
        if raw_url and is_valid_url(raw_url):
            display += f" (<a href='{html.escape(raw_url)}'>ссылка</a>)"
        text += f"• {display}\n"
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"❌ Отвязать {code}", callback_data=f"unbind:{code}")
        ])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons),
        disable_web_page_preview=True
    )

@realtor_router.callback_query(F.data.startswith("unbind:"))
async def callback_unbind(call: CallbackQuery):
    telegram_id = call.from_user.id
    object_code = call.data.split(":", 1)[1]

    success = await unbind_object(telegram_id, object_code)
    if success:
        await call.answer(f"Объект {object_code} отвязан!", show_alert=False)
        # Обновляем список объектов
        objects = await get_manager_objects(telegram_id)
        if not objects:
            await call.message.edit_text("📭 У вас больше нет закрепленных объектов.")
            return

        text = f"📋 <b>Ваши закрепленные объекты ({len(objects)} шт.):</b>\n\n"
        keyboard_buttons = []
        for obj in objects:
            code = html.escape(str(obj["object_code"]))
            raw_url = (obj.get("raw_url") or "").strip()
            display = f"Код: <code>{code}</code>"
            if raw_url and is_valid_url(raw_url):
                display += f" (<a href='{html.escape(raw_url)}'>ссылка</a>)"
            text += f"• {display}\n"
            keyboard_buttons.append([
                InlineKeyboardButton(text=f"❌ Отвязать {code}", callback_data=f"unbind:{code}")
            ])

        await call.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons),
            disable_web_page_preview=True
        )
    else:
        await call.answer("Не удалось отвязать объект или он уже удален.", show_alert=True)

@realtor_router.message(F.text)
async def handle_incoming_links(message: Message):
    telegram_id = message.from_user.id
    manager = await get_manager(telegram_id)

    if not manager:
        await message.answer("Сначала подключитесь к агентству по инвайт-ссылке.")
        return

    codes = extract_all_object_codes(message.text)
    if not codes:
        await message.answer(
            "Не удалось распознать ссылку на объявление или код объекта.\n"
            "Пришлите прямую ссылку на Циан или Авито, например:\n"
            "<code>https://cian.ru/sale/suburban/335208747/</code>"
        )
        return

    agency_id = manager["agency_id"]
    added_codes = []

    for code in codes:
        await bind_object(
            agency_id=agency_id,
            manager_id=telegram_id,
            object_code=code,
            raw_url=message.text.strip() if len(codes) == 1 else ""
        )
        added_codes.append(code)

    if len(added_codes) == 1:
        await message.answer(f"✅ Объект <code>{added_codes[0]}</code> успешно закреплен за вами!")
    else:
        codes_str = ", ".join([f"<code>{c}</code>" for c in added_codes])
        await message.answer(f"✅ Закреплено объектов ({len(added_codes)} шт.): {codes_str}")
