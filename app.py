import os
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor
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
DATABASE_URL = os.getenv("DATABASE_URL")

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

TELEGRAM_MESSAGE_LIMIT = 4000
SUPPORTED_LANGS = {"ru", "en", "de"}
ZERO_WIDTH_SPACE = "\u200B"

TRANSLATIONS = {
    "ru": {
        "lang_name": "Русский",
        "onboarding_intro": (
            "Привет! Я Anna — SMM-ментор по запуску и ведению блога.\n\n"
            "Сейчас задам пару коротких вопросов, чтобы точнее тебе отвечать."
        ),
        "ask_name": "Как мне к тебе обращаться?",
        "ask_gender": "Какое обращение тебе ближе?",
        "gender_female": "Женщина",
        "gender_male": "Мужчина",
        "gender_neutral": "Нейтрально",
        "gender_skip": "Пропустить",
        "ask_age": "Сколько тебе лет? Можно написать число или диапазон, например 25–30.",
        "ask_country": "В какой стране ты сейчас живёшь?",
        "onboarding_done": "Супер, познакомились ✨\n\nВыбери, с чего хочешь начать:",
        "main_intro": (
            "Привет! ✨\n\n"
            "Я Anna — SMM-ментор по запуску и ведению блога в Instagram и Telegram.\n\n"
            "Я рядом, если:\n"
            "— давно хочешь начать блог, но всё время что-то стопорит\n"
            "— уже ведёшь, но не понимаешь, почему не идёт\n"
            "— не знаешь, о чём писать и как сделать всё без перегруза\n\n"
            "Выбери, с чего хочешь начать:"
        ),
        "help": (
            "Я могу помочь тебе с таким:\n\n"
            "— начать блог с нуля\n"
            "— понять, о чём тебе вести блог\n"
            "— собрать простой план на 7 дней\n"
            "— разобраться, почему блог не работает\n"
            "— понять, что делать сегодня, если всё встало\n\n"
            "Если не хочется выбирать сценарий, просто напиши мне как есть."
        ),
        "menu_start_blog": "🚀 Начать блог с нуля",
        "menu_pick_direction": "🧭 Определить тему и направление",
        "menu_plan": "📅 План на 7 дней",
        "menu_analyze": "🔍 Разобрать почему не работает",
        "menu_checkin": "☀️ Чек-ин на сегодня",
        "menu_free_chat": "💬 Свободный чат",
        "menu_language": "🌐 Сменить язык",
        "menu_home": "🏠 Домой",
        "start_blog_screen": (
            "Давай спокойно начнём с базы.\n\n"
            "Что сейчас ближе всего к твоей ситуации?\n\n"
            "1. Хочу начать, но не могу выбрать тему\n"
            "2. Тема есть, но не понимаю, как вести блог\n"
            "3. Боюсь проявляться и публиковать\n"
            "4. Уже начал(а), но всё без системы\n\n"
            "Напиши цифру — и пойдём дальше."
        ),
        "pick_direction_screen": (
            "Напиши коротко 3 вещи:\n\n"
            "1. Что тебе по-настоящему интересно\n"
            "2. В чём у тебя уже есть опыт или насмотренность\n"
            "3. С кем тебе хотелось бы говорить через блог"
        ),
        "plan_screen": (
            "Напиши:\n\n"
            "— о чём ты примерно хочешь вести блог\n"
            "— где тебе ближе начать: Instagram, Telegram или оба\n"
            "— сколько времени ты реально готов(а) уделять в день"
        ),
        "analyze_screen": (
            "Напиши в 2–4 строках:\n\n"
            "— о чём у тебя блог\n"
            "— что ты уже делаешь\n"
            "— что именно не работает"
        ),
        "checkin_screen": (
            "Быстрый check-in ☀️\n\n"
            "1. Ничего не сделал(а)\n"
            "2. Что-то сделал(а), но как будто мало\n"
            "3. Застрял(а) и не понимаю, куда двигаться\n"
            "4. Хочу понять, какой у меня один фокус на сегодня"
        ),
        "free_chat_screen": (
            "Ты в свободном чате.\n\n"
            "Можешь написать как есть: про блог, контент, страх проявляться, Instagram, Telegram или просто про ступор."
        ),
        "start_choice_invalid": "Напиши, пожалуйста, только 1, 2, 3 или 4.",
        "start_choice_1": "Ответь коротко: что тебе было бы интересно обсуждать долго и в чём у тебя уже есть опыт или путь?",
        "start_choice_2": "Напиши: какая у тебя тема и что сейчас сложнее всего — регулярность, контент или понимание, что сработает?",
        "start_choice_3": "Скажи коротко: что страшнее всего — камера, мнение людей или ощущение кринжа?",
        "start_choice_4": "Напиши: где ты сейчас ведёшь блог и что ломается сильнее всего — регулярность, идеи, мотивация или стратегия?",
        "openai_language_instruction": "Отвечай строго на русском языке.",
    },
    "en": {
        "lang_name": "English",
        "onboarding_intro": (
            "Hi! I’m Anna — an SMM mentor for starting and growing a blog.\n\n"
            "I’ll ask you a couple of short questions so I can guide you more accurately."
        ),
        "ask_name": "What should I call you?",
        "ask_gender": "What form of address feels right for you?",
        "gender_female": "Woman",
        "gender_male": "Man",
        "gender_neutral": "Neutral",
        "gender_skip": "Skip",
        "ask_age": "How old are you? You can send a number or a range like 25–30.",
        "ask_country": "Which country do you currently live in?",
        "onboarding_done": "Great, now we know each other a bit ✨\n\nChoose where you want to start:",
        "main_intro": (
            "Hi! ✨\n\n"
            "I’m Anna — an SMM mentor for starting and growing a blog on Instagram and Telegram.\n\n"
            "Choose where you want to start:"
        ),
        "help": "I can help you start a blog, choose a topic, create a 7-day plan, analyze what’s not working, or simply think through your next step.",
        "menu_start_blog": "🚀 Start a blog from scratch",
        "menu_pick_direction": "🧭 Find topic and direction",
        "menu_plan": "📅 7-day plan",
        "menu_analyze": "🔍 Analyze what’s not working",
        "menu_checkin": "☀️ Today check-in",
        "menu_free_chat": "💬 Free chat",
        "menu_language": "🌐 Change language",
        "menu_home": "🏠 Home",
        "start_blog_screen": "Which situation feels closest right now?\n\n1. I want to start, but can’t choose a topic\n2. I have a topic, but don’t know how to run the blog\n3. I’m afraid to show up and publish\n4. I already started, but there’s no system",
        "pick_direction_screen": "Write 3 short things:\n1. What genuinely interests you\n2. What you already have experience in\n3. Who you’d like to talk to through your blog",
        "plan_screen": "Write:\n— what your blog may be about\n— where you want to start: Instagram, Telegram or both\n— how much time you can realistically spend daily",
        "analyze_screen": "Write in 2–4 lines:\n— what your blog is about\n— what you are already doing\n— what exactly isn’t working",
        "checkin_screen": "Quick check-in ☀️\n1. I did nothing today\n2. I did something, but it feels too little\n3. I’m stuck\n4. I want one clear focus for today",
        "free_chat_screen": "You’re in free chat mode. Just write naturally about your blog, content, fear of showing up, Instagram, Telegram, or your current block.",
        "start_choice_invalid": "Please send only 1, 2, 3, or 4.",
        "start_choice_1": "Answer briefly: what could you talk about for a long time, and where do you already have experience or perspective?",
        "start_choice_2": "Write: what your topic is and what feels hardest right now — consistency, content, or understanding what works?",
        "start_choice_3": "Tell me briefly: what feels scariest — camera, people’s opinions, or cringe?",
        "start_choice_4": "Write: where you post now and what breaks most — consistency, ideas, motivation, or strategy?",
        "openai_language_instruction": "Reply strictly in English.",
    },
    "de": {
        "lang_name": "Deutsch",
        "onboarding_intro": (
            "Hallo! Ich bin Anna — eine SMM-Mentorin für den Start und Aufbau eines Blogs.\n\n"
            "Ich stelle dir jetzt ein paar kurze Fragen, damit ich dir passender antworten kann."
        ),
        "ask_name": "Wie soll ich dich ansprechen?",
        "ask_gender": "Welche Anrede passt für dich am besten?",
        "gender_female": "Frau",
        "gender_male": "Mann",
        "gender_neutral": "Neutral",
        "gender_skip": "Überspringen",
        "ask_age": "Wie alt bist du? Du kannst eine Zahl oder einen Bereich wie 25–30 schreiben.",
        "ask_country": "In welchem Land lebst du aktuell?",
        "onboarding_done": "Super, jetzt kennen wir uns etwas besser ✨\n\nWähle, womit du anfangen möchtest:",
        "main_intro": (
            "Hallo! ✨\n\n"
            "Ich bin Anna — eine SMM-Mentorin für den Start und Aufbau eines Blogs auf Instagram und Telegram.\n\n"
            "Wähle, womit du anfangen möchtest:"
        ),
        "help": "Ich kann dir beim Blogstart, bei der Themenwahl, bei einem 7-Tage-Plan, bei der Analyse von Problemen oder beim nächsten sinnvollen Schritt helfen.",
        "menu_start_blog": "🚀 Blog von null starten",
        "menu_pick_direction": "🧭 Thema und Richtung finden",
        "menu_plan": "📅 7-Tage-Plan",
        "menu_analyze": "🔍 Analysieren, was nicht funktioniert",
        "menu_checkin": "☀️ Check-in für heute",
        "menu_free_chat": "💬 Freier Chat",
        "menu_language": "🌐 Sprache ändern",
        "menu_home": "🏠 Start",
        "start_blog_screen": "Welche Situation passt gerade am ehesten?\n\n1. Ich will anfangen, kann aber kein Thema wählen\n2. Ich habe ein Thema, weiß aber nicht, wie ich den Blog führen soll\n3. Ich habe Angst, mich zu zeigen und zu posten\n4. Ich habe schon angefangen, aber ohne System",
        "pick_direction_screen": "Schreib 3 kurze Dinge:\n1. Was dich wirklich interessiert\n2. Worin du schon Erfahrung hast\n3. Mit wem du über deinen Blog sprechen willst",
        "plan_screen": "Schreib:\n— worum es in deinem Blog ungefähr gehen soll\n— wo du starten willst: Instagram, Telegram oder beides\n— wie viel Zeit du täglich realistisch investieren kannst",
        "analyze_screen": "Schreib in 2–4 Zeilen:\n— worum es in deinem Blog geht\n— was du schon machst\n— was genau nicht funktioniert",
        "checkin_screen": "Kurzer Check-in ☀️\n1. Ich habe heute nichts gemacht\n2. Ich habe etwas gemacht, aber es fühlt sich nach zu wenig an\n3. Ich stecke fest\n4. Ich will einen klaren Fokus für heute",
        "free_chat_screen": "Du bist im freien Chat. Schreib einfach natürlich über deinen Blog, Content, die Angst sichtbar zu werden, Instagram, Telegram oder deinen aktuellen Stillstand.",
        "start_choice_invalid": "Bitte sende nur 1, 2, 3 oder 4.",
        "start_choice_1": "Antworte kurz: Worüber könntest du lange sprechen und worin hast du schon Erfahrung oder Perspektive?",
        "start_choice_2": "Schreib: Was ist dein Thema und was ist gerade am schwierigsten — Regelmäßigkeit, Content oder zu verstehen, was funktioniert?",
        "start_choice_3": "Sag mir kurz: Was macht dir am meisten Angst — Kamera, Meinungen anderer oder Fremdscham?",
        "start_choice_4": "Schreib: Wo postest du aktuell und was bricht am meisten — Regelmäßigkeit, Ideen, Motivation oder Strategie?",
        "openai_language_instruction": "Antworte ausschließlich auf Deutsch.",
    }
}

