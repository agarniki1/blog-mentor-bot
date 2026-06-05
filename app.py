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
    level=logging.INFO,
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)
logging.getLogger("telegram.ext").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

client = OpenAI(api_key=OPENAI_API_KEY)

TELEGRAM_MESSAGE_LIMIT = 4000
SUPPORTED_LANGS = {"ru", "en", "de"}

TRANSLATIONS = {
    "ru": {
        "lang_name": "Русский",
        "onboarding_hi": "Hi! / Привет! / Hallo!",
        "onboarding_gender": "Как к тебе лучше обращаться?",
        "onboarding_country": "В какой стране ты сейчас живёшь?",
        "onboarding_done": (
            "Готово ✨\n\n"
            "Я Anna — SMM-ментор по запуску и ведению блога в Instagram и Telegram.\n\n"
            "Помогаю, если:\n"
            "— давно хочешь начать блог, но всё время что-то тормозит\n"
            "— уже ведёшь, но не понимаешь, почему не работает\n"
            "— не знаешь, о чём писать и как сделать всё без перегруза\n\n"
            "С чего начнём?"
        ),
        "gender_female": "Женщина",
        "gender_male": "Мужчина",
        "gender_skip": "Не указывать",
        "start_want_blog": "🚀 Хочу начать блог",
        "start_not_working": "🔍 Уже веду, но не идёт",
        "start_no_idea": "🧭 Не знаю, о чём писать",
        "start_focus": "☀️ Мне нужен фокус на сегодня",
        "help": (
            "Я могу помочь тебе с таким:\n\n"
            "— начать блог с нуля\n"
            "— понять, о чём тебе вести блог\n"
            "— собрать простой план на 7 дней\n"
            "— разобраться, почему блог не работает\n"
            "— понять, что делать сегодня, если всё встало\n\n"
            "Если не хочется выбирать сценарий, просто напиши мне как есть."
        ),
        "main_intro": (
            "Привет! ✨\n\n"
            "Я Anna — SMM-ментор по запуску и ведению блога в Instagram и Telegram.\n\n"
            "Выбери, с чего хочешь начать:"
        ),
        "menu_start_blog": "🚀 Начать блог с нуля",
        "menu_pick_direction": "🧭 Определить тему и направление",
        "menu_plan": "📅 План на 7 дней",
        "menu_analyze": "🔍 Разобрать почему не работает",
        "menu_checkin": "☀️ Чек-ин на сегодня",
        "menu_free_chat": "💬 Свободный чат",
        "menu_language": "🌐 Сменить язык",
        "menu_home": "🏠 Домой",
        "prestart_want_blog_text": (
            "Поняла.\n\n"
            "Чаще всего здесь проблема не в лени, а в перегрузе и отсутствии ясной точки старта."
        ),
        "prestart_not_working_text": (
            "Похоже, ты уже что-то делаешь, но пока не видишь отдачи."
        ),
        "prestart_no_idea_text": (
            "Это нормальная точка.\n\n"
            "Обычно здесь не нужен идеальный выбор — нужна рабочая тема, с которой можно начать."
        ),
        "prestart_focus_text": (
            "Окей.\n\n"
            "Тогда пойдём не в большие планы, а в один понятный шаг на сегодня."
        ),
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
            "Давай попробуем найти направление, которое тебе правда подойдёт.\n\n"
            "Напиши коротко 3 вещи:\n\n"
            "1. Что тебе по-настоящему интересно\n"
            "2. В чём у тебя уже есть опыт или насмотренность\n"
            "3. С кем тебе хотелось бы говорить через блог"
        ),
        "plan_screen": (
            "Соберу тебе простой и живой план на 7 дней — без перегруза.\n\n"
            "Перед этим напиши:\n\n"
            "— о чём ты примерно хочешь вести блог\n"
            "— где тебе ближе начать: Instagram, Telegram или оба\n"
            "— сколько времени ты реально готов(а) уделять в день"
        ),
        "analyze_screen": (
            "Окей, давай спокойно посмотрим, где сейчас затык.\n\n"
            "Напиши в 2–4 строках:\n\n"
            "— о чём у тебя блог\n"
            "— что ты уже делаешь\n"
            "— что именно не работает"
        ),
        "checkin_screen": (
            "Быстрый check-in ☀️\n\n"
            "Что сегодня ближе всего?\n\n"
            "1. Ничего не сделал(а)\n"
            "2. Что-то сделал(а), но как будто мало\n"
            "3. Застрял(а) и не понимаю, куда двигаться\n"
            "4. Хочу понять, какой у меня один фокус на сегодня"
        ),
        "free_chat_screen": (
            "Ты в свободном чате.\n\n"
            "Можешь написать как есть: про блог, тему, контент, страх проявляться или просто про ступор."
        ),
        "start_choice_invalid": "Напиши, пожалуйста, только 1, 2, 3 или 4.",
        "start_choice_1": (
            "Это очень живая точка старта.\n\n"
            "Ответь коротко на 2 вещи:\n"
            "1. Что тебе правда было бы интересно обсуждать долго\n"
            "2. В чём у тебя уже есть опыт, путь или насмотренность"
        ),
        "start_choice_2": (
            "Это уже хорошая база.\n\n"
            "Напиши:\n"
            "1. Какая у тебя тема\n"
            "2. Что сейчас сложнее всего"
        ),
        "start_choice_3": (
            "Ты не один(одна) в этом.\n\n"
            "Скажи коротко:\n"
            "1. Что страшнее всего\n"
            "2. Тебе сейчас легче писать, чем снимать видео?"
        ),
        "start_choice_4": (
            "Поняла.\n\n"
            "Тогда проблема не в старте, а в том, что всё держится без системы.\n\n"
            "Напиши коротко:\n"
            "1. Где ты сейчас ведёшь блог\n"
            "2. Что ломается сильнее всего"
        ),
        "openai_language_instruction": "Отвечай строго на русском языке.",
    },
    "en": {
        "lang_name": "English",
        "onboarding_hi": "Hi! / Привет! / Hallo!",
        "onboarding_gender": "How should I address you?",
        "onboarding_country": "Which country do you currently live in?",
        "onboarding_done": (
            "Done ✨\n\n"
            "I’m Anna — an SMM mentor for starting and growing a blog on Instagram and Telegram.\n\n"
            "I can help if:\n"
            "— you’ve wanted to start a blog for a while but keep getting stuck\n"
            "— you already post but don’t understand why it isn’t working\n"
            "— you don’t know what to post about or how to do it without overload\n\n"
            "Where do you want to start?"
        ),
        "gender_female": "Female",
        "gender_male": "Male",
        "gender_skip": "Prefer not to say",
        "start_want_blog": "🚀 I want to start a blog",
        "start_not_working": "🔍 I already post, but it’s not working",
        "start_no_idea": "🧭 I don’t know what to post about",
        "start_focus": "☀️ I need a focus for today",
        "help": (
            "I can help with:\n\n"
            "— starting a blog from scratch\n"
            "— figuring out your topic\n"
            "— building a simple 7-day plan\n"
            "— understanding why your blog is not working\n"
            "— finding today’s focus"
        ),
        "main_intro": (
            "Hi! ✨\n\n"
            "I’m Anna — an SMM mentor for starting and growing a blog on Instagram and Telegram.\n\n"
            "Choose where you want to start:"
        ),
        "menu_start_blog": "🚀 Start a blog from scratch",
        "menu_pick_direction": "🧭 Find topic and direction",
        "menu_plan": "📅 7-day plan",
        "menu_analyze": "🔍 Analyze what’s not working",
        "menu_checkin": "☀️ Today check-in",
        "menu_free_chat": "💬 Free chat",
        "menu_language": "🌐 Change language",
        "menu_home": "🏠 Home",
        "prestart_want_blog_text": (
            "Got it.\n\n"
            "Most often, the issue here is not laziness, but overload and lack of a clear starting point."
        ),
        "prestart_not_working_text": (
            "It looks like you're already doing something, but not seeing results yet."
        ),
        "prestart_no_idea_text": (
            "This is a normal place to be.\n\n"
            "Usually you don't need the perfect choice — you need a workable topic to start with."
        ),
        "prestart_focus_text": (
            "Okay.\n\n"
            "Then let’s not go into big plans, but into one clear step for today."
        ),
        "start_blog_screen": (
            "Let’s start calmly with the basics.\n\n"
            "Which situation feels closest to you right now?\n\n"
            "1. I want to start, but I can’t choose a topic\n"
            "2. I have a topic, but I don’t know how to run the blog\n"
            "3. I’m afraid to show up and publish\n"
            "4. I already started, but there’s no system"
        ),
        "pick_direction_screen": (
            "Let’s find a direction that actually fits you.\n\n"
            "Write 3 short things:\n\n"
            "1. What genuinely interests you\n"
            "2. What you already have experience in\n"
            "3. Who you’d like to talk to through your blog"
        ),
        "plan_screen": (
            "I’ll build you a simple and realistic 7-day plan.\n\n"
            "Before that, write:\n\n"
            "— what your blog is roughly about\n"
            "— where you want to start: Instagram, Telegram, or both\n"
            "— how much time you can realistically spend per day"
        ),
        "analyze_screen": (
            "Okay, let’s calmly look at where the bottleneck is.\n\n"
            "Write in 2–4 lines:\n\n"
            "— what your blog is about\n"
            "— what you’re already doing\n"
            "— what exactly isn’t working"
        ),
        "checkin_screen": (
            "Quick check-in ☀️\n\n"
            "What feels closest today?\n\n"
            "1. I did nothing today\n"
            "2. I did something, but it feels like too little\n"
            "3. I’m stuck and don’t know where to move next\n"
            "4. I want one clear focus for today"
        ),
        "free_chat_screen": (
            "You’re in free chat mode.\n\n"
            "You can write as you are: about your blog, topic, content, fear of showing up, or just your current block."
        ),
        "start_choice_invalid": "Please send only 1, 2, 3, or 4.",
        "start_choice_1": (
            "That’s a very real starting point.\n\n"
            "Answer these 2 things briefly:\n"
            "1. What could you genuinely talk about for a long time?\n"
            "2. What do you already have experience in?"
        ),
        "start_choice_2": (
            "That’s already a good base.\n\n"
            "Write:\n"
            "1. What your topic is\n"
            "2. What feels hardest right now"
        ),
        "start_choice_3": (
            "You’re not alone in this.\n\n"
            "Tell me briefly:\n"
            "1. What feels scariest\n"
            "2. Is writing easier for you right now than filming videos?"
        ),
        "start_choice_4": (
            "Got it.\n\n"
            "Then the issue is not starting — it’s that everything is running without a system.\n\n"
            "Write briefly:\n"
            "1. Where you currently post\n"
            "2. What breaks most"
        ),
        "openai_language_instruction": "Reply strictly in English.",
    },
    "de": {
        "lang_name": "Deutsch",
        "onboarding_hi": "Hi! / Привет! / Hallo!",
        "onboarding_gender": "Wie soll ich dich ansprechen?",
        "onboarding_country": "In welchem Land lebst du gerade?",
        "onboarding_done": (
            "Fertig ✨\n\n"
            "Ich bin Anna — SMM-Mentorin für den Start und Aufbau eines Blogs auf Instagram und Telegram.\n\n"
            "Ich helfe dir, wenn:\n"
            "— du schon lange starten willst, aber immer wieder feststeckst\n"
            "— du schon postest, aber nicht verstehst, warum es nicht funktioniert\n"
            "— du nicht weißt, worüber du schreiben sollst und wie du das ohne Überforderung aufbauen kannst\n\n"
            "Womit möchtest du anfangen?"
        ),
        "gender_female": "Frau",
        "gender_male": "Mann",
        "gender_skip": "Möchte ich nicht angeben",
        "start_want_blog": "🚀 Ich will einen Blog starten",
        "start_not_working": "🔍 Ich poste schon, aber es funktioniert nicht",
        "start_no_idea": "🧭 Ich weiß nicht, worüber ich schreiben soll",
        "start_focus": "☀️ Ich brauche einen Fokus für heute",
        "help": (
            "Ich kann dir helfen bei:\n\n"
            "— einem Blogstart von null\n"
            "— der Wahl deines Themas\n"
            "— einem einfachen 7-Tage-Plan\n"
            "— der Analyse, warum dein Blog nicht funktioniert\n"
            "— deinem Fokus für heute"
        ),
        "main_intro": (
            "Hallo! ✨\n\n"
            "Ich bin Anna — SMM-Mentorin für den Start und Aufbau eines Blogs auf Instagram und Telegram.\n\n"
            "Womit möchtest du anfangen?"
        ),
        "menu_start_blog": "🚀 Blog von null starten",
        "menu_pick_direction": "🧭 Thema und Richtung finden",
        "menu_plan": "📅 7-Tage-Plan",
        "menu_analyze": "🔍 Analysieren, was nicht funktioniert",
        "menu_checkin": "☀️ Check-in für heute",
        "menu_free_chat": "💬 Freier Chat",
        "menu_language": "🌐 Sprache ändern",
        "menu_home": "🏠 Start",
        "prestart_want_blog_text": (
            "Verstanden.\n\n"
            "Meist liegt das Problem hier nicht an Faulheit, sondern an Überforderung und einem unklaren Startpunkt."
        ),
        "prestart_not_working_text": (
            "Es sieht so aus, als würdest du schon etwas tun, aber noch keine Ergebnisse sehen."
        ),
        "prestart_no_idea_text": (
            "Das ist ein ganz normaler Punkt.\n\n"
            "Meist brauchst du nicht die perfekte Wahl, sondern ein funktionierendes Thema für den Start."
        ),
        "prestart_focus_text": (
            "Okay.\n\n"
            "Dann gehen wir nicht in große Pläne, sondern in einen klaren Schritt für heute."
        ),
        "start_blog_screen": (
            "Lass uns ruhig mit den Grundlagen anfangen.\n\n"
            "Welche Situation passt im Moment am ehesten zu dir?\n\n"
            "1. Ich will anfangen, kann aber kein Thema wählen\n"
            "2. Ich habe ein Thema, weiß aber nicht, wie ich den Blog führen soll\n"
            "3. Ich habe Angst, mich zu zeigen und zu posten\n"
            "4. Ich habe schon angefangen, aber ohne System"
        ),
        "pick_direction_screen": (
            "Lass uns eine Richtung finden, die wirklich zu dir passt.\n\n"
            "Schreib kurz 3 Dinge:\n\n"
            "1. Was dich wirklich interessiert\n"
            "2. Worin du schon Erfahrung hast\n"
            "3. Mit wem du über deinen Blog sprechen möchtest"
        ),
        "plan_screen": (
            "Ich erstelle dir einen einfachen und realistischen 7-Tage-Plan.\n\n"
            "Schreib davor bitte:\n\n"
            "— worum es in deinem Blog ungefähr gehen soll\n"
            "— wo du starten willst: Instagram, Telegram oder beides\n"
            "— wie viel Zeit du pro Tag realistisch investieren kannst"
        ),
        "analyze_screen": (
            "Okay, lass uns ruhig anschauen, wo gerade der Engpass liegt.\n\n"
            "Schreib in 2–4 Zeilen:\n\n"
            "— worum es in deinem Blog geht\n"
            "— was du bereits machst\n"
            "— was genau nicht funktioniert"
        ),
        "checkin_screen": (
            "Kurzer Check-in ☀️\n\n"
            "Was passt heute am ehesten?\n\n"
            "1. Ich habe heute nichts gemacht\n"
            "2. Ich habe etwas gemacht, aber es fühlt sich nach zu wenig an\n"
            "3. Ich stecke fest und weiß nicht, wie es weitergeht\n"
            "4. Ich möchte einen klaren Fokus für heute"
        ),
        "free_chat_screen": (
            "Du bist jetzt im freien Chat.\n\n"
            "Du kannst einfach schreiben: über deinen Blog, dein Thema, Content oder deinen Stillstand."
        ),
        "start_choice_invalid": "Bitte sende nur 1, 2, 3 oder 4.",
        "start_choice_1": (
            "Das ist ein sehr echter Startpunkt.\n\n"
            "Beantworte kurz 2 Dinge:\n"
            "1. Worüber könntest du wirklich lange sprechen?\n"
            "2. Worin hast du schon Erfahrung?"
        ),
        "start_choice_2": (
            "Das ist schon eine gute Basis.\n\n"
            "Schreib:\n"
            "1. Was dein Thema ist\n"
            "2. Was sich gerade am schwierigsten anfühlt"
        ),
        "start_choice_3": (
            "Du bist damit nicht allein.\n\n"
            "Sag mir kurz:\n"
            "1. Was dir am meisten Angst macht\n"
            "2. Fällt dir Schreiben gerade leichter als Videos aufzunehmen?"
        ),
        "start_choice_4": (
            "Verstanden.\n\n"
            "Dann liegt das Problem nicht am Anfang, sondern daran, dass alles ohne System läuft.\n\n"
            "Schreib kurz:\n"
            "1. Wo du gerade postest\n"
            "2. Was am meisten bricht"
        ),
        "openai_language_instruction": "Antworte ausschließlich auf Deutsch.",
    },
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
- если смысл уже понятен, не уточняешь очевидное, а делаешь разумное предположение и идёшь дальше
- не делай полотно без необходимости

