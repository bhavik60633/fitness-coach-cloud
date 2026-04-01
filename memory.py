"""
memory_cloud.py — Cloud-ready persistent memory using Supabase PostgreSQL.

Replaces SQLite with Supabase for 24/7 cloud deployment.
All data persists even when the server restarts.
"""

import json
import os
from datetime import date, datetime, timedelta
from typing import Any

from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


class CoachMemory:
    """Supabase-backed memory for the fitness coach (cloud-ready)."""

    def __init__(self) -> None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set in environment!"
            )
        self.db: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅  Supabase memory connected")

    # ── Conversation history ──────────────────────────────────────────────

    def save_message(self, user_id: str, role: str, message: str) -> None:
        self.db.table("conversations").insert({
            "user_id": user_id,
            "role": role,
            "message": message,
        }).execute()

    def get_recent_history(self, user_id: str, limit: int = 20) -> list[dict]:
        """Return the last `limit` messages, oldest first."""
        result = (
            self.db.table("conversations")
            .select("role, message, timestamp")
            .eq("user_id", user_id)
            .order("timestamp", desc=True)
            .limit(limit)
            .execute()
        )
        rows = result.data if result.data else []
        return list(reversed(rows))

    def get_history_summary(self, user_id: str) -> str:
        """Format recent history as a readable string for the prompt."""
        history = self.get_recent_history(user_id, limit=16)
        if not history:
            return "No previous conversation."
        lines = []
        for h in history:
            role = "Bhavik" if h["role"] == "user" else "Coach"
            lines.append(f"{role}: {h['message']}")
        return "\n".join(lines)

    def get_all_history_count(self, user_id: str) -> int:
        result = (
            self.db.table("conversations")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .execute()
        )
        return result.count if result.count else 0

    # ── User profile & goals ──────────────────────────────────────────────

    def get_profile(self, user_id: str) -> dict | None:
        result = (
            self.db.table("user_profile")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    def upsert_profile(self, user_id: str, **kwargs: Any) -> None:
        data = {"user_id": user_id, **kwargs}
        data["updated_at"] = datetime.utcnow().isoformat()
        self.db.table("user_profile").upsert(data).execute()

    def format_goal_context(self, user_id: str) -> str:
        """Return a short goal summary string to include in prompts."""
        p = self.get_profile(user_id)
        if not p or not p.get("goal_summary"):
            return "No goal set yet."

        lines = [f"Goal: {p['goal_summary']}"]
        if p.get("goal_start_date") and p.get("goal_end_date"):
            start = date.fromisoformat(p["goal_start_date"])
            end = date.fromisoformat(p["goal_end_date"])
            today = date.today()
            days_done = max(0, (today - start).days)
            days_left = max(0, (end - today).days)
            lines.append(
                f"Progress: Day {days_done} of {p['goal_days_total']} "
                f"({days_left} days remaining)"
            )
        if p.get("current_weight") and p.get("target_weight"):
            diff = round(p["current_weight"] - p["target_weight"], 1)
            lines.append(
                f"Weight: {p['current_weight']} kg "
                f"(target {p['target_weight']} kg, {diff} kg to go)"
            )
        if p.get("current_plan"):
            try:
                plan = json.loads(p["current_plan"])
                lines.append(f"Current plan: {plan.get('summary', 'custom plan')}")
            except Exception:
                pass
        return "\n".join(lines)

    # ── Daily logs ────────────────────────────────────────────────────────

    def log_today(self, user_id: str, **kwargs: Any) -> None:
        today = date.today().isoformat()

        # Check if log exists
        result = (
            self.db.table("daily_logs")
            .select("id")
            .eq("user_id", user_id)
            .eq("log_date", today)
            .execute()
        )

        if result.data and len(result.data) > 0:
            # Update existing
            self.db.table("daily_logs").update(kwargs).eq(
                "id", result.data[0]["id"]
            ).execute()
        else:
            # Insert new
            data = {"user_id": user_id, "log_date": today, **kwargs}
            self.db.table("daily_logs").insert(data).execute()

    def get_recent_logs(self, user_id: str, days: int = 7) -> list[dict]:
        result = (
            self.db.table("daily_logs")
            .select("*")
            .eq("user_id", user_id)
            .order("log_date", desc=True)
            .limit(days)
            .execute()
        )
        return result.data if result.data else []

    def has_logged_today(self, user_id: str) -> bool:
        today = date.today().isoformat()
        result = (
            self.db.table("daily_logs")
            .select("id")
            .eq("user_id", user_id)
            .eq("log_date", today)
            .execute()
        )
        return bool(result.data and len(result.data) > 0)

    def format_recent_logs(self, user_id: str, days: int = 7) -> str:
        """Format last N days' logs for the coach prompt."""
        logs = self.get_recent_logs(user_id, days)
        if not logs:
            return "No recent logs."
        lines = []
        for log in logs:
            status = "✅ Trained" if log.get("workout_done") else "❌ Skipped"
            parts = [f"{log['log_date']}: {status}"]
            if log.get("workout_notes"):
                parts.append(f"  Notes: {log['workout_notes']}")
            if log.get("weight"):
                parts.append(f"  Weight: {log['weight']} kg")
            if log.get("energy_level"):
                parts.append(f"  Energy: {log['energy_level']}/10")
            if log.get("sleep_hours"):
                parts.append(f"  Sleep: {log['sleep_hours']}h")
            lines.append("\n".join(parts))
        return "\n\n".join(lines)

    def get_streak(self, user_id: str) -> int:
        """Count current consecutive days with workout_done = 1."""
        logs = self.get_recent_logs(user_id, days=60)
        if not logs:
            return 0
        streak = 0
        today = date.today()
        for log in logs:
            log_date = date.fromisoformat(log["log_date"])
            expected = today - timedelta(days=streak)
            if log_date == expected and log.get("workout_done"):
                streak += 1
            else:
                break
        return streak

    # ── Reminders ────────────────────────────────────────────────────────

    def set_reminder(
        self,
        user_id: str,
        reminder_type: str,
        hour: int,
        minute: int,
    ) -> None:
        self.db.table("reminders").upsert({
            "user_id": user_id,
            "reminder_type": reminder_type,
            "hour": hour,
            "minute": minute,
            "enabled": True,
        }).execute()

    def get_all_reminders(self) -> list[dict]:
        result = (
            self.db.table("reminders")
            .select("*")
            .eq("enabled", True)
            .execute()
        )
        return result.data if result.data else []

    # ── Food / calorie logs ───────────────────────────────────────────────

    def save_food_log(
        self,
        user_id: str,
        meal_name: str,
        food_description: str,
        calories: int,
        protein_g: float = 0,
        carbs_g: float = 0,
        fat_g: float = 0,
        image_analyzed: bool = False,
        notes: str = "",
    ) -> str:
        """Save a food entry. Returns its UUID."""
        result = self.db.table("food_logs").insert({
            "user_id": user_id,
            "log_date": date.today().isoformat(),
            "meal_name": meal_name,
            "food_description": food_description,
            "calories": calories,
            "protein_g": protein_g,
            "carbs_g": carbs_g,
            "fat_g": fat_g,
            "image_analyzed": image_analyzed,
            "notes": notes,
        }).execute()
        return result.data[0]["id"] if result.data else ""

    def update_food_log(self, log_id: str, **kwargs: Any) -> None:
        kwargs["updated_at"] = datetime.utcnow().isoformat()
        self.db.table("food_logs").update(kwargs).eq("id", log_id).execute()

    def delete_food_log(self, log_id: str) -> None:
        self.db.table("food_logs").delete().eq("id", log_id).execute()

    def get_food_logs_by_date(self, user_id: str, log_date: str | None = None) -> list[dict]:
        if not log_date:
            log_date = date.today().isoformat()
        result = (
            self.db.table("food_logs")
            .select("*")
            .eq("user_id", user_id)
            .eq("log_date", log_date)
            .order("created_at", desc=False)
            .execute()
        )
        return result.data if result.data else []

    def get_daily_calorie_total(self, user_id: str, log_date: str | None = None) -> dict:
        logs = self.get_food_logs_by_date(user_id, log_date)
        total: dict = {"calories": 0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "entries": len(logs)}
        for log in logs:
            total["calories"]  += log.get("calories")  or 0
            total["protein_g"] += log.get("protein_g") or 0
            total["carbs_g"]   += log.get("carbs_g")   or 0
            total["fat_g"]     += log.get("fat_g")     or 0
        return total

    def format_food_logs_today(self, user_id: str) -> str:
        logs = self.get_food_logs_by_date(user_id)
        if not logs:
            return "No food logged today yet."
        lines = []
        for i, log in enumerate(logs, 1):
            src = "📷" if log.get("image_analyzed") else "✏️"
            line = f"{i}. {src} *{log['meal_name']}* — {log['food_description']} ({log['calories']} kcal)"
            if log.get("protein_g") or log.get("carbs_g") or log.get("fat_g"):
                line += f"\n   P:{log.get('protein_g',0):.0f}g C:{log.get('carbs_g',0):.0f}g F:{log.get('fat_g',0):.0f}g"
            lines.append(line)
        total = self.get_daily_calorie_total(user_id)
        lines.append(
            f"\n📊 *Daily Total: {total['calories']} kcal*\n"
            f"Protein: {total['protein_g']:.0f}g | Carbs: {total['carbs_g']:.0f}g | Fat: {total['fat_g']:.0f}g"
        )
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════════
    # BRAIN INTEGRATION — Coach thoughts, follow-ups, and pattern tracking
    # ══════════════════════════════════════════════════════════════════════

    # ── Coach Thoughts (brain's reasoning chain) ─────────────────────────

    def save_coach_thought(
        self,
        user_id: str,
        thought_type: str,
        content: str,
        context_snapshot: str = "",
    ) -> None:
        """Persist a single thought from the brain's reasoning chain."""
        self.db.table("coach_thoughts").insert({
            "user_id": user_id,
            "thought_type": thought_type,
            "content": content,
            "context_snapshot": context_snapshot,
        }).execute()

    def get_recent_thoughts(
        self, user_id: str, limit: int = 10
    ) -> list[dict]:
        """Get the brain's recent thoughts for a user."""
        result = (
            self.db.table("coach_thoughts")
            .select("thought_type, content, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        rows = result.data if result.data else []
        return list(reversed(rows))

    # ── Follow-up Queue ──────────────────────────────────────────────────

    def queue_followup(
        self,
        user_id: str,
        followup_type: str,
        message: str,
        scheduled_at: str,
        trigger_reason: str = "",
        priority: int = 5,
    ) -> None:
        """Add a proactive follow-up to the queue."""
        self.db.table("followup_queue").insert({
            "user_id": user_id,
            "followup_type": followup_type,
            "message": message,
            "scheduled_at": scheduled_at,
            "trigger_reason": trigger_reason,
            "priority": priority,
        }).execute()

    def get_due_followups(self) -> list[dict]:
        """Get all follow-ups that are due (scheduled_at <= now, not yet sent)."""
        now = datetime.utcnow().isoformat()
        result = (
            self.db.table("followup_queue")
            .select("*")
            .eq("sent", False)
            .lte("scheduled_at", now)
            .order("priority", desc=False)
            .limit(20)
            .execute()
        )
        return result.data if result.data else []

    def mark_followup_sent(self, followup_id: str) -> None:
        """Mark a follow-up as sent."""
        self.db.table("followup_queue").update({
            "sent": True,
            "sent_at": datetime.utcnow().isoformat(),
        }).eq("id", followup_id).execute()

    def cancel_followups(self, user_id: str, followup_type: str) -> None:
        """Cancel all pending follow-ups of a specific type."""
        self.db.table("followup_queue").update({
            "sent": True,
            "sent_at": datetime.utcnow().isoformat(),
        }).eq("user_id", user_id).eq("followup_type", followup_type).eq(
            "sent", False
        ).execute()

    def cancel_all_followups(self, user_id: str) -> None:
        """Cancel all pending follow-ups for a user."""
        self.db.table("followup_queue").update({
            "sent": True,
            "sent_at": datetime.utcnow().isoformat(),
        }).eq("user_id", user_id).eq("sent", False).execute()

    def get_last_followup_time(
        self, user_id: str, followup_type: str
    ) -> str | None:
        """When was the last follow-up of this type sent or queued?"""
        result = (
            self.db.table("followup_queue")
            .select("scheduled_at")
            .eq("user_id", user_id)
            .eq("followup_type", followup_type)
            .order("scheduled_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data and result.data[0]:
            return result.data[0].get("scheduled_at")
        return None

    def count_pending_followups(self, user_id: str) -> int:
        """Count unsent follow-ups for a user."""
        result = (
            self.db.table("followup_queue")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("sent", False)
            .execute()
        )
        return result.count if result.count else 0

    # ── User Patterns ────────────────────────────────────────────────────

    def upsert_pattern(
        self,
        user_id: str,
        pattern_type: str,
        pattern_data: str,
        confidence: float = 0.5,
    ) -> None:
        """Insert or update a behavioral pattern."""
        self.db.table("user_patterns").upsert({
            "user_id": user_id,
            "pattern_type": pattern_type,
            "pattern_data": pattern_data,
            "confidence": confidence,
            "last_updated": datetime.utcnow().isoformat(),
        }).execute()

    def get_pattern(self, user_id: str, pattern_type: str) -> dict | None:
        """Retrieve a specific pattern."""
        result = (
            self.db.table("user_patterns")
            .select("*")
            .eq("user_id", user_id)
            .eq("pattern_type", pattern_type)
            .execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    def get_all_patterns(self, user_id: str) -> list[dict]:
        """Retrieve all learned patterns for a user."""
        result = (
            self.db.table("user_patterns")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        return result.data if result.data else []
