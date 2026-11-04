import uuid
import html
from contextlib import suppress
from typing import Optional
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest

from config import settings
from database import (
    create_agency,
    get_agencies,
    get_agency_by_id,
    update_agency_fallback_chat,
    get_agency_stats,
    get_total_stats,
    get_agency_managers_with_objects,
    get_recent_leads,
    get_lead_by_id
)
from api_client import DialogiAIClient

admin_router = Router()

class AddAgencyStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_key = State()
    waiting_for_chat = State()

class SetChatStates(StatesGroup):
    waiting_for_chat_id = State()

def is_admin(telegram_id: int) -> bool:
    if not settings.admin_ids:
        return False
    return telegram_id in settings.admin_ids

def get_admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить агентство", callback_data="admin:add_agency")],
        [InlineKeyboardButton(text="🏢 Список агентств и ссылки", callback_data="admin:list_agencies")],
        [InlineKeyboardButton(text="📥 Сообщения риелторам (Лиды)", callback_data="admin:leads:0")],
        [InlineKeyboardButton(text="📊 Статистика системы", callback_data="admin:stats")]
    ])

async def show_admin_panel(message: Message, edit: bool = False):
    text = (
        "👑 <b>Панель администратора</b>\n\n"
        "Здесь вы можете подключать агентства, управлять общими чатами "
        "и получать персональные инвайт-ссылки для риелторов."
    )
    kb = get_admin_main_kb()
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)

@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к административной панели.")
        return
    await state.clear()
    await show_admin_panel(message)

@admin_router.callback_query(F.data == "admin:main")
async def cb_admin_main(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.clear()
    await show_admin_panel(call.message, edit=True)
    await call.answer()

@admin_router.callback_query(F.data == "admin:cancel")
async def cb_admin_cancel(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.clear()
    await show_admin_panel(call.message, edit=True)
    await call.answer("Действие отменено.")

# --- Сценарий добавления агентства (FSM) ---

@admin_router.callback_query(F.data == "admin:add_agency")
async def cb_add_agency_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    await state.set_state(AddAgencyStates.waiting_for_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel")]
    ])
    await call.message.edit_text(
        "🏢 <b>Шаг 1 из 3: Название агентства</b>\n\n"
        "Введите название агентства недвижимости (например: <code>Новая Жизнь</code>):",
        reply_markup=kb
    )
    await call.answer()

@admin_router.message(AddAgencyStates.waiting_for_name)
async def state_agency_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Отправьте название агентства обычным текстом.")
        return

    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Слишком короткое название. Введите ещё раз:")
        return

    await state.update_data(agency_name=name)
    await state.set_state(AddAgencyStates.waiting_for_key)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel")]
    ])
    await message.answer(
        f"🏢 Агентство: <b>{html.escape(name)}</b>\n\n"
        "🔑 <b>Шаг 2 из 3: API-ключ</b>\n"
        "Отправьте API-ключ DialogiAI (<code>X-Api-Key</code>):",
        reply_markup=kb
    )

@admin_router.message(AddAgencyStates.waiting_for_key)
async def state_agency_key(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Отправьте API-ключ обычным текстом.")
        return

    api_key = message.text.strip()
    status_msg = await message.answer("🔄 Проверяю API-ключ в DialogiAI...")

    client = DialogiAIClient(api_key=api_key, base_url=settings.DIALOGIAI_BASE_URL)
    me = await client.get_me()

    if not me:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel")]
        ])
        await status_msg.edit_text(
            "❌ <b>Ключ не прошел проверку!</b>\n"
            "Сервер DialogiAI вернул ошибку авторизации (401) или недоступен.\n\n"
            "Пожалуйста, проверьте и пришлите корректный ключ:",
            reply_markup=kb
        )
        return

    client_info = me.get("client", {})
    client_name = client_info.get("name") or "Аккаунт подтверждён"

    await state.update_data(api_key=api_key, client_name=client_name)
    await state.set_state(AddAgencyStates.waiting_for_chat)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить (без чата)", callback_data="admin:skip_chat")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:cancel")]
    ])
    await status_msg.edit_text(
        f"✅ Ключ подтверждён (Клиент: <b>{html.escape(client_name)}</b>)!\n\n"
        "💬 <b>Шаг 3 из 3: Запасной общий чат</b>\n"
        "Введите ID общего чата/группы (например <code>-1001234567890</code>), куда будут падать лиды, если объект не закреплен за риелтором.\n\n"
        "Либо нажмите «Пропустить»:",
        reply_markup=kb
    )

