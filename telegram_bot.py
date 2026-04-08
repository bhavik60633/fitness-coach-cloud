"""
telegram_bot.py — Cloud-ready Telegram bot.

Identical to local version but imports from cloud modules.
The Ollama health check is removed (Groq API is always available).
"""

import asyncio
import base64
import json
import logging
import os
import re
from datetime import time as dtime, datetime, timedelta

from dotenv import load_dotenv

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from memory import CoachMemory
from rag_engine import FitnessCoachRAG
from followup_engine import FollowupEngine, PatternTracker
from smart_scheduler import SmartScheduler
from conversation_exporter import export_conversations
from infographic_generator import is_graphic_request, generate_infographic

# ── Load environment ──────────────────────────────────────────────────────
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN not set in .env!")

AUTHORIZED_USER = os.getenv("TELEGRAM_USER_ID", "")

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Shared memory + RAG + Brain systems ───────────────────────────────────
memory = CoachMemory()
rag    = FitnessCoachRAG(memory=memory)

# 🧠 Claw Code integration: proactive coaching systems
followup_engine  = FollowupEngine(memory)
pattern_tracker  = PatternTracker(memory)
smart_scheduler  = SmartScheduler(memory, followup_engine, rag, rag.brain)

# ── ConversationHandler states ────────────────────────────────────────────
(
    # ETF Onboarding flow
    OB_GOAL_TYPE,
    OB_CURRENT_WEIGHT,
    OB_TARGET_WEIGHT,
    OB_DAYS,
    OB_AGE,
    OB_TRAINING_HISTORY,
    OB_CALORIE_TRACKING,
    OB_SLEEP,
    OB_OBSTACLES,
    OB_CONFIRM,
    # Legacy setgoal
    GOAL_TARGET_WEIGHT,
    GOAL_CURRENT_WEIGHT,
    GOAL_DAYS,
    GOAL_CONFIRM,
    # Daily log
    LOG_WORKOUT_DONE,
    LOG_NOTES,
    LOG_WEIGHT,
    LOG_ENERGY,
    LOG_SLEEP,
    MISSED_REASON,
    CHECKIN_HOUR,
    FOOD_MEAL_TYPE,
    EDIT_FOOD_FIELD,
    EDIT_FOOD_VALUE,
) = range(24)

# ── Helpers ───────────────────────────────────────────────────────────────

def uid(update: Update) -> str:
    return str(update.effective_user.id)

def is_authorised(update: Update) -> bool:
    if not AUTHORIZED_USER:
        return True
    return uid(update) == AUTHORIZED_USER

def name(update: Update) -> str:
    return update.effective_user.first_name or "Bhavik"

async def typing(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await ctx.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

async def reply(update: Update, text: str) -> None:
    MAX = 4000
    for i in range(0, len(text), MAX):
        await update.message.reply_text(text[i:i+MAX])

async def run_rag(question: str, user_id: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, rag.query, question, user_id)

async def run_adjustment(reason: str, user_id: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, rag.adjust_plan_query, reason, user_id)

async def run_checkin(user_id: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, rag.generate_daily_checkin, user_id)

async def run_weekly_review(user_id: str) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, rag.generate_weekly_review, user_id)

async def run_food_analysis(image_b64: str) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, rag.analyze_food_image, image_b64)

