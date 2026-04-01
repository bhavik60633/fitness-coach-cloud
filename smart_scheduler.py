"""
smart_scheduler.py — Intelligent reminder & follow-up delivery system.

Handles:
- Pulling due follow-ups from the queue and sending them
- Multiple reminder types (workout, meal, water, sleep, weigh-in)
- Contextual messages (different message based on situation)
- Evening log reminder if user hasn't logged
- Weekly review auto-send
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dtime, timedelta

from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class SmartScheduler:
    """
    Orchestrates all proactive messages.

    Sets up recurring jobs:
    1. Followup processor — checks queue every 5 minutes
    2. Evening nudge — reminds to log if they haven't
    3. Water reminders — periodic hydration nudges
    4. Weekly review — auto-send on Sundays
    """

    def __init__(self, memory, followup_engine, rag, brain) -> None:
        self.memory = memory
        self.followup_engine = followup_engine
        self.rag = rag
        self.brain = brain

    def setup_jobs(self, job_queue, user_id_int: int) -> None:
        """
        Set up all recurring smart jobs for a user.
        Called once on bot startup or when user first interacts.
        """
        user_id_str = str(user_id_int)

        # ── Followup processor: runs every 5 minutes ──
        job_name = f"followup_proc_{user_id_str}"
        existing = job_queue.get_jobs_by_name(job_name)
        if not existing:
            job_queue.run_repeating(
                self._process_followups,
                interval=300,  # 5 minutes
                first=30,      # wait 30s after startup
                name=job_name,
                data={"user_id_int": user_id_int, "user_id_str": user_id_str},
            )
            logger.info(f"Started followup processor for {user_id_str}")

        # ── Evening log nudge: 9pm IST (3:30pm UTC) ──
        nudge_name = f"evening_nudge_{user_id_str}"
        existing = job_queue.get_jobs_by_name(nudge_name)
        if not existing:
            job_queue.run_daily(
                self._evening_log_nudge,
                time=dtime(hour=15, minute=30),  # 9pm IST
                name=nudge_name,
                data={"user_id_int": user_id_int, "user_id_str": user_id_str},
            )
            logger.info(f"Set evening nudge for {user_id_str} at 21:00 IST")

        # ── Weekly review: Sunday 8pm IST (2:30pm UTC) ──
        review_name = f"weekly_review_{user_id_str}"
        existing = job_queue.get_jobs_by_name(review_name)
        if not existing:
            job_queue.run_daily(
                self._weekly_review,
                time=dtime(hour=14, minute=30),  # 8pm IST
                days=(6,),  # Sunday = 6
                name=review_name,
                data={"user_id_int": user_id_int, "user_id_str": user_id_str},
            )
            logger.info(f"Set weekly review for {user_id_str} on Sundays 20:00 IST")

    # ── Followup Queue Processor ─────────────────────────────────────────

    async def _process_followups(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Check the queue for due follow-ups and send them.
        Runs every 5 minutes.
        """
        try:
            due = self.followup_engine.get_due_followups()
            if not due:
                return

            for item in due:
                user_id_int = int(item["user_id"])
                message = item["message"]
                followup_id = item["id"]

                try:
                    await context.bot.send_message(
                        chat_id=user_id_int,
                        text=message,
                    )
                    self.followup_engine.mark_sent(followup_id)
                    logger.info(
                        f"Sent followup [{item['followup_type']}] to {user_id_int}: "
                        f"{message[:50]}..."
                    )
                except Exception as exc:
                    logger.error(f"Failed to send followup to {user_id_int}: {exc}")

        except Exception as exc:
            logger.error(f"Followup processor error: {exc}")

    # ── Evening Log Nudge ────────────────────────────────────────────────

    async def _evening_log_nudge(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        If user hasn't logged today by 9pm, send a gentle nudge.
        """
        data = context.job.data
        user_id_str = data["user_id_str"]
        user_id_int = data["user_id_int"]

        try:
            if self.memory.has_logged_today(user_id_str):
                return  # Already logged — no nudge needed

            profile = self.memory.get_profile(user_id_str)
            if not profile:
                return

            name = profile.get("name", "Bhavik")
            streak = self.memory.get_streak(user_id_str)

            if streak > 0:
                msg = (
                    f"Hey {name}! 🌙\n\n"
                    f"You're on a {streak}-day streak but I don't see today's log yet.\n"
                    f"🔥 Don't let it slip!\n\n"
                    f"Even if you just did a light walk — use /log to keep the chain going! 💪"
                )
            else:
                msg = (
                    f"Hey {name}! 🌙\n\n"
                    f"Quick reminder — did you work out today?\n"
                    f"Use /log to track it. Even rest days are worth logging!\n\n"
                    f"Every log helps me coach you better 📊"
                )

            await context.bot.send_message(chat_id=user_id_int, text=msg)
            logger.info(f"Sent evening nudge to {user_id_int}")

        except Exception as exc:
            logger.error(f"Evening nudge error: {exc}")

    # ── Weekly Review Auto-send ──────────────────────────────────────────

    async def _weekly_review(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Auto-send weekly review every Sunday evening.
        """
        data = context.job.data
        user_id_str = data["user_id_str"]
        user_id_int = data["user_id_int"]

        try:
            loop = asyncio.get_event_loop()
            review = await loop.run_in_executor(
                None, self.rag.generate_weekly_review, user_id_str
            )
            await context.bot.send_message(
                chat_id=user_id_int,
                text=f"📊 *Sunday Weekly Review*\n\n{review}",
                parse_mode="Markdown",
            )
            logger.info(f"Sent weekly review to {user_id_int}")
        except Exception as exc:
            logger.error(f"Weekly review error: {exc}")

    # ── On-demand: Cancel followups when user responds ───────────────────

    def on_user_message(self, user_id: str) -> None:
        """
        Called whenever the user sends any message.
        Cancels certain follow-ups that are no longer needed.
        """
        # If user is actively chatting, cancel motivation nudges
        self.followup_engine.cancel_type(user_id, "motivation")

        # If they're responding, cancel streak checks (they're active)
        self.followup_engine.cancel_type(user_id, "streak_check")

    def on_workout_logged(self, user_id: str) -> None:
        """
        Called when user logs a workout.
        Cancels any pending streak/log reminders.
        """
        self.followup_engine.cancel_type(user_id, "streak_check")
        self.followup_engine.cancel_type(user_id, "meal_reminder")
