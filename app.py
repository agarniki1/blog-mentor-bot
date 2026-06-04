import logging
import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DB_PATH = "bot.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()
    logger.info("Database initialized")


def upsert_user(user):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    cur.execute(
        """
        INSERT INTO users (user_id, username, first_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            updated_at = excluded.updated_at
        """,
        (
            user.id,
            user.username,
            user.first_name,
            now,
            now,
        ),
    )

    conn.commit()
    conn.close()


def save_message(user_id: int, role: str, content: str):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO messages (user_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            role,
            content,
            datetime.now(timezone.utc).isoformat(),
        ),
    )

    conn.commit()
    conn.close()


def get_last_messages(user_id: int, limit: int = 12):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT role, content
        FROM messages
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )

    rows = cur.fetchall()
    conn.close()
    return list(reversed(rows))


def build_main_menu():
    keyboard = [
        [InlineKeyboardButton("Что ты умеешь", callback_data="about")],
        [InlineKeyboardButton("С чего начать", callback_data="start_here")],
        [InlineKeyboardButton("Написать запрос", callback_data="write_prompt")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def safe_edit_message(query, text: str, reply_markup=None):
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Skipped edit: message is not modified")
        else:
            raise


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)

    text = (
        "Привет! Я твой AI-ассистент внутри Telegram.\n\n"
        "Я могу помочь:\n"
        "- сформулировать идею продукта;\n"
        "- упаковать оффер;\n"
        "- придумать контент;\n"
        "- помочь с текстами и структурой.\n\n"
        "Выбери действие ниже или просто напиши сообщение."
    )

    await update.message.reply_text(text, reply_markup=build_main_menu())


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "about":
        text = (
            "Я помогаю как AI-ассистент:\n\n"
            "- идеи и позиционирование;\n"
            "- тексты и офферы;\n"
            "- структура продукта;\n"
            "- быстрые черновики для запуска.\n\n"
            "Можешь просто написать задачу обычным сообщением."
        )
        await safe_edit_message(query, text, reply_markup=build_main_menu())

    elif data == "start_here":
        text = (
            "Лучше всего начать так:\n\n"
            "1. Кто твоя аудитория\n"
            "2. Что именно ты продаёшь\n"
            "3. Какой результат человек получает\n"
            "4. Где сейчас у тебя затык\n\n"
            "После этого я помогу упаковать всё в понятный оффер."
        )
        await safe_edit_message(query, text, reply_markup=build_main_menu())

    elif data == "write_prompt":
        text = (
            "Просто пришли сообщение в свободной форме.\n\n"
            "Например:\n"
            "\"Помоги упаковать мой Telegram-продукт для экспертов\"\n"
            "или\n"
            "\"Сделай оффер для подписки с AI-наставником\""
        )
        await safe_edit_message(query, text, reply_markup=build_main_menu())


def generate_reply(user_text: str, history: list[sqlite3.Row]) -> str:
    user_text_lower = user_text.lower()

    if "оффер" in user_text_lower:
        return (
            "Вот базовая формула оффера:\n\n"
            "Я помогаю [кому] получить [результат] без [главная боль/барьер].\n\n"
            "Если хочешь, я могу сразу сделать 3 варианта оффера под твою нишу."
        )

    if "контент" in user_text_lower:
        return (
            "Могу помочь с контентом в трёх форматах:\n"
            "- контент-план на неделю;\n"
            "- идеи постов;\n"
            "- сильные хуки и заходы.\n\n"
            "Напиши тему и аудиторию."
        )

    if "цена" in user_text_lower or "сколько брать" in user_text_lower:
        return (
            "Чтобы назвать цену, обычно смотрят на 3 вещи:\n"
            "- ценность результата;\n"
            "- срочность боли;\n"
            "- насколько это ручная работа или подписка.\n\n"
            "Опиши продукт, и я предложу вилку цены."
        )

    return (
        "Принял. Могу помочь это докрутить в практичный результат.\n\n"
        "Что удобнее сделать следующим шагом:\n"
        "1. Упаковать оффер\n"
        "2. Придумать структуру продукта\n"
        "3. Написать продающий текст\n"
        "4. Определить цену"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    upsert_user(user)
    save_message(user.id, "user", text)

    history = get_last_messages(user.id)
    reply = generate_reply(text, history)

    save_message(user.id, "assistant", reply)
    await update.message.reply_text(reply, reply_markup=build_main_menu())


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")

    init_db()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(menu_callback))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
