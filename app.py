import os
import sqlite3
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DB_PATH = os.getenv("DB_PATH", "/data/mentor_bot.db")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("telegram.ext").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """
Ты Anna — тёплый, спокойный и современный SMM-ментор по запуску и ведению блога в Instagram и Telegram.

Твоя роль:
помогать человеку начать блог без перегруза, понять что именно ему мешает, выбрать направление, не перегореть в начале и двигаться маленькими понятными шагами.

Как ты работаешь:
- отвечаешь на языке пользователя
- пишешь просто, тепло, спокойно и по делу
- не звучишь как корпоративный консультант
- не перегружаешь теорией
- один ответ = один понятный следующий шаг
- если человек запутался, сужаешь выбор до 2-3 вариантов
- если контекста не хватает, задаёшь только один короткий уточняющий вопрос
- после одного уточнения переходишь к полезному ответу
- если смысл уже понятен, не уточняешь очевидное, а делаешь разумное предположение и идёшь дальше
- не играешь в двусмысленности слов, если смысл пользователя очевиден
- не задаёшь глупые, буквальные или абсурдные уточняющие вопросы
- не просишь переписать сообщение, если смысл уже можно понять
- не делаешь больше одного уточнения подряд
- создаёшь ощущение, что рядом живой, умный и поддерживающий ментор

Формат:
- только plain text
- без markdown
- без звездочек, подчеркиваний, хешей, backticks
- без жирного текста и markdown-заголовков
- абзацы короткие
- списки короткие и полезные
- без воды и канцелярита

Границы:
- ты помогаешь по темам: блог, контент, позиционирование, Instagram, Telegram, личный бренд, форматы контента, страх проявления, старт, система, простые планы действий
- если вопрос сильно вне темы, мягко связывай ответ с блогом, контентом, личным позиционированием или выбором направления

Цель:
пользователь должен чувствовать, что с ним говорит умный, спокойный, современный и тёплый SMM-ментор.
"""

def clean_text(text: str) -> str:
    cleaned = (
        text.replace("**", "")
            .replace("*", "")
            .replace("__", "")
            .replace("_", "")
            .replace("```", "")
            .replace("`", "")
            .replace("##", "")
            .replace("#", "")
            .strip()
    )

    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")

    return cleaned.strip()

def get_db_connection():
    try:
        return sqlite3.connect(DB_PATH)
    except sqlite3.Error as e:
        logger.exception("SQLite connection error: %s", e)
        raise

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER UNIQUE,
            username TEXT,
            first_name TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER,
            role TEXT,
            text TEXT,
            created_at TEXT
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER UNIQUE,
            summary TEXT,
            updated_at TEXT
        )
        """)

        conn.commit()
        conn.close()
        logger.info("Database initialized")
    except sqlite3.Error as e:
        logger.exception("Database init failed: %s", e)
        raise

def save_user(update: Update):
    try:
        telegram_user = update.effective_user
        now = datetime.now(timezone.utc).isoformat()

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO users (telegram_user_id, username, first_name, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_user_id)
        DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            updated_at=excluded.updated_at
        """, (
            telegram_user.id,
            telegram_user.username,
            telegram_user.first_name,
            now,
            now
        ))

        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.exception("save_user failed: %s", e)

def save_message(telegram_user_id: int, role: str, text: str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO messages (telegram_user_id, role, text, created_at)
        VALUES (?, ?, ?, ?)
        """, (
            telegram_user_id,
            role,
            text,
            datetime.now(timezone.utc).isoformat()
        ))

        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.exception("save_message failed: %s", e)

def get_recent_messages(telegram_user_id: int, limit: int = 8):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT role, text
        FROM messages
        WHERE telegram_user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """, (telegram_user_id, limit))

        rows = cursor.fetchall()
        conn.close()
        rows.reverse()
        return rows
    except sqlite3.Error as e:
        logger.exception("get_recent_messages failed: %s", e)
        return []

def get_user_memory(telegram_user_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT summary
        FROM user_memory
        WHERE telegram_user_id = ?
        """, (telegram_user_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return row
        return ""
    except sqlite3.Error as e:
        logger.exception("get_user_memory failed: %s", e)
        return ""

def update_user_memory(telegram_user_id: int, summary: str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO user_memory (telegram_user_id, summary, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_user_id)
        DO UPDATE SET
            summary=excluded.summary,
            updated_at=excluded.updated_at
        """, (
            telegram_user_id,
            summary,
            datetime.now(timezone.utc).isoformat()
        ))

        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        logger.exception("update_user_memory failed: %s", e)

