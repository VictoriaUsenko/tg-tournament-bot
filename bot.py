import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message_text)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
MAIN_SLOTS = 8
RESERVE_SLOTS = 2
TOTAL_SLOTS = MAIN_SLOTS + RESERVE_SLOTS

# Глобальные данные (в продакшене — БД!)
participants = []  # [{'user_id', 'username', 'status'}]
registration_open = False
register_message_id = None  # ID сообщения с кнопкой (чтобы обновлять его)


async def open_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админская команда /open — открывает регистрацию и публикует сообщение с кнопкой"""
    global registration_open, participants, register_message_id

    if registration_open:
        await update.message.reply_text("Регистрация уже открыта!")
        return

    registration_open = True
    participants = []

    keyboard = [[InlineKeyboardButton("Зарегистрироваться", callback_data="register")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await update.message.reply_text(
        "🎉 Открыта регистрация на турнир!\n"
        f"Места: {MAIN_SLOTS} основных + {RESERVE_SLOTS} запасных.\n"
        "Нажмите кнопку ниже, чтобы записаться:",
        reply_markup=reply_markup
    )

    # Сохраняем ID сообщения, чтобы потом его обновить
    register_message_id = message.message_id


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий на кнопки"""
    global registration_open, participants, register_message_id

    query = update.callback_query
    await query.answer()

    user = update.effective_user
    user_id = user.id

    # Если регистрация закрыта — ничего не делаем
    if not registration_open:
        await query.edit_message_text("❌ Регистрация закрыта.")
        return

    # Проверяем, не зарегистрирован ли уже
    if any(p['user_id'] == user_id for p in participants):
        await query.answer("Вы уже зарегистрированы!", show_alert=True)
        return

    # Добавляем участника
    status = 'main' if len(participants) < MAIN_SLOTS else 'reserve'
    participants.append({
        'user_id': user_id,
        'username': user.username or user.first_name,
        'status': status
    })

    # Уведомляем пользователя
    status_text = "основной участник" if status == 'main' else "запасной"
    await query.answer(f"✅ Вы зарегистрированы как {status_text}!", show_alert=True)

    # Обновляем исходное сообщение: показываем текущий прогресс
    main_count = len([p for p in participants if p['status'] == 'main'])
    reserve_count = len([p for p in participants if p['status'] == 'reserve'])

    progress_text = (
        "🎉 Открыта регистрация на турнир!\n"
        f"Места: {MAIN_SLOTS} основных + {RESERVE_SLOTS} запасных.\n\n"
        f"🔹 Основные: {main_count}/{MAIN_SLOTS}\n"
        f"🔸 Запасные: {reserve_count}/{RESERVE_SLOTS}"
    )

    # Если места закончились — закрываем регистрацию
    if len(participants) >= TOTAL_SLOTS:
        registration_open = False
        progress_text += "\n\n🔒 Регистрация закрыта: все места заняты!"
        new_reply_markup = None  # убираем кнопку
    else:
        # Оставляем кнопку активной
        new_reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("Зарегистрироваться", callback_data="register")]])

    # Обновляем сообщение с кнопкой
    if register_message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=register_message_id,
                text=progress_text,
                reply_markup=new_reply_markup
            )
        except Exception as e:
            logger.warning(f"Не удалось обновить сообщение: {e}")


async def list_participants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /list — показать всех участников (для админа)"""
    if not participants:
        await update.message.reply_text("Пока никто не зарегистрирован.")
        return

    main_list = [p['username'] for p in participants if p['status'] == 'main']
    reserve_list = [p['username'] for p in participants if p['status'] == 'reserve']

    msg = "📋 Участники турнира:\n\n"
    if main_list:
        msg += "🔹 Основные:\n" + "\n".join(f"• {u}" for u in main_list) + "\n\n"
    if reserve_list:
        msg += "🔸 Запасные:\n" + "\n".join(f"• {u}" for u in reserve_list)

    await update.message.reply_text(msg)


def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        raise ValueError("Токен не задан! Установите TELEGRAM_BOT_TOKEN в переменных окружения.")

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("open", open_registration))
    application.add_handler(CommandHandler("list", list_participants))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()


if __name__ == '__main__':
    main()