@admin_router.callback_query(F.data == "admin:skip_chat")
async def cb_skip_chat(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    await finish_agency_creation(call.message, state, fallback_chat_id=None, is_edit=True)
    await call.answer()

@admin_router.message(AddAgencyStates.waiting_for_chat)
async def state_agency_chat(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Отправьте ID чата числом или <code>-</code> для пропуска.")
        return

    text = message.text.strip()
    if text == "-":
        await finish_agency_creation(message, state, fallback_chat_id=None, is_edit=False)
        return

    try:
        chat_id = int(text)
    except ValueError:
        await message.answer("ID чата должен быть числом (например <code>-1001234567890</code>). Попробуйте ещё раз или отправьте <code>-</code>:")
        return

    await finish_agency_creation(message, state, fallback_chat_id=chat_id, is_edit=False)

async def finish_agency_creation(message: Message, state: FSMContext, fallback_chat_id: Optional[int], is_edit: bool = False):
    data = await state.get_data()
    await state.clear()

    if not data.get("agency_name") or not data.get("api_key"):
        error_text = "Сценарий добавления агентства устарел. Начните его заново."
        if is_edit:
            await message.edit_text(error_text)
        else:
            await message.answer(error_text)
        return

    name = data["agency_name"]
    api_key = data["api_key"]
    invite_code = uuid.uuid4().hex[:8]

    try:
        agency_id = await create_agency(
            name=name,
            api_key=api_key,
            invite_code=invite_code,
            fallback_chat_id=fallback_chat_id
        )
    except Exception as e:
        err_text = f"❌ Ошибка сохранения агентства: {e}"
        if is_edit:
            await message.edit_text(err_text)
        else:
            await message.answer(err_text)
        return

    bot_user = await message.bot.get_me()
    invite_url = f"https://t.me/{bot_user.username}?start=agency_{invite_code}"

    text = (
        f"🎉 <b>Агентство «{html.escape(name)}» успешно создано!</b>\n\n"
        f"<b>ID агентства:</b> <code>{agency_id}</code>\n"
        f"<b>Общий дежурный чат:</b> <code>{fallback_chat_id or 'Не назначен'}</code>\n\n"
        f"🔗 <b>Пригласительная ссылка для риелторов:</b>\n"
        f"<code>{invite_url}</code>\n\n"
        f"<i>(Нажмите на ссылку, чтобы скопировать и отправить риелторам)</i>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 К списку агентств", callback_data="admin:list_agencies")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="admin:main")]
    ])

    if is_edit:
        await message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    else:
        await message.answer(text, reply_markup=kb, disable_web_page_preview=True)

# --- Список агентств ---

@admin_router.callback_query(F.data == "admin:list_agencies")
async def cb_list_agencies(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    agencies = await get_agencies()
    if not agencies:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить агентство", callback_data="admin:add_agency")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:main")]
        ])
        await call.message.edit_text("📭 В системе пока нет подключенных агентств.", reply_markup=kb)
        await call.answer()
        return

    bot_user = await call.bot.get_me()
    text = "🏢 <b>Список подключенных агентств:</b>\n\n"
    buttons = []

    for a in agencies:
        stats = await get_agency_stats(a["id"])
        invite_url = f"https://t.me/{bot_user.username}?start=agency_{a['invite_code']}"
        text += (
            f"🔹 <b>{html.escape(a['name'])}</b> (ID: {a['id']})\n"
            f"👥 Риелторов: <b>{stats['managers_count']}</b> | 🏠 Объектов: <b>{stats['objects_count']}</b>\n"
            f"📥 Доставлено в личные сообщения: <b>{stats['delivered_leads']}</b>\n"
            f"💬 Дежурный чат: <code>{a.get('fallback_chat_id') or 'Не задан'}</code>\n"
            f"🔗 <b>Инвайт-ссылка для риелторов:</b>\n<code>{invite_url}</code>\n\n"
        )
        buttons.append([
            InlineKeyboardButton(text=f"👥 Риелторы «{a['name'][:12]}»", callback_data=f"admin:managers:{a['id']}"),
            InlineKeyboardButton(text="✏️ Сменить чат", callback_data=f"admin:set_chat:{a['id']}")
        ])

    buttons.append([InlineKeyboardButton(text="➕ Добавить агентство", callback_data="admin:add_agency")])
    buttons.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="admin:main")])

    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        disable_web_page_preview=True
    )
    await call.answer()

