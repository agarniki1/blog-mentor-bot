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

TRANSLATIONS = {
    "ru": {
        "lang_name": "Русский",
        "choose_language": "Привет! Выбери язык, на котором тебе удобно общаться:",
        "language_saved": "Готово — теперь бот будет говорить с тобой на русском.",
        "main_intro": (
            "Привет! ✨\n\n"
            "Я Anna — SMM-ментор по запуску и ведению блога в Instagram и Telegram.\n\n"
            "Я рядом, если:\n"
            "— давно хочешь начать блог, но всё время что-то стопорит\n"
            "— уже ведёшь, но не понимаешь, почему не идёт\n"
            "— не знаешь, о чём писать и как сделать всё без перегруза\n\n"
            "Без воды, без давления и без ощущения, что с тобой что-то не так.\n\n"
            "Выбери, с чего хочешь начать:"
        ),
        "help": (
            "Я могу помочь тебе с таким:\n\n"
            "— начать блог с нуля\n"
            "— понять, о чём тебе вести блог\n"
            "— собрать простой план на 7 дней\n"
            "— разобраться, почему блог не работает\n"
            "— понять, что делать сегодня, если всё встало\n\n"
            "Если не хочется выбирать сценарий, просто напиши мне как есть.\n"
            "Коротко, своими словами — этого достаточно."
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
            "Давай попробуем найти направление, которое тебе правда подойдёт.\n\n"
            "Напиши коротко 3 вещи:\n\n"
            "1. Что тебе по-настоящему интересно\n"
            "2. В чём у тебя уже есть опыт или насмотренность\n"
            "3. С кем тебе хотелось бы говорить через блог\n\n"
            "Можно коротко и без красивых формулировок."
        ),
        "plan_screen": (
            "Соберу тебе простой и живой план на 7 дней — без перегруза и лишнего.\n\n"
            "Перед этим напиши:\n\n"
            "— о чём ты примерно хочешь вести блог\n"
            "— где тебе ближе начать: Instagram, Telegram или оба\n"
            "— сколько времени ты реально готов(а) уделять в день\n\n"
            "Можно ответить совсем коротко."
        ),
        "analyze_screen": (
            "Окей, давай спокойно посмотрим, где сейчас затык.\n\n"
            "Напиши в 2–4 строках:\n\n"
            "— о чём у тебя блог\n"
            "— что ты уже делаешь\n"
            "— что именно не работает: идеи, регулярность, охваты, вовлечённость или что-то ещё\n\n"
            "Я помогу увидеть, что тебя сейчас тормозит сильнее всего."
        ),
        "checkin_screen": (
            "Быстрый check-in ☀️\n\n"
            "Что сегодня ближе всего?\n\n"
            "1. Ничего не сделал(а)\n"
            "2. Что-то сделал(а), но как будто мало\n"
            "3. Застрял(а) и не понимаю, куда двигаться\n"
            "4. Хочу понять, какой у меня один фокус на сегодня\n\n"
            "Напиши цифру или пару слов про своё состояние."
        ),
        "free_chat_screen": (
            "Ты в свободном чате.\n\n"
            "Можешь написать как есть:\n"
            "про блог, тему, контент, страх проявляться, Instagram, Telegram или просто про ступор.\n\n"
            "Без правильных формулировок.\n"
            "Просто по-человечески."
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
            "2. Что сейчас сложнее всего: вести регулярно, придумывать контент или понимать, что вообще сработает"
        ),
        "start_choice_3": (
            "Ты не один(одна) в этом.\n\n"
            "Скажи коротко:\n"
            "1. Что страшнее всего — камера, мнение людей или ощущение кринжа\n"
            "2. Тебе сейчас легче писать, чем снимать видео?"
        ),
        "start_choice_4": (
            "Поняла.\n\n"
            "Тогда проблема не в старте, а в том, что всё держится без системы.\n\n"
            "Напиши коротко:\n"
            "1. Где ты сейчас ведёшь блог\n"
            "2. Что у тебя ломается сильнее всего — регулярность, идеи, мотивация или понимание стратегии"
        ),
        "openai_language_instruction": "Отвечай строго на русском языке.",
    },
    "en": {
        "lang_name": "English",
        "choose_language": "Hi! Choose the language you want to use with the bot:",
        "language_saved": "Done — the bot will now talk to you in English.",
        "main_intro": (
            "Hi! ✨\n\n"
            "I’m Anna — an SMM mentor for starting and growing a blog on Instagram and Telegram.\n\n"
            "I’m here if:\n"
            "— you’ve wanted to start a blog for a while but keep getting stuck\n"
            "— you already post but don’t understand why it isn’t working\n"
            "— you don’t know what to post about or how to do it without overload\n\n"
            "No fluff, no pressure, and no feeling that something is wrong with you.\n\n"
            "Choose where you want to start:"
        ),
        "help": (
            "I can help with:\n\n"
            "— starting a blog from scratch\n"
            "— figuring out your blog topic and direction\n"
            "— building a simple 7-day plan\n"
            "— understanding why your blog is not working\n"
            "— deciding what to focus on today if you feel stuck\n\n"
            "If you don’t want to choose a scenario, just write to me in your own words.\n"
            "A short message is enough."
        ),
        "menu_start_blog": "🚀 Start a blog from scratch",
        "menu_pick_direction": "🧭 Find topic and direction",
        "menu_plan": "📅 7-day plan",
        "menu_analyze": "🔍 Analyze what’s not working",
        "menu_checkin": "☀️ Today check-in",
        "menu_free_chat": "💬 Free chat",
        "menu_language": "🌐 Change language",
        "menu_home": "🏠 Home",
        "start_blog_screen": (
            "Let’s start calmly with the basics.\n\n"
            "Which situation feels closest to you right now?\n\n"
            "1. I want to start, but I can’t choose a topic\n"
            "2. I have a topic, but I don’t know how to run the blog\n"
            "3. I’m afraid to show up and publish\n"
            "4. I already started, but there’s no system\n\n"
            "Send the number and we’ll move on."
        ),
        "pick_direction_screen": (
            "Let’s find a direction that actually fits you.\n\n"
            "Write 3 short things:\n\n"
            "1. What genuinely interests you\n"
            "2. What you already have experience or strong exposure in\n"
            "3. Who you’d like to talk to through your blog\n\n"
            "Short and simple is completely fine."
        ),
        "plan_screen": (
            "I’ll build you a simple and realistic 7-day plan — without overload.\n\n"
            "Before that, write:\n\n"
            "— what you roughly want your blog to be about\n"
            "— where you want to start: Instagram, Telegram, or both\n"
            "— how much time you can realistically spend per day\n\n"
            "A short answer is enough."
        ),
        "analyze_screen": (
            "Okay, let’s calmly look at where the bottleneck is.\n\n"
            "Write in 2–4 lines:\n\n"
            "— what your blog is about\n"
            "— what you’re already doing\n"
            "— what exactly isn’t working: ideas, consistency, reach, engagement, or something else\n\n"
            "I’ll help you see what is slowing you down most."
        ),
        "checkin_screen": (
            "Quick check-in ☀️\n\n"
            "What feels closest today?\n\n"
            "1. I did nothing today\n"
            "2. I did something, but it feels like too little\n"
            "3. I’m stuck and don’t understand where to move next\n"
            "4. I want one clear focus for today\n\n"
            "Send a number or a couple of words about how you feel."
        ),
        "free_chat_screen": (
            "You’re in free chat mode.\n\n"
            "You can write as you are:\n"
            "about your blog, topic, content, fear of showing up, Instagram, Telegram, or just your current block.\n\n"
            "No perfect wording needed.\n"
            "Just write like a human."
        ),
        "start_choice_invalid": "Please send only 1, 2, 3, or 4.",
        "start_choice_1": (
            "That’s a very real starting point.\n\n"
            "Answer these 2 things briefly:\n"
            "1. What could you genuinely talk about for a long time?\n"
            "2. What do you already have experience, a journey, or strong perspective in?"
        ),
        "start_choice_2": (
            "That’s already a good base.\n\n"
            "Write:\n"
            "1. What your topic is\n"
            "2. What feels hardest right now: posting consistently, coming up with content, or understanding what can actually work"
        ),
        "start_choice_3": (
            "You’re not alone in this.\n\n"
            "Tell me briefly:\n"
            "1. What feels scariest — camera, people’s opinions, or the feeling of cringe\n"
            "2. Is writing easier for you right now than filming videos?"
        ),
        "start_choice_4": (
            "Got it.\n\n"
            "Then the issue is not starting — it’s that everything is running without a system.\n\n"
            "Write briefly:\n"
            "1. Where you currently post\n"
            "2. What breaks most: consistency, ideas, motivation, or understanding strategy"
        ),
        "openai_language_instruction": "Reply strictly in English.",
    },
    "de": {
        "lang_name": "Deutsch",
        "choose_language": "Hallo! Wähle die Sprache, in der du mit dem Bot sprechen möchtest:",
        "language_saved": "Fertig — der Bot spricht jetzt mit dir auf Deutsch.",
        "main_intro": (
            "Hallo! ✨\n\n"
            "Ich bin Anna — eine SMM-Mentorin für den Start und Aufbau eines Blogs auf Instagram und Telegram.\n\n"
            "Ich bin für dich da, wenn:\n"
            "— du schon lange einen Blog starten willst, aber immer wieder ins Stocken gerätst\n"
            "— du schon postest, aber nicht verstehst, warum es nicht funktioniert\n"
            "— du nicht weißt, worüber du posten sollst oder wie du ohne Überforderung anfangen kannst\n\n"
            "Ohne leere Worte, ohne Druck und ohne das Gefühl, dass etwas mit dir nicht stimmt.\n\n"
            "Wähle, womit du anfangen möchtest:"
        ),
        "help": (
            "Ich kann dir helfen bei:\n\n"
            "— einem Blogstart von null\n"
            "— der Wahl deines Themas und deiner Richtung\n"
            "— einem einfachen 7-Tage-Plan\n"
            "— der Analyse, warum dein Blog nicht funktioniert\n"
            "— der Frage, worauf du dich heute konzentrieren solltest, wenn du feststeckst\n\n"
            "Wenn du kein Szenario auswählen willst, schreib mir einfach frei heraus.\n"
            "Eine kurze Nachricht reicht."
        ),
        "menu_start_blog": "🚀 Blog von null starten",
        "menu_pick_direction": "🧭 Thema und Richtung finden",
        "menu_plan": "📅 7-Tage-Plan",
        "menu_analyze": "🔍 Analysieren, was nicht funktioniert",
        "menu_checkin": "☀️ Check-in für heute",
        "menu_free_chat": "💬 Freier Chat",
        "menu_language": "🌐 Sprache ändern",
        "menu_home": "🏠 Start",
        "start_blog_screen": (
            "Lass uns ruhig mit den Grundlagen anfangen.\n\n"
            "Welche Situation passt im Moment am ehesten zu dir?\n\n"
            "1. Ich will anfangen, kann aber kein Thema wählen\n"
            "2. Ich habe ein Thema, weiß aber nicht, wie ich den Blog führen soll\n"
            "3. Ich habe Angst, mich zu zeigen und zu posten\n"
            "4. Ich habe schon angefangen, aber ohne System\n\n"
            "Schreib die Zahl, dann gehen wir weiter."
        ),
        "pick_direction_screen": (
            "Lass uns eine Richtung finden, die wirklich zu dir passt.\n\n"
            "Schreib kurz 3 Dinge:\n\n"
            "1. Was dich wirklich interessiert\n"
            "2. Worin du schon Erfahrung oder viel Gespür hast\n"
            "3. Mit wem du über deinen Blog sprechen möchtest\n\n"
            "Kurz und einfach reicht völlig."
        ),
        "plan_screen": (
            "Ich erstelle dir einen einfachen und realistischen 7-Tage-Plan — ohne Überforderung.\n\n"
            "Schreib davor bitte:\n\n"
            "— worum es in deinem Blog ungefähr gehen soll\n"
            "— wo du starten willst: Instagram, Telegram oder beides\n"
            "— wie viel Zeit du pro Tag realistisch investieren kannst\n\n"
            "Eine kurze Antwort reicht."
        ),
        "analyze_screen": (
            "Okay, lass uns ruhig anschauen, wo gerade der Engpass liegt.\n\n"
            "Schreib in 2–4 Zeilen:\n\n"
            "— worum es in deinem Blog geht\n"
            "— was du bereits machst\n"
            "— was genau nicht funktioniert: Ideen, Regelmäßigkeit, Reichweite, Engagement oder etwas anderes\n\n"
            "Ich helfe dir zu sehen, was dich gerade am stärksten bremst."
        ),
        "checkin_screen": (
            "Kurzer Check-in ☀️\n\n"
            "Was passt heute am ehesten?\n\n"
            "1. Ich habe heute nichts gemacht\n"
            "2. Ich habe etwas gemacht, aber es fühlt sich nach zu wenig an\n"
            "3. Ich stecke fest und weiß nicht, wie es weitergeht\n"
            "4. Ich möchte einen klaren Fokus für heute\n\n"
            "Schreib eine Zahl oder ein paar Worte zu deinem Zustand."
        ),
        "free_chat_screen": (
            "Du bist jetzt im freien Chat.\n\n"
            "Du kannst einfach so schreiben, wie es dir gerade kommt:\n"
            "über deinen Blog, dein Thema, Content, die Angst sichtbar zu werden, Instagram, Telegram oder einfach über deinen Stillstand.\n\n"
            "Keine perfekten Formulierungen nötig.\n"
            "Schreib einfach menschlich."
        ),
        "start_choice_invalid": "Bitte sende nur 1, 2, 3 oder 4.",
        "start_choice_1": (
            "Das ist ein sehr echter Startpunkt.\n\n"
            "Beantworte kurz 2 Dinge:\n"
            "1. Worüber könntest du wirklich lange sprechen?\n"
            "2. Worin hast du schon Erfahrung, einen Weg oder eine starke Perspektive?"
        ),
        "start_choice_2": (
            "Das ist schon eine gute Basis.\n\n"
            "Schreib:\n"
            "1. Was dein Thema ist\n"
            "2. Was sich gerade am schwierigsten anfühlt: regelmäßig posten, Content-Ideen finden oder verstehen, was wirklich funktionieren kann"
        ),
        "start_choice_3": (
            "Du bist damit nicht allein.\n\n"
            "Sag mir kurz:\n"
            "1. Was dir am meisten Angst macht — Kamera, Meinungen anderer oder das Gefühl von Fremdscham\n"
            "2. Fällt dir Schreiben gerade leichter als Videos aufzunehmen?"
        ),
        "start_choice_4": (
            "Verstanden.\n\n"
            "Dann liegt das Problem nicht am Anfang, sondern daran, dass alles ohne System läuft.\n\n"
            "Schreib kurz:\n"
            "1. Wo du gerade postest\n"
            "2. Was am meisten bricht: Regelmäßigkeit, Ideen, Motivation oder Strategieverständnis"
        ),
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
- если смысл уже понятен, не уточняешь очевидное, а делаешь разумное предположение и идёшь дальше
- не играешь в двусмысленности слов, если смысл пользователя очевиден
- не задаёшь глупые, буквальные или абсурдные уточняющие вопросы
- не просишь переписать сообщение, если смысл уже можно понять
- не делаешь больше одного уточнения подряд
- создаёшь ощущение, что рядом живой, умный и поддерживающий ментор
- не растягивай ответ без необходимости
- предпочитай 2-3 сильных варианта вместо длинного списка
- обычно держи ответ компактным и не делай полотно без причины

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

def tr(lang: str, key: str) -> str:
    lang = normalize_lang(lang)
    return TRANSLATIONS[lang][key]

def normalize_lang(lang_code: str | None) -> str:
    if not lang_code:
        return "en"
    base = lang_code.split("-")[0].lower()
    if base in SUPPORTED_LANGS:
        return base
    return "en"

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
    try:
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
    except Exception as e:
        logger.exception("Postgres connection error: %s", e)
        raise

def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_user_id BIGINT UNIQUE,
            username TEXT,
            first_name TEXT,
            language_code TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """)

        cur.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS language_code TEXT
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
    except Exception as e:
        logger.exception("Database init failed: %s", e)
        raise

def save_user(update: Update):
    try:
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

def get_user_language(telegram_user_id: int) -> str:
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
        SELECT language_code
        FROM users
        WHERE telegram_user_id = %s
        """, (telegram_user_id,))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if row and row["language_code"]:
            return normalize_lang(row["language_code"])
        return "en"
    except Exception as e:
        logger.exception("get_user_language failed: %s", e)
        return "en"

def set_user_language(telegram_user_id: int, lang: str):
    try:
        lang = normalize_lang(lang)
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
        UPDATE users
        SET language_code = %s,
            updated_at = %s
        WHERE telegram_user_id = %s
        """, (
            lang,
            datetime.now(timezone.utc).isoformat(),
            telegram_user_id
        ))

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("set_user_language failed: %s", e)

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

        if row:
            return row["summary"]
        return ""
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
    lang = normalize_lang(lang)
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
        instructions="Ты помогаешь сжато обновлять память о пользователе. Верни summary на том же языке, на котором она уже ведётся, или на языке пользователя."
    )

    if summary:
        update_user_memory(telegram_user_id, summary)

def build_context_prompt(telegram_user_id: int, user_text: str):
    memory = get_user_memory(telegram_user_id)
    recent_messages = get_recent_messages(telegram_user_id, limit=4)

    history_block = ""
    for row in recent_messages:
        history_block += f"{row['role']}: {row['text']}\n"

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

def classify_request(user_text: str) -> str:
    text = user_text.lower()

    topic_keywords = [
        "о чем вести", "о чём вести", "тема блога", "направление", "ниша",
        "какую тему", "выбрать тему", "определить тему", "направление блога",
        "what should i blog about", "blog topic", "choose topic", "direction",
        "worüber bloggen", "thema wählen", "richtung"
    ]
    content_keywords = [
        "идеи", "контент", "рубрики", "что снимать", "что писать",
        "сценарии", "рилс", "reels", "сторис", "посты", "контент-план",
        "контент план", "хуки", "темы постов",
        "content ideas", "content plan", "hooks", "post ideas",
        "content ideen", "contentplan", "reels", "hooks"
    ]
    plan_keywords = [
        "план на 7 дней", "7 дней", "на неделю", "план запуска",
        "что делать по дням", "план на неделю",
        "7 day plan", "weekly plan",
        "7-tage-plan", "wochenplan"
    ]
    diagnose_keywords = [
        "не работает", "нет охватов", "не идет", "не идёт", "мало просмотров",
        "нет отклика", "нет продаж", "почему блог", "не растет", "не растёт",
        "not working", "low reach", "no engagement", "why blog",
        "funktioniert nicht", "keine reichweite", "wenig engagement"
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
    context_block = get_user_context_block(telegram_user_id, user_text)

    prompt = f"""
{context_block}

Задача:
помоги пользователю понять, о чём ему вести блог.

Требования к качеству:
- предложи 2-3 сильных направления максимум
- не давай банальные темы
- не пиши абстрактно вроде "лайфстайл", "делись опытом", "экспертный блог" без расшифровки
- добавляй конкретику: что именно человек может говорить, для кого, через какие углы
- объясни, почему именно это направление подходит пользователю
- помоги сузить выбор
- не растягивай ответ

Формат ответа:
1. Коротко отрази, что ты поняла про человека
2. Дай 2-3 направления
3. Для каждого — в чём суть и почему это может сработать
4. В конце — что я бы выбрала на его месте и почему
"""
    return call_openai(prompt, lang=lang)

def generate_content_ideas_response(telegram_user_id: int, user_text: str) -> str:
    lang = get_user_language(telegram_user_id)
    context_block = get_user_context_block(telegram_user_id, user_text)

    prompt = f"""
{context_block}

Задача:
дать пользователю качественные идеи контента.

Требования к качеству:
- предложи 5 сильных идей максимум
- не давай пустые идеи вроде "расскажи свою историю" без конкретики
- каждая идея должна быть пригодна для реального поста, reels, stories или telegram-поста
- для каждой идеи укажи:
  1. саму идею
  2. сильный угол подачи
  3. пример хука или захода
  4. какой формат лучше
- идеи должны быть современными, конкретными и usable
- не растягивай ответ

Формат ответа:
- коротко скажи, на что я бы делала упор в контенте
- потом дай 5 идей списком
- в конце предложи, какие 2 идеи лучше взять первыми
"""
    return call_openai(prompt, lang=lang)

def generate_7_day_plan_response(telegram_user_id: int, user_text: str) -> str:
    lang = get_user_language(telegram_user_id)
    context_block = get_user_context_block(telegram_user_id, user_text)

    prompt = f"""
{context_block}

Задача:
сделать сильный, реалистичный и небанальный план на 7 дней.

Требования:
- каждый день = один основной фокус
- для каждого дня укажи:
  1. фокус дня
  2. что конкретно сделать
  3. какой результат должен получиться к концу дня
- не пиши пустые советы вроде "определи ЦА" без расшифровки
- план должен быть выполнимым без команды и без перегруза
- если тема уже есть, двигай человека дальше, а не возвращай назад
- не растягивай ответ

Формат:
- короткое вступление
- потом дни 1-7
- в конце: на чём не надо зацикливаться в эту неделю
"""
    return call_openai(prompt, lang=lang)

def generate_blog_diagnosis_response(telegram_user_id: int, user_text: str) -> str:
    lang = get_user_language(telegram_user_id)
    context_block = get_user_context_block(telegram_user_id, user_text)

    prompt = f"""
{context_block}

Задача:
помочь пользователю понять, почему его блог или контент не работает.

Требования:
- выдели 1 главную и максимум 1 дополнительную проблему
- объясни это простым языком
- покажи, почему именно это похоже на его ситуацию
- потом дай один понятный следующий шаг
- не растягивай ответ

Формат:
1. Что, скорее всего, происходит
2. Почему я так думаю
3. Что делать дальше
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
    final_prompt = build_context_prompt(telegram_user_id, user_text)
    return call_openai(final_prompt, lang=lang)

def get_language_keyboard():
    keyboard = [
        [InlineKeyboardButton("Русский", callback_data="lang_ru")],
        [InlineKeyboardButton("English", callback_data="lang_en")],
        [InlineKeyboardButton("Deutsch", callback_data="lang_de")],
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
    keyboard = [
        [InlineKeyboardButton(tr(lang, "menu_home"), callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

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
        first_chunk = chunks
        await query.edit_message_text(text=first_chunk)

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
    await safe_reply(
        message_obj,
        "Hi! / Привет! / Hallo!\n\nChoose your language:",
        reply_markup=get_language_keyboard()
    )

async def send_main_menu_message(target, lang: str):
    await safe_reply(target, tr(lang, "main_intro"), reply_markup=get_main_menu(lang))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
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

async def show_change_language_screen(query, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["awaiting_language_selection"] = True
    user_id = query.from_user.id
    current_lang = get_user_language(user_id)
    await safe_edit(query, tr(current_lang, "choose_language"), reply_markup=get_language_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except TelegramError as e:
        logger.exception("callback answer failed: %s", e)

    if query.data.startswith("lang_"):
        selected_lang = normalize_lang(query.data.replace("lang_", ""))
        save_user(update)
        set_user_language(query.from_user.id, selected_lang)
        context.user_data.clear()
        await safe_edit(
            query,
            tr(selected_lang, "language_saved") + "\n\n" + tr(selected_lang, "main_intro"),
            reply_markup=get_main_menu(selected_lang)
        )
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

async def handle_start_blog_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str):
    step = context.user_data.get("step")
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    if step == "awaiting_start_blog_choice":
        choice = user_text.strip()
        context.user_data["start_blog_choice"] = choice

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

    prompt = f"""
{get_user_context_block(user_id, user_text)}

Задача:
пользователь прислал ежедневный check-in.

Дай ответ так, чтобы:
- сначала было ощущение поддержки
- потом появилась ясность
- потом один фокус на сегодня
- не было давления
- не было банальных советов
- не было длинного списка дел
- отвечай компактно

Формат:
1. короткая поддержка
2. что, скорее всего, сейчас происходит
3. один фокус на сегодня
"""
    answer = call_openai(prompt, lang=lang)
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
    awaiting_language_selection = context.user_data.get("awaiting_language_selection", False)

    if awaiting_language_selection:
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

    lang = get_user_language(user_id)
    if not lang:
        await send_language_picker(update.message)
        return

    await handle_free_chat(update, context, user_text)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Exception while handling update:", exc_info=context.error)

def main():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL is not set")

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