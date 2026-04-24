from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, time
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import feedparser
import httpx
from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SUBSCRIBERS_FILE = DATA_DIR / "subscribers.json"
ASSISTANT_DATA_FILE = DATA_DIR / "assistant_data.json"

DEFAULT_TOPICS = ["flutter", "python", "django", "fastapi", "ai", "backend"]
DEFAULT_JOB_KEYWORDS = ["flutter", "dart", "python", "django", "fastapi", "backend", "api"]
NEWS_FEEDS = [
    "https://blog.python.org/feeds/posts/default",
    "https://www.djangoproject.com/rss/weblog/",
    "https://fastapi.tiangolo.com/release-notes/index.xml",
    "https://medium.com/feed/flutter",
    "https://realpython.com/atom.xml",
    "https://hnrss.org/frontpage",
]
JOB_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://remoteyeah.com/rss.xml",
]

CODING_PROMPTS = [
    "Your future self will love what you build today. Start with one small win and let momentum do the rest.",
    "You do not need a perfect day to make progress. Twenty focused minutes of real coding still counts.",
    "Show up for the work, even if it begins messy. Clean code often starts as courage, not clarity.",
    "One commit today is stronger than ten plans for tomorrow. Open the project and move it forward.",
    "Keep the streak alive. A tiny feature, a fixed bug, or one better function is enough to make today matter.",
    "Skill compounds quietly. Every Flutter screen, Python script, Django view, or FastAPI route adds up.",
    "Progress is built in sessions like this one. Sit down, begin, and let the next good idea meet you there.",
    "You already know enough to start. Write the first line, then give yourself permission to improve it.",
]

BOT_COMMANDS = [
    BotCommand("start", "Show bot help"),
    BotCommand("subscribe", "Enable daily reminder, example: /subscribe 09:00"),
    BotCommand("unsubscribe", "Disable daily reminders"),
    BotCommand("news", "Get latest tech news for your topics"),
    BotCommand("brief", "Get an AI summary of the latest tech updates"),
    BotCommand("ask", "Ask an AI coding question"),
    BotCommand("jobs", "Show recent job opportunities"),
    BotCommand("addtask", "Add a task, example: /addtask Finish API auth"),
    BotCommand("tasks", "Show your open tasks"),
    BotCommand("done", "Mark a task done, example: /done 2"),
    BotCommand("schedule", "Add an event, example: /schedule 2026-04-25 18:30 | Client call"),
    BotCommand("agenda", "Show today's agenda and upcoming schedule"),
    BotCommand("note", "Save a quick note"),
    BotCommand("notes", "Show your recent notes"),
    BotCommand("setjobkeywords", "Set job keywords, example: /setjobkeywords flutter python"),
    BotCommand("alerts", "Control live alerts, example: /alerts on"),
    BotCommand("settopics", "Set your topics, example: /settopics flutter python"),
    BotCommand("topics", "Show your current topics"),
    BotCommand("status", "Show your reminder status"),
]

INTENT_EXAMPLES = [
    "give me flutter news -> news",
    "remind me tomorrow at 8 pm to practice django -> schedule_add",
    "add task finish portfolio homepage -> task_add",
    "show my tasks -> task_list",
    "save note call recruiter next week -> note_add",
    "what is my agenda today -> agenda",
]


@dataclass
class Subscriber:
    chat_id: int
    reminder_time: str
    topics: list[str] = field(default_factory=lambda: DEFAULT_TOPICS.copy())
    prompt_order: list[int] = field(default_factory=list)
    prompt_position: int = 0


@dataclass
class TaskItem:
    id: int
    title: str
    created_at: str
    done: bool = False
    completed_at: str | None = None


@dataclass
class ScheduleItem:
    id: int
    title: str
    scheduled_for: str
    reminded: bool = False
    done: bool = False


@dataclass
class NoteItem:
    id: int
    text: str
    created_at: str


@dataclass
class AssistantProfile:
    chat_id: int
    tasks: list[TaskItem] = field(default_factory=list)
    schedule: list[ScheduleItem] = field(default_factory=list)
    notes: list[NoteItem] = field(default_factory=list)
    news_alerts_enabled: bool = True
    job_alerts_enabled: bool = True
    job_keywords: list[str] = field(default_factory=lambda: DEFAULT_JOB_KEYWORDS.copy())
    seen_news_links: list[str] = field(default_factory=list)
    seen_job_links: list[str] = field(default_factory=list)


def load_config() -> tuple[str, ZoneInfo, str, str, str]:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing. Add it to your .env file.")

    timezone_name = os.getenv("TIMEZONE", "Asia/Dhaka").strip()
    default_time = os.getenv("DEFAULT_REMINDER_TIME", "09:00").strip()
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip()
    return token, ZoneInfo(timezone_name), default_time, groq_api_key, groq_model


def now_in_timezone(timezone: ZoneInfo) -> datetime:
    return datetime.now(timezone)


def read_subscribers() -> dict[str, Subscriber]:
    if not SUBSCRIBERS_FILE.exists():
        return {}

    raw_data = json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
    subscribers: dict[str, Subscriber] = {}
    for chat_id, values in raw_data.items():
        subscribers[chat_id] = Subscriber(
            chat_id=int(chat_id),
            reminder_time=values.get("reminder_time", "09:00"),
            topics=values.get("topics", DEFAULT_TOPICS.copy()),
            prompt_order=values.get("prompt_order", []),
            prompt_position=values.get("prompt_position", 0),
        )
    return subscribers