def call_openai(prompt: str, instructions: str = SYSTEM_PROMPT) -> str:
    try:
        response = client.responses.create(
            model="gpt-5.2",
            instructions=instructions,
            input=prompt
        )
        return clean_text(response.output_text)
    except Exception as e:
        logger.exception("OpenAI request failed: %s", e)
        return (
            "Сейчас я не могу нормально ответить из-за технической ошибки.\n\n"
            "Попробуй ещё раз чуть позже."
        )

def maybe_update_memory(telegram_user_id: int, user_text: str, bot_text: str):
    current_memory = get_user_memory(telegram_user_id)

    prompt = f"""
У тебя есть диалог между пользователем и SMM-ментором Anna.

Твоя задача:
обновить краткую полезную память о пользователе.

Правила:
- сохрани только устойчивые и полезные факты
- не пересказывай весь диалог
- максимум 5 коротких строк
- включай только то, что поможет в будущих ответах:
  цель блога, тема, формат, страхи, платформа, стадия, барьеры
- если новых устойчивых фактов нет, верни предыдущую summary почти без изменений
- только plain text
- без markdown

Текущая summary:
{current_memory if current_memory else "Пока памяти нет."}

Новый фрагмент диалога:
User: {user_text}
Bot: {bot_text}
"""

    summary = call_openai(
        prompt,
        instructions="Ты помогаешь сжато обновлять память о пользователе."
    )

    if summary:
        update_user_memory(telegram_user_id, summary)

