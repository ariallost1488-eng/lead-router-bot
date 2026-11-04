# Lead Router Bot

Telegram-бот для агентств недвижимости. Он получает заявки из DialogiAI и отправляет их риелтору, который отвечает за объявление.

## Зачем нужен этот бот

Когда агентство ведёт объявления на Циан и Авито из нескольких кабинетов, новые заявки легко пропустить. Если сотрудники пересылают их вручную, заявка может затеряться или уйти не тому риелтору.

Бот связывает код объявления с ответственным сотрудником и сам доставляет заявку ему в Telegram. Руководителю не нужно разбирать общий поток сообщений и вручную распределять клиентов.

## Как работает

Руководитель подключает агентство через DialogiAI и отправляет риелторам ссылку-приглашение. Риелтор открывает её в Telegram, затем присылает боту ссылку на объявление или его код. Бот проверяет DialogiAI на новые заявки и отправляет каждую ответственному сотруднику.

Если для объявления ещё нет ответственного, заявка может уйти в общий чат агентства. Повторно обрабатывать одну и ту же заявку бот не будет.

## Что умеет

- Подключать несколько агентств к одному боту.
- Закреплять объявления Циан и Авито за риелторами.
- Проверять DialogiAI на новые заявки и отправлять их в личный чат сотрудника.
- Показывать ссылки на объявление и диалог CRM.
- Пересылать неназначенные заявки в общий чат, если он настроен.
- Показывать в админ-панели только заявки, которые Telegram подтвердил как доставленные риелтору. Для защиты от повторов отдельно хранится только ID обработанных заявок.

## Что понадобится

- Python 3.9 или новее.
- Токен Telegram-бота от [@BotFather](https://t.me/BotFather).
- API-ключ DialogiAI для каждого агентства.

## Установка

```bash
git clone https://github.com/ariallost1488-eng/lead-router-bot.git
cd lead-router-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Откройте `.env` и заполните параметры:

```dotenv
BOT_TOKEN=
ADMIN_TELEGRAM_IDS=
POLL_INTERVAL_SECONDS=60
DATABASE_PATH=leads_bot.db
DIALOGIAI_BASE_URL=https://api.dialogiai.ru
```

В `BOT_TOKEN` укажите токен Telegram-бота. В `ADMIN_TELEGRAM_IDS` перечислите через запятую Telegram ID администраторов.

Запуск:

```bash
python main.py
```

Для одного Telegram-токена должен работать только один экземпляр бота.

## Настройка агентства

1. Администратор открывает бота и отправляет `/admin`.
2. В панели добавляет агентство и его API-ключ DialogiAI.
3. При необходимости задаёт ID общего чата для неназначенных заявок.
4. Отправляет риелторам созданную ботом ссылку.
5. Риелторы переходят по ссылке и отправляют боту свои объявления.

Посмотреть закреплённые объявления можно командой `/my`. Повторная привязка объявления передаёт его новому ответственному в этом агентстве.

## Автозапуск на macOS

В `launchd/com.lead-router-bot.plist` замените `__PROJECT_DIR__` на полный путь к каталогу проекта, затем установите LaunchAgent:

```bash
mkdir -p ~/Library/LaunchAgents
sed "s|__PROJECT_DIR__|$(pwd)|g" launchd/com.lead-router-bot.plist > ~/Library/LaunchAgents/com.lead-router-bot.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lead-router-bot.plist
```

Бот будет запускаться при входе пользователя в macOS. Если он завершится с ошибкой, система запустит его снова. Чтобы остановить бота и отключить автозапуск:

```bash
launchctl bootout gui/$(id -u)/com.lead-router-bot
```

Для постоянной работы лучше перенести бота на сервер и запускать через системный менеджер процессов, например `systemd`. Настройка LaunchAgent предназначена только для macOS.

## Тесты

```bash
python -m unittest discover -s tests -v
```

Проверяются доставка заявок, защита от дублей, обновление старой базы и разбор ссылок на объявления. Для тестов не нужны токены и доступ к API.

## Безопасность данных

Не добавляйте в Git файл `.env`, базу `leads_bot.db` и журнал `bot.log`. Они исключены настройками `.gitignore`. Не публикуйте токены Telegram, ключи DialogiAI, телефоны клиентов и переписку.

## English

Lead Router Bot sends new DialogiAI real-estate inquiries to the realtor responsible for each listing.

### The problem it solves

Agencies often manage listings across multiple Cian and Avito accounts. New inquiries can be missed, forwarded to the wrong person, or lost in a busy group chat. This bot matches each inquiry to its listing and delivers it directly to the right realtor on Telegram.

### How it works

An administrator connects an agency with its DialogiAI API key and shares an invitation link with the team. Realtors use the link to join the agency, then send the bot a listing URL or ID. The bot checks DialogiAI for new inquiries and routes each one to the assigned realtor. Unassigned inquiries can go to an agency group chat.

The admin panel lists only inquiries that Telegram confirmed as delivered to a realtor's private chat. Processed inquiry IDs are stored separately to prevent duplicates.

### Features

- Multiple agencies in one bot.
- Cian and Avito listing assignments.
- Automatic DialogiAI polling and Telegram delivery.
- Links to the listing and CRM conversation.
- Optional group-chat delivery for unassigned inquiries.
- macOS LaunchAgent template for automatic startup.

### Requirements and setup

Python 3.9 or newer, a Telegram bot token, and a DialogiAI API key for each agency are required.

Follow the installation steps above, fill in `.env`, and run `python main.py`. Only one polling instance can use a Telegram bot token at a time.

Tests run with `python -m unittest discover -s tests -v`.
