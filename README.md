# AzrulAssistant Telegram Bot

A personal Telegram bot for daily coding reminders and tech news around Flutter, Python, Django, FastAPI, backend development, and AI.

## Important token note

The token you pasted in chat should be treated as compromised. Open BotFather, revoke/regenerate the token, then use the new token in `.env`.

## Setup

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your-new-token-from-botfather
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=llama-3.1-8b-instant
DEFAULT_REMINDER_TIME=09:00
TIMEZONE=Asia/Dhaka
```

## Run

```powershell
.\.venv\Scripts\python.exe bot.py
```

## Bot commands

- `/start` - show help
- `/subscribe 09:00` - receive daily reminder and tech news
- `/unsubscribe` - stop reminders
- `/news` - get current tech headlines
- `/brief` - get an AI summary of the latest updates
- `/ask How should I structure a FastAPI app?` - ask an AI coding question
- `/settopics flutter python django fastapi` - customize news topics
- `/topics` - show selected topics
- `/status` - show reminder status

Subscriber data is stored in `data/subscribers.json`.
"# Assistaint-TelegramBot" 
