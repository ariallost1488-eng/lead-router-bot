import re
import html
from typing import Optional, List, Dict, Any
from urllib.parse import urlsplit
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def _escaped_field(value: Any, default: str, max_chars: int) -> str:
    return html.escape(str(value or default)[:max_chars])

def extract_object_code(text_or_url: str) -> Optional[str]:
    """
    Извлекает уникальный числовой идентификатор объявления из ссылки или текста.
    Поддерживает:
      - Циан: https://cian.ru/sale/suburban/335208747/ -> 335208747
      - Авито: https://www.avito.ru/.../8155143014 -> 8155143014
      - Прямой ввод: 335208747
    """
    if not text_or_url:
        return None

    clean_text = text_or_url.strip()

    # Если пользователь просто ввел цифры (ID объявления)
    if clean_text.isdigit() and len(clean_text) >= 5:
        return clean_text

    candidate = clean_text.strip("<>()[]{}.,;")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not any(host == domain or host.endswith(f".{domain}") for domain in ("cian.ru", "avito.ru")):
        return None

    codes = re.findall(r"\d{5,}", parsed.path)
    return codes[-1] if codes else None

def extract_all_object_codes(text: str) -> List[str]:
    """
    Извлекает все найденные коды объектов из многострочного сообщения.
    """
    codes = []
    seen = set()
    lines = text.strip().split()
    for line in lines:
        code = extract_object_code(line.strip(".,;:()[]{}<>"))
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes

def format_lead_short(lead: Dict[str, Any], is_unassigned: bool = False, agency_name: str = "") -> str:
    """Краткое сообщение без переписки на случай аварийных сбоев длины"""
    platform = _escaped_field(lead.get("platform"), "Не указано", 80).capitalize()
    profile_name = _escaped_field(lead.get("profile_name"), "Не указан", 120)
    ad_title = _escaped_field(lead.get("ad_title"), "Без названия", 300)
    ad_url = str(lead.get("ad_url") or "").strip()[:500]
    customer_name = _escaped_field(lead.get("customer_name"), "Клиент", 120)
    contact = _escaped_field(lead.get("contact"), "Не указан", 200)

    header = "⚠️ НОВЫЙ ЛИД (НЕ НАЗНАЧЕН РИЕЛТОР) ━━━━━━━━━━━━" if is_unassigned else "🔥 НОВЫЙ ЛИД ━━━━━━━━━━━━━━━━━━"
    lines = [header]
    if agency_name:
        lines.append(f"🏢 <b>Агентство:</b> {_escaped_field(agency_name, '', 120)}")
    lines.extend([
        f"<b>Площадка:</b> {platform}",
        f"<b>Кабинет:</b> {profile_name}",
        f"<b>Объявление:</b> {ad_title}",
    ])
    if ad_url:
        lines.append(f"<b>Ссылка:</b> {html.escape(ad_url)}")
    lines.extend([
        f"<b>Имя:</b> {customer_name}",
        f"<b>Контакт:</b> <code>{contact}</code>",
        "",
        "<i>(Переписка не поместилась, откройте диалог по кнопке ниже)</i>"
    ])
    return "\n".join(lines)

