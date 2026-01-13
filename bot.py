import os
import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
MAIN_SLOTS = 8
RESERVE_SLOTS = 2
TOTAL_SLOTS = MAIN_SLOTS + RESERVE_SLOTS

# Глобальные данные для текущего турнира
participants = []
registration_open = False
register_message_id = None
tournament_date = None  # Например: "13.10.26"
admin_user_ids = set()


async def get_group_admin_ids(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        return {admin.user.id for admin in admins}
    except Exception as e:
        logger.warning(f"Не удалось получить админов чата {chat_id}: {e}")
        return set()


def get_display_name(user) -> str:
    full_name = user.first_name
    if user.last_name:
        full_name += " " + user.last_name
    if user.id in admin_user_ids:
        full_name += " (админ)"
    return full_name


async def update_registration_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    global register_message_id, registration_open, tournament_date

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
            InlineKeyboardButton("Зарегистрироваться", callback_data="register"),
            InlineKeyboardButton("Отменить регистрацию", callback_data="unregister")
        ])

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=register_message_id,
            text=text,
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.warning(f"Не удалось обновить сообщение: {e}")


async def open_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/open <дата> — открывает регистрацию на турнир указанной даты"""
    global registration_open, participants, register_message_id, tournament_date, admin_user_ids

    if registration_open:
        await update.message.reply_text("Регистрация уже открыта!")
        return

    # Получаем аргумент: дата
    if not context.args:
        await update.message.reply_text("Укажите дату турнира в формате ДД.ММ.ГГ\nПример: /open 13.10.26")
        return

    date_input = context.args[0].strip()

    # Проверка формата: ДД.ММ.ГГ (например, 13.10.26)
    if not re.fullmatch(r'\d{2}\.\d{2}\.\d{2}', date_input):
        await update.message.reply_text("Неверный формат даты. Используйте ДД.ММ.ГГ (например, 13.10.26)")
        return

    tournament_date = date_input
    chat_id = update.effective_chat.id
    admin_user_ids.update(await get_group_admin_ids(context, chat_id))

    registration_open = True
    participants = []

    keyboard = [
        [
            InlineKeyboardButton("Зарегистрироваться", callback_data="register"),
            InlineKeyboardButton("Отменить регистрацию", callback_data="unregister")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = await update.message.reply_text(
        f"🎉 Открыта регистрация на турнир {tournament_date}!\n"
        f"Места: {MAIN_SLOTS} основных + {RESERVE_SLOTS} запасных.\n"
        "Нажмите кнопку ниже, чтобы записаться:",
        reply_markup=reply_markup
    )
    register_message_id = message.message_id


async def close_registration_manually(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/close — завершает текущую регистрацию"""
    global registration_open, register_message_id, tournament_date

    if not registration_open:
        await update.message.reply_text("Регистрация не активна.")
        return

    registration_open = False
    main_count = len([p for p in participants if p['status'] == 'main'])
    reserve_count = len([p for p in participants if p['status'] == 'reserve'])

    final_text = (
        f"🔒 Регистрация на турнир {tournament_date} завершена!\n\n"
        f"🔹 Основные: {main_count}/{MAIN_SLOTS}\n"
        f"🔸 Запасные: {reserve_count}/{RESERVE_SLOTS}"
    )

    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=register_message_id,
            text=final_text
        )
    except:
        pass

    await update.message.reply_text("✅ Регистрация закрыта.")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global registration_open, participants, tournament_date

    query = update.callback_query
    await query.answer()
    user = update.effective_user
    chat_id = update.effective_chat.id

    if not registration_open or not tournament_date:
        await query.edit_message_text("❌ Регистрация закрыта.")
        return

    user_id = user.id
    user_entry = next((p for p in participants if p['user_id'] == user_id), None)

    if query.data == "register":
        if user_entry:
            await query.answer("Вы уже зарегистрированы!", show_alert=True)
            return
        if len(participants) >= TOTAL_SLOTS:
            await query.answer("Все места заняты!", show_alert=True)
            return

        status = 'main' if len(participants) < MAIN_SLOTS else 'reserve'
        full_name = get_display_name(user)
        participants.append({
            'user_id': user_id,
            'full_name': full_name,
            'status': status
        })

        await query.answer(f"✅ Вы зарегистрированы как {'основной участник' if status == 'main' else 'запасной'}!", show_alert=True)

        if len(participants) >= TOTAL_SLOTS:
            registration_open = False
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=register_message_id,
                text=(
                    f"🔒 Регистрация на турнир {tournament_date} закрыта: все места заняты!\n\n"
                    f"🔹 Основные: {MAIN_SLOTS}/{MAIN_SLOTS}\n"
                    f"🔸 Запасные: {RESERVE_SLOTS}/{RESERVE_SLOTS}"
                )
            )
        else:
            await update_registration_message(context, chat_id)

    elif query.data == "unregister":
        if not user_entry:
            await query.answer("Вы не зарегистрированы.", show_alert=True)
            return

        participants[:] = [p for p in participants if p['user_id'] != user_id]
        await query.answer("❌ Ваша регистрация отменена.", show_alert=True)
        await update_registration_message(context, chat_id)


async def list_participants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not participants or not tournament_date:
        await update.message.reply_text("Нет активного турнира или участников.")
        return

    main_list = [p['full_name'] for p in participants if p['status'] == 'main']
    reserve_list = [p['full_name'] for p in participants if p['status'] == 'reserve']

    msg = f"📋 Участники турнира {tournament_date}:\n\n"
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
    application.add_handler(CommandHandler("close", close_registration_manually))
    application.add_handler(CommandHandler("list", list_participants))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()


if __name__ == '__main__':
    main()