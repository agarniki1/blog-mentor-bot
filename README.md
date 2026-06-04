# SMM Mentor Telegram Bot

Telegram AI-бот, который помогает выбрать направление блога, начать без перегруза и двигаться маленькими шагами.

## Возможности
- Выбор направления блога
- Сценарий "Начать блог"
- План на 7 дней
- Daily check-in
- Свободный чат
- Память пользователя через SQLite
- Базовая обработка ошибок

## Стек
- Python
- python-telegram-bot
- OpenAI API
- SQLite
- Railway
- GitHub

## Локальный запуск

1. Установить зависимости:
   pip install -r requirements.txt

2. Создать .env файл по образцу .env.example

3. Запустить:
   python app.py

## Переменные окружения
- TELEGRAM_BOT_TOKEN
- OPENAI_API_KEY

## Deploy
Проект можно задеплоить на Railway через Deploy from GitHub repo.