# --- Просмотр риелторов агентства ---

@admin_router.callback_query(F.data.startswith("admin:managers:"))
async def cb_view_agency_managers(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    agency_id = int(call.data.split(":")[-1])
    agency = await get_agency_by_id(agency_id)
    if not agency:
        await call.answer("Агентство не найдено", show_alert=True)
        return

    managers = await get_agency_managers_with_objects(agency_id)

    text = f"🏢 <b>Риелторы агентства «{html.escape(agency['name'])}»:</b>\n\n"
    if not managers:
        text += "<i>В этом агентстве пока нет зарегистрированных риелторов.\nОтправьте им инвайт-ссылку.</i>"
    else:
        for idx, m in enumerate(managers, 1):
            username_str = f"@{m['username']}" if m.get("username") else "нет username"
            full_name = html.escape(m.get("full_name") or "Риелтор")
            codes = html.escape(str(m.get("object_codes") or "нет закрепленных объектов"))
            count = m.get("objects_count", 0)
            text += (
                f"{idx}. <b>{full_name}</b> ({username_str}, ID: <code>{m['telegram_id']}</code>)\n"
                f"   🏠 Закреплено объектов: <b>{count}</b>\n"
                f"   📋 Коды: <code>{codes}</code>\n\n"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 К списку агентств", callback_data="admin:list_agencies")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="admin:main")]
    ])
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()

# --- Смена чата для агентства ---

@admin_router.callback_query(F.data.startswith("admin:set_chat:"))
async def cb_set_chat_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    agency_id = int(call.data.split(":")[-1])
    agency = await get_agency_by_id(agency_id)
    if not agency:
        await call.answer("Агентство не найдено", show_alert=True)
        return

    await state.update_data(target_agency_id=agency_id)
    await state.set_state(SetChatStates.waiting_for_chat_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin:list_agencies")]
    ])
    await call.message.edit_text(
        f"💬 <b>Смена общего дежурного чата</b> для «<b>{html.escape(agency['name'])}</b>»:\n\n"
        "Отправьте новый ID группы (например <code>-1001234567890</code>) "
        "или <code>0</code> чтобы отключить общий чат:",
        reply_markup=kb
    )
    await call.answer()

@admin_router.message(SetChatStates.waiting_for_chat_id)
async def state_set_chat_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Отправьте ID чата числом или <code>0</code>, чтобы отключить чат.")
        return

    try:
        val = int(message.text.strip())
    except ValueError:
        await message.answer("ID чата должен быть числом. Попробуйте ещё раз:")
        return

    data = await state.get_data()
    agency_id = data["target_agency_id"]
    await state.clear()

    new_chat_id = val if val != 0 else None
    if not await update_agency_fallback_chat(agency_id, new_chat_id):
        await message.answer("Не удалось обновить чат: агентство не найдено.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 К списку агентств", callback_data="admin:list_agencies")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="admin:main")]
    ])
    await message.answer(
        f"✅ Дежурный чат успешно обновлён на <code>{new_chat_id or 'Отключен'}</code>!",
        reply_markup=kb
    )

# --- Статистика ---

@admin_router.callback_query(F.data == "admin:stats")
async def cb_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    stats = await get_total_stats()
    text = (
        "📊 <b>Общая статистика системы:</b>\n\n"
        f"🏢 Подключено агентств: <b>{stats['agencies_count']}</b>\n"
        f"👥 Зарегистрировано риелторов: <b>{stats['managers_count']}</b>\n"
        f"🏠 Активных объектов в базе: <b>{stats['objects_count']}</b>\n"
        f"📥 Лидов доставлено риелторам в личные сообщения: <b>{stats['delivered_count']}</b>\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:stats")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="admin:main")]
    ])
    with suppress(TelegramBadRequest):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()