# ── /start ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    n = name(update)
    profile = memory.get_profile(uid(update))
    if profile and profile.get("goal_summary"):
        goal = profile["goal_summary"]
        compliance = profile.get("compliance_score") or 0
        await update.message.reply_text(
            f"Welcome back, {n}.\n\n"
            f"Goal: *{goal}*\n"
            f"Compliance: *{compliance}%*\n\n"
            f"What do you need? Send a message or use /help.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Fat Loss",            callback_data="goal_fat_loss")],
            [InlineKeyboardButton("Muscle Gain",         callback_data="goal_muscle_gain")],
            [InlineKeyboardButton("Body Recomposition",  callback_data="goal_recomp")],
        ])
        await update.message.reply_text(
            f"I'm your ETF Personal Coach, {n}.\n\n"
            f"Before I can coach you, I need your baseline data.\n"
            f"This takes 2 minutes. Answer honestly.\n\n"
            f"*What is your primary goal?*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
        return OB_GOAL_TYPE

# ── ETF Onboarding flow ────────────────────────────────────────────────────

async def ob_goal_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    goal_map = {
        "goal_fat_loss":    "fat_loss",
        "goal_muscle_gain": "muscle_gain",
        "goal_recomp":      "recomp",
    }
    ctx.user_data["goal_type"] = goal_map.get(query.data, "fat_loss")
    await query.edit_message_text(
        "What is your *current weight* in kg?\n_(e.g. 87)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return OB_CURRENT_WEIGHT

async def ob_current_weight(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ctx.user_data["current_weight"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Enter a number in kg, e.g. 87")
        return OB_CURRENT_WEIGHT
    await update.message.reply_text(
        "What is your *target weight* in kg?\n_(e.g. 75)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return OB_TARGET_WEIGHT

async def ob_target_weight(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ctx.user_data["target_weight"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Enter a number in kg, e.g. 75")
        return OB_TARGET_WEIGHT
    await update.message.reply_text(
        "How many *days* to reach this goal?\n_(e.g. 90)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return OB_DAYS

async def ob_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ctx.user_data["goal_days"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Enter number of days, e.g. 90")
        return OB_DAYS
    await update.message.reply_text("How old are you?\n_(e.g. 25)_")
    return OB_AGE

async def ob_age(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ctx.user_data["age"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Enter your age, e.g. 25")
        return OB_AGE
    await update.message.reply_text(
        "Describe your *training history* in one line.\n\n"
        "Examples:\n"
        "- Never trained before\n"
        "- Trained 2 years but inconsistent, 1 year off gym\n"
        "- Training consistently 3 years",
        parse_mode=ParseMode.MARKDOWN,
    )
    return OB_TRAINING_HISTORY

async def ob_training_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ctx.user_data["training_history"] = text
    tl = text.lower()
    if any(w in tl for w in ["never", "beginner", "first time", "no experience"]):
        ctx.user_data["training_level"] = "beginner"
    elif any(w in tl for w in ["inconsistent", "off", "stopped", "1 year", "2 year", "not consistent"]):
        ctx.user_data["training_level"] = "beginner"
    elif any(w in tl for w in ["3 year", "4 year", "5 year", "consistent", "advanced"]):
        ctx.user_data["training_level"] = "intermediate"
    else:
        ctx.user_data["training_level"] = "beginner"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("No — not tracking calories", callback_data="cal_no")],
        [InlineKeyboardButton("Yes — I track my calories",  callback_data="cal_yes")],
    ])
    await update.message.reply_text(
        "Are you currently *tracking your calories?*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )
    return OB_CALORIE_TRACKING

async def ob_calorie_tracking(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    ctx.user_data["calories_tracking"] = 1 if query.data == "cal_yes" else 0
    cw = ctx.user_data.get("current_weight", 80)
    maintenance = round(cw * 30)
    if ctx.user_data.get("goal_type") == "fat_loss":
        ctx.user_data["calorie_target"] = maintenance - 500
    elif ctx.user_data.get("goal_type") == "muscle_gain":
        ctx.user_data["calorie_target"] = maintenance + 300
    else:
        ctx.user_data["calorie_target"] = maintenance

    await query.edit_message_text(
        "What time do you *wake up* and *go to sleep?*\n\n"
        "Reply in this format:\n`wake 06:30 / sleep 22:30`",
        parse_mode=ParseMode.MARKDOWN,
    )
    return OB_SLEEP

async def ob_sleep(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().lower()
    times = re.findall(r"\d{1,2}:\d{2}", text)
    if len(times) >= 2:
        ctx.user_data["sleep_wake_time"] = times[0]
        ctx.user_data["sleep_bed_time"]  = times[1]
    elif len(times) == 1:
        ctx.user_data["sleep_wake_time"] = times[0]
        ctx.user_data["sleep_bed_time"]  = "23:00"
    else:
        ctx.user_data["sleep_wake_time"] = "07:00"
        ctx.user_data["sleep_bed_time"]  = "23:00"

    await update.message.reply_text(
        "What is your *biggest obstacle* right now?\n\n"
        "Be honest — motivation, no knowledge, going alone, fatigue, diet, etc.\n"
        "_(This helps me identify your weak points)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return OB_OBSTACLES

async def ob_obstacles(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["obstacles"] = update.message.text.strip()
    gt   = ctx.user_data.get("goal_type", "fat_loss").replace("_", " ").title()
    cw   = ctx.user_data.get("current_weight", "?")
    tw   = ctx.user_data.get("target_weight", "?")
    days = ctx.user_data.get("goal_days", "?")
    age  = ctx.user_data.get("age", "?")
    tl   = ctx.user_data.get("training_level", "beginner").title()
    cal  = ctx.user_data.get("calorie_target", "?")
    wake = ctx.user_data.get("sleep_wake_time", "?")
    bed  = ctx.user_data.get("sleep_bed_time", "?")
    obs  = ctx.user_data.get("obstacles", "?")
    tracking = "Yes" if ctx.user_data.get("calories_tracking") else "No"

    summary = (
        f"*Your ETF Profile*\n\n"
        f"Goal: {gt}\n"
        f"Weight: {cw} kg → {tw} kg in {days} days\n"
        f"Age: {age}\n"
        f"Training Level: {tl}\n"
        f"Calorie Target: {cal} kcal/day\n"
        f"Tracking calories: {tracking}\n"
        f"Sleep: Wake {wake} / Bed {bed}\n"
        f"Main obstacle: {obs}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Confirm — Start Coaching", callback_data="ob_confirm")],
        [InlineKeyboardButton("Start Over",               callback_data="ob_restart")],
    ])
    await update.message.reply_text(
        summary, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard,
    )
    return OB_CONFIRM

async def ob_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)

    if query.data == "ob_restart":
        await query.edit_message_text("Starting over. Send /start to begin again.")
        return ConversationHandler.END

    from datetime import date as date_cls, timedelta
    days  = ctx.user_data.get("goal_days", 90)
    start = date_cls.today()
    end   = start + timedelta(days=days)
    cw    = ctx.user_data.get("current_weight", 0)
    tw    = ctx.user_data.get("target_weight", 0)
    gt    = ctx.user_data.get("goal_type", "fat_loss")
    diff  = abs(cw - tw)
    action = "Lose" if cw > tw else "Gain"
    goal_summary = f"{action} {diff} kg in {days} days ({cw} kg → {tw} kg)"

    obs = ctx.user_data.get("obstacles", "").lower()
    weak = []
    if any(w in obs for w in ["motivation", "discipline", "lazy"]):
        weak.append("motivation/discipline")
    if any(w in obs for w in ["knowledge", "don't know", "no idea", "confused"]):
        weak.append("knowledge gap")
    if any(w in obs for w in ["diet", "food", "eating", "calories", "nutrition"]):
        weak.append("nutrition")
    if any(w in obs for w in ["tired", "fatigue", "sleep", "energy"]):
        weak.append("fatigue/recovery")
    if any(w in obs for w in ["alone", "no partner", "no friend"]):
        weak.append("accountability")
    weak_points_str = ", ".join(weak) if weak else "to be assessed"

    memory.upsert_profile(
        user_id,
        name=query.from_user.first_name,
        goal_type=gt,
        current_weight=cw,
        target_weight=tw,
        goal_summary=goal_summary,
        goal_start_date=start.isoformat(),
        goal_end_date=end.isoformat(),
        goal_days_total=days,
        age=ctx.user_data.get("age"),
        training_level=ctx.user_data.get("training_level", "beginner"),
        training_history=ctx.user_data.get("training_history", ""),
        calorie_target=ctx.user_data.get("calorie_target"),
        calories_tracking=ctx.user_data.get("calories_tracking", 0),
        sleep_wake_time=ctx.user_data.get("sleep_wake_time"),
        sleep_bed_time=ctx.user_data.get("sleep_bed_time"),
        obstacles=ctx.user_data.get("obstacles", ""),
        weak_points=weak_points_str,
        compliance_score=0,
        missed_days=0,
        behavior_flags="[]",
    )

    if not ctx.user_data.get("calories_tracking"):
        memory.add_behavior_flag(user_id, "not_tracking_calories")
    if "1 year" in (ctx.user_data.get("training_history") or "").lower() or \
       "inconsistent" in (ctx.user_data.get("training_history") or "").lower():
        memory.add_behavior_flag(user_id, "inconsistency_pattern")

    await query.edit_message_text(
        f"Profile saved.\n\n*{goal_summary}*\n\n"
        f"Weak points: {weak_points_str}\n\n"
        f"Use /checkin to get your first coaching message.\n"
        f"Use /setreminder to schedule daily check-ins.",
        parse_mode=ParseMode.MARKDOWN,
    )
    ctx.user_data.clear()
    return ConversationHandler.END

async def ob_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Onboarding cancelled. Send /start to begin again.")
    ctx.user_data.clear()
    return ConversationHandler.END

# ── /help ─────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🏋️ *Your Fitness Coach — Commands*\n\n"
        "*Setup*\n"
        "  /setgoal — Set your goal (e.g. lose 10 kg in 90 days)\n"
        "  /mygoal  — View current goal & progress\n\n"
        "*Daily*\n"
        "  /checkin — Get your morning coach message\n"
        "  /log     — Log today's workout & notes\n"
        "  /missed  — Missed gym today? Get an adjusted plan\n\n"
        "*Food & Calories 🍽️*\n"
        "  📷 Send a photo — AI analyzes calories automatically\n"
        "  /calories — See today's full food log & totals\n\n"
        "*Progress*\n"
        "  /history — Last 7 days of logs\n"
        "  /streak  — Your current workout streak\n"
        "  /review  — Weekly progress review\n\n"
        "*Just chat!*\n"
        "Send any message — your coach always remembers the context 🎯",
        parse_mode=ParseMode.MARKDOWN,
    )

# ── /setgoal conversation ─────────────────────────────────────────────────

async def cmd_setgoal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Let's set your goal! 🎯\n\n"
        "What's your *current weight* in kg?\n_(e.g. 85)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return GOAL_CURRENT_WEIGHT

async def goal_current_weight(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        w = float(update.message.text.strip())
        ctx.user_data["current_weight"] = w
    except ValueError:
        await update.message.reply_text("Please enter a number (e.g. 85).")
        return GOAL_CURRENT_WEIGHT
    await update.message.reply_text("What's your *target weight*? (kg)", parse_mode=ParseMode.MARKDOWN)
    return GOAL_TARGET_WEIGHT

async def goal_target_weight(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        w = float(update.message.text.strip())
        ctx.user_data["target_weight"] = w
    except ValueError:
        await update.message.reply_text("Please enter a number (e.g. 75).")
        return GOAL_TARGET_WEIGHT
    await update.message.reply_text(
        "How many *days* do you want to achieve this in?\n_(e.g. 90)_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return GOAL_DAYS

async def goal_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        d = int(update.message.text.strip())
        ctx.user_data["goal_days"] = d
    except ValueError:
        await update.message.reply_text("Please enter a number of days (e.g. 90).")
        return GOAL_DAYS

    cw  = ctx.user_data["current_weight"]
    tw  = ctx.user_data["target_weight"]
    d   = ctx.user_data["goal_days"]
    diff = abs(cw - tw)
    action = "lose" if cw > tw else "gain"
    summary = f"{action.capitalize()} {diff} kg in {d} days ({cw} kg → {tw} kg)"
    ctx.user_data["goal_summary"] = summary

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, set this goal!", callback_data="goal_confirm")],
        [InlineKeyboardButton("✏️ Start over",         callback_data="goal_restart")],
    ])
    await update.message.reply_text(
        f"Your goal:\n🎯 *{summary}*\n\nLooks good?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )
    return GOAL_CONFIRM

async def goal_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)

    if query.data == "goal_restart":
        await query.edit_message_text("No problem! Type /setgoal to start again.")
        return ConversationHandler.END

    from datetime import date, timedelta
    days    = ctx.user_data["goal_days"]
    start   = date.today()
    end     = start + timedelta(days=days)

    memory.upsert_profile(
        user_id,
        name=query.from_user.first_name,
        current_weight=ctx.user_data["current_weight"],
        target_weight=ctx.user_data["target_weight"],
        goal_summary=ctx.user_data["goal_summary"],
        goal_start_date=start.isoformat(),
        goal_end_date=end.isoformat(),
        goal_days_total=days,
    )

    await query.edit_message_text(
        f"🎯 Goal set!\n\n*{ctx.user_data['goal_summary']}*\n\n"
        f"Starting today, {start.strftime('%d %b %Y')}. "
        f"I'll track every step with you.\n\n"
        f"Type /checkin to get your first coaching message! 💪",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END

async def goal_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Goal setup cancelled. Type /setgoal to try again.")
    return ConversationHandler.END

# ── /mygoal ───────────────────────────────────────────────────────────────

async def cmd_mygoal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    profile = memory.get_profile(uid(update))
    if not profile or not profile.get("goal_summary"):
        await update.message.reply_text(
            "No goal set yet. Type /setgoal to create one! 🎯"
        )
        return

    goal_text = memory.format_goal_context(uid(update))
    streak    = memory.get_streak(uid(update))
    await update.message.reply_text(
        f"🎯 *Your Goal*\n\n{goal_text}\n\n🔥 Current streak: {streak} days",
        parse_mode=ParseMode.MARKDOWN,
    )

# ── /checkin ──────────────────────────────────────────────────────────────

async def cmd_checkin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await typing(update, ctx)
    await update.message.reply_text("Getting your morning check-in… ⏳")
    msg = await run_checkin(uid(update))
    await reply(update, msg)

# ── /log conversation ─────────────────────────────────────────────────────

async def cmd_log(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, completed it!",  callback_data="log_done")],
        [InlineKeyboardButton("❌ No, I skipped it",   callback_data="log_skipped")],
    ])
    await update.message.reply_text(
        "📋 *Daily Log*\n\nDid you complete your workout today?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )
    return LOG_WORKOUT_DONE

async def log_workout_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    ctx.user_data["workout_done"] = 1 if query.data == "log_done" else 0

    if ctx.user_data["workout_done"]:
        await query.edit_message_text("Great! 💪 Tell me briefly what you did (or type 'skip' to skip):")
    else:
        await query.edit_message_text("No worries! What got in the way? (or type 'skip' to skip):")
    return LOG_NOTES

async def log_notes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    ctx.user_data["workout_notes"] = "" if text.lower() == "skip" else text
    await update.message.reply_text(
        "Did you weigh yourself today? (Enter weight in kg, or type 'skip')"
    )
    return LOG_WEIGHT

async def log_weight(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.lower() != "skip":
        try:
            ctx.user_data["weight"] = float(text)
            memory.upsert_profile(uid(update), current_weight=float(text))
        except ValueError:
            await update.message.reply_text("That doesn't look like a number — I'll skip weight for today.")
    await update.message.reply_text(
        "Energy level today? (1–10, or type 'skip')"
    )
    return LOG_ENERGY

async def log_energy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.lower() != "skip":
        try:
            ctx.user_data["energy_level"] = int(text)
        except ValueError:
            pass
    await update.message.reply_text(
        "How many hours did you sleep last night? (e.g. 7.5, or type 'skip')"
    )
    return LOG_SLEEP

async def log_sleep(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.lower() != "skip":
        try:
            ctx.user_data["sleep_hours"] = float(text)
        except ValueError:
            pass

    # Save the log
    log_data = {
        "workout_done":  ctx.user_data.get("workout_done", 0),
        "workout_notes": ctx.user_data.get("workout_notes", ""),
        "weight":        ctx.user_data.get("weight"),
        "energy_level":  ctx.user_data.get("energy_level"),
        "sleep_hours":   ctx.user_data.get("sleep_hours"),
    }
    log_data = {k: v for k, v in log_data.items() if v is not None}
    memory.log_today(uid(update), **log_data)

    streak     = memory.get_streak(uid(update))
    compliance = memory.update_compliance_score(uid(update))
    done       = log_data.get("workout_done", 0)

    if done:
        if compliance >= 70:
            memory.remove_behavior_flag(uid(update), "low_discipline")
        await update.message.reply_text(
            f"Log saved.\n\n"
            f"Streak: {streak} day{'s' if streak != 1 else ''}\n"
            f"Compliance: {compliance}%"
        )
    else:
        memory.increment_missed_days(uid(update))
        if compliance < 50:
            memory.add_behavior_flag(uid(update), "low_discipline")
        await update.message.reply_text(
            f"Log saved. Missed session recorded.\n"
            f"Compliance: {compliance}%\n\n"
            "Type /missed to get an adjusted plan."
        )

    ctx.user_data.clear()
    return ConversationHandler.END

async def log_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Log cancelled.")
    ctx.user_data.clear()
    return ConversationHandler.END

# ── /missed conversation ──────────────────────────────────────────────────

async def cmd_missed(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "No worries, it happens to everyone! 🙏\n\n"
        "Tell me what happened so I can adjust your plan:"
    )
    return MISSED_REASON

async def missed_reason(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    reason = update.message.text.strip()
    await typing(update, ctx)
    await update.message.reply_text("Got it — adjusting your plan… ⏳")

    memory.log_today(uid(update), workout_done=0, workout_notes=reason)
    answer = await run_adjustment(reason, uid(update))
    await reply(update, answer)
    return ConversationHandler.END

async def missed_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled. Type /missed to try again.")
    return ConversationHandler.END

# ── /history ──────────────────────────────────────────────────────────────

async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logs = memory.format_recent_logs(uid(update), days=7)
    if not logs or logs == "No recent logs.":
        await update.message.reply_text(
            "No logs yet! Use /log after each session to track your progress."
        )
        return
    await update.message.reply_text(f"📊 *Last 7 days*\n\n{logs}", parse_mode=ParseMode.MARKDOWN)

# ── /streak ───────────────────────────────────────────────────────────────

async def cmd_streak(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    streak = memory.get_streak(uid(update))
    if streak == 0:
        await update.message.reply_text(
            "No streak yet — log a completed workout to start one! 🔥\n"
            "Use /log after your session."
        )
    else:
        emoji = "🔥" * min(streak, 5)
        await update.message.reply_text(
            f"{emoji} You're on a *{streak}-day streak!*\n\n"
            f"Don't break the chain! 💪",
            parse_mode=ParseMode.MARKDOWN,
        )

# ── /review ───────────────────────────────────────────────────────────────

async def cmd_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await typing(update, ctx)
    await update.message.reply_text("Preparing your weekly review… ⏳")
    review = await run_weekly_review(uid(update))
    await reply(update, review)

# ── /calories — show today's food log ────────────────────────────────────

async def cmd_calories(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    summary = memory.format_food_logs_today(uid(update))
    await update.message.reply_text(
        f"🍽️ *Today's Food Log*\n\n{summary}",
        parse_mode=ParseMode.MARKDOWN,
    )

# ── Photo handler — analyze food image ───────────────────────────────────

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        return

    await typing(update, ctx)
    await update.message.reply_text("📷 Analyzing your food photo… ⏳")

    # Download the highest-resolution photo
    photo = update.message.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()
    image_b64 = base64.b64encode(file_bytes).decode("utf-8")

    result = await run_food_analysis(image_b64)

    if result["calories"] == 0:
        await update.message.reply_text(
            "❌ Couldn't analyze the image clearly.\n\n"
            "Try a clearer, well-lit photo — or log manually:\n"
            "Just type: `Lunch: 2 rotis + dal = 450 kcal`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Save to Supabase
    log_id = memory.save_food_log(
        user_id=uid(update),
        meal_name=result["meal_name"],
        food_description=result["food_description"],
        calories=result["calories"],
        protein_g=result.get("protein_g", 0),
        carbs_g=result.get("carbs_g", 0),
        fat_g=result.get("fat_g", 0),
        image_analyzed=True,
        notes=result.get("notes", ""),
    )

    # Store last log_id so user can edit right after
    ctx.user_data["last_food_log_id"] = log_id

    daily = memory.get_daily_calorie_total(uid(update))
    confidence_emoji = {"high": "✅", "medium": "⚠️", "low": "❓"}.get(result.get("confidence", "low"), "⚠️")

    msg = (
        f"📷 *Food Analyzed* {confidence_emoji}\n\n"
        f"🍽️ *{result['meal_name']}:* {result['food_description']}\n\n"
        f"🔥 Calories: *{result['calories']} kcal*\n"
        f"💪 Protein: {result.get('protein_g', 0):.0f}g\n"
        f"🌾 Carbs: {result.get('carbs_g', 0):.0f}g\n"
        f"🫒 Fat: {result.get('fat_g', 0):.0f}g\n"
    )
    if result.get("notes"):
        msg += f"\n📝 Note: {result['notes']}\n"
    msg += f"\n📊 *Today's total so far: {daily['calories']} kcal*"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit this entry", callback_data=f"editfood_{log_id}")],
        [InlineKeyboardButton("🗑️ Delete this entry", callback_data=f"delfood_{log_id}")],
        [InlineKeyboardButton("📋 See full day log", callback_data="show_calories")],
    ])
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

# ── Inline button callbacks for food entries ──────────────────────────────

async def food_action_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "show_calories":
        summary = memory.format_food_logs_today(str(query.from_user.id))
        await query.edit_message_text(
            f"🍽️ *Today's Food Log*\n\n{summary}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if data.startswith("delfood_"):
        log_id = data[len("delfood_"):]
        memory.delete_food_log(log_id)
        daily = memory.get_daily_calorie_total(str(query.from_user.id))
        await query.edit_message_text(
            f"🗑️ Entry deleted.\n📊 *Today's total: {daily['calories']} kcal*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if data.startswith("editfood_"):
        log_id = data[len("editfood_"):]
        ctx.user_data["editing_food_id"] = log_id
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 Calories",    callback_data="editfield_calories")],
            [InlineKeyboardButton("💪 Protein (g)", callback_data="editfield_protein_g")],
            [InlineKeyboardButton("🌾 Carbs (g)",   callback_data="editfield_carbs_g")],
            [InlineKeyboardButton("🫒 Fat (g)",     callback_data="editfield_fat_g")],
            [InlineKeyboardButton("🍽️ Meal name",  callback_data="editfield_meal_name")],
            [InlineKeyboardButton("📝 Description", callback_data="editfield_food_description")],
        ])
        await query.edit_message_text(
            "What do you want to edit?",
            reply_markup=keyboard,
        )

async def editfield_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    field = query.data[len("editfield_"):]
    ctx.user_data["editing_food_field"] = field
    labels = {
        "calories": "new calorie count (e.g. 450)",
        "protein_g": "new protein in grams (e.g. 30)",
        "carbs_g": "new carbs in grams (e.g. 55)",
        "fat_g": "new fat in grams (e.g. 12)",
        "meal_name": "meal name (Breakfast / Lunch / Dinner / Snack)",
        "food_description": "food description",
    }
    await query.edit_message_text(f"Enter the {labels.get(field, field)}:")
    return EDIT_FOOD_VALUE

async def editfood_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    log_id = ctx.user_data.get("editing_food_id")
    field  = ctx.user_data.get("editing_food_field")
    value  = update.message.text.strip()

    if not log_id or not field:
        await update.message.reply_text("Nothing to edit. Send a food photo first.")
        return ConversationHandler.END

    numeric_fields = {"calories", "protein_g", "carbs_g", "fat_g"}
    if field in numeric_fields:
        try:
            value = int(value) if field == "calories" else float(value)
        except ValueError:
            await update.message.reply_text("Please enter a valid number.")
            return EDIT_FOOD_VALUE

    memory.update_food_log(log_id, **{field: value})
    daily = memory.get_daily_calorie_total(uid(update))

    await update.message.reply_text(
        f"✅ Updated! 📊 *Today's total: {daily['calories']} kcal*",
        parse_mode=ParseMode.MARKDOWN,
    )
    ctx.user_data.pop("editing_food_id", None)
    ctx.user_data.pop("editing_food_field", None)
    return ConversationHandler.END

# ── /help ─────────────────────────────────────────────────────────────────
# (updated below — keeping original position, just adding to the text)

# ── General message handler ───────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        await update.message.reply_text("Sorry, this is a private coach bot.")
        return

    question = update.message.text.strip()
    user_id = uid(update)
    await typing(update, ctx)
    logger.info(f"[{user_id}] {question[:80]}")

    # 🧠 Cancel stale follow-ups (user is active now)
    smart_scheduler.on_user_message(user_id)

    try:
        answer = await run_rag(question, user_id)

        # 🧠 Queue any follow-ups the brain planned during reasoning
        chain = rag.get_last_reasoning_chain()
        if chain and chain.followup_actions:
            queued = followup_engine.queue_followups(user_id, chain.followup_actions)
            if queued:
                logger.info(f"Queued {queued} follow-ups for {user_id}")

    except Exception as exc:
        logger.error(f"RAG error: {exc}")
        answer = f"⚠️ Something went wrong: {exc}"

    await reply(update, answer)

    # Send infographic if user asked for a visual/graphic/picture
    if is_graphic_request(question):
        try:
            await ctx.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_PHOTO
            )
            loop = asyncio.get_event_loop()
            openai_key = os.getenv("OPENAI_API_KEY", "")
            img_bytes = await loop.run_in_executor(
                None, generate_infographic, question, openai_key
            )
            await ctx.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=img_bytes,
                caption="Here's your visual breakdown!",
            )
        except Exception as exc:
            logger.warning(f"Infographic generation failed: {exc}")

    # 🧠 Set up smart scheduler jobs on first interaction
    if ctx.job_queue and AUTHORIZED_USER:
        smart_scheduler.setup_jobs(ctx.job_queue, int(AUTHORIZED_USER))

    # Export conversation to Obsidian every 10 messages (runs in background)
    try:
        total = memory.get_all_history_count(user_id)
        if total % 10 == 0:
            asyncio.get_event_loop().run_in_executor(
                None, export_conversations, memory, user_id, 30
            )
            logger.info(f"Triggered conversation export at {total} messages")
    except Exception as exc:
        logger.warning(f"Conversation export skipped: {exc}")

# ── Scheduled daily check-in ──────────────────────────────────────────────

async def send_daily_checkin(context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id_int = context.job.data["user_id_int"]
    user_id_str = str(user_id_int)

    try:
        msg = await run_checkin(user_id_str)
        await context.bot.send_message(chat_id=user_id_int, text=msg)
        logger.info(f"Sent daily check-in to {user_id_int}")
    except Exception as exc:
        logger.error(f"Daily check-in error: {exc}")


async def send_weekly_review(context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id_int = context.job.data["user_id_int"]
    user_id_str = str(user_id_int)

    try:
        review = await run_weekly_review(user_id_str)
        await context.bot.send_message(
            chat_id=user_id_int,
            text=f"📊 *Weekly Review*\n\n{review}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logger.error(f"Weekly review error: {exc}")

# ── /setreminder ──────────────────────────────────────────────────────────

async def cmd_setreminder(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "What time should I send your daily check-in?\n"
        "Reply with the time in HH:MM format (24h, e.g. *07:30*).",
        parse_mode=ParseMode.MARKDOWN,
    )
    return CHECKIN_HOUR

async def reminder_hour(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not match:
        await update.message.reply_text("Please use HH:MM format, e.g. 07:30")
        return CHECKIN_HOUR

    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        await update.message.reply_text("Invalid time. Try again, e.g. 07:30")
        return CHECKIN_HOUR

    user_id_int = update.effective_user.id
    user_id_str = str(user_id_int)

    for job in ctx.job_queue.get_jobs_by_name(f"checkin_{user_id_str}"):
        job.schedule_removal()

    ctx.job_queue.run_daily(
        send_daily_checkin,
        time=dtime(hour=hour, minute=minute),
        name=f"checkin_{user_id_str}",
        data={"user_id_int": user_id_int},
    )

    memory.set_reminder(user_id_str, "daily_checkin", hour, minute)

    await update.message.reply_text(
        f"✅ Daily check-in set for *{hour:02d}:{minute:02d}* every morning! 🌅\n\n"
        f"I'll message you with your plan for the day and check how you're doing.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END

# ── Error handler ─────────────────────────────────────────────────────────

async def handle_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Error: {ctx.error}", exc_info=ctx.error)

# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    app = ApplicationBuilder().token(TOKEN).build()

    # ── ETF Onboarding conversation
    onboard_conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            OB_GOAL_TYPE:        [CallbackQueryHandler(ob_goal_type, pattern="^goal_")],
            OB_CURRENT_WEIGHT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_current_weight)],
            OB_TARGET_WEIGHT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_target_weight)],
            OB_DAYS:             [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_days)],
            OB_AGE:              [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_age)],
            OB_TRAINING_HISTORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_training_history)],
            OB_CALORIE_TRACKING: [CallbackQueryHandler(ob_calorie_tracking, pattern="^cal_")],
            OB_SLEEP:            [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_sleep)],
            OB_OBSTACLES:        [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_obstacles)],
            OB_CONFIRM:          [CallbackQueryHandler(ob_confirm_callback, pattern="^ob_")],
        },
        fallbacks=[CommandHandler("cancel", ob_cancel)],
    )

    # ── Goal-setting conversation (update via /setgoal)
    goal_conv = ConversationHandler(
        entry_points=[CommandHandler("setgoal", cmd_setgoal)],
        states={
            GOAL_CURRENT_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_current_weight)],
            GOAL_TARGET_WEIGHT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_target_weight)],
            GOAL_DAYS:           [MessageHandler(filters.TEXT & ~filters.COMMAND, goal_days)],
            GOAL_CONFIRM:        [CallbackQueryHandler(goal_confirm_callback, pattern="^goal_")],
        },
        fallbacks=[CommandHandler("cancel", goal_cancel)],
    )

    # ── Daily log conversation
    log_conv = ConversationHandler(
        entry_points=[CommandHandler("log", cmd_log)],
        states={
            LOG_WORKOUT_DONE: [CallbackQueryHandler(log_workout_callback, pattern="^log_")],
            LOG_NOTES:        [MessageHandler(filters.TEXT & ~filters.COMMAND, log_notes)],
            LOG_WEIGHT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, log_weight)],
            LOG_ENERGY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, log_energy)],
            LOG_SLEEP:        [MessageHandler(filters.TEXT & ~filters.COMMAND, log_sleep)],
        },
        fallbacks=[CommandHandler("cancel", log_cancel)],
    )

    # ── Missed session conversation
    missed_conv = ConversationHandler(
        entry_points=[CommandHandler("missed", cmd_missed)],
        states={
            MISSED_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, missed_reason)],
        },
        fallbacks=[CommandHandler("cancel", missed_cancel)],
    )

    # ── Reminder conversation
    reminder_conv = ConversationHandler(
        entry_points=[CommandHandler("setreminder", cmd_setreminder)],
        states={
            CHECKIN_HOUR: [MessageHandler(filters.TEXT & ~filters.COMMAND, reminder_hour)],
        },
        fallbacks=[CommandHandler("cancel", goal_cancel)],
    )

    # ── Edit food conversation
    editfood_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(editfield_callback, pattern="^editfield_")],
        states={
            EDIT_FOOD_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, editfood_value)],
        },
        fallbacks=[CommandHandler("cancel", log_cancel)],
    )

    # ── Register all handlers
    app.add_handler(onboard_conv)
    app.add_handler(goal_conv)
    app.add_handler(log_conv)
    app.add_handler(missed_conv)
    app.add_handler(reminder_conv)
    app.add_handler(editfood_conv)

    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("mygoal",      cmd_mygoal))
    app.add_handler(CommandHandler("checkin",     cmd_checkin))
    app.add_handler(CommandHandler("history",     cmd_history))
    app.add_handler(CommandHandler("streak",      cmd_streak))
    app.add_handler(CommandHandler("review",      cmd_review))
    app.add_handler(CommandHandler("calories",    cmd_calories))

    # Food action buttons (edit/delete/show)
    app.add_handler(CallbackQueryHandler(food_action_callback, pattern="^(editfood_|delfood_|show_calories)"))

    # Photo handler — must be before text handler
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(handle_error)

    # ── Restore saved reminders
    saved = memory.get_all_reminders()
    for rem in saved:
        if rem["reminder_type"] == "daily_checkin":
            user_id_int = int(rem["user_id"])
            user_id_str = rem["user_id"]
            app.job_queue.run_daily(
                send_daily_checkin,
                time=dtime(hour=rem["hour"], minute=rem["minute"]),
                name=f"checkin_{user_id_str}",
                data={"user_id_int": user_id_int},
            )
            logger.info(
                f"Restored check-in reminder for {user_id_str} "
                f"at {rem['hour']:02d}:{rem['minute']:02d}"
            )

    # ── Set up smart scheduler for known user
    if AUTHORIZED_USER:
        smart_scheduler.setup_jobs(app.job_queue, int(AUTHORIZED_USER))
        logger.info(f"🧠 Smart scheduler active for user {AUTHORIZED_USER}")

    logger.info("🤖 Fitness Coach Bot is running on CLOUD … (24/7) [Brain + Proactive Mode]")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
