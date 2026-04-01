"""
followup_engine.py — Proactive follow-up system.

Inspired by Claw Code's ExecutionRegistry + SessionStore patterns:
- Queues proactive messages for the user
- Deduplicates — won't spam the same type of follow-up
- Priority system — urgent messages go first
- Cooldown logic — respects spacing between messages
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# Minimum hours between same followup type
COOLDOWN_HOURS = {
    "streak_check":   12,
    "soreness_check": 20,
    "meal_reminder":  4,
    "motivation":     24,
    "weigh_in":       48,
    "water":          3,
    "sleep":          20,
}

# Max pending followups per user (prevent queue flooding)
MAX_PENDING_PER_USER = 5


class FollowupEngine:
    """
    Manages the proactive follow-up queue.

    Flow:
    1. CoachBrain generates followup_actions during reasoning
    2. FollowupEngine queues them (with dedup + cooldown checks)
    3. SmartScheduler pulls from the queue and sends at the right time
    """

    def __init__(self, memory) -> None:
        self.memory = memory

    def queue_followups(self, user_id: str, actions: list[dict]) -> int:
        """
        Queue a batch of follow-up actions from the brain.

        Each action dict has:
        - type: str (followup type)
        - delay_hours: float (hours from now)
        - message: str (what to send)
        - priority: int (1=urgent, 10=low)
        - reason: str (why this was triggered)

        Returns the number of actions actually queued.
        """
        queued = 0

        for action in actions:
            ftype = action.get("type", "")
            delay = action.get("delay_hours", 1)
            message = action.get("message", "")
            priority = action.get("priority", 5)
            reason = action.get("reason", "")

            if not ftype or not message:
                continue

            # Check cooldown — don't send same type too often
            if self._is_on_cooldown(user_id, ftype):
                logger.info(f"Followup '{ftype}' on cooldown for {user_id} — skipping")
                continue

            # Check max pending
            pending = self._count_pending(user_id)
            if pending >= MAX_PENDING_PER_USER:
                logger.info(f"Max pending ({MAX_PENDING_PER_USER}) reached for {user_id} — skipping")
                break

            # Calculate scheduled time
            scheduled_at = datetime.utcnow() + timedelta(hours=delay)

            # Queue it
            try:
                self.memory.queue_followup(
                    user_id=user_id,
                    followup_type=ftype,
                    message=message,
                    scheduled_at=scheduled_at.isoformat(),
                    trigger_reason=reason,
                    priority=priority,
                )
                queued += 1
                logger.info(f"Queued followup '{ftype}' for {user_id} at {scheduled_at}")
            except Exception as exc:
                logger.error(f"Failed to queue followup: {exc}")

        return queued

    def get_due_followups(self) -> list[dict]:
        """
        Fetch all follow-ups across all users that are due NOW.
        Called by SmartScheduler on a timer.
        """
        return self.memory.get_due_followups()

    def mark_sent(self, followup_id: str) -> None:
        """Mark a follow-up as sent."""
        self.memory.mark_followup_sent(followup_id)

    def cancel_type(self, user_id: str, followup_type: str) -> None:
        """
        Cancel all pending follow-ups of a specific type for a user.
        Useful when the user already responded to the situation.
        """
        self.memory.cancel_followups(user_id, followup_type)

    def cancel_all(self, user_id: str) -> None:
        """Cancel all pending follow-ups for a user."""
        self.memory.cancel_all_followups(user_id)

    # ── Internal checks ──────────────────────────────────────────────────

    def _is_on_cooldown(self, user_id: str, followup_type: str) -> bool:
        """Check if this followup type was recently sent/queued."""
        cooldown_hours = COOLDOWN_HOURS.get(followup_type, 12)
        last_sent = self.memory.get_last_followup_time(user_id, followup_type)

        if not last_sent:
            return False

        try:
            last_dt = datetime.fromisoformat(last_sent.replace("Z", "+00:00")).replace(tzinfo=None)
            hours_ago = (datetime.utcnow() - last_dt).total_seconds() / 3600
            return hours_ago < cooldown_hours
        except Exception:
            return False

    def _count_pending(self, user_id: str) -> int:
        """Count unsent follow-ups for this user."""
        return self.memory.count_pending_followups(user_id)


class PatternTracker:
    """
    Learns user behavioral patterns over time.

    Tracks:
    - Usual workout time (from log timestamps)
    - Which days they tend to skip
    - Energy/sleep trends
    - Meal timing patterns
    """

    def __init__(self, memory) -> None:
        self.memory = memory

    def update_patterns(self, user_id: str) -> None:
        """
        Analyze recent data and update learned patterns.
        Called after each interaction or daily log.
        """
        logs = self.memory.get_recent_logs(user_id, days=30)
        if len(logs) < 5:
            return  # Not enough data

        # Pattern 1: Workout days
        workout_days = {}
        skip_days = {}
        for log in logs:
            try:
                log_date = datetime.strptime(log["log_date"], "%Y-%m-%d")
                day_name = log_date.strftime("%A")
                if log.get("workout_done"):
                    workout_days[day_name] = workout_days.get(day_name, 0) + 1
                else:
                    skip_days[day_name] = skip_days.get(day_name, 0) + 1
            except Exception:
                continue

        if workout_days:
            self.memory.upsert_pattern(
                user_id=user_id,
                pattern_type="workout_days",
                pattern_data=json.dumps(workout_days),
                confidence=min(1.0, len(logs) / 20),
            )

        if skip_days:
            self.memory.upsert_pattern(
                user_id=user_id,
                pattern_type="skip_days",
                pattern_data=json.dumps(skip_days),
                confidence=min(1.0, len(logs) / 20),
            )

        # Pattern 2: Energy trend
        energies = [l.get("energy_level") for l in logs[:14] if l.get("energy_level")]
        if len(energies) >= 5:
            first_half = sum(energies[:len(energies)//2]) / (len(energies)//2)
            second_half = sum(energies[len(energies)//2:]) / (len(energies) - len(energies)//2)
            trend = "stable"
            if second_half - first_half > 1.5:
                trend = "improving"
            elif first_half - second_half > 1.5:
                trend = "declining"

            self.memory.upsert_pattern(
                user_id=user_id,
                pattern_type="energy_trend",
                pattern_data=json.dumps({"trend": trend, "recent_avg": round(second_half, 1)}),
                confidence=min(1.0, len(energies) / 10),
            )

        # Pattern 3: Sleep pattern
        sleeps = [l.get("sleep_hours") for l in logs[:14] if l.get("sleep_hours")]
        if len(sleeps) >= 5:
            avg_sleep = sum(sleeps) / len(sleeps)
            self.memory.upsert_pattern(
                user_id=user_id,
                pattern_type="sleep_pattern",
                pattern_data=json.dumps({"avg_hours": round(avg_sleep, 1), "min": min(sleeps), "max": max(sleeps)}),
                confidence=min(1.0, len(sleeps) / 10),
            )

    def get_pattern(self, user_id: str, pattern_type: str) -> dict | None:
        """Retrieve a learned pattern."""
        raw = self.memory.get_pattern(user_id, pattern_type)
        if raw:
            try:
                raw["pattern_data"] = json.loads(raw["pattern_data"])
            except Exception:
                pass
        return raw

    def get_skip_day_prediction(self, user_id: str) -> str | None:
        """Predict which day the user is most likely to skip."""
        pattern = self.get_pattern(user_id, "skip_days")
        if not pattern or not isinstance(pattern.get("pattern_data"), dict):
            return None
        skip_data = pattern["pattern_data"]
        if skip_data:
            return max(skip_data, key=skip_data.get)
        return None