def format_lead_message(lead: Dict[str, Any], is_unassigned: bool = False, agency_name: str = "", max_len: int = 3900) -> str:
    """
    Форматирует лид в человекопонятный текст.
    Гарантирует непревышение лимита длины Telegram (4096 символов).
    """
    platform = _escaped_field(lead.get("platform"), "Не указано", 80).capitalize()
    profile_name = _escaped_field(lead.get("profile_name"), "Не указан", 120)
    ad_title = _escaped_field(lead.get("ad_title"), "Без названия", 300)
    ad_url = str(lead.get("ad_url") or "").strip()[:500]
    customer_name = _escaped_field(lead.get("customer_name"), "Клиент", 120)
    contact = _escaped_field(lead.get("contact"), "Не указан", 200)

    header = "⚠️ НОВЫЙ ЛИД (НЕ НАЗНАЧЕН РИЕЛТОР) ━━━━━━━━━━━━" if is_unassigned else "🔥 НОВЫЙ ЛИД ━━━━━━━━━━━━━━━━━━"

    lines = [header]
    if agency_name:
        lines.append(f"🏢 <b>Агентство:</b> {_escaped_field(agency_name, '', 120)}")
    lines.extend([
        f"<b>Площадка:</b> {platform}",
        f"<b>Кабинет:</b> {profile_name}",
        f"<b>Объявление:</b> {ad_title}",
    ])

    if ad_url:
        lines.append(f"<b>Ссылка:</b> {html.escape(ad_url)}")

    lines.extend([
        f"<b>Имя:</b> {customer_name}",
        f"<b>Контакт:</b> <code>{contact}</code>",
        "",
        "<b>История переписки:</b>"
    ])

    base_header = "\n".join(lines)
    remaining_space = max_len - len(base_header)

    messages = lead.get("messages") or []
    if not messages:
        return base_header + "\n<i>(Диалог пуст или переписка не передана)</i>"

    # Форматируем каждое сообщение
    formatted_msgs = []
    for msg in messages:
        direction = msg.get("direction")
        text = html.escape((msg.get("text") or "").strip())
        sender = "👤 Клиент" if direction == "in" else "🤖 ИИ"
        formatted_msgs.append(f"<b>{sender}:</b> {text}")

    full_dialogue = "\n".join(formatted_msgs)
    if len(full_dialogue) <= remaining_space:
        return f"{base_header}\n{full_dialogue}"

    # Если диалог длинный, формируем умную выжимку (первые сообщения + последние)
    notice = "\n<i>[...часть диалога сокращена...]</i>\n"
    target_space = remaining_space - len(notice)

    if target_space < 100:
        return format_lead_short(lead, is_unassigned, agency_name)

    # Берём последние сообщения, которые помещаются
    fitted_msgs = []
    current_len = 0
    for msg_str in reversed(formatted_msgs):
        if current_len + len(msg_str) + 1 <= target_space:
            fitted_msgs.append(msg_str)
            current_len += len(msg_str) + 1
        else:
            break

    fitted_msgs.reverse()
    return f"{base_header}{notice}" + "\n".join(fitted_msgs)

def is_valid_url(url: Optional[str]) -> bool:
    if not url:
        return False
    u = url.strip()
    return u.startswith("http://") or u.startswith("https://")

def build_lead_keyboard(lead: Dict[str, Any], crm_base_url: str = "https://crm.212-41-8-249.sslip.io") -> Optional[InlineKeyboardMarkup]:
    """
    Создает кнопки под сообщением с лидом.
    Возвращает None, если ссылок нет.
    """
    buttons = []

    # Кнопка перехода к объявлению
    ad_url = (lead.get("ad_url") or "").strip()
    if is_valid_url(ad_url):
        buttons.append([InlineKeyboardButton(text="🏠 Открыть объявление", url=ad_url)])

    # Ссылки в CRM (диалог и остановка ИИ)
    dialogue_id = lead.get("dialogue_id")
    if dialogue_id and crm_base_url:
        raw_id = dialogue_id.split(":")[-1]
        platform = lead.get("platform") or "cian"
        inbox_url = f"{crm_base_url.rstrip('/')}/inbox/{raw_id}".strip()
        stop_url = f"{crm_base_url.rstrip('/')}/disable-ai/{platform}/{raw_id}".strip()

        if is_valid_url(inbox_url) and is_valid_url(stop_url):
            buttons.append([
                InlineKeyboardButton(text="✍️ Ответить клиенту", url=inbox_url),
                InlineKeyboardButton(text="🛑 Остановить ИИ", url=stop_url)
            ])

    if not buttons:
        return None

    return InlineKeyboardMarkup(inline_keyboard=buttons)
