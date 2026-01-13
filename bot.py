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
MAIN_SLOTS = 8
RESERVE_SLOTS = 2
TOTAL_SLOTS = MAIN_SLOTS + RESERVE_SLOTS

# ================== ГЛОБАЛЬНЫЕ ДАННЫЕ ==================
participants = []
registration_open = False
register_message_id = None
tournament_date = None
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
    if not participants or not tournament_date:
        return "Нет участников."

    main_list = [p['full_name'] for p in participants if p['status'] == 'main']
    reserve_list = [p['full_name'] for p in participants if p['status'] == 'reserve']

    msg = f"📋 Участники турнира {tournament_date}:\n\n"
    if main_list:
        msg += "🔹 Основные:\n" + "\n".join(f"• {u}" for u in main_list) + "\n\n"
    if reserve_list:
        msg += "🔸 Запасные:\n" + "\n".join(f"• {u}" for u in reserve_list)

    return msg

async def update_registration_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    global register_message_id, tournament_date

    if not register_message_id or not tournament_date:
        return

    main_count = len([p for p in participants if p['status'] == 'main'])
    reserve_count = len([p for p in participants if p['status'] == 'reserve'])

    text = (
        f"🎉 Регистрация на турнир {tournament_date}!\n"
        f"Места: {MAIN_SLOTS} основных + {RESERVE_SLOTS} запасных.\n\n"
        f"🔹 Основные: {main_count}/{MAIN_SLOTS}\n"
        f"🔸 Запасные: {reserve_count}/{RESERVE_SLOTS}"
    )

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

# ================== ОБРАБОТЧИКИ КОМАНД И КНОПОК ==================

async def open_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_open, participants, register_message_id, tournament_date, admin_user_titles

    if registration_open:
        await update.message.reply_text("Регистрация уже открыта!")
        return

    if not context.args:
        await update.message.reply_text(
            "Укажите дату турнира в формате ДД.ММ.ГГ\nПример: /open 13.10.26"
        )
        return

    date_input = context.args[0].strip()
    if not re.fullmatch(r'\d{2}\.\d{2}\.\d{2}', date_input):
        await update.message.reply_text(
            "Неверный формат даты. Используйте ДД.ММ.ГГ (например, 13.10.26)"
        )
        return

    tournament_date = date_input
    chat_id = update.effective_chat.id

    admin_user_titles = await get_group_admin_titles(context, chat_id)

    registration_open = True
    participants = []

    keyboard = [[
        InlineKeyboardButton("✅ Зарегистрироваться", callback_data="register"),
        InlineKeyboardButton("❌ Отменить регистрацию", callback_data="unregister")
    ]]

    message = await update.message.reply_text(
        f"🎉 Открыта регистрация на турнир {tournament_date}!\n"
        f"Места: {MAIN_SLOTS} основных + {RESERVE_SLOTS} запасных.\n"
        "Нажмите кнопку ниже, чтобы записаться:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    register_message_id = message.message_id

async def close_registration_manually(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_open

    if not register_message_id or not tournament_date:
        await update.message.reply_text("Нет активной регистрации.")
        return

    registration_open = False

    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=register_message_id,
            text=f"🔒 Регистрация на турнир {tournament_date} завершена!"
        )
    except:
        pass

    await update.message.reply_text(format_participants_list())
    await update.message.reply_text("✅ Регистрация закрыта.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_open, participants

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

        await context.bot.send_message(chat_id, format_participants_list())
        await update_registration_message(context, chat_id)

    elif query.data == "unregister":
        if not user_entry:
            await query.answer("Вы не зарегистрированы.", show_alert=True)
            return

        participants = [p for p in participants if p["user_id"] != user.id]
        await context.bot.send_message(chat_id, format_participants_list())
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

def run_telegram_app():
    """Запускает Telegram Application в фоновом потоке."""
    global application
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def main():
        global application
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        application.add_handler(CommandHandler("open", open_registration))
        application.add_handler(CommandHandler("close", close_registration_manually))
        application.add_handler(CommandHandler("list", list_participants))
        application.add_handler(CallbackQueryHandler(button_handler))

        await application.bot.set_webhook(url=WEBHOOK_URL)
        logger.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

        await application.initialize()
        await application.start()
        logger.info("✅ Telegram-приложение готово к работе.")

        # Блокировка потока
        await asyncio.Event().wait()

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(application.stop())
        loop.close()

@app.before_request
def start_telegram_once():
    global _started
    if not _started:
        _started = True
        thread = threading.Thread(target=run_telegram_app, daemon=True)
        thread.start()
        # Даём время на инициализацию
        time.sleep(2)

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