BASE_SYSTEM_PROMPT = """
Ты Anna — тёплый, спокойный и современный SMM-ментор по запуску и ведению блога в Instagram и Telegram.

Твоя роль:
помогать человеку начать блог без перегруза, понять что именно ему мешает, выбрать направление, не перегореть в начале и двигаться маленькими понятными шагами.

Как ты работаешь:
- пишешь просто, тепло, спокойно и по делу
- не звучишь как корпоративный консультант
- не перегружаешь теорией
- один ответ = один понятный следующий шаг
- если человек запутался, сужаешь выбор до 2-3 вариантов
- если контекста не хватает, задаёшь только один короткий уточняющий вопрос
- после одного уточнения переходишь к полезному ответу
- не растягивай ответ без необходимости
- предпочитай 2-3 сильных варианта вместо длинного списка
- только plain text, без markdown
"""

def normalize_lang(lang_code):
    if not lang_code:
        return "en"
    base = str(lang_code).split("-")[0].lower()
    return base if base in SUPPORTED_LANGS else "en"

def tr(lang, key):
    return TRANSLATIONS[normalize_lang(lang)][key]

def clean_text(text: str) -> str:
    if text is None:
        return ZERO_WIDTH_SPACE

    if text == ZERO_WIDTH_SPACE:
        return text

    cleaned = (
        str(text).replace("**", "")
        .replace("*", "")
        .replace("__", "")
        .replace("_", "")
        .replace("```", "")
        .replace("`", "")
        .replace("##", "")
        .replace("#", "")
    )

    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")

    cleaned = cleaned.strip()

    return cleaned if cleaned else ZERO_WIDTH_SPACE

