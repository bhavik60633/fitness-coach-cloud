# -*- coding: utf-8 -*-
"""
conversation_exporter.py

Exports Supabase conversations into structured daily notes.

Storage strategy:
  - PRIMARY: saves to Supabase `conversation_notes` table (survives Railway restarts)
  - SECONDARY: also writes to Obsidian vault if OBSIDIAN_VAULT_PATH is accessible

These notes are then ingested into ChromaDB so the agent can search full history.

Run manually:   python conversation_exporter.py
Auto-trigger:   called from telegram_bot.py every 10 messages
"""

import os
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

OBSIDIAN_VAULT = os.getenv("OBSIDIAN_VAULT_PATH", "")
CONVERSATIONS_DIR = Path(OBSIDIAN_VAULT) / "Conversations" if OBSIDIAN_VAULT else None

# Topic keyword map
TOPIC_KEYWORDS = {
    "Workout":    ["workout", "train", "exercise", "session", "gym", "lift", "reps", "sets", "squat", "bench", "deadlift", "push", "pull"],
    "Nutrition":  ["eat", "food", "calories", "protein", "carbs", "fat", "meal", "diet", "recipe", "macro", "calorie", "hungry", "snack"],
    "Sleep":      ["sleep", "rest", "tired", "fatigue", "bed", "wake", "hours", "recovery", "insomnia"],
    "Weight":     ["weight", "kg", "scale", "fat loss", "cut", "bulk", "lean", "body"],
    "Motivation": ["motivat", "discipline", "mindset", "habit", "goal", "streak", "miss", "skip", "lazy"],
    "Progress":   ["progress", "week", "review", "check", "update", "log", "improve", "result"],
    "Plan":       ["plan", "program", "schedule", "routine", "adjust", "change", "modify"],
}


def detect_topics(messages: list[dict]) -> list[str]:
    full_text = " ".join(m.get("message", "").lower() for m in messages)
    found = [topic for topic, kws in TOPIC_KEYWORDS.items() if any(kw in full_text for kw in kws)]
    return found or ["General"]


def group_by_date(messages: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for msg in messages:
        ts = msg.get("timestamp", "")
        day = ts[:10] if ts else date.today().isoformat()
        groups.setdefault(day, []).append(msg)
    return groups


def format_conversation_note(day: str, messages: list[dict], user_name: str = "Bhavik") -> str:
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
        "## Topics Covered",
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

    coach_msgs = [m["message"] for m in messages if m.get("role") == "coach"]
    if coach_msgs:
        lines += ["## Coach Observations", ""]
        for cm in coach_msgs[:3]:
            summary = cm[:200].replace("\n", " ")
            lines.append(f"- {summary}...")
            lines.append("")

    lines += ["---", "", f"*Exported automatically - {len(messages)} messages*"]
    return "\n".join(lines)


def export_conversations(memory, user_id: str, days: int = 30) -> int:
    """
    Pull conversations from Supabase, write structured notes.
    Saves to Supabase (persistent) + Obsidian (if available).
    Returns number of notes written.
    """
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

    try:
        profile = memory.get_profile(user_id)
        user_name = profile.get("name", "Bhavik") if profile else "Bhavik"
    except Exception:
        user_name = "Bhavik"

    written = 0
    for day, day_messages in sorted(grouped.items()):
        topics = detect_topics(day_messages)
        content = format_conversation_note(day, day_messages, user_name)

        # 1. Save to Supabase (always — survives Railway restarts)
        try:
            memory.db.table("conversation_notes").upsert({
                "user_id": user_id,
                "note_date": day,
                "topics": ", ".join(topics),
                "content": content,
                "msg_count": len(day_messages),
                "updated_at": datetime.utcnow().isoformat(),
            }).execute()
            print(f"  Saved to Supabase: Chat - {day} ({len(day_messages)} messages)")
        except Exception as exc:
            print(f"  Supabase save failed for {day}: {exc}")

        # 2. Write to Obsidian vault if accessible (local dev / volume mount)
        if CONVERSATIONS_DIR:
            try:
                CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
                note_path = CONVERSATIONS_DIR / f"Chat - {day}.md"
                note_path.write_text(content, encoding="utf-8")
                print(f"  Wrote Obsidian: Chat - {day}.md")
            except Exception as exc:
                print(f"  Obsidian write skipped ({exc})")

        written += 1

    # Update Obsidian index if vault is accessible
    if CONVERSATIONS_DIR:
        _update_obsidian_index(grouped)

    print(f"\nExported {written} conversation notes.")

    # Re-ingest conversation notes into ChromaDB
    _reingest_notes(memory, user_id)

    return written


def _reingest_notes(memory, user_id: str) -> None:
    """Pull notes from Supabase and add them to ChromaDB."""
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
        import hashlib

        db_path = os.getenv("CHROMA_DB_PATH", "./chroma_db")
        client = chromadb.PersistentClient(path=db_path)
        try:
            collection = client.get_collection("fitness_docs")
        except Exception:
            print("  ChromaDB collection not found — skipping note re-ingest.")
            return

        embedder = SentenceTransformer("all-MiniLM-L6-v2")

        result = (
            memory.db.table("conversation_notes")
            .select("note_date, topics, content")
            .eq("user_id", user_id)
            .order("note_date", desc=True)
            .limit(90)
            .execute()
        )
        notes = result.data if result.data else []

        added = 0
        for note in notes:
            text = note["content"]
            words = text.split()
            if len(words) < 20:
                continue
            doc_id = hashlib.md5(f"conv_note_{user_id}_{note['note_date']}".encode()).hexdigest()
            emb = embedder.encode(text[:2000]).tolist()
            collection.upsert(
                embeddings=[emb],
                documents=[text[:2000]],
                ids=[doc_id],
                metadatas=[{
                    "source": f"Chat - {note['note_date']}.md",
                    "folder": "Conversations",
                    "type": "conversation_note",
                    "topics": note.get("topics", ""),
                    "chunk_index": 0,
                }],
            )
            added += 1

        print(f"  Re-ingested {added} conversation notes into ChromaDB.")
    except Exception as exc:
        print(f"  ChromaDB re-ingest skipped: {exc}")


def _update_obsidian_index(grouped: dict[str, list]) -> None:
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
        lines.append(f"- [[Conversations/Chat - {day}|{weekday} {day}]] - {', '.join(topics)} ({len(msgs)} messages)")

    lines += [
        "", "---", "", "## Topics", "",
        "- [[Workout]]", "- [[Nutrition]]", "- [[Sleep]]",
        "- [[Weight]]", "- [[Motivation]]", "- [[Progress]]", "- [[Plan]]",
    ]
    try:
        index_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  Updated: Conversations Index.md")
    except Exception as exc:
        print(f"  Obsidian index skipped: {exc}")


if __name__ == "__main__":
    from memory import CoachMemory

    user_id = os.getenv("TELEGRAM_USER_ID", "")
    if not user_id:
        print("Set TELEGRAM_USER_ID in .env to export conversations.")
    else:
        memory = CoachMemory()
        export_conversations(memory, user_id, days=90)
        print("\nDone.")
