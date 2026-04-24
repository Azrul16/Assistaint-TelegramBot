# AzrulAssistant Telegram Bot

A personal Telegram bot that works like a lightweight personal assistant for coding, schedules, notes, and tech news around Flutter, Python, Django, FastAPI, backend development, and AI.

You can also chat with it naturally. Example messages:

- `give me flutter news`
- `send me job opportunities for flutter and python`
- `remind me tomorrow at 8 pm to practice django`
- `add a task to finish the portfolio homepage`
- `save a note to follow up with the recruiter`
- `what is on my agenda today`
- `turn alerts on`

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
- `/jobs` - show recent matching jobs
- `/addtask Finish landing page` - add a task
- `/tasks` - show open tasks
- `/done 1` - mark a task done
- `/schedule 2026-04-25 18:30 | Client call` - create a scheduled reminder
- `/agenda` - show today's agenda and upcoming items
- `/note Follow up with recruiter tomorrow` - save a note
- `/notes` - show saved notes
- `/setjobkeywords flutter dart python backend` - customize job matching
- `/alerts on` - enable live tech and job alerts
- `/settopics flutter python django fastapi` - customize news topics
- `/topics` - show selected topics
- `/status` - show reminder status

Subscriber data is stored in `data/subscribers.json`.
Assistant data for tasks, notes, and schedules is stored in `data/assistant_data.json`.
"# Assistaint-TelegramBot" 
