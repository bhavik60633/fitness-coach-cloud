"""
coach_brain.py — Human-like reasoning engine for the fitness coach.

Inspired by Claw Code's runtime.py + query_engine.py patterns:
- Multi-turn internal reasoning (thinks before answering)
- Context compaction (keeps only relevant info in working memory)
- Intent routing (understands what the user actually needs)
- Thought persistence (remembers its reasoning chain)
- Pattern detection (learns user behaviors over time)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


# ── Intent types the brain can detect ────────────────────────────────────

INTENT_TYPES = {
    "motivation":    ["tired", "lazy", "can't", "don't feel", "skip", "unmotivated", "boring", "thak", "nahi"],
    "food_question": ["eat", "food", "diet", "calorie", "protein", "meal", "recipe", "khana", "kya khau"],
    "workout_query": ["exercise", "workout", "training", "gym", "sets", "reps", "routine", "kaun sa"],
    "progress_check":["progress", "weight", "goal", "track", "how am i", "kitna", "result"],
    "pain_injury":   ["pain", "hurt", "injury", "sore", "ache", "strain", "dard"],
    "sleep_issue":   ["sleep", "insomnia", "tired", "rest", "neend", "recovery"],
    "plan_change":   ["change", "modify", "adjust", "different", "new plan", "badal"],
    "greeting":      ["hi", "hello", "hey", "sup", "good morning", "namaste"],
    "gratitude":     ["thanks", "thank you", "shukriya", "dhanyawad", "great", "awesome"],
    "accountability":["did i", "how many", "streak", "missed", "skip", "kitna"],
}


@dataclass(frozen=True)
class CoachThought:
    """A single thought in the coach's reasoning chain."""
    thought_type: str    # 'observation' | 'reasoning' | 'decision' | 'followup_plan'
    content: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class ReasoningChain:
    """
    Multi-step reasoning chain — inspired by Claw Code's TurnResult.
    The brain thinks in steps before producing a final answer.
    """
    user_message: str
    detected_intents: list[str] = field(default_factory=list)
    thoughts: list[CoachThought] = field(default_factory=list)
    context_used: dict[str, Any] = field(default_factory=dict)
    final_decision: str = ""
    followup_actions: list[dict] = field(default_factory=list)

    def add_thought(self, thought_type: str, content: str) -> None:
        self.thoughts.append(CoachThought(thought_type=thought_type, content=content))

    def as_prompt_context(self) -> str:
        """Render the reasoning chain as context for the LLM."""
        lines = ["[Coach's Internal Reasoning]"]
        for t in self.thoughts:
            lines.append(f"  [{t.thought_type}] {t.content}")
        if self.followup_actions:
            lines.append(f"  [planned follow-ups] {len(self.followup_actions)} actions queued")
        return "\n".join(lines)


@dataclass
class UserSnapshot:
    """
    Everything the coach knows about the user RIGHT NOW.
    Inspired by Claw Code's PortContext — a snapshot of the working state.
    """
    user_id: str
    name: str = "Bhavik"
    current_weight: float | None = None
    target_weight: float | None = None
    goal_summary: str = ""
    days_into_goal: int = 0
    days_remaining: int = 0
    streak: int = 0
    today_logged: bool = False
    last_workout_type: str = ""
    energy_trend: str = "stable"        # 'rising' | 'falling' | 'stable'
    sleep_avg: float = 0.0
    calories_today: int = 0
    protein_today: float = 0.0
    missed_last_session: bool = False
    time_since_last_msg: float = 0.0    # hours since last interaction
    conversation_count: int = 0