Формат:
- только plain text
- без markdown
- абзацы короткие
- списки короткие и полезные

Границы:
- ты помогаешь по темам: блог, контент, позиционирование, Instagram, Telegram, личный бренд, страх проявления, старт, система, простые планы действий

Цель:
пользователь должен чувствовать, что с ним говорит умный, спокойный, современный и тёплый SMM-ментор.
"""

def normalize_lang(lang_code: str | None) -> str:
    if not lang_code:
        return "en"
    base = lang_code.split("-")[0].lower()
    if base in SUPPORTED_LANGS:
        return base
    return "en"

def tr(lang: str, key: str) -> str:
    return TRANSLATIONS[normalize_lang(lang)][key]

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

    if sslmode is None:
        return psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    return psycopg2.connect(f"{db_url}?sslmode={sslmode}", cursor_factory=RealDictCursor)

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
        gender TEXT,
        country_raw TEXT,
        onboarding_completed BOOLEAN DEFAULT FALSE,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS language_code TEXT""")
    cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS gender TEXT""")
    cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS country_raw TEXT""")
    cur.execute("""ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT FALSE""")

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
    try:
        telegram_user = update.effective_user
        now = datetime.now(timezone.utc).isoformat()
        detected_lang = normalize_lang(getattr(telegram_user, "language_code", None))

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
        INSERT INTO users (
            telegram_user_id,
            username,
            first_name,
            language_code,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (telegram_user_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
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
    except Exception as e:
        logger.exception("save_user failed: %s", e)

def get_user_profile(telegram_user_id: int) -> dict:
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
        SELECT telegram_user_id, language_code, gender, country_raw, onboarding_completed
        FROM users
        WHERE telegram_user_id = %s
        """, (telegram_user_id,))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            return dict(row)

    except Exception as e:
        logger.exception("get_user_profile failed: %s", e)

    return {
        "telegram_user_id": telegram_user_id,
        "language_code": "en",
        "gender": None,
        "country_raw": None,
        "onboarding_completed": False,
    }

def get_user_language(telegram_user_id: int) -> str:
    profile = get_user_profile(telegram_user_id)
    return normalize_lang(profile.get("language_code"))

def set_user_language(telegram_user_id: int, lang: str):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
        UPDATE users
        SET language_code = %s,
            updated_at = %s
        WHERE telegram_user_id = %s
        """, (
            normalize_lang(lang),
            datetime.now(timezone.utc).isoformat(),
            telegram_user_id
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("set_user_language failed: %s", e)

def set_user_gender(telegram_user_id: int, gender: str):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
        UPDATE users
        SET gender = %s,
            updated_at = %s
        WHERE telegram_user_id = %s
        """, (
            gender,
            datetime.now(timezone.utc).isoformat(),
            telegram_user_id
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("set_user_gender failed: %s", e)

def set_user_country(telegram_user_id: int, country_raw: str):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
        UPDATE users
        SET country_raw = %s,
            updated_at = %s
        WHERE telegram_user_id = %s
        """, (
            country_raw.strip(),
            datetime.now(timezone.utc).isoformat(),
            telegram_user_id
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("set_user_country failed: %s", e)

def set_onboarding_completed(telegram_user_id: int, completed: bool = True):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
        UPDATE users
        SET onboarding_completed = %s,
            updated_at = %s
        WHERE telegram_user_id = %s
        """, (
            completed,
            datetime.now(timezone.utc).isoformat(),
            telegram_user_id
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("set_onboarding_completed failed: %s", e)

def is_onboarding_completed(telegram_user_id: int) -> bool:
    profile = get_user_profile(telegram_user_id)
    return bool(profile.get("onboarding_completed"))

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

def build_system_prompt(lang: str) -> str:
    return BASE_SYSTEM_PROMPT + "\n\n" + tr(lang, "openai_language_instruction")

def call_openai(prompt: str, lang: str, instructions: str | None = None) -> str:
    try:
        final_instructions = instructions or build_system_prompt(lang)
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
        return fallback[normalize_lang(lang)]

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
- максимум 3 короткие строки
- включай только то, что поможет в будущих ответах
- если новых устойчивых фактов нет, верни предыдущую summary почти без изменений
- только plain text

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

def get_user_context_block(telegram_user_id: int, user_text: str):
    memory = get_user_memory(telegram_user_id)
    recent_messages = get_recent_messages(telegram_user_id, limit=4)

    history_block = ""
    for row in recent_messages:
        history_block += f"{row['role']}: {row['text']}\n"

    return f"""
Память о пользователе:
{memory if memory else "Пока нет сохранённой памяти."}

Недавние сообщения:
{history_block if history_block else "Нет истории."}

Новое сообщение пользователя:
{user_text}
"""

def build_context_prompt(telegram_user_id: int, user_text: str):
    return f"""
Ниже контекст пользователя для ответа.

{get_user_context_block(telegram_user_id, user_text)}

Ответь как Anna — тёплый SMM-ментор по правилам системы.
"""

def classify_request(user_text: str) -> str:
    text = user_text.lower()

    topic_keywords = ["о чем вести", "о чём вести", "тема блога", "direction", "blog topic", "thema"]
    content_keywords = ["идеи", "контент", "что писать", "content ideas", "content", "hooks"]
    plan_keywords = ["план на 7 дней", "7 day plan", "7-tage-plan", "на неделю"]
    diagnose_keywords = ["не работает", "нет охватов", "not working", "keine reichweite"]

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
    prompt = f"""
{get_user_context_block(telegram_user_id, user_text)}

Задача:
помоги пользователю понять, о чём ему вести блог.

Дай 2-3 сильных направления максимум.
Объясни, почему именно это ему подходит.
В конце скажи, что бы ты выбрала на его месте.
"""
    return call_openai(prompt, lang=lang)

def generate_content_ideas_response(telegram_user_id: int, user_text: str) -> str:
    lang = get_user_language(telegram_user_id)
    prompt = f"""
{get_user_context_block(telegram_user_id, user_text)}

Задача:
дать пользователю качественные идеи контента.

Предложи 5 сильных идей максимум.
Для каждой идеи укажи:
1. саму идею
2. сильный угол подачи
3. пример хука
4. лучший формат
"""
    return call_openai(prompt, lang=lang)

def generate_7_day_plan_response(telegram_user_id: int, user_text: str) -> str:
    lang = get_user_language(telegram_user_id)
    prompt = f"""
{get_user_context_block(telegram_user_id, user_text)}

Задача:
сделать реалистичный план на 7 дней.

Каждый день = один основной фокус.
Для каждого дня укажи:
1. фокус дня
2. что конкретно сделать
3. результат к концу дня
"""
    return call_openai(prompt, lang=lang)

def generate_blog_diagnosis_response(telegram_user_id: int, user_text: str) -> str:
    lang = get_user_language(telegram_user_id)
    prompt = f"""
{get_user_context_block(telegram_user_id, user_text)}

Задача:
помочь пользователю понять, почему его блог или контент не работает.

Выдели 1 главную проблему и максимум 1 дополнительную.
Потом дай один понятный следующий шаг.
"""
    return call_openai(prompt, lang=lang)

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
    return call_openai(build_context_prompt(telegram_user_id, user_text), lang=lang)

def get_language_keyboard():
    keyboard = [[
        InlineKeyboardButton("Русский", callback_data="lang_ru"),
        InlineKeyboardButton("English", callback_data="lang_en"),
        InlineKeyboardButton("Deutsch", callback_data="lang_de"),
    ]]
    return InlineKeyboardMarkup(keyboard)

def get_gender_keyboard(lang: str):
    keyboard = [
        [InlineKeyboardButton(tr(lang, "gender_female"), callback_data="gender_female")],
        [InlineKeyboardButton(tr(lang, "gender_male"), callback_data="gender_male")],
        [InlineKeyboardButton(tr(lang, "gender_skip"), callback_data="gender_skip")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_onboarding_start_menu(lang: str):
    keyboard = [
        [InlineKeyboardButton(tr(lang, "start_want_blog"), callback_data="prestart_want_blog")],
        [InlineKeyboardButton(tr(lang, "start_not_working"), callback_data="prestart_not_working")],
        [InlineKeyboardButton(tr(lang, "start_no_idea"), callback_data="prestart_no_idea")],
        [InlineKeyboardButton(tr(lang, "start_focus"), callback_data="prestart_focus")],
    ]
    return InlineKeyboardMarkup(keyboard)

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

        message = query.message
        for chunk in chunks[1:-1]:
            await message.reply_text(chunk)

        if len(chunks) > 1:
            await message.reply_text(chunks[-1], reply_markup=reply_markup)

    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.info("Skipped edit: message is not modified")
        else:
            logger.exception("BadRequest on edit_message_text: %s", e)
    except TelegramError as e:
        logger.exception("edit_message_text failed: %s", e)

async def send_language_picker(message_obj):
    await safe_reply(message_obj, "Hi! / Привет! / Hallo!", reply_markup=get_language_keyboard())

async def send_gender_picker(query, lang: str):
    await safe_edit(query, tr(lang, "onboarding_gender"), reply_markup=get_gender_keyboard(lang))

async def send_country_request(query, lang: str):
    await safe_edit(query, tr(lang, "onboarding_country"))

async def send_post_onboarding_welcome(message_obj, lang: str):
    await safe_reply(
        message_obj,
        tr(lang, "onboarding_done"),
        reply_markup=get_onboarding_start_menu(lang)
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    user_id = update.effective_user.id

    if is_onboarding_completed(user_id):
        lang = get_user_language(user_id)
        context.user_data.clear()
        await safe_reply(update.message, tr(lang, "main_intro"), reply_markup=get_main_menu(lang))
        return

    context.user_data.clear()
    context.user_data["awaiting_language_selection"] = True
    await send_language_picker(update.message)

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
    context.user_data["step"] = "awaiting_pick_direction_answer"
    await safe_edit(query, tr(lang, "pick_direction_screen"), reply_markup=get_home_menu(lang))

async def show_plan_7_days_screen(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data["mode"] = "plan_7_days"
    context.user_data["step"] = "awaiting_plan_7_days_answer"
    await safe_edit(query, tr(lang, "plan_screen"), reply_markup=get_home_menu(lang))

async def show_analyze_blog_screen(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data["mode"] = "analyze_blog"
    context.user_data["step"] = "awaiting_analyze_blog_answer"
    await safe_edit(query, tr(lang, "analyze_screen"), reply_markup=get_home_menu(lang))

async def show_daily_checkin_screen(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data["mode"] = "daily_checkin"
    context.user_data["step"] = "awaiting_daily_checkin_answer"
    await safe_edit(query, tr(lang, "checkin_screen"), reply_markup=get_home_menu(lang))

async def show_free_chat_screen(query, context: ContextTypes.DEFAULT_TYPE):
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    context.user_data.clear()
    await safe_edit(query, tr(lang, "free_chat_screen"), reply_markup=get_home_menu(lang))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except TelegramError as e:
        logger.exception("callback answer failed: %s", e)

    user_id = query.from_user.id

    if query.data.startswith("lang_"):
        selected_lang = normalize_lang(query.data.replace("lang_", ""))
        save_user(update)
        set_user_language(user_id, selected_lang)
        context.user_data.clear()
        context.user_data["awaiting_gender_selection"] = True
        await send_gender_picker(query, selected_lang)
        return

    if query.data.startswith("gender_"):
        lang = get_user_language(user_id)

        if query.data == "gender_female":
            set_user_gender(user_id, "female")
        elif query.data == "gender_male":
            set_user_gender(user_id, "male")
        else:
            set_user_gender(user_id, "unspecified")

        context.user_data.clear()
        context.user_data["awaiting_country_input"] = True
        await send_country_request(query, lang)
        return

    if query.data == "prestart_want_blog":
        lang = get_user_language(user_id)
        await safe_edit(query, tr(lang, "prestart_want_blog_text"), reply_markup=get_main_menu(lang))
        return

    if query.data == "prestart_not_working":
        lang = get_user_language(user_id)
        await safe_edit(query, tr(lang, "prestart_not_working_text"), reply_markup=get_main_menu(lang))
        return

    if query.data == "prestart_no_idea":
        lang = get_user_language(user_id)
        await safe_edit(query, tr(lang, "prestart_no_idea_text"), reply_markup=get_main_menu(lang))
        return

    if query.data == "prestart_focus":
        lang = get_user_language(user_id)
        await safe_edit(query, tr(lang, "prestart_focus_text"), reply_markup=get_main_menu(lang))
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
        context.user_data.clear()
        context.user_data["awaiting_language_selection"] = True
        await safe_edit(query, "Hi! / Привет! / Hallo!", reply_markup=get_language_keyboard())
    elif query.data == "main_menu":
        await show_main_menu(query, context)

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
        if choice == "2":
            context.user_data["step"] = "awaiting_answer_for_choice_2"
            await safe_reply(update.message, tr(lang, "start_choice_2"), reply_markup=get_home_menu(lang))
            return
        if choice == "3":
            context.user_data["step"] = "awaiting_answer_for_choice_3"
            await safe_reply(update.message, tr(lang, "start_choice_3"), reply_markup=get_home_menu(lang))
            return
        if choice == "4":
            context.user_data["step"] = "awaiting_answer_for_choice_4"
            await safe_reply(update.message, tr(lang, "start_choice_4"), reply_markup=get_home_menu(lang))
            return

        await safe_reply(update.message, tr(lang, "start_choice_invalid"), reply_markup=get_home_menu(lang))
        return

    answer = generate_general_response(user_id, user_text)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_pick_direction_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    answer = generate_blog_direction_response(user_id, user_text)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_plan_7_days_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    answer = generate_7_day_plan_response(user_id, user_text)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_analyze_blog_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    answer = generate_blog_diagnosis_response(user_id, user_text)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_daily_checkin_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    prompt = f"""
{get_user_context_block(user_id, user_text)}

Задача:
пользователь прислал ежедневный check-in.

Дай ответ так, чтобы:
- сначала было ощущение поддержки
- потом появилась ясность
- потом один фокус на сегодня
- отвечай компактно
"""
    answer = call_openai(prompt, lang=lang)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)
    context.user_data.clear()

async def handle_free_chat(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    answer = generate_general_response(user_id, user_text)
    await safe_reply(update.message, answer, reply_markup=get_home_menu(lang))
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", answer)
    maybe_update_memory(user_id, user_text, answer)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    user_id = update.effective_user.id
    user_text = update.message.text.strip()
    mode = context.user_data.get("mode")

    if context.user_data.get("awaiting_country_input"):
        lang = get_user_language(user_id)
        set_user_country(user_id, user_text)
        set_onboarding_completed(user_id, True)
        context.user_data.clear()
        await send_post_onboarding_welcome(update.message, lang)
        return

    if context.user_data.get("awaiting_language_selection"):
        await send_language_picker(update.message)
        return

    if context.user_data.get("awaiting_gender_selection"):
        lang = get_user_language(user_id)
        await safe_reply(update.message, tr(lang, "onboarding_gender"), reply_markup=get_gender_keyboard(lang))
        return

    if not is_onboarding_completed(user_id):
        context.user_data.clear()
        context.user_data["awaiting_language_selection"] = True
        await send_language_picker(update.message)
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