# --- Просмотр пришедших сообщений риелторам ---

@admin_router.callback_query(F.data.startswith("admin:leads:"))
async def cb_view_leads(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    offset = int(call.data.split(":")[-1])
    limit = 5
    leads = await get_recent_leads(limit=limit, offset=offset)

    if not leads and offset == 0:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="admin:main")]
        ])
        await call.message.edit_text("📭 Пока нет лидов, доставленных риелторам в личные сообщения.", reply_markup=kb)
        await call.answer()
        return

    text = f"📥 <b>Последние лиды, доставленные риелторам в личку</b> [Стр. {offset // limit + 1}]:\n\n"
    keyboard_rows = []

    for idx, l in enumerate(leads, 1):
        manager_str = html.escape(l.get("manager_name") or f"ID: {l.get('manager_id')}")
        if l.get("manager_username"):
            manager_str += f" (@{html.escape(l['manager_username'])})"
        agency_name = html.escape(l.get("agency_name") or "Не указано")
        contact_str = html.escape(l.get("contact") or "Не указан")
        ad_title_str = html.escape(l.get("ad_title") or "Объявление")
        time_str = l.get("delivered_at") or ""

        text += (
            f"<b>{idx}.</b> 👤 <b>Риелтор:</b> {manager_str}\n"
            f"   🏢 <b>Агентство:</b> {agency_name}\n"
            f"   🏠 <b>Объект:</b> {ad_title_str} (код: <code>{l.get('object_code') or '—'}</code>)\n"
            f"   📞 <b>Клиент:</b> {html.escape(l.get('customer_name') or 'Клиент')} (<code>{contact_str}</code>)\n"
            f"   🕒 {time_str}\n\n"
        )

        keyboard_rows.append([
            InlineKeyboardButton(
                text=f"👁 Читать #{idx} ({contact_str[:12]})",
                callback_data=f"admin:rl:{l['agency_id']}:id:{l['lead_id']}:{offset}"
            )
        ])

    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin:leads:{max(0, offset - limit)}"))
    if len(leads) == limit:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"admin:leads:{offset + limit}"))

    if nav_buttons:
        keyboard_rows.append(nav_buttons)
    keyboard_rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="admin:main")])

    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
        disable_web_page_preview=True
    )
    await call.answer()

@admin_router.callback_query(F.data.startswith("admin:rl:"))
async def cb_read_lead(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    prefix = "admin:rl:"
    rest = call.data[len(prefix):]
    head, offset_text = rest.rsplit(":", 1)
    parts = head.split(":", 2)
    if len(parts) == 3 and parts[0].isdigit() and parts[1] == "id":
        agency_id, lead_id = int(parts[0]), parts[2]
        offset = int(offset_text) if offset_text.isdigit() else 0
    else:
        lead_id = head
        agency_id = None
        offset = int(offset_text) if offset_text.isdigit() else 0

    lead = await get_lead_by_id(lead_id, agency_id)
    if not lead:
        await call.answer("Лид не найден в базе данных.", show_alert=True)
        return

    manager_str = html.escape(lead.get("manager_name") or f"ID: {lead.get('manager_id')}")
    if lead.get("manager_username"):
        manager_str += f" (@{html.escape(lead['manager_username'])})"
    header = (
        f"👤 <b>Получатель:</b> {manager_str}\n"
        f"🏢 <b>Агентство:</b> {html.escape(lead.get('agency_name') or '')}\n"
        f"🕒 <b>Время доставки:</b> {lead.get('delivered_at')}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    msg_body = lead.get("message_text") or "<i>(Текст сообщения не был сохранён)</i>"
    full_text = header + msg_body

    # Проверка на лимит длины
    if len(full_text) > 4000:
        full_text = full_text[:3900] + "\n\n<i>[...содержимое сообщения обрезано для Telegram...]</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К списку лидов", callback_data=f"admin:leads:{offset}")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="admin:main")]
    ])

    await call.message.edit_text(full_text, reply_markup=kb, disable_web_page_preview=True)
    await call.answer()
