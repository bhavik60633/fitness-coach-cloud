# -*- coding: utf-8 -*-
"""
conversation_exporter.py

Exports Supabase conversations into structured Obsidian markdown notes.
Each day gets its own note, tagged by topic, linked to the graph.

Run manually:   python conversation_exporter.py
Auto-trigger:   called from telegram_bot.py after each session
"""

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

OBSIDIAN_VAULT = os.getenv(
    "OBSIDIAN_VAULT_PATH",
    r"C:\Users\PC\OneDrive\Documents\Obsidian Vault"
)
CONVERSATIONS_DIR = Path(OBSIDIAN_VAULT) / "Conversations"

# Topic keyword map — message -> tag
TOPIC_KEYWORDS = {
    "Workout":    ["workout", "train", "exercise", "session", "gym", "lift", "reps", "sets", "squat", "bench", "deadlift", "push", "pull"],
    "Nutrition":  ["eat", "food", "calories", "protein", "carbs", "fat", "meal", "diet", "recipe", "macro", "calorie", "hungry", "snack"],
    "Sleep":      ["sleep", "rest", "tired", "fatigue", "bed", "wake", "hours", "recovery", "insomnia"],
    "Weight":     ["weight", "kg", "scale", "fat loss", "cut", "bulk", "lean", "body"],
    "Motivation": ["motivat", "discipline", "mindset", "habit", "goal", "streak", "miss", "skip", "lazy", "tired"],
    "Progress":   ["progress", "week", "review", "check", "update", "log", "improve", "result"],
    "Plan":       ["plan", "program", "schedule", "routine", "adjust", "change", "modify"],
}


def detect_topics(messages: list[dict]) -> list[str]:
    """Detect which topics appear in a conversation."""
    full_text = " ".join(m.get("message", "").lower() for m in messages)
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in full_text for kw in keywords):
            found.append(topic)
    return found or ["General"]


def group_by_date(messages: list[dict]) -> dict[str, list[dict]]:
    """Group messages by date string YYYY-MM-DD."""
    groups: dict[str, list[dict]] = {}
    for msg in messages:
        ts = msg.get("timestamp", "")
        if ts:
            day = ts[:10]
        else:
            day = date.today().isoformat()
        groups.setdefault(day, []).append(msg)
    return groups


def format_conversation_note(day: str, messages: list[dict], user_name: str = "Bhavik") -> str:
    """Build an Obsidian markdown note for one day's conversation."""
    topics = detect_topics(messages)
    topic_links = " ".join(f"[[{t}]]" for t in topics)
    weekday = datetime.fromisoformat(day).strftime("%A")

    lines = [
        f"# Conversation - {day} ({weekday})",
        "",
        f"Tags: {topic_links}  [[Conversations Index]]  [[Trainers & Coaches]]",
        "",
        "---",
        "",
        f"## Topics Covered",
        ", ".join(topics),
        "",
        "## Exchanges",
        "",
    ]

    for msg in messages:
        role = user_name if msg.get("role") == "user" else "Coach"
        ts = msg.get("timestamp", "")[:16] if msg.get("timestamp") else ""
        text = msg.get("message", "").strip()
        if text:
            lines.append(f"**[{ts}] {role}:** {text}")
            lines.append("")

    # Key insights section — pull coach messages as observations
    coach_msgs = [m["message"] for m in messages if m.get("role") == "coach"]
    if coach_msgs:
        lines += [
            "## Coach Observations",
            "",
        ]
        for cm in coach_msgs[:3]:  # top 3 coach responses as reference
            summary = cm[:200].replace("\n", " ")
            lines.append(f"- {summary}...")
            lines.append("")

    lines += [
        "---",
        "",
        f"*Exported automatically — {len(messages)} messages*",
    ]

    return "\n".join(lines)


def export_conversations(memory, user_id: str, days: int = 30) -> int:
    """
    Pull conversations from Supabase, write structured Obsidian notes.
    Returns number of notes written.
    """
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)

    # Pull all messages for the period
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    result = (
        memory.db.table("conversations")
        .select("role, message, timestamp")
        .eq("user_id", user_id)
        .gte("timestamp", cutoff)
        .order("timestamp", desc=False)
        .execute()
    )
    messages = result.data if result.data else []

    if not messages:
        print(f"No conversations found for user {user_id} in last {days} days.")
        return 0

    grouped = group_by_date(messages)
    written = 0

    # Get user name from profile
    try:
        profile = memory.get_profile(user_id)
        user_name = profile.get("name", "Bhavik") if profile else "Bhavik"
    except Exception:
        user_name = "Bhavik"

    for day, day_messages in sorted(grouped.items()):
        note_path = CONVERSATIONS_DIR / f"Chat - {day}.md"
        content = format_conversation_note(day, day_messages, user_name)
        note_path.write_text(content, encoding="utf-8")
        print(f"  Wrote: Chat - {day}.md ({len(day_messages)} messages)")
        written += 1

    # Update the Conversations Index note
    _update_index(grouped, user_name)

    print(f"\nExported {written} conversation notes to Obsidian.")
    return written


def _update_index(grouped: dict[str, list], user_name: str) -> None:
    """Rebuild the Conversations Index note with links to all days."""
    index_path = Path(OBSIDIAN_VAULT) / "Conversations Index.md"

    days_sorted = sorted(grouped.keys(), reverse=True)

    lines = [
        "# Conversations Index",
        "",
        "Part of [[Fitness Hub]] | [[Trainers & Coaches]]",
        "",
        "All coaching conversations, organized by date.",
        "",
        "---",
        "",
        "## All Sessions",
        "",
    ]

    for day in days_sorted:
        msgs = grouped[day]
        topics = detect_topics(msgs)
        weekday = datetime.fromisoformat(day).strftime("%A")
        topic_str = ", ".join(topics)
        lines.append(f"- [[Conversations/Chat - {day}|{weekday} {day}]] — {topic_str} ({len(msgs)} messages)")

    lines += [
        "",
        "---",
        "",
        "## Topics",
        "",
        "- [[Workout]]",
        "- [[Nutrition]]",
        "- [[Sleep]]",
        "- [[Weight]]",
        "- [[Motivation]]",
        "- [[Progress]]",
        "- [[Plan]]",
    ]

    index_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Updated: Conversations Index.md")


if __name__ == "__main__":
    from memory import CoachMemory

    user_id = os.getenv("TELEGRAM_USER_ID", "")
    if not user_id:
        print("Set TELEGRAM_USER_ID in .env to export conversations.")
    else:
        memory = CoachMemory()
        export_conversations(memory, user_id, days=90)
        print("\nDone. Now run: python ingest.py to re-index into ChromaDB.")