class CoachBrain:
    """
    The thinking engine — inspired by Claw Code's PortRuntime.

    This is what makes the coach feel human:
    1. Receives a message
    2. Builds a snapshot of everything it knows
    3. Detects intent (what does the user really need?)
    4. Reasons through the situation (multi-step thinking)
    5. Decides on follow-up actions (proactive coaching)
    6. Returns an enhanced prompt for the LLM
    """

    def __init__(self, memory) -> None:
        self.memory = memory

    # ── Intent Detection ─────────────────────────────────────────────────

    def detect_intents(self, message: str) -> list[str]:
        """Route the user's message to intent categories."""
        msg_lower = message.lower()
        detected = []
        for intent, keywords in INTENT_TYPES.items():
            if any(kw in msg_lower for kw in keywords):
                detected.append(intent)
        if not detected:
            detected.append("general")
        return detected

    # ── Build User Snapshot ──────────────────────────────────────────────

    def build_snapshot(self, user_id: str) -> UserSnapshot:
        """
        Build a complete picture of the user's current state.
        Like Claw Code's build_port_context() — gathers everything relevant.
        """
        profile = self.memory.get_profile(user_id) or {}
        logs = self.memory.get_recent_logs(user_id, days=7)
        streak = self.memory.get_streak(user_id)
        today_logged = self.memory.has_logged_today(user_id)
        daily_cal = self.memory.get_daily_calorie_total(user_id)
        history = self.memory.get_recent_history(user_id, limit=5)

        # Calculate time since last message
        hours_since = 999
        if history:
            last_ts = history[-1].get("timestamp", "")
            if last_ts:
                try:
                    last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    hours_since = (datetime.utcnow() - last_dt.replace(tzinfo=None)).total_seconds() / 3600
                except Exception:
                    pass

        # Calculate energy trend from recent logs
        energy_trend = "stable"
        if len(logs) >= 3:
            energies = [l.get("energy_level") for l in logs[:3] if l.get("energy_level")]
            if len(energies) >= 2:
                if energies[0] and energies[-1]:
                    diff = energies[0] - energies[-1]
                    if diff >= 2:
                        energy_trend = "falling"
                    elif diff <= -2:
                        energy_trend = "rising"

        # Calculate sleep average
        sleep_list = [l.get("sleep_hours") for l in logs if l.get("sleep_hours")]
        sleep_avg = sum(sleep_list) / len(sleep_list) if sleep_list else 0.0

        # Days into goal
        days_into = 0
        days_left = 0
        if profile.get("goal_start_date"):
            try:
                start = date.fromisoformat(profile["goal_start_date"])
                days_into = max(0, (date.today() - start).days)
            except Exception:
                pass
        if profile.get("goal_end_date"):
            try:
                end = date.fromisoformat(profile["goal_end_date"])
                days_left = max(0, (end - date.today()).days)
            except Exception:
                pass

        # Check if last session was missed
        missed_last = False
        if logs and not logs[0].get("workout_done"):
            missed_last = True

        return UserSnapshot(
            user_id=user_id,
            name=profile.get("name", "Bhavik"),
            current_weight=profile.get("current_weight"),
            target_weight=profile.get("target_weight"),
            goal_summary=profile.get("goal_summary", ""),
            days_into_goal=days_into,
            days_remaining=days_left,
            streak=streak,
            today_logged=today_logged,
            last_workout_type=logs[0].get("workout_notes", "") if logs else "",
            energy_trend=energy_trend,
            sleep_avg=round(sleep_avg, 1),
            calories_today=daily_cal.get("calories", 0),
            protein_today=daily_cal.get("protein_g", 0.0),
            missed_last_session=missed_last,
            time_since_last_msg=round(hours_since, 1),
            conversation_count=self.memory.get_all_history_count(user_id),
        )

    # ── Multi-Step Reasoning ─────────────────────────────────────────────

    def reason(self, message: str, user_id: str) -> ReasoningChain:
        """
        The core thinking loop — inspired by Claw Code's run_turn_loop().

        Step 1: Detect what the user needs
        Step 2: Build a snapshot of everything we know
        Step 3: Think through observations
        Step 4: Make coaching decisions
        Step 5: Plan follow-up actions
        """
        chain = ReasoningChain(user_message=message)

        # Step 1: Detect intents
        intents = self.detect_intents(message)
        chain.detected_intents = intents
        chain.add_thought("observation", f"Detected intents: {', '.join(intents)}")

        # Step 2: Build snapshot
        snapshot = self.build_snapshot(user_id)
        chain.context_used = {
            "streak": snapshot.streak,
            "days_remaining": snapshot.days_remaining,
            "energy_trend": snapshot.energy_trend,
            "today_logged": snapshot.today_logged,
            "missed_last": snapshot.missed_last_session,
            "hours_since_contact": snapshot.time_since_last_msg,
            "calories_today": snapshot.calories_today,
        }

        # Step 3: Situational observations
        if snapshot.streak >= 7:
            chain.add_thought("observation", f"🔥 Strong streak of {snapshot.streak} days — reinforce this!")
        elif snapshot.streak == 0 and snapshot.missed_last_session:
            chain.add_thought("observation", "⚠️ Streak broken. Be encouraging, not guilt-tripping.")

        if snapshot.energy_trend == "falling":
            chain.add_thought("observation", "Energy has been dropping. Consider suggesting rest day or lighter session.")

        if snapshot.sleep_avg > 0 and snapshot.sleep_avg < 6:
            chain.add_thought("observation", f"Sleep averaging {snapshot.sleep_avg}h — this could be hurting recovery.")

        if snapshot.days_remaining and snapshot.days_remaining < 14:
            chain.add_thought("observation", f"Only {snapshot.days_remaining} days left on goal — sprint mode!")

        if snapshot.time_since_last_msg > 24:
            chain.add_thought("observation", f"Haven't heard from user in {snapshot.time_since_last_msg:.0f}h — be warm on return.")

        if snapshot.calories_today > 0 and snapshot.calories_today > 2200:
            chain.add_thought("observation", f"Already at {snapshot.calories_today} kcal today — might need to suggest lighter dinner.")

        # Step 4: Coaching decisions based on intents
        if "motivation" in intents:
            if snapshot.streak > 0:
                chain.add_thought("decision", f"Use streak ({snapshot.streak} days) as motivation anchor.")
            else:
                chain.add_thought("decision", "Focus on small wins. Suggest just 15 min of activity.")
            chain.final_decision = "motivation_boost"

        elif "pain_injury" in intents:
            chain.add_thought("decision", "SAFETY FIRST. Don't prescribe — suggest rest and professional help.")
            chain.final_decision = "safety_first"
            # Schedule a follow-up to check on them tomorrow
            chain.followup_actions.append({
                "type": "soreness_check",
                "delay_hours": 20,
                "message": f"Hey {snapshot.name}! How's that pain feeling today? Better or same?",
                "priority": 2,
                "reason": "User reported pain/injury",
            })

        elif "sleep_issue" in intents:
            chain.add_thought("decision", "Address sleep directly — it affects everything else.")
            chain.final_decision = "sleep_guidance"

        elif "greeting" in intents:
            if snapshot.time_since_last_msg > 48:
                chain.add_thought("decision", "Welcome back warmly — reference what they missed.")
            else:
                chain.add_thought("decision", "Quick friendly greeting — get to the point.")
            chain.final_decision = "greeting"

        else:
            chain.final_decision = "standard_coaching"

        # Step 5: Plan automatic follow-ups
        self._plan_followups(chain, snapshot)

        # Persist thoughts
        self._save_thoughts(user_id, chain)

        return chain

    # ── Follow-up Planning ───────────────────────────────────────────────

    def _plan_followups(self, chain: ReasoningChain, snapshot: UserSnapshot) -> None:
        """
        Proactively schedule follow-ups based on the current situation.
        This is what makes the coach feel ALIVE — it messages you first.
        """
        now = datetime.utcnow()

        # If user just logged a hard workout, check on soreness tomorrow
        if snapshot.today_logged and "workout" in chain.user_message.lower():
            chain.followup_actions.append({
                "type": "soreness_check",
                "delay_hours": 18,
                "message": f"Morning {snapshot.name}! 💪 How's the body feeling after yesterday's session? Any soreness?",
                "priority": 4,
                "reason": "Post-workout recovery check",
            })

        # If streak is about to break (no log today and it's getting late)
        current_hour = (now.hour + 5) % 24 + (now.minute + 30) // 60  # IST approximation
        if not snapshot.today_logged and current_hour >= 19 and snapshot.streak > 0:
            chain.followup_actions.append({
                "type": "streak_check",
                "delay_hours": 1,
                "message": f"Hey {snapshot.name}! 🔥 You're on a {snapshot.streak}-day streak! Don't let it slip — even a quick 20 min walk counts. Did you train today?",
                "priority": 1,
                "reason": f"Streak protection — {snapshot.streak} day streak at risk",
            })

        # If calories are low and it's past lunch, remind about nutrition
        if snapshot.calories_today < 500 and current_hour >= 14:
            chain.followup_actions.append({
                "type": "meal_reminder",
                "delay_hours": 0.5,
                "message": f"{snapshot.name}, you've only logged {snapshot.calories_today} kcal today! 🍽️ Remember to eat well — your muscles need fuel. Send me a photo of your next meal!",
                "priority": 3,
                "reason": "Low calorie intake detected",
            })

        # Weekly weigh-in reminder (every Sunday if not weighed recently)
        if now.weekday() == 6:  # Sunday
            logs = self.memory.get_recent_logs(snapshot.user_id, days=7)
            weighed_this_week = any(l.get("weight") for l in logs)
            if not weighed_this_week:
                chain.followup_actions.append({
                    "type": "weigh_in",
                    "delay_hours": 2,
                    "message": f"Hey {snapshot.name}! 📊 It's Sunday — weigh-in day! Step on the scale and use /log to record it. Let's see your progress!",
                    "priority": 3,
                    "reason": "Weekly weigh-in not done",
                })

        # If user has been silent for 2+ days
        if snapshot.time_since_last_msg > 48:
            chain.followup_actions.append({
                "type": "motivation",
                "delay_hours": 0,
                "message": f"Hey {snapshot.name}! 👋 Haven't heard from you in a while. Everything okay? Remember — even on bad weeks, showing up matters. What's going on?",
                "priority": 2,
                "reason": f"No contact for {snapshot.time_since_last_msg:.0f} hours",
            })

    # ── Thought Persistence ──────────────────────────────────────────────

    def _save_thoughts(self, user_id: str, chain: ReasoningChain) -> None:
        """Save the reasoning chain to Supabase for future reference."""
        try:
            context_json = json.dumps(chain.context_used, default=str)
            for thought in chain.thoughts:
                self.memory.save_coach_thought(
                    user_id=user_id,
                    thought_type=thought.thought_type,
                    content=thought.content,
                    context_snapshot=context_json,
                )
        except Exception as exc:
            logger.warning(f"Failed to save thoughts: {exc}")

    # ── Build Enhanced System Prompt ─────────────────────────────────────

    def build_brain_context(self, message: str, user_id: str) -> str:
        """
        Returns a rich context block to inject into the system prompt.
        This makes the LLM's response feel like a real coach who KNOWS you.
        """
        chain = self.reason(message, user_id)
        snapshot = self.build_snapshot(user_id)

        lines = []

        # Situational awareness
        lines.append("=== COACH'S SITUATIONAL AWARENESS ===")
        if snapshot.streak > 0:
            lines.append(f"• Streak: {snapshot.streak} days 🔥")
        if snapshot.days_remaining:
            lines.append(f"• Goal deadline: {snapshot.days_remaining} days left")
        if snapshot.energy_trend != "stable":
            lines.append(f"• Energy trend: {snapshot.energy_trend}")
        if snapshot.sleep_avg > 0:
            lines.append(f"• Sleep average: {snapshot.sleep_avg}h/night")
        if snapshot.calories_today > 0:
            lines.append(f"• Calories today so far: {snapshot.calories_today} kcal")
        if snapshot.missed_last_session:
            lines.append("• Last session was missed")
        if snapshot.time_since_last_msg > 24:
            lines.append(f"• User was away for {snapshot.time_since_last_msg:.0f} hours")

        # Reasoning chain
        lines.append("")
        lines.append("=== COACH'S INTERNAL THINKING ===")
        for thought in chain.thoughts:
            emoji = {"observation": "👁️", "reasoning": "🧠", "decision": "✅"}.get(thought.thought_type, "💭")
            lines.append(f"{emoji} [{thought.thought_type}] {thought.content}")

        # Behavioral directive based on decision
        lines.append("")
        lines.append("=== RESPONSE DIRECTIVE ===")
        directives = {
            "motivation_boost": "User needs encouragement. Use their streak and progress as motivation. Keep it short and punchy.",
            "safety_first": "User mentioned pain/injury. DON'T suggest exercises. Recommend rest and seeing a doctor if serious.",
            "sleep_guidance": "Address sleep directly. Give actionable tips from the documents. Connect sleep to their fitness goal.",
            "greeting": "Keep it brief and warm. Reference something specific — their goal, streak, or last session.",
            "standard_coaching": "Give direct, confident coaching. Reference their data. Be a real trainer, not a chatbot.",
        }
        lines.append(directives.get(chain.final_decision, directives["standard_coaching"]))

        lines.append("=== END ===")

        return "\n".join(lines)

    def get_pending_followups(self, user_id: str, chain: ReasoningChain | None = None) -> list[dict]:
        """Return follow-up actions that need to be scheduled."""
        if chain:
            return chain.followup_actions
        return []