def build_context_prompt(telegram_user_id: int, user_text: str):
    memory = get_user_memory(telegram_user_id)
    recent_messages = get_recent_messages(telegram_user_id, limit=8)

    history_block = ""
    for role, text in recent_messages:
        history_block += f"{role}: {text}\n"

    prompt = f"""
Ниже контекст пользователя для ответа.

Память о пользователе:
{memory if memory else "Пока нет сохранённой памяти."}

Недавние сообщения:
{history_block if history_block else "Нет истории."}

Новое сообщение пользователя:
{user_text}

Ответь как Anna — тёплый SMM-ментор по правилам системы.
"""
    return prompt

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🚀 Начать блог с нуля", callback_data="start_blog")],
        [InlineKeyboardButton("🧭 Определить тему и направление", callback_data="pick_direction")],
        [InlineKeyboardButton("📅 План на 7 дней", callback_data="plan_7_days")],
        [InlineKeyboardButton("🔍 Разобрать почему не работает", callback_data="analyze_blog")],
        [InlineKeyboardButton("☀️ Чек-ин на сегодня", callback_data="daily_checkin")],
        [InlineKeyboardButton("💬 Свободный чат", callback_data="free_chat")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_menu():
    keyboard = [
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="back"),
            InlineKeyboardButton("🏠 В меню", callback_data="main_menu"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def safe_reply(message_obj, text, reply_markup=None):
    try:
        text = clean_text(text)
        await message_obj.reply_text(text, reply_markup=reply_markup)
    except TelegramError as e:
        logger.exception("reply_text failed: %s", e)

async def safe_edit(query, text, reply_markup=None):
    try:
        text = clean_text(text)
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Skipped edit: message is not modified")
        else:
            logger.exception("BadRequest on edit_message_text: %s", e)
    except TelegramError as e:
        logger.exception("edit_message_text failed: %s", e)

async def send_main_menu_message(target):
    text = (
        "Привет! ✨\n\n"
        "Я Anna — SMM-ментор по запуску и ведению блога в Instagram и Telegram.\n\n"
        "Я рядом, если:\n"
        "— давно хочешь начать блог, но всё время что-то стопорит\n"
        "— уже ведёшь, но не понимаешь, почему не идёт\n"
        "— не знаешь, о чём писать и как сделать всё без перегруза\n\n"
        "Без воды, без давления и без ощущения, что с тобой что-то не так.\n\n"
        "Выбери, с чего хочешь начать:"
    )
    await safe_reply(target, text, reply_markup=get_main_menu())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    context.user_data.clear()
    await send_main_menu_message(update.message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    text = (
        "Я могу помочь тебе с таким:\n\n"
        "— начать блог с нуля\n"
        "— понять, о чём тебе вести блог\n"
        "— собрать простой план на 7 дней\n"
        "— разобраться, почему блог не работает\n"
        "— понять, что делать сегодня, если всё встало\n\n"
        "Если не хочется выбирать сценарий, просто напиши мне как есть.\n"
        "Коротко, своими словами — этого достаточно."
    )
    await safe_reply(update.message, text, reply_markup=get_main_menu())

async def show_main_menu(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = (
        "Привет! ✨\n\n"
        "Я Anna — SMM-ментор по запуску и ведению блога в Instagram и Telegram.\n\n"
        "Я рядом, если:\n"
        "— давно хочешь начать блог, но всё время что-то стопорит\n"
        "— уже ведёшь, но не понимаешь, почему не идёт\n"
        "— не знаешь, о чём писать и как сделать всё без перегруза\n\n"
        "Без воды, без давления и без ощущения, что с тобой что-то не так.\n\n"
        "Выбери, с чего хочешь начать:"
    )
    await safe_edit(query, text, reply_markup=get_main_menu())

async def show_start_blog_screen(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "start_blog"
    context.user_data["step"] = "awaiting_start_blog_choice"

    text = (
        "Давай спокойно начнём с базы.\n\n"
        "Что сейчас ближе всего к твоей ситуации?\n\n"
        "1. Хочу начать, но не могу выбрать тему\n"
        "2. Тема есть, но не понимаю, как вести блог\n"
        "3. Боюсь проявляться и публиковать\n"
        "4. Уже начал(а), но всё без системы\n\n"
        "Напиши цифру — и пойдём дальше."
    )
    await safe_edit(query, text, reply_markup=get_back_menu())

async def show_pick_direction_screen(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "pick_direction"
    context.user_data["step"] = "awaiting_pick_direction_answer"

    text = (
        "Давай попробуем найти направление, которое тебе правда подойдёт.\n\n"
        "Напиши коротко 3 вещи:\n\n"
        "1. Что тебе по-настоящему интересно\n"
        "2. В чём у тебя уже есть опыт или насмотренность\n"
        "3. С кем тебе хотелось бы говорить через блог\n\n"
        "Можно коротко и без красивых формулировок."
    )
    await safe_edit(query, text, reply_markup=get_back_menu())

async def show_plan_7_days_screen(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "plan_7_days"
    context.user_data["step"] = "awaiting_plan_7_days_answer"

    text = (
        "Соберу тебе простой и живой план на 7 дней — без перегруза и лишнего.\n\n"
        "Перед этим напиши:\n\n"
        "— о чём ты примерно хочешь вести блог\n"
        "— где тебе ближе начать: Instagram, Telegram или оба\n"
        "— сколько времени ты реально готов(а) уделять в день\n\n"
        "Можно ответить совсем коротко."
    )
    await safe_edit(query, text, reply_markup=get_back_menu())

async def show_analyze_blog_screen(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "analyze_blog"
    context.user_data["step"] = "awaiting_analyze_blog_answer"

    text = (
        "Окей, давай спокойно посмотрим, где сейчас затык.\n\n"
        "Напиши в 2–4 строках:\n\n"
        "— о чём у тебя блог\n"
        "— что ты уже делаешь\n"
        "— что именно не работает: идеи, регулярность, охваты, вовлечённость или что-то ещё\n\n"
        "Я помогу увидеть, что тебя сейчас тормозит сильнее всего."
    )
    await safe_edit(query, text, reply_markup=get_back_menu())

async def show_daily_checkin_screen(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "daily_checkin"
    context.user_data["step"] = "awaiting_daily_checkin_answer"

    text = (
        "Быстрый check-in ☀️\n\n"
        "Что сегодня ближе всего?\n\n"
        "1. Ничего не сделал(а)\n"
        "2. Что-то сделал(а), но как будто мало\n"
        "3. Застрял(а) и не понимаю, куда двигаться\n"
        "4. Хочу понять, какой у меня один фокус на сегодня\n\n"
        "Напиши цифру или пару слов про своё состояние."
    )
    await safe_edit(query, text, reply_markup=get_back_menu())

async def show_free_chat_screen(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = (
        "Ты в свободном чате.\n\n"
        "Можешь написать как есть:\n"
        "про блог, тему, контент, страх проявляться, Instagram, Telegram или просто про ступор.\n\n"
        "Без правильных формулировок.\n"
        "Просто по-человечески."
    )
    await safe_edit(query, text, reply_markup=get_back_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "start_blog":
        await show_start_blog_screen(query, context)
    elif query.data == "pick_direction":
        await show_pick_direction_screen(query, context)
    elif query.data == "plan_7_days":
        await show_plan_7_days_screen(query, context)
    elif query.data == "analyze_blog":
        await show_analyze_blog_screen(query, context)
    elif query.data == "daily_checkin":
        await show_daily_checkin_screen(query, context)
    elif query.data == "free_chat":
        await show_free_chat_screen(query, context)
    elif query.data == "back":
        mode = context.user_data.get("mode")

        if mode == "start_blog":
            await show_start_blog_screen(query, context)
        elif mode == "pick_direction":
            await show_pick_direction_screen(query, context)
        elif mode == "plan_7_days":
            await show_plan_7_days_screen(query, context)
        elif mode == "analyze_blog":
            await show_analyze_blog_screen(query, context)
        elif mode == "daily_checkin":
            await show_daily_checkin_screen(query, context)
        else:
            await show_main_menu(query, context)
    elif query.data == "main_menu":
        await show_main_menu(query, context)

def generate_response(telegram_user_id: int, prompt: str) -> str:
    final_prompt = build_context_prompt(telegram_user_id, prompt)
    return call_openai(final_prompt, instructions=SYSTEM_PROMPT)

async def handle_start_blog_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    step = context.user_data.get("step")
    user_id = update.effective_user.id

    if step == "awaiting_start_blog_choice":
        choice = user_text.strip()
        context.user_data["start_blog_choice"] = choice

        if choice == "1":
            context.user_data["step"] = "awaiting_answer_for_choice_1"
            await safe_reply(
                update.message,
                "Это очень живая точка старта.\n\n"
                "Ответь коротко на 2 вещи:\n"
                "1. Что тебе правда было бы интересно обсуждать долго\n"
                "2. В чём у тебя уже есть опыт, путь или насмотренность"
            )
            return

        elif choice == "2":
            context.user_data["step"] = "awaiting_answer_for_choice_2"
            await safe_reply(
                update.message,
                "Это уже хорошая база.\n\n"
                "Напиши:\n"
                "1. Какая у тебя тема\n"
                "2. Что сейчас сложнее всего: вести регулярно, придумывать контент или понимать, что вообще сработает"
            )
            return

        elif choice == "3":
            context.user_data["step"] = "awaiting_answer_for_choice_3"
            await safe_reply(
                update.message,
                "Ты не один(одна) в этом.\n\n"
                "Скажи коротко:\n"
                "1. Что страшнее всего — камера, мнение людей или ощущение кринжа\n"
                "2. Тебе сейчас легче писать, чем снимать видео?"
            )
            return

        elif choice == "4":
            context.user_data["step"] = "awaiting_answer_for_choice_4"
            await safe_reply(
                update.message,
                "Поняла.\n\n"
                "Тогда проблема не в старте, а в том, что всё держится без системы.\n\n"
                "Напиши коротко:\n"
                "1. Где ты сейчас ведёшь блог\n"
                "2. Что у тебя ломается сильнее всего — регулярность, идеи, мотивация или понимание стратегии"
            )
            return

        else:
            await safe_reply(update.message, "Напиши, пожалуйста, только 1, 2, 3 или 4.")
            return

    prompt = f"Пользователь в сценарии 'Начать блог с нуля'. Его ответ: {user_text}. Дай тёплый, полезный и конкретный следующий шаг как сильный SMM-ментор Anna."
    answer = generate_response(user_id, prompt)
    await safe_reply(update.message, answer, reply_markup=get_main_menu())
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_pick_direction_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    prompt = f"Пользователь хочет понять, о чём ему вести блог. Вот его вводные: {user_text}. Предложи 2-3 живых направления и помоги выбрать без перегруза."
    answer = generate_response(user_id, prompt)
    await safe_reply(update.message, answer, reply_markup=get_main_menu())
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_plan_7_days_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    prompt = f"Пользователь хочет простой и реалистичный план запуска блога на 7 дней. Вот вводные: {user_text}. Дай живой, понятный и выполнимый 7-дневный план."
    answer = generate_response(user_id, prompt)
    await safe_reply(update.message, answer, reply_markup=get_main_menu())
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_analyze_blog_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    prompt = f"Пользователь хочет понять, почему блог не работает. Вот его вводные: {user_text}. Помоги спокойно увидеть главную проблему и дай один понятный следующий шаг."
    answer = generate_response(user_id, prompt)
    await safe_reply(update.message, answer, reply_markup=get_main_menu())
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_daily_checkin_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    prompt = f"Пользователь прислал ежедневный check-in. Вот его ответ: {user_text}. Поддержи его спокойно и по-человечески и дай один фокус на сегодня."
    answer = generate_response(user_id, prompt)
    await safe_reply(update.message, answer, reply_markup=get_main_menu())
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_free_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    answer = generate_response(user_id, user_text)
    await safe_reply(update.message, answer)
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    user_text = update.message.text.strip()
    mode = context.user_data.get("mode")

    if mode == "start_blog":
        await handle_start_blog_flow(update, context, user_text)
        return

    if mode == "pick_direction":
        await handle_pick_direction_flow(update, context, user_text)
        return

    if mode == "plan_7_days":
        await handle_plan_7_days_flow(update, context, user_text)
        return

    if mode == "analyze_blog":
        await handle_analyze_blog_flow(update, context, user_text)
        return

    if mode == "daily_checkin":
        await handle_daily_checkin_flow(update, context, user_text)
        return

    await handle_free_chat(update, context, user_text)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Exception while handling update:", exc_info=context.error)

def main():
    init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
