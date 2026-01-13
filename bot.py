import os
import logging
import re
import asyncio
import threading
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from flask import Flask, request

# ================== ЛОГИРОВАНИЕ ==================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== КОНСТАНТЫ ==================
# Константы теперь будут задаваться динамически через /open
MAIN_SLOTS = 0
RESERVE_SLOTS = 0
TOTAL_SLOTS = 0

# ================== ГЛОБАЛЬНЫЕ ДАННЫЕ ==================
participants = []
registration_open = False
register_message_id = None
tournament_display = None
admin_user_titles = {}

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================

async def get_group_admin_titles(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        titles = {}
        for admin in admins:
            if admin.custom_title:
                titles[admin.user.id] = admin.custom_title
        return titles
    except Exception as e:
        logger.warning(f"Не удалось получить админов чата {chat_id}: {e}")
        return {}

def get_display_name(user) -> str:
    full_name = user.first_name
    if user.last_name:
        full_name += " " + user.last_name

    custom_title = admin_user_titles.get(user.id)
    if custom_title:
        full_name += f" ({custom_title})"

    return full_name

def format_participants_list():
    if not participants or not tournament_display:
        return "Нет участников."

    main_list = [p['full_name'] for p in participants if p['status'] == 'main']
    reserve_list = [p['full_name'] for p in participants if p['status'] == 'reserve']

    msg = f"📋 Участники турнира {tournament_display}:\n\n"
    if main_list:
        msg += "🔹 Основные:\n" + "\n".join(f"• {u}" for u in main_list) + "\n\n"
    if reserve_list:
        msg += "🔸 Запасные:\n" + "\n".join(f"• {u}" for u in reserve_list)

    return msg

async def update_registration_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    global register_message_id, tournament_display, MAIN_SLOTS, RESERVE_SLOTS

    if not register_message_id or not tournament_display:
        return

    main_list = [p['full_name'] for p in participants if p['status'] == 'main']
    reserve_list = [p['full_name'] for p in participants if p['status'] == 'reserve']

    main_count = len(main_list)
    reserve_count = len(reserve_list)

    text = (
        f"🎉 Регистрация на турнир {tournament_display}!\n"
        f"Места: {MAIN_SLOTS} основных + {RESERVE_SLOTS} запасных.\n\n"
        f"🔹 Основные: {main_count}/{MAIN_SLOTS}\n"
    )
    if main_list:
        text += "\n".join(f"• {u}" for u in main_list) + "\n"

    text += f"\n🔸 Запасные: {reserve_count}/{RESERVE_SLOTS}\n"
    if reserve_list:
        text += "\n".join(f"• {u}" for u in reserve_list)

    buttons = []
    if registration_open:
        buttons.append([
            InlineKeyboardButton("✅ Зарегистрироваться", callback_data="register"),
            InlineKeyboardButton("❌ Отменить регистрацию", callback_data="unregister")
        ])

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=register_message_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
        )
    except Exception as e:
        logger.warning(f"Не удалось обновить сообщение: {e}")

def promote_reserve_to_main():
    """Повышает первого резервного до основного, если есть свободное место в основном составе."""
    global participants, MAIN_SLOTS

    main_count = sum(1 for p in participants if p['status'] == 'main')
    if main_count < MAIN_SLOTS:
        # Находим первого резервного
        for p in participants:
            if p['status'] == 'reserve':
                p['status'] = 'main'
                break

# ================== ОБРАБОТЧИКИ КОМАНД И КНОПОК ==================