def write_subscribers(subscribers: dict[str, Subscriber]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    payload = {
        chat_id: {
            "reminder_time": subscriber.reminder_time,
            "topics": subscriber.topics,
            "prompt_order": subscriber.prompt_order,
            "prompt_position": subscriber.prompt_position,
        }
        for chat_id, subscriber in subscribers.items()
    }
    SUBSCRIBERS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_assistant_profiles() -> dict[str, AssistantProfile]:
    if not ASSISTANT_DATA_FILE.exists():
        return {}

    raw_data = json.loads(ASSISTANT_DATA_FILE.read_text(encoding="utf-8"))
    profiles: dict[str, AssistantProfile] = {}
    for chat_id, values in raw_data.items():
        profiles[chat_id] = AssistantProfile(
            chat_id=int(chat_id),
            tasks=[
                TaskItem(
                    id=item["id"],
                    title=item["title"],
                    created_at=item["created_at"],
                    done=item.get("done", False),
                    completed_at=item.get("completed_at"),
                )
                for item in values.get("tasks", [])
            ],
            schedule=[
                ScheduleItem(
                    id=item["id"],
                    title=item["title"],
                    scheduled_for=item["scheduled_for"],
                    reminded=item.get("reminded", False),
                    done=item.get("done", False),
                )
                for item in values.get("schedule", [])
            ],
            notes=[
                NoteItem(
                    id=item["id"],
                    text=item["text"],
                    created_at=item["created_at"],
                )
                for item in values.get("notes", [])
            ],
            news_alerts_enabled=values.get("news_alerts_enabled", True),
            job_alerts_enabled=values.get("job_alerts_enabled", True),
            job_keywords=values.get("job_keywords", DEFAULT_JOB_KEYWORDS.copy()),
            seen_news_links=values.get("seen_news_links", []),
            seen_job_links=values.get("seen_job_links", []),
        )
    return profiles


def write_assistant_profiles(profiles: dict[str, AssistantProfile]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    payload = {
        chat_id: {
            "tasks": [
                {
                    "id": item.id,
                    "title": item.title,
                    "created_at": item.created_at,
                    "done": item.done,
                    "completed_at": item.completed_at,
                }
                for item in profile.tasks
            ],
            "schedule": [
                {
                    "id": item.id,
                    "title": item.title,
                    "scheduled_for": item.scheduled_for,
                    "reminded": item.reminded,
                    "done": item.done,
                }
                for item in profile.schedule
            ],
            "notes": [
                {
                    "id": item.id,
                    "text": item.text,
                    "created_at": item.created_at,
                }
                for item in profile.notes
            ],
            "news_alerts_enabled": profile.news_alerts_enabled,
            "job_alerts_enabled": profile.job_alerts_enabled,
            "job_keywords": profile.job_keywords,
            "seen_news_links": profile.seen_news_links[-100:],
            "seen_job_links": profile.seen_job_links[-100:],
        }
        for chat_id, profile in profiles.items()
    }
    ASSISTANT_DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_profile(application: Application, chat_id: int) -> AssistantProfile:
    profiles: dict[str, AssistantProfile] = application.bot_data["assistant_profiles"]
    key = str(chat_id)
    if key not in profiles:
        profiles[key] = AssistantProfile(chat_id=chat_id)
    return profiles[key]


def next_id(items: list[Any]) -> int:
    if not items:
        return 1
    return max(item.id for item in items) + 1


def parse_reminder_time(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("Use 24-hour format like 09:00 or 21:30.") from exc

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Hour must be 00-23 and minute must be 00-59.")

    return time(hour=hour, minute=minute)


def parse_schedule_input(value: str, timezone: ZoneInfo) -> tuple[datetime, str]:
    if "|" not in value:
        raise ValueError("Use: /schedule YYYY-MM-DD HH:MM | title")

    when_text, title = [part.strip() for part in value.split("|", maxsplit=1)]
    if not title:
        raise ValueError("Your schedule item needs a title.")

    try:
        scheduled_for = datetime.strptime(when_text, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Use date and time like 2026-04-25 18:30.") from exc

    return scheduled_for.replace(tzinfo=timezone), title


def parse_datetime_text(value: str, timezone: ZoneInfo) -> datetime:
    try:
        scheduled_for = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Datetime should look like 2026-04-25 18:30.") from exc
    return scheduled_for.replace(tzinfo=timezone)


def normalize_topics(topics: list[str]) -> list[str]:
    cleaned = []
    for topic in topics:
        value = topic.strip().lower().replace("#", "")
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned or DEFAULT_TOPICS.copy()


def item_matches_topics(item: Any, topics: list[str]) -> bool:
    haystack = " ".join(
        [
            str(getattr(item, "title", "")),
            str(getattr(item, "summary", "")),
            str(getattr(item, "tags", "")),
        ]
    ).lower()
    return any(topic.lower() in haystack for topic in topics)


def fetch_news(topics: list[str], limit: int = 6) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    seen_links: set[str] = set()

    for feed_url in NEWS_FEEDS:
        parsed = feedparser.parse(feed_url)
        for item in parsed.entries[:12]:
            title = str(getattr(item, "title", "")).strip()
            link = str(getattr(item, "link", "")).strip()
            if not title or not link or link in seen_links:
                continue
            if item_matches_topics(item, topics):
                matches.append((title, link))
                seen_links.add(link)
            if len(matches) >= limit:
                return matches

    return matches


async def fetch_news_async(topics: list[str], limit: int = 6) -> list[tuple[str, str]]:
    return await asyncio.to_thread(fetch_news, topics, limit)


def fetch_jobs(keywords: list[str], limit: int = 6) -> list[tuple[str, str, str]]:
    matches: list[tuple[str, str, str]] = []
    seen_links: set[str] = set()

    for feed_url in JOB_FEEDS:
        parsed = feedparser.parse(feed_url)
        for item in parsed.entries[:20]:
            title = str(getattr(item, "title", "")).strip()
            link = str(getattr(item, "link", "")).strip()
            summary = str(getattr(item, "summary", "")).strip()
            source = str(getattr(parsed.feed, "title", "Job Feed")).strip() or "Job Feed"
            haystack = " ".join([title, summary, str(getattr(item, "tags", ""))]).lower()
            if not title or not link or link in seen_links:
                continue
            if any(keyword.lower() in haystack for keyword in keywords):
                matches.append((title, link, source))
                seen_links.add(link)
            if len(matches) >= limit:
                return matches

    return matches


async def fetch_jobs_async(keywords: list[str], limit: int = 6) -> list[tuple[str, str, str]]:
    return await asyncio.to_thread(fetch_jobs, keywords, limit)


def format_news(news_items: list[tuple[str, str]]) -> str:
    if not news_items:
        return "I could not find fresh matching headlines right now. Try /news again later."

    lines = ["<b>Tech updates for you</b>"]
    for index, (title, link) in enumerate(news_items, start=1):
        lines.append(f'{index}. <a href="{escape(link)}">{escape(title)}</a>')
    return "\n".join(lines)


def format_jobs(job_items: list[tuple[str, str, str]]) -> str:
    if not job_items:
        return "I could not find matching job openings right now. Try /jobs again later."

    lines = ["<b>Job opportunities for you</b>"]
    for index, (title, link, source) in enumerate(job_items, start=1):
        lines.append(f'{index}. <a href="{escape(link)}">{escape(title)}</a> - {escape(source)}')
    return "\n".join(lines)


def remember_links(existing: list[str], links: list[str], limit: int = 100) -> list[str]:
    merged = existing + [link for link in links if link not in existing]
    return merged[-limit:]


async def generate_groq_text(
    groq_api_key: str,
    groq_model: str,
    system_prompt: str,
    user_prompt: str,
    max_completion_tokens: int = 250,
) -> str | None:
    if not groq_api_key:
        return None

    payload = {
        "model": groq_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_completion_tokens": max_completion_tokens,
    }
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logging.warning("Groq request failed: %s", exc)
        return None

    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        return None

    return choices[0].get("message", {}).get("content", "").strip() or None


def extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def parse_chat_intent(
    application: Application,
    chat_id: int,
    text: str,
    timezone: ZoneInfo,
) -> dict[str, Any] | None:
    groq_api_key: str = application.bot_data.get("groq_api_key", "")
    groq_model: str = application.bot_data.get("groq_model", "llama-3.1-8b-instant")
    if not groq_api_key:
        return None

    profile = get_profile(application, chat_id)
    now = now_in_timezone(timezone).strftime("%Y-%m-%d %H:%M")
    open_tasks = [f"{task.id}: {task.title}" for task in profile.tasks if not task.done][:10]

    prompt = (
        f"Current local datetime: {now}\n"
        f"Timezone: {timezone.key}\n"
        f"Open tasks: {open_tasks or ['none']}\n"
        f"User message: {text}\n\n"
        "Choose the best intent and return JSON only with this shape:\n"
        '{'
        '"intent":"news|brief|jobs|agenda|task_add|task_list|task_done|schedule_add|note_add|notes|status|topics_set|alerts_on|alerts_off|question|unknown",'
        '"title":"string or empty",'
        '"datetime":"YYYY-MM-DD HH:MM or empty",'
        '"task_id":0,'
        '"topics":["topic"],'
        '"question":"string or empty",'
        '"answer":"short assistant reply to send back if no tool/action is needed"'
        '}\n'
        "Rules:\n"
        "- For reminder or meeting requests, use schedule_add and convert relative dates like tomorrow into exact datetime.\n"
        "- For schedule_add, put the reminder text in title.\n"
        "- For task requests, extract a short task title.\n"
        "- For direct coding or productivity questions, use question.\n"
        "- For requests to see updates or headlines, use news or brief.\n"
        "- For requests to save thoughts, use note_add.\n"
        "- If uncertain, use unknown.\n"
        f"Examples: {INTENT_EXAMPLES}"
    )

    raw = await generate_groq_text(
        groq_api_key,
        groq_model,
        "You are a strict intent parser for a Telegram personal assistant. Return JSON only.",
        prompt,
        max_completion_tokens=220,
    )
    return extract_json_object(raw) if raw else None


def fallback_intent(text: str) -> dict[str, Any]:
    lowered = text.lower().strip()
    if any(word in lowered for word in ["news", "headline", "update"]):
        return {"intent": "news"}
    if any(word in lowered for word in ["job", "vacancy", "hiring", "opportunity", "openings"]):
        return {"intent": "jobs"}
    if any(word in lowered for word in ["agenda", "schedule today", "what do i have", "today plan"]):
        return {"intent": "agenda"}
    if "alerts on" in lowered:
        return {"intent": "alerts_on"}
    if "alerts off" in lowered:
        return {"intent": "alerts_off"}
    if any(word in lowered for word in ["show tasks", "my tasks", "task list"]):
        return {"intent": "task_list"}
    if lowered.startswith("note ") or lowered.startswith("save note "):
        note_text = re.sub(r"^(save\s+)?note\s+", "", text, flags=re.IGNORECASE).strip()
        return {"intent": "note_add", "title": note_text}
    if lowered.startswith("add task ") or lowered.startswith("task "):
        title = re.sub(r"^(add\s+)?task\s+", "", text, flags=re.IGNORECASE).strip()
        return {"intent": "task_add", "title": title}
    return {"intent": "question", "question": text}


async def build_ai_news_brief(
    application: Application,
    topics: list[str],
    news_items: list[tuple[str, str]],
) -> str | None:
    groq_api_key: str = application.bot_data.get("groq_api_key", "")
    groq_model: str = application.bot_data.get("groq_model", "llama-3.1-8b-instant")
    if not groq_api_key or not news_items:
        return None

    headlines = "\n".join(f"- {title} ({link})" for title, link in news_items[:5])
    prompt = (
        f"Topics: {', '.join(topics)}\n"
        "Summarize the most relevant points from these headlines for a software developer. "
        "Keep it short, practical, and motivating.\n\n"
        f"{headlines}"
    )
    return await generate_groq_text(
        groq_api_key,
        groq_model,
        "You are a concise developer news assistant. Focus on why the update matters to the reader's work.",
        prompt,
        max_completion_tokens=220,
    )


async def build_ai_agenda_brief(application: Application, profile: AssistantProfile, timezone: ZoneInfo) -> str | None:
    groq_api_key: str = application.bot_data.get("groq_api_key", "")
    groq_model: str = application.bot_data.get("groq_model", "llama-3.1-8b-instant")
    if not groq_api_key:
        return None

    now = now_in_timezone(timezone)
    open_tasks = [task.title for task in profile.tasks if not task.done][:6]
    upcoming = []
    for item in sorted(profile.schedule, key=lambda x: x.scheduled_for):
        if item.done:
            continue
        when = datetime.fromisoformat(item.scheduled_for)
        if when >= now:
            upcoming.append(f"{when.strftime('%Y-%m-%d %H:%M')} - {item.title}")
        if len(upcoming) >= 5:
            break

    prompt = (
        "Create a short personal assistant brief for today.\n"
        f"Open tasks: {open_tasks or ['none']}\n"
        f"Upcoming schedule: {upcoming or ['none']}\n"
        "Keep it focused, encouraging, and practical in 4 short lines max."
    )
    return await generate_groq_text(
        groq_api_key,
        groq_model,
        "You are a calm, practical personal assistant helping a developer prioritize the day.",
        prompt,
        max_completion_tokens=180,
    )


def format_ai_brief(text: str) -> str:
    return f"<b>Why this matters today</b>\n{escape(text)}"


def build_prompt_order(chat_id: int, previous_last: int | None = None) -> list[int]:
    order = list(range(len(CODING_PROMPTS)))
    random.Random(f"{chat_id}:{len(CODING_PROMPTS)}").shuffle(order)
    if previous_last is not None and len(order) > 1 and order[0] == previous_last:
        order.append(order.pop(0))
    return order


def get_next_prompt(subscriber: Subscriber) -> str:
    if not subscriber.prompt_order:
        subscriber.prompt_order = build_prompt_order(subscriber.chat_id)
        subscriber.prompt_position = 0

    if subscriber.prompt_position >= len(subscriber.prompt_order):
        previous_last = subscriber.prompt_order[-1] if subscriber.prompt_order else None
        subscriber.prompt_order = build_prompt_order(subscriber.chat_id + subscriber.prompt_position, previous_last)
        subscriber.prompt_position = 0

    prompt_index = subscriber.prompt_order[subscriber.prompt_position]
    subscriber.prompt_position += 1
    return CODING_PROMPTS[prompt_index]


def format_tasks(profile: AssistantProfile) -> str:
    open_tasks = [task for task in profile.tasks if not task.done]
    if not open_tasks:
        return "No open tasks right now. Add one with /addtask."

    lines = ["<b>Your tasks</b>"]
    for task in open_tasks[:15]:
        lines.append(f"{task.id}. {escape(task.title)}")
    return "\n".join(lines)


def format_notes(profile: AssistantProfile) -> str:
    if not profile.notes:
        return "No notes saved yet. Use /note to save one."

    lines = ["<b>Recent notes</b>"]
    for note in sorted(profile.notes, key=lambda item: item.created_at, reverse=True)[:10]:
        created = datetime.fromisoformat(note.created_at).strftime("%b %d %H:%M")
        lines.append(f"{note.id}. [{created}] {escape(note.text)}")
    return "\n".join(lines)


def format_agenda(profile: AssistantProfile, timezone: ZoneInfo) -> str:
    now = now_in_timezone(timezone)
    today = now.date()
    today_items = []
    upcoming_items = []

    for item in sorted(profile.schedule, key=lambda entry: entry.scheduled_for):
        if item.done:
            continue
        scheduled = datetime.fromisoformat(item.scheduled_for)
        label = f"{item.id}. {scheduled.strftime('%b %d %H:%M')} - {escape(item.title)}"
        if scheduled.date() == today:
            today_items.append(label)
        elif scheduled > now and len(upcoming_items) < 5:
            upcoming_items.append(label)

    open_tasks = [task for task in profile.tasks if not task.done][:5]
    lines = ["<b>Your agenda</b>"]
    lines.append(f"Open tasks: {len([task for task in profile.tasks if not task.done])}")

    if today_items:
        lines.append("")
        lines.append("<b>Today</b>")
        lines.extend(today_items[:8])

    if open_tasks:
        lines.append("")
        lines.append("<b>Next tasks</b>")
        for task in open_tasks:
            lines.append(f"{task.id}. {escape(task.title)}")

    if upcoming_items:
        lines.append("")
        lines.append("<b>Upcoming</b>")
        lines.extend(upcoming_items)

    return "\n".join(lines)


async def send_daily_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    job_data = context.job.data or {}
    chat_id = job_data["chat_id"]
    subscribers: dict[str, Subscriber] = context.application.bot_data["subscribers"]
    subscriber = subscribers.get(str(chat_id))
    if subscriber is None:
        return

    timezone: ZoneInfo = context.application.bot_data["timezone"]
    profile = get_profile(context.application, chat_id)
    topics = subscriber.topics
    prompt = get_next_prompt(subscriber)
    write_subscribers(subscribers)
    news_items = await fetch_news_async(topics, limit=4)
    ai_brief = await build_ai_news_brief(context.application, topics, news_items)
    agenda = format_agenda(profile, timezone)

    message = (
        f"<b>Daily coding reminder</b>\n"
        f"{escape(prompt)}\n\n"
        f"{agenda}\n\n"
        f"{format_news(news_items)}"
    )
    if ai_brief:
        message += f"\n\n{format_ai_brief(ai_brief)}"

    await context.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def send_due_schedule_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    timezone: ZoneInfo = context.application.bot_data["timezone"]
    profiles: dict[str, AssistantProfile] = context.application.bot_data["assistant_profiles"]
    now = now_in_timezone(timezone)
    changed = False

    for profile in profiles.values():
        due_items = []
        for item in profile.schedule:
            scheduled = datetime.fromisoformat(item.scheduled_for)
            if not item.done and not item.reminded and scheduled <= now:
                due_items.append(item)

        for item in due_items:
            item.reminded = True
            changed = True
            await context.bot.send_message(
                chat_id=profile.chat_id,
                text=(
                    f"<b>Schedule reminder</b>\n"
                    f"It is time for: {escape(item.title)}\n"
                    f"When: {escape(datetime.fromisoformat(item.scheduled_for).strftime('%b %d, %Y %H:%M'))}"
                ),
                parse_mode=ParseMode.HTML,
            )

    if changed:
        write_assistant_profiles(profiles)


async def poll_live_alerts(context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: dict[str, Subscriber] = context.application.bot_data["subscribers"]
    profiles: dict[str, AssistantProfile] = context.application.bot_data["assistant_profiles"]
    changed = False

    for profile in profiles.values():
        subscriber = subscribers.get(str(profile.chat_id))
        topics = subscriber.topics if subscriber else DEFAULT_TOPICS.copy()

        if profile.news_alerts_enabled:
            tech_items = await fetch_news_async(topics, limit=8)
            tech_links = [link for _, link in tech_items]
            if not profile.seen_news_links:
                profile.seen_news_links = remember_links([], tech_links)
                changed = True
            else:
                new_items = [(title, link) for title, link in tech_items if link not in profile.seen_news_links]
                if new_items:
                    profile.seen_news_links = remember_links(profile.seen_news_links, [link for _, link in new_items])
                    changed = True
                    for title, link in reversed(new_items[:3]):
                        await context.bot.send_message(
                            chat_id=profile.chat_id,
                            text=(
                                "<b>New tech update</b>\n"
                                f'<a href="{escape(link)}">{escape(title)}</a>'
                            ),
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )

        if profile.job_alerts_enabled:
            job_items = await fetch_jobs_async(profile.job_keywords, limit=10)
            job_links = [link for _, link, _ in job_items]
            if not profile.seen_job_links:
                profile.seen_job_links = remember_links([], job_links)
                changed = True
            else:
                new_jobs = [(title, link, source) for title, link, source in job_items if link not in profile.seen_job_links]
                if new_jobs:
                    profile.seen_job_links = remember_links(profile.seen_job_links, [link for _, link, _ in new_jobs])
                    changed = True
                    for title, link, source in reversed(new_jobs[:3]):
                        await context.bot.send_message(
                            chat_id=profile.chat_id,
                            text=(
                                "<b>New job opportunity</b>\n"
                                f'{escape(title)}\n'
                                f"Source: {escape(source)}\n"
                                f'<a href="{escape(link)}">Open listing</a>'
                            ),
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )

    if changed:
        write_assistant_profiles(profiles)


def schedule_subscriber(application: Application, subscriber: Subscriber, timezone: ZoneInfo) -> None:
    chat_id = str(subscriber.chat_id)
    for job in application.job_queue.get_jobs_by_name(chat_id):
        job.schedule_removal()

    reminder_time = parse_reminder_time(subscriber.reminder_time).replace(tzinfo=timezone)
    application.job_queue.run_daily(
        send_daily_reminder,
        time=reminder_time,
        name=chat_id,
        data={"chat_id": subscriber.chat_id},
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi, I am your personal assistant bot.\n\n"
        "Core commands:\n"
        "/subscribe 09:00 - daily coding reminder, agenda, and news\n"
        "/addtask Finish onboarding screen\n"
        "/tasks\n"
        "/done 1\n"
        "/schedule 2026-04-25 18:30 | Client call\n"
        "/agenda\n"
        "/note Ask recruiter about timeline\n"
        "/notes\n"
        "/brief - AI summary of fresh tech updates\n"
        "/ask How do I structure a FastAPI project?\n"
        "/settopics flutter python django fastapi\n"
        "/status"
    )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: dict[str, Subscriber] = context.application.bot_data["subscribers"]
    timezone: ZoneInfo = context.application.bot_data["timezone"]
    default_time: str = context.application.bot_data["default_time"]
    chat_id = update.effective_chat.id
    requested_time = context.args[0] if context.args else default_time

    try:
        parse_reminder_time(requested_time)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    existing = subscribers.get(str(chat_id))
    subscriber = Subscriber(
        chat_id=chat_id,
        reminder_time=requested_time,
        topics=existing.topics if existing else DEFAULT_TOPICS.copy(),
        prompt_order=existing.prompt_order if existing else [],
        prompt_position=existing.prompt_position if existing else 0,
    )
    subscribers[str(chat_id)] = subscriber
    write_subscribers(subscribers)
    schedule_subscriber(context.application, subscriber, timezone)

    await update.message.reply_text(f"Subscribed. I will check in every day at {requested_time}.")


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: dict[str, Subscriber] = context.application.bot_data["subscribers"]
    chat_id = str(update.effective_chat.id)
    subscribers.pop(chat_id, None)
    write_subscribers(subscribers)

    for job in context.application.job_queue.get_jobs_by_name(chat_id):
        job.schedule_removal()

    await update.message.reply_text("Daily reminders are paused.")


async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: dict[str, Subscriber] = context.application.bot_data["subscribers"]
    chat_id = str(update.effective_chat.id)
    topics = subscribers.get(chat_id, Subscriber(int(chat_id), "09:00")).topics
    news_items = await fetch_news_async(topics)

    await update.message.reply_text(
        format_news(news_items),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: dict[str, Subscriber] = context.application.bot_data["subscribers"]
    timezone: ZoneInfo = context.application.bot_data["timezone"]
    chat_id = update.effective_chat.id
    topics = subscribers.get(str(chat_id), Subscriber(chat_id, "09:00")).topics
    profile = get_profile(context.application, chat_id)
    news_items = await fetch_news_async(topics, limit=5)
    ai_brief = await build_ai_news_brief(context.application, topics, news_items)
    ai_agenda = await build_ai_agenda_brief(context.application, profile, timezone)

    parts = []
    if ai_agenda:
        parts.append(f"<b>Today at a glance</b>\n{escape(ai_agenda)}")
    if ai_brief:
        parts.append(format_ai_brief(ai_brief))
    parts.append(format_agenda(profile, timezone))
    parts.append(format_news(news_items))

    await update.message.reply_text(
        "\n\n".join(parts),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile = get_profile(context.application, update.effective_chat.id)
    job_items = await fetch_jobs_async(profile.job_keywords, limit=6)
    await update.message.reply_text(
        format_jobs(job_items),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args).strip()
    if not question:
        await update.message.reply_text("Ask something like: /ask How should I structure a Django app?")
        return

    groq_api_key: str = context.application.bot_data.get("groq_api_key", "")
    groq_model: str = context.application.bot_data.get("groq_model", "llama-3.1-8b-instant")
    if not groq_api_key:
        await update.message.reply_text("AI mode is not configured yet. Add GROQ_API_KEY to .env and restart the bot.")
        return

    answer = await generate_groq_text(
        groq_api_key,
        groq_model,
        (
            "You are a helpful coding and productivity assistant for a developer working with Flutter, Python, Django, FastAPI, and backend engineering. "
            "Give practical, concise answers with direct advice."
        ),
        question,
        max_completion_tokens=350,
    )
    if not answer:
        await update.message.reply_text("I could not reach the AI service right now. Please try again in a moment.")
        return

    await update.message.reply_text(answer)


async def answer_question_text(application: Application, question: str) -> str:
    groq_api_key: str = application.bot_data.get("groq_api_key", "")
    groq_model: str = application.bot_data.get("groq_model", "llama-3.1-8b-instant")
    if not groq_api_key:
        return "AI mode is not configured yet. Add GROQ_API_KEY to .env and restart the bot."

    answer = await generate_groq_text(
        groq_api_key,
        groq_model,
        (
            "You are a helpful coding and productivity assistant for a developer working with Flutter, Python, Django, FastAPI, and backend engineering. "
            "Give practical, concise answers with direct advice."
        ),
        question,
        max_completion_tokens=350,
    )
    if not answer:
        return "I could not reach the AI service right now. Please try again in a moment."
    return answer


async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    title = " ".join(context.args).strip()
    if not title:
        await update.message.reply_text("Use: /addtask Finish portfolio landing page")
        return

    timezone: ZoneInfo = context.application.bot_data["timezone"]
    profiles: dict[str, AssistantProfile] = context.application.bot_data["assistant_profiles"]
    profile = get_profile(context.application, update.effective_chat.id)
    task = TaskItem(
        id=next_id(profile.tasks),
        title=title,
        created_at=now_in_timezone(timezone).isoformat(),
    )
    profile.tasks.append(task)
    write_assistant_profiles(profiles)
    await update.message.reply_text(f"Task added: {task.id}. {task.title}")


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile = get_profile(context.application, update.effective_chat.id)
    await update.message.reply_text(format_tasks(profile), parse_mode=ParseMode.HTML)


async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Use: /done 2")
        return

    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task id should be a number, for example /done 2")
        return

    timezone: ZoneInfo = context.application.bot_data["timezone"]
    profiles: dict[str, AssistantProfile] = context.application.bot_data["assistant_profiles"]
    profile = get_profile(context.application, update.effective_chat.id)
    task = next((item for item in profile.tasks if item.id == task_id and not item.done), None)
    if task is None:
        await update.message.reply_text("I could not find that open task.")
        return

    task.done = True
    task.completed_at = now_in_timezone(timezone).isoformat()
    write_assistant_profiles(profiles)
    await update.message.reply_text(f"Nice. Task {task.id} marked as done.")


async def add_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args).strip()
    timezone: ZoneInfo = context.application.bot_data["timezone"]
    if not text:
        await update.message.reply_text("Use: /schedule 2026-04-25 18:30 | Client call")
        return

    try:
        scheduled_for, title = parse_schedule_input(text, timezone)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    profiles: dict[str, AssistantProfile] = context.application.bot_data["assistant_profiles"]
    profile = get_profile(context.application, update.effective_chat.id)
    item = ScheduleItem(
        id=next_id(profile.schedule),
        title=title,
        scheduled_for=scheduled_for.isoformat(),
    )
    profile.schedule.append(item)
    write_assistant_profiles(profiles)
    await update.message.reply_text(
        f"Scheduled: {item.id}. {item.title} at {scheduled_for.strftime('%b %d, %Y %H:%M')}"
    )


async def agenda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    timezone: ZoneInfo = context.application.bot_data["timezone"]
    profile = get_profile(context.application, update.effective_chat.id)
    ai_agenda = await build_ai_agenda_brief(context.application, profile, timezone)
    text = format_agenda(profile, timezone)
    if ai_agenda:
        text = f"<b>Today at a glance</b>\n{escape(ai_agenda)}\n\n{text}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def add_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Use: /note Follow up on deployment issue tomorrow")
        return

    timezone: ZoneInfo = context.application.bot_data["timezone"]
    profiles: dict[str, AssistantProfile] = context.application.bot_data["assistant_profiles"]
    profile = get_profile(context.application, update.effective_chat.id)
    note = NoteItem(
        id=next_id(profile.notes),
        text=text,
        created_at=now_in_timezone(timezone).isoformat(),
    )
    profile.notes.append(note)
    write_assistant_profiles(profiles)
    await update.message.reply_text(f"Saved note {note.id}.")


async def list_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile = get_profile(context.application, update.effective_chat.id)
    await update.message.reply_text(format_notes(profile), parse_mode=ParseMode.HTML)


async def set_job_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Send job keywords like: /setjobkeywords flutter dart python backend")
        return

    profiles: dict[str, AssistantProfile] = context.application.bot_data["assistant_profiles"]
    profile = get_profile(context.application, update.effective_chat.id)
    profile.job_keywords = normalize_topics(context.args)
    profile.seen_job_links = []
    write_assistant_profiles(profiles)
    await update.message.reply_text("Job keywords updated: " + ", ".join(profile.job_keywords))


async def alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profiles: dict[str, AssistantProfile] = context.application.bot_data["assistant_profiles"]
    profile = get_profile(context.application, update.effective_chat.id)
    choice = context.args[0].lower() if context.args else ""

    if choice == "on":
        profile.news_alerts_enabled = True
        profile.job_alerts_enabled = True
        write_assistant_profiles(profiles)
        await update.message.reply_text("Live tech news and job alerts are on.")
        return

    if choice == "off":
        profile.news_alerts_enabled = False
        profile.job_alerts_enabled = False
        write_assistant_profiles(profiles)
        await update.message.reply_text("Live tech news and job alerts are off.")
        return

    await update.message.reply_text(
        f"News alerts: {'on' if profile.news_alerts_enabled else 'off'}\n"
        f"Job alerts: {'on' if profile.job_alerts_enabled else 'off'}\n"
        f"Job keywords: {', '.join(profile.job_keywords)}"
    )


async def set_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Send topics like: /settopics flutter python django fastapi")
        return

    subscribers: dict[str, Subscriber] = context.application.bot_data["subscribers"]
    timezone: ZoneInfo = context.application.bot_data["timezone"]
    chat_id = str(update.effective_chat.id)
    subscriber = subscribers.get(chat_id, Subscriber(int(chat_id), "09:00"))
    subscriber.topics = normalize_topics(context.args)
    subscribers[chat_id] = subscriber
    write_subscribers(subscribers)
    schedule_subscriber(context.application, subscriber, timezone)

    await update.message.reply_text("Topics updated: " + ", ".join(subscriber.topics))


async def topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: dict[str, Subscriber] = context.application.bot_data["subscribers"]
    chat_id = str(update.effective_chat.id)
    subscriber = subscribers.get(chat_id, Subscriber(int(chat_id), "09:00"))
    await update.message.reply_text("Your topics: " + ", ".join(subscriber.topics))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    subscribers: dict[str, Subscriber] = context.application.bot_data["subscribers"]
    timezone: ZoneInfo = context.application.bot_data["timezone"]
    chat_id = str(update.effective_chat.id)
    subscriber = subscribers.get(chat_id)
    profile = get_profile(context.application, update.effective_chat.id)

    reminder_text = subscriber.reminder_time if subscriber else "not subscribed"
    next_event = None
    for item in sorted(profile.schedule, key=lambda entry: entry.scheduled_for):
        when = datetime.fromisoformat(item.scheduled_for)
        if not item.done and when >= now_in_timezone(timezone):
            next_event = f"{when.strftime('%b %d %H:%M')} - {item.title}"
            break

    text = (
        f"Reminder time: {reminder_text}\n"
        f"Open tasks: {len([task for task in profile.tasks if not task.done])}\n"
        f"Saved notes: {len(profile.notes)}\n"
        f"Next event: {next_event or 'none scheduled'}\n"
        f"Tech alerts: {'on' if profile.news_alerts_enabled else 'off'}\n"
        f"Job alerts: {'on' if profile.job_alerts_enabled else 'off'}"
    )
    await update.message.reply_text(text)


async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None or not message.text:
        return

    text = message.text.strip()
    chat_id = update.effective_chat.id
    timezone: ZoneInfo = context.application.bot_data["timezone"]
    profiles: dict[str, AssistantProfile] = context.application.bot_data["assistant_profiles"]
    subscribers: dict[str, Subscriber] = context.application.bot_data["subscribers"]
    profile = get_profile(context.application, chat_id)

    parsed = await parse_chat_intent(context.application, chat_id, text, timezone)
    intent_data = parsed or fallback_intent(text)
    intent = str(intent_data.get("intent", "unknown")).strip().lower()

    if intent == "news":
        topics_list = subscribers.get(str(chat_id), Subscriber(chat_id, "09:00")).topics
        news_items = await fetch_news_async(topics_list)
        await message.reply_text(format_news(news_items), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return

    if intent == "brief":
        topics_list = subscribers.get(str(chat_id), Subscriber(chat_id, "09:00")).topics
        news_items = await fetch_news_async(topics_list, limit=5)
        ai_brief = await build_ai_news_brief(context.application, topics_list, news_items)
        response = f"{format_ai_brief(ai_brief)}\n\n{format_news(news_items)}" if ai_brief else format_news(news_items)
        await message.reply_text(response, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return

    if intent == "jobs":
        job_items = await fetch_jobs_async(profile.job_keywords, limit=6)
        await message.reply_text(format_jobs(job_items), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return

    if intent == "agenda":
        ai_agenda = await build_ai_agenda_brief(context.application, profile, timezone)
        response = format_agenda(profile, timezone)
        if ai_agenda:
            response = f"<b>Today at a glance</b>\n{escape(ai_agenda)}\n\n{response}"
        await message.reply_text(response, parse_mode=ParseMode.HTML)
        return

    if intent == "task_list":
        await message.reply_text(format_tasks(profile), parse_mode=ParseMode.HTML)
        return

    if intent == "task_add":
        title = (
            str(intent_data.get("title", "")).strip()
            or str(intent_data.get("question", "")).strip()
            or text
        )
        task = TaskItem(
            id=next_id(profile.tasks),
            title=title,
            created_at=now_in_timezone(timezone).isoformat(),
        )
        profile.tasks.append(task)
        write_assistant_profiles(profiles)
        await message.reply_text(f"Task added: {task.id}. {task.title}")
        return

    if intent == "task_done":
        task_id_value = intent_data.get("task_id", 0)
        try:
            task_id = int(task_id_value)
        except (TypeError, ValueError):
            task_id = 0

        task = next((item for item in profile.tasks if item.id == task_id and not item.done), None)
        if task is None:
            await message.reply_text("I could not tell which task to mark done. Try something like 'mark task 2 done'.")
            return
        task.done = True
        task.completed_at = now_in_timezone(timezone).isoformat()
        write_assistant_profiles(profiles)
        await message.reply_text(f"Task {task.id} marked as done.")
        return

    if intent == "schedule_add":
        title = (
            str(intent_data.get("title", "")).strip()
            or str(intent_data.get("question", "")).strip()
        )
        datetime_text = str(intent_data.get("datetime", "")).strip()
        if not title or not datetime_text:
            await message.reply_text(
                "I can set that reminder, but I need a clearer time. Try: remind me tomorrow at 8 pm to practice Django."
            )
            return
        try:
            scheduled_for = parse_datetime_text(datetime_text, timezone)
        except ValueError:
            await message.reply_text(
                "I understood this as a reminder, but the time was unclear. Try: remind me on 2026-04-25 18:30 to join the client call."
            )
            return

        item = ScheduleItem(
            id=next_id(profile.schedule),
            title=title,
            scheduled_for=scheduled_for.isoformat(),
        )
        profile.schedule.append(item)
        write_assistant_profiles(profiles)
        await message.reply_text(
            f"Reminder set: {item.id}. {item.title} at {scheduled_for.strftime('%b %d, %Y %H:%M')}"
        )
        return

    if intent == "note_add":
        note_text = str(intent_data.get("title", "")).strip() or text
        note = NoteItem(
            id=next_id(profile.notes),
            text=note_text,
            created_at=now_in_timezone(timezone).isoformat(),
        )
        profile.notes.append(note)
        write_assistant_profiles(profiles)
        await message.reply_text(f"Saved note {note.id}.")
        return

    if intent == "notes":
        await message.reply_text(format_notes(profile), parse_mode=ParseMode.HTML)
        return

    if intent == "topics_set":
        topics_values = intent_data.get("topics", [])
        if isinstance(topics_values, list):
            topics_list = normalize_topics([str(item) for item in topics_values])
        else:
            topics_list = DEFAULT_TOPICS.copy()
        subscriber = subscribers.get(str(chat_id), Subscriber(chat_id, "09:00"))
        subscriber.topics = topics_list
        subscribers[str(chat_id)] = subscriber
        write_subscribers(subscribers)
        schedule_subscriber(context.application, subscriber, timezone)
        await message.reply_text("Topics updated: " + ", ".join(subscriber.topics))
        return

    if intent == "alerts_on":
        profile.news_alerts_enabled = True
        profile.job_alerts_enabled = True
        write_assistant_profiles(profiles)
        await message.reply_text("Live tech news and job alerts are on.")
        return

    if intent == "alerts_off":
        profile.news_alerts_enabled = False
        profile.job_alerts_enabled = False
        write_assistant_profiles(profiles)
        await message.reply_text("Live tech news and job alerts are off.")
        return

    if intent == "status":
        subscriber = subscribers.get(str(chat_id))
        next_event = None
        for item in sorted(profile.schedule, key=lambda entry: entry.scheduled_for):
            when = datetime.fromisoformat(item.scheduled_for)
            if not item.done and when >= now_in_timezone(timezone):
                next_event = f"{when.strftime('%b %d %H:%M')} - {item.title}"
                break
        response = (
            f"Reminder time: {subscriber.reminder_time if subscriber else 'not subscribed'}\n"
            f"Open tasks: {len([task for task in profile.tasks if not task.done])}\n"
            f"Saved notes: {len(profile.notes)}\n"
            f"Next event: {next_event or 'none scheduled'}"
        )
        await message.reply_text(response)
        return

    question_text = str(intent_data.get("question", "")).strip() or text
    answer = await answer_question_text(context.application, question_text)
    await message.reply_text(answer)


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)


def build_application() -> Application:
    token, timezone, default_time, groq_api_key, groq_model = load_config()
    subscribers = read_subscribers()
    profiles = read_assistant_profiles()
    application = Application.builder().token(token).post_init(post_init).build()
    application.bot_data["subscribers"] = subscribers
    application.bot_data["assistant_profiles"] = profiles
    application.bot_data["timezone"] = timezone
    application.bot_data["default_time"] = default_time
    application.bot_data["groq_api_key"] = groq_api_key
    application.bot_data["groq_model"] = groq_model

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("news", news))
    application.add_handler(CommandHandler("brief", brief))
    application.add_handler(CommandHandler("ask", ask))
    application.add_handler(CommandHandler("jobs", jobs))
    application.add_handler(CommandHandler("addtask", add_task))
    application.add_handler(CommandHandler("tasks", list_tasks))
    application.add_handler(CommandHandler("done", complete_task))
    application.add_handler(CommandHandler("schedule", add_schedule))
    application.add_handler(CommandHandler("agenda", agenda))
    application.add_handler(CommandHandler("note", add_note))
    application.add_handler(CommandHandler("notes", list_notes))
    application.add_handler(CommandHandler("setjobkeywords", set_job_keywords))
    application.add_handler(CommandHandler("alerts", alerts))
    application.add_handler(CommandHandler("settopics", set_topics))
    application.add_handler(CommandHandler("topics", topics))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_message))

    for subscriber in subscribers.values():
        schedule_subscriber(application, subscriber, timezone)

    application.job_queue.run_repeating(
        send_due_schedule_reminders,
        interval=60,
        first=10,
        name="due_schedule_reminders",
    )
    application.job_queue.run_repeating(
        poll_live_alerts,
        interval=300,
        first=15,
        name="live_alerts",
    )
    return application


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        level=logging.INFO,
    )
    application = build_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