def split_text_into_chunks(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT):
    text = clean_text(text)

    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > limit:
        chunk = remaining[:limit]
        split_index = chunk.rfind("\n\n")
        if split_index == -1:
            split_index = chunk.rfind("\n")
        if split_index == -1:
            split_index = chunk.rfind(". ")
        if split_index == -1:
            split_index = chunk.rfind(" ")
        if split_index == -1:
            split_index = limit

        part = remaining[:split_index].strip()
        if not part:
            part = remaining[:limit].strip()
            split_index = limit

        chunks.append(part)
        remaining = remaining[split_index:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks

def normalize_database_url(url: str) -> str:
    if not url:
        raise ValueError("DATABASE_URL is not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url

def get_db_connection():
    db_url = normalize_database_url(DATABASE_URL)
    parsed = urlparse(db_url)
    sslmode = "require"
    query = parsed.query or ""
    if "sslmode=" in query:
        sslmode = None

    conn = psycopg2.connect(
        db_url if sslmode is None else f"{db_url}?sslmode={sslmode}",
        cursor_factory=RealDictCursor
    )
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        telegram_user_id BIGINT UNIQUE,
        username TEXT,
        first_name TEXT,
        language_code TEXT,
        selected_language TEXT,
        display_name TEXT,
        gender TEXT,
        age_range TEXT,
        country TEXT,
        onboarding_completed BOOLEAN DEFAULT FALSE,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS language_code TEXT,
    ADD COLUMN IF NOT EXISTS selected_language TEXT,
    ADD COLUMN IF NOT EXISTS display_name TEXT,
    ADD COLUMN IF NOT EXISTS gender TEXT,
    ADD COLUMN IF NOT EXISTS age_range TEXT,
    ADD COLUMN IF NOT EXISTS country TEXT,
    ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT FALSE
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        telegram_user_id BIGINT,
        role TEXT,
        text TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_memory (
        id SERIAL PRIMARY KEY,
        telegram_user_id BIGINT UNIQUE,
        summary TEXT,
        updated_at TEXT
    )
    """)

    conn.commit()
    cur.close()
    conn.close()
    logger.info("Database initialized")

def save_user(update: Update):
    telegram_user = update.effective_user
    now = datetime.now(timezone.utc).isoformat()
    detected_lang = normalize_lang(getattr(telegram_user, "language_code", None))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO users (telegram_user_id, username, first_name, language_code, created_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (telegram_user_id)
    DO UPDATE SET
        username = EXCLUDED.username,
        first_name = EXCLUDED.first_name,
        language_code = COALESCE(users.language_code, EXCLUDED.language_code),
        updated_at = EXCLUDED.updated_at
    """, (
        telegram_user.id,
        telegram_user.username,
        telegram_user.first_name,
        detected_lang,
        now,
        now
    ))

    conn.commit()
    cur.close()
    conn.close()

def get_user_profile(telegram_user_id: int):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
        SELECT *
        FROM users
        WHERE telegram_user_id = %s
        """, (telegram_user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row or {}
    except Exception as e:
        logger.exception("get_user_profile failed: %s", e)
        return {}

def update_user_profile(telegram_user_id: int, **fields):
    if not fields:
        return

    allowed = {
        "selected_language",
        "display_name",
        "gender",
        "age_range",
        "country",
        "onboarding_completed",
        "updated_at"
    }

    updates = []
    values = []

    for key, value in fields.items():
        if key in allowed:
            updates.append(f"{key} = %s")
            values.append(value)

    if not updates:
        return

    values.append(telegram_user_id)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE telegram_user_id = %s",
        values
    )
    conn.commit()
    cur.close()
    conn.close()

def get_user_language(telegram_user_id: int) -> str:
    profile = get_user_profile(telegram_user_id)
    selected = profile.get("selected_language")
    fallback = profile.get("language_code")
    return normalize_lang(selected or fallback or "en")

def save_message(telegram_user_id: int, role: str, text: str):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO messages (telegram_user_id, role, text, created_at)
        VALUES (%s, %s, %s, %s)
        """, (
            telegram_user_id,
            role,
            text,
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("save_message failed: %s", e)

def get_recent_messages(telegram_user_id: int, limit: int = 4):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
        SELECT role, text
        FROM messages
        WHERE telegram_user_id = %s
        ORDER BY id DESC
        LIMIT %s
        """, (telegram_user_id, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        rows.reverse()
        return rows
    except Exception as e:
        logger.exception("get_recent_messages failed: %s", e)
        return []

def get_user_memory(telegram_user_id: int):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
        SELECT summary
        FROM user_memory
        WHERE telegram_user_id = %s
        """, (telegram_user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row["summary"] if row else ""
    except Exception as e:
        logger.exception("get_user_memory failed: %s", e)
        return ""

def update_user_memory(telegram_user_id: int, summary: str):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO user_memory (telegram_user_id, summary, updated_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (telegram_user_id)
        DO UPDATE SET
            summary = EXCLUDED.summary,
            updated_at = EXCLUDED.updated_at
        """, (
            telegram_user_id,
            summary,
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("update_user_memory failed: %s", e)

def get_profile_context_text(profile: dict, lang: str) -> str:
    name = profile.get("display_name") or profile.get("first_name") or ""
    gender = profile.get("gender") or ""
    age_range = profile.get("age_range") or ""
    country = profile.get("country") or ""

    return (
        f"Имя пользователя: {name or 'не указано'}\n"
        f"Пол / способ обращения: {gender or 'не указан'}\n"
        f"Возраст: {age_range or 'не указан'}\n"
        f"Страна проживания: {country or 'не указана'}\n"
        f"Выбранный язык: {lang}"
    )

def build_system_prompt(lang: str, profile: dict | None = None) -> str:
    lang = normalize_lang(lang)
    extra = tr(lang, "openai_language_instruction")

    profile_text = ""
    if profile:
        gender = profile.get("gender")
        if lang == "ru":
            if gender == "female":
                profile_text = (
                    "Обращайся к пользователю мягко и естественно. "
                    "Если формулировка зависит от рода, используй женскую форму."
                )
            elif gender == "male":
                profile_text = (
                    "Обращайся к пользователю мягко и естественно. "
                    "Если формулировка зависит от рода, используй мужскую форму."
                )
            else:
                profile_text = (
                    "Если формулировка зависит от рода, по возможности строй фразы нейтрально."
                )

    return BASE_SYSTEM_PROMPT + "\n\n" + extra + "\n" + profile_text

def call_openai(prompt: str, lang: str, profile: dict | None = None, instructions: str | None = None) -> str:
    try:
        final_instructions = instructions or build_system_prompt(lang, profile)
        response = client.responses.create(
            model="gpt-5.2",
            instructions=final_instructions,
            input=prompt
        )
        return clean_text(response.output_text)
    except Exception as e:
        logger.exception("OpenAI request failed: %s", e)
        fallback = {
            "ru": "Сейчас я не могу нормально ответить из-за технической ошибки.\n\nПопробуй ещё раз чуть позже.",
            "en": "I can’t answer properly right now because of a technical error.\n\nPlease try again a bit later.",
            "de": "Ich kann im Moment wegen eines technischen Fehlers nicht richtig antworten.\n\nBitte versuche es etwas später noch einmal."
        }
        return fallback.get(normalize_lang(lang), fallback["en"])

def maybe_update_memory(telegram_user_id: int, user_text: str, bot_text: str):
    if len(user_text.strip()) < 25:
        return

    lang = get_user_language(telegram_user_id)
    current_memory = get_user_memory(telegram_user_id)

    prompt = f"""
У тебя есть диалог между пользователем и SMM-ментором Anna.

Твоя задача:
обновить краткую полезную память о пользователе.

Правила:
- сохрани только устойчивые и полезные факты
- не пересказывай весь диалог
- максимум 3 короткие строки
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
        lang=lang,
        instructions="Ты помогаешь сжато обновлять память о пользователе. Верни summary на языке пользователя."
    )
    if summary:
        update_user_memory(telegram_user_id, summary)

def build_context_prompt(telegram_user_id: int, user_text: str):
    profile = get_user_profile(telegram_user_id)
    lang = get_user_language(telegram_user_id)
    memory = get_user_memory(telegram_user_id)
    recent_messages = get_recent_messages(telegram_user_id, limit=4)

    history_block = ""
    for row in recent_messages:
        history_block += f"{row['role']}: {row['text']}\n"

    prompt = f"""
Ниже контекст пользователя для ответа.

Профиль пользователя:
{get_profile_context_text(profile, lang)}

Память о пользователе:
{memory if memory else "Пока нет сохранённой памяти."}

Недавние сообщения:
{history_block if history_block else "Нет истории."}

Новое сообщение пользователя:
{user_text}

Ответь как Anna — тёплый SMM-ментор по правилам системы.
"""
    return prompt

def get_user_context_block(telegram_user_id: int, user_text: str):
    profile = get_user_profile(telegram_user_id)
    lang = get_user_language(telegram_user_id)
    memory = get_user_memory(telegram_user_id)
    recent_messages = get_recent_messages(telegram_user_id, limit=4)

    history_block = ""
    for row in recent_messages:
        history_block += f"{row['role']}: {row['text']}\n"

    return f"""
Профиль пользователя:
{get_profile_context_text(profile, lang)}

Память о пользователе:
{memory if memory else "Пока нет сохранённой памяти."}

Недавние сообщения:
{history_block if history_block else "Нет истории."}

Новое сообщение пользователя:
{user_text}
"""

def classify_request(user_text: str) -> str:
    text = user_text.lower()

    topic_keywords = [
        "о чем вести", "о чём вести", "тема блога", "направление", "ниша",
        "какую тему", "выбрать тему", "определить тему",
        "what should i blog about", "blog topic", "choose topic",
        "worüber bloggen", "thema wählen"
    ]
    content_keywords = [
        "идеи", "контент", "рубрики", "что снимать", "что писать",
        "сценарии", "рилс", "reels", "сторис", "посты", "контент-план",
        "content ideas", "content plan", "hooks",
        "content ideen", "contentplan"
    ]
    plan_keywords = [
        "план на 7 дней", "7 дней", "на неделю",
        "7 day plan", "weekly plan",
        "7-tage-plan", "wochenplan"
    ]
    diagnose_keywords = [
        "не работает", "нет охватов", "не идет", "не идёт", "мало просмотров",
        "нет отклика", "нет продаж", "не растет", "не растёт",
        "not working", "low reach", "no engagement",
        "funktioniert nicht", "keine reichweite"
    ]

    if any(keyword in text for keyword in plan_keywords):
        return "plan_7_days"
    if any(keyword in text for keyword in diagnose_keywords):
        return "diagnose_blog"
    if any(keyword in text for keyword in content_keywords):
        return "content_ideas"
    if any(keyword in text for keyword in topic_keywords):
        return "blog_direction"

    return "general"

def generate_blog_direction_response(telegram_user_id: int, user_text: str) -> str:
    lang = get_user_language(telegram_user_id)
    profile = get_user_profile(telegram_user_id)
    context_block = get_user_context_block(telegram_user_id, user_text)

    prompt = f"""
{context_block}

Задача:
помоги пользователю понять, о чём ему вести блог.

Требования:
- предложи 2-3 сильных направления максимум
- добавляй конкретику
- помоги сузить выбор
- не растягивай ответ
"""
    return call_openai(prompt, lang=lang, profile=profile)

def generate_content_ideas_response(telegram_user_id: int, user_text: str) -> str:
    lang = get_user_language(telegram_user_id)
    profile = get_user_profile(telegram_user_id)
    context_block = get_user_context_block(telegram_user_id, user_text)

    prompt = f"""
{context_block}

Задача:
дать пользователю качественные идеи контента.

Требования:
- предложи 5 сильных идей максимум
- для каждой идеи укажи идею, угол подачи, пример хука и лучший формат
- не растягивай ответ
"""
    return call_openai(prompt, lang=lang, profile=profile)

def generate_7_day_plan_response(telegram_user_id: int, user_text: str) -> str:
    lang = get_user_language(telegram_user_id)
    profile = get_user_profile(telegram_user_id)
    context_block = get_user_context_block(telegram_user_id, user_text)

    prompt = f"""
{context_block}

Задача:
сделать реалистичный и сильный план на 7 дней.

Требования:
- каждый день = один основной фокус
- для каждого дня укажи: фокус, действие, результат
- не перегружай
"""
    return call_openai(prompt, lang=lang, profile=profile)

def generate_blog_diagnosis_response(telegram_user_id: int, user_text: str) -> str:
    lang = get_user_language(telegram_user_id)
    profile = get_user_profile(telegram_user_id)
    context_block = get_user_context_block(telegram_user_id, user_text)

    prompt = f"""
{context_block}

Задача:
помочь пользователю понять, почему блог или контент не работает.

Требования:
- выдели 1 главную и максимум 1 дополнительную проблему
- объясни просто
- потом дай один следующий шаг
"""
    return call_openai(prompt, lang=lang, profile=profile)

def generate_general_response(telegram_user_id: int, user_text: str) -> str:
    request_type = classify_request(user_text)

    if request_type == "blog_direction":
        return generate_blog_direction_response(telegram_user_id, user_text)
    if request_type == "content_ideas":
        return generate_content_ideas_response(telegram_user_id, user_text)
    if request_type == "plan_7_days":
        return generate_7_day_plan_response(telegram_user_id, user_text)
    if request_type == "diagnose_blog":
        return generate_blog_diagnosis_response(telegram_user_id, user_text)

    lang = get_user_language(telegram_user_id)
    profile = get_user_profile(telegram_user_id)
    final_prompt = build_context_prompt(telegram_user_id, user_text)
    return call_openai(final_prompt, lang=lang, profile=profile)

def get_language_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Русский", callback_data="lang_ru")],
        [InlineKeyboardButton("English", callback_data="lang_en")],
        [InlineKeyboardButton("Deutsch", callback_data="lang_de")],
    ])

def get_gender_keyboard(lang: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(lang, "gender_female"), callback_data="gender_female")],
        [InlineKeyboardButton(tr(lang, "gender_male"), callback_data="gender_male")],
        [InlineKeyboardButton(tr(lang, "gender_neutral"), callback_data="gender_neutral")],
        [InlineKeyboardButton(tr(lang, "gender_skip"), callback_data="gender_skip")],
    ])

