# AzrulAssistant Telegram Bot

A personal Telegram assistant for coding, schedules, notes, reminders, tech news, job tracking, and day planning.

The bot is designed for natural chat. You can write normally, and Groq detects your intent before the bot chooses the right action.

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
GROQ_MODEL=llama-3.3-70b-versatile
DEFAULT_REMINDER_TIME=09:00
TIMEZONE=Asia/Dhaka
```

## Run

```powershell
.\.venv\Scripts\python.exe bot.py
```

Subscriber data is stored in `data/subscribers.json`.
Assistant data for tasks, notes, and schedules is stored in `data/assistant_data.json`.
