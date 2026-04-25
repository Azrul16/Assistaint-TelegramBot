# Personal Assistant Telegram Bot

```text
Personal Assistant Telegram Bot
Natural chat -> Groq intent detection -> tasks, reminders, notes, news, jobs, and daily planning
```

A private Telegram assistant built for personal productivity, coding support, reminders, notes, tech news, job tracking, and day planning. The bot is designed to feel like a personal agent: you message it normally, Groq understands your intent, and the bot runs the right action.

## What It Does

- Understands normal chat instead of relying on bot commands
- Uses Groq Llama 3.3 for intent detection and assistant replies
- Manages tasks, notes, schedules, and reminders
- Sends daily coding reminders with agenda and tech updates
- Fetches tech news for your selected topics
- Tracks job opportunities from remote job feeds
- Supports live tech and job alerts
- Stores personal data locally in JSON files

## Natural Chat

You can write messages like:

```text
remind me tomorrow at 8 pm to practice Django
add a task to finish the portfolio homepage
mark task 2 done
save a note to follow up with the recruiter
what is on my agenda today
send me Flutter news
show me Python backend jobs
turn daily reminders on at 09:00
set topics Flutter Python Django FastAPI
```

The bot sends your message to Groq for intent detection, receives a structured action, then executes that action in Python.

## Tech Stack

- Python
- python-telegram-bot
- Groq API
- Feedparser
- JSON file storage
- Optional 24/7 hosting on Google Cloud Compute Engine

## Project Files

```text
bot.py                 Main Telegram bot application
requirements.txt       Python dependencies
.env.example           Example environment variables
data/subscribers.json  Daily reminder and topic settings
data/assistant_data.json Tasks, notes, schedules, alerts, and job settings
```

## Setup

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your-botfather-token
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=llama-3.3-70b-versatile
DEFAULT_REMINDER_TIME=09:00
TIMEZONE=Asia/Dhaka
```

## Run Locally

```powershell
.\.venv\Scripts\python.exe bot.py
```

Open Telegram and send a normal message to your bot.

## Google Cloud Free Tier Hosting

For 24/7 hosting, use a Google Cloud Compute Engine VM that matches the free tier.

Recommended VM settings:

```text
Machine type: e2-micro
Region: us-central1, us-east1, or us-west1
Boot disk type: Standard persistent disk
Disk size: 10 GB
Firewall HTTP/HTTPS: off
```

After creating the VM, deploy the bot with a Python virtual environment and run it as a `systemd` service so it restarts automatically after crashes or reboots.

## Data Storage

The bot stores data locally:

- `data/subscribers.json` for daily reminders and news topics
- `data/assistant_data.json` for tasks, notes, schedules, alert state, and job keywords

Back up the `data` folder if you move servers.

## Security

Keep `.env` private. Never commit real Telegram bot tokens or Groq API keys.

If a token is exposed, rotate it immediately:

- Telegram token: regenerate it with BotFather
- Groq key: create a new API key from the Groq console

## Notes

This bot is built for personal use. It uses Telegram polling, so it does not need a public domain, HTTPS certificate, or open web ports.