def get_main_menu(lang: str):
    keyboard = [
        [InlineKeyboardButton(tr(lang, "menu_start_blog"), callback_data="start_blog")],
        [InlineKeyboardButton(tr(lang, "menu_pick_direction"), callback_data="pick_direction")],
        [InlineKeyboardButton(tr(lang, "menu_plan"), callback_data="plan_7_days")],
        [InlineKeyboardButton(tr(lang, "menu_analyze"), callback_data="analyze_blog")],
        [InlineKeyboardButton(tr(lang, "menu_checkin"), callback_data="daily_checkin")],
        [InlineKeyboardButton(tr(lang, "menu_free_chat"), callback_data="free_chat")],
        [InlineKeyboardButton(tr(lang, "menu_language"), callback_data="change_language")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_home_menu(lang: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(tr(lang, "menu_home"), callback_data="main_menu")]
    ])

async def safe_reply(message_obj, text, reply_markup=None):
    try:
        text = clean_text(text)
        chunks = split_text_into_chunks(text)

        for i, chunk in enumerate(chunks):
            current_markup = reply_markup if i == len(chunks) - 1 else None
            await message_obj.reply_text(chunk, reply_markup=current_markup)
    except TelegramError as e:
        logger.exception("reply_text failed: %s", e)

async def safe_edit(query, text, reply_markup=None):
    try:
        text = clean_text(text)

        if len(text) <= TELEGRAM_MESSAGE_LIMIT:
            await query.edit_message_text(text=text, reply_markup=reply_markup)
            return

        chunks = split_text_into_chunks(text)
        await query.edit_message_text(text=chunks)

        for chunk in chunks[1:-1]:
            await query.message.reply_text(chunk)

        if len(chunks) > 1:
            await query.message.reply_text(chunks[-1], reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Skipped edit: message is not modified")
        else:
            logger.exception("BadRequest on edit_message_text: %s", e)
    except TelegramError as e:
        logger.exception("edit_message_text failed: %s", e)

async def send_main_menu_message(target, lang: str):
    await safe_reply(target, tr(lang, "main_intro"), reply_markup=get_main_menu(lang))

async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    context.user_data.clear()
    context.user_data["mode"] = "onboarding"
    context.user_data["onboarding_step"] = "language"
    await safe_reply(update.message, ZERO_WIDTH_SPACE, reply_markup=get_language_keyboard())

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    user_id = update.effective_user.id
    profile = get_user_profile(user_id)

    if not profile or not profile.get("onboarding_completed"):
        await start_onboarding(update, context)
        return

    context.user_data.clear()
    lang = get_user_language(user_id)
    await send_main_menu_message(update.message, lang)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    await safe_reply(update.message, tr(lang, "help"), reply_markup=get_main_menu(lang))

async def show_main_menu(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data.clear()
    await safe_edit(query, tr(lang, "main_intro"), reply_markup=get_main_menu(lang))

async def show_start_blog_screen(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data["mode"] = "start_blog"
    context.user_data["step"] = "awaiting_start_blog_choice"
    await safe_edit(query, tr(lang, "start_blog_screen"), reply_markup=get_home_menu(lang))

async def show_pick_direction_screen(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data["mode"] = "pick_direction"
    await safe_edit(query, tr(lang, "pick_direction_screen"), reply_markup=get_home_menu(lang))

async def show_plan_7_days_screen(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data["mode"] = "plan_7_days"
    await safe_edit(query, tr(lang, "plan_screen"), reply_markup=get_home_menu(lang))

async def show_analyze_blog_screen(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data["mode"] = "analyze_blog"
    await safe_edit(query, tr(lang, "analyze_screen"), reply_markup=get_home_menu(lang))

async def show_daily_checkin_screen(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data["mode"] = "daily_checkin"
    await safe_edit(query, tr(lang, "checkin_screen"), reply_markup=get_home_menu(lang))

async def show_free_chat_screen(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data.clear()
    await safe_edit(query, tr(lang, "free_chat_screen"), reply_markup=get_home_menu(lang))

async def show_change_language_screen(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["mode"] = "onboarding"
    context.user_data["onboarding_step"] = "language"
    await safe_edit(query, ZERO_WIDTH_SPACE, reply_markup=get_language_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data.startswith("lang_"):
        selected_lang = normalize_lang(query.data.replace("lang_", ""))
        update_user_profile(
            user_id,
            selected_language=selected_lang,
            updated_at=datetime.now(timezone.utc).isoformat()
        )
        context.user_data["mode"] = "onboarding"
        context.user_data["onboarding_step"] = "name"
        await safe_edit(query, tr(selected_lang, "onboarding_intro"))
        await query.message.reply_text(tr(selected_lang, "ask_name"))
        return

    if query.data.startswith("gender_"):
        lang = get_user_language(user_id)
        gender_value = query.data.replace("gender_", "")
        if gender_value == "skip":
            gender_value = "unspecified"

        update_user_profile(
            user_id,
            gender=gender_value,
            updated_at=datetime.now(timezone.utc).isoformat()
        )
        context.user_data["mode"] = "onboarding"
        context.user_data["onboarding_step"] = "age"
        await safe_edit(query, tr(lang, "ask_age"))
        return

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
    elif query.data == "change_language":
        await show_change_language_screen(query, context)
    elif query.data == "main_menu":
        await show_main_menu(query, context)

async def finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    lang = get_user_language(user_id)
    update_user_profile(
        user_id,
        onboarding_completed=True,
        updated_at=datetime.now(timezone.utc).isoformat()
    )
    context.user_data.clear()
    await safe_reply(
        update.message,
        tr(lang, "onboarding_done"),
        reply_markup=get_main_menu(lang)
    )

async def handle_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    step = context.user_data.get("onboarding_step")

    if step == "name":
        update_user_profile(
            user_id,
            display_name=user_text.strip(),
            updated_at=datetime.now(timezone.utc).isoformat()
        )
        context.user_data["onboarding_step"] = "gender"
        await safe_reply(update.message, tr(lang, "ask_gender"), reply_markup=get_gender_keyboard(lang))
        return

    if step == "age":
        update_user_profile(
            user_id,
            age_range=user_text.strip(),
            updated_at=datetime.now(timezone.utc).isoformat()
        )
        context.user_data["onboarding_step"] = "country"
        await safe_reply(update.message, tr(lang, "ask_country"))
        return

    if step == "country":
        update_user_profile(
            user_id,
            country=user_text.strip(),
            updated_at=datetime.now(timezone.utc).isoformat()
        )
        await finish_onboarding(update, context, user_id)
        return

    await safe_reply(update.message, ZERO_WIDTH_SPACE, reply_markup=get_language_keyboard())

async def handle_start_blog_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    step = context.user_data.get("step")
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    if step == "awaiting_start_blog_choice":
        choice = user_text.strip()

        if choice == "1":
            context.user_data["step"] = "awaiting_answer_for_choice_1"
            await safe_reply(update.message, tr(lang, "start_choice_1"), reply_markup=get_home_menu(lang))
            return
        elif choice == "2":
            context.user_data["step"] = "awaiting_answer_for_choice_2"
            await safe_reply(update.message, tr(lang, "start_choice_2"), reply_markup=get_home_menu(lang))
            return
        elif choice == "3":
            context.user_data["step"] = "awaiting_answer_for_choice_3"
            await safe_reply(update.message, tr(lang, "start_choice_3"), reply_markup=get_home_menu(lang))
            return
        elif choice == "4":
            context.user_data["step"] = "awaiting_answer_for_choice_4"
            await safe_reply(update.message, tr(lang, "start_choice_4"), reply_markup=get_home_menu(lang))
            return
        else:
            await safe_reply(update.message, tr(lang, "start_choice_invalid"), reply_markup=get_home_menu(lang))
            return

    answer = generate_general_response(user_id, user_text)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    if len(user_text) > 40:
        maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_pick_direction_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    answer = generate_blog_direction_response(user_id, user_text)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    if len(user_text) > 40:
        maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_plan_7_days_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    answer = generate_7_day_plan_response(user_id, user_text)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    if len(user_text) > 40:
        maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_analyze_blog_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    answer = generate_blog_diagnosis_response(user_id, user_text)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    if len(user_text) > 40:
        maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_daily_checkin_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    profile = get_user_profile(user_id)

    prompt = f"""
{get_user_context_block(user_id, user_text)}

Задача:
пользователь прислал ежедневный check-in.

Дай ответ так, чтобы:
- сначала была поддержка
- потом ясность
- потом один фокус на сегодня
- без давления
- компактно
"""
    answer = call_openai(prompt, lang=lang, profile=profile)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    if len(user_text) > 40:
        maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_free_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    answer = generate_general_response(user_id, user_text)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    if len(user_text) > 40:
        maybe_update_memory(user_id, user_text, answer)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    user_id = update.effective_user.id
    user_text = update.message.text.strip()
    mode = context.user_data.get("mode")
    profile = get_user_profile(user_id)

    if not profile or not profile.get("onboarding_completed"):
        if not mode:
            context.user_data["mode"] = "onboarding"
            context.user_data["onboarding_step"] = "language"
            await safe_reply(update.message, ZERO_WIDTH_SPACE, reply_markup=get_language_keyboard())
            return

    if mode == "onboarding":
        await handle_onboarding(update, context, user_text)
        return

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
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set")

    init_db()

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .connection_pool_size(20)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()