async def open_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_open, participants, register_message_id, tournament_display, admin_user_titles
    global MAIN_SLOTS, RESERVE_SLOTS, TOTAL_SLOTS

    if registration_open:
        await update.message.reply_text("Регистрация уже открыта!")
        return

    if not context.args or len(context.args) < 3:
        await update.message.reply_text(
            "Укажите количество мест и дату/время турнира:\n"
            "Формат: /open-M-R ДД.ММ.ГГ ЧЧ-ММ\n"
            "Пример: /open-8-2 19.10.26 14-10"
        )
        return

    # Парсим первую часть как /open-M-R
    command_part = context.args[0]
    match = re.fullmatch(r'/open-(\d+)-(\d+)', command_part)
    if not match:
        await update.message.reply_text(
            "Неверный формат команды. Используйте: /open-8-2 19.10.26 14-10"
        )
        return

    try:
        MAIN_SLOTS = int(match.group(1))
        RESERVE_SLOTS = int(match.group(2))
        if MAIN_SLOTS <= 0 or RESERVE_SLOTS < 0:
            raise ValueError
        TOTAL_SLOTS = MAIN_SLOTS + RESERVE_SLOTS
    except (ValueError, IndexError):
        await update.message.reply_text("Количество мест должно быть положительным числом.")
        return

    date_input = context.args[1].strip()
    time_input = context.args[2].strip()

    if not re.fullmatch(r'\d{2}\.\d{2}\.\d{2}', date_input):
        await update.message.reply_text(
            "Неверный формат даты. Используйте ДД.ММ.ГГ (например, 19.10.26)"
        )
        return

    if not re.fullmatch(r'\d{2}-\d{2}', time_input):
        await update.message.reply_text(
            "Неверный формат времени. Используйте ЧЧ-ММ (например, 14-10)"
        )
        return

    time_display = time_input.replace('-', ':')
    tournament_display = f"{date_input} в {time_display} по МСК"

    chat_id = update.effective_chat.id
    admin_user_titles = await get_group_admin_titles(context, chat_id)

    registration_open = True
    participants = []

    keyboard = [[
        InlineKeyboardButton("✅ Зарегистрироваться", callback_data="register"),
        InlineKeyboardButton("❌ Отменить регистрацию", callback_data="unregister")
    ]]

    message = await update.message.reply_text(
        f"🎉 Открыта регистрация на турнир {tournament_display}!\n"
        f"Места: {MAIN_SLOTS} основных + {RESERVE_SLOTS} запасных.\n"
        "Нажмите кнопку ниже, чтобы записаться:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    register_message_id = message.message_id

async def close_registration_manually(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_open, tournament_display

    if not register_message_id or not tournament_display:
        await update.message.reply_text("Нет активной регистрации.")
        return

    registration_open = False
    await update_registration_message(context, update.effective_chat.id)

    await update.message.reply_text(format_participants_list())
    await update.message.reply_text("✅ Регистрация закрыта.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_open, participants, MAIN_SLOTS, RESERVE_SLOTS, TOTAL_SLOTS

    query = update.callback_query
    await query.answer()

    user = update.effective_user
    chat_id = update.effective_chat.id

    if not registration_open:
        await query.answer("Регистрация закрыта.", show_alert=True)
        return

    user_entry = next((p for p in participants if p['user_id'] == user.id), None)

    if query.data == "register":
        if user_entry:
            await query.answer("Вы уже зарегистрированы!", show_alert=True)
            return

        if len(participants) >= TOTAL_SLOTS:
            await query.answer("Все места заняты!", show_alert=True)
            return

        status = "main" if len(participants) < MAIN_SLOTS else "reserve"

        participants.append({
            "user_id": user.id,
            "full_name": get_display_name(user),
            "status": status
        })

        if len(participants) >= TOTAL_SLOTS:
            registration_open = False

        await update_registration_message(context, chat_id)

    elif query.data == "unregister":
        if not user_entry:
            await query.answer("Вы не зарегистрированы.", show_alert=True)
            return

        was_main = (user_entry['status'] == 'main')
        participants = [p for p in participants if p["user_id"] != user.id]

        # Если вышел из основного состава — пробуем повысить резервного
        if was_main:
            promote_reserve_to_main()

        if len(participants) < TOTAL_SLOTS:
            registration_open = True

        await update_registration_message(context, chat_id)

async def list_participants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_participants_list())

# ================== FLASK WEB SERVER ==================

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Токен не задан!")

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")
if not RENDER_EXTERNAL_URL:
    raise ValueError("Переменная RENDER_EXTERNAL_URL не задана!")

WEBHOOK_PATH = f"/webhook/{TELEGRAM_BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"

application = None
_started = False
_ready = False

def run_telegram_app():
    """Запускает Telegram Application в фоновом потоке без блокировки."""
    global application, _ready
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def main():
        global application, _ready
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        application.add_handler(CommandHandler("open", open_registration))
        application.add_handler(CommandHandler("close", close_registration_manually))
        application.add_handler(CommandHandler("list", list_participants))
        application.add_handler(CallbackQueryHandler(button_handler))

        await application.bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

        await application.initialize()
        await application.start()
        logger.info("✅ Telegram-приложение запущено и ОБРАБАТЫВАЕТ обновления.")
        
        _ready = True

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass

    try:
        loop.run_until_complete(main())
    except Exception as e:
        logger.error(f"Ошибка в Telegram-потоке: {e}")
    finally:
        if application:
            loop.run_until_complete(application.stop())
        loop.close()

@app.before_request
def start_telegram_once():
    global _started
    if not _started:
        _started = True
        thread = threading.Thread(target=run_telegram_app, daemon=True)
        thread.start()
        for _ in range(10):
            if _ready:
                break
            time.sleep(0.5)
        if not _ready:
            logger.warning("⚠️ Telegram-приложение может быть не готово!")

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    global application
    if application is None:
        logger.warning("Webhook получен до инициализации бота!")
        return "Bot not ready", 503

    if request.headers.get("content-type") == "application/json":
        update_dict = request.get_json(force=True)
        update = Update.de_json(update_dict, application.bot)
        application.update_queue.put_nowait(update)
        return "OK"
    else:
        return "Invalid content type", 400

@app.route("/health", methods=["GET"])
def health_check():
    return "OK", 200

@app.route("/", methods=["GET"])
def home():
    return "Telegram tournament bot is running!", 200

# ================== ЗАПУСК ==================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)