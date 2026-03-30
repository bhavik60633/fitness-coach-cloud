"""
telegram_bot.py — Cloud-ready Telegram bot.

Identical to local version but imports from cloud modules.
The Ollama health check is removed (Groq API is always available).
"""

import asyncio
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

# ── Shared memory + RAG ───────────────────────────────────────────────────
memory = CoachMemory()
rag    = FitnessCoachRAG(memory=memory)

# ── ConversationHandler states ────────────────────────────────────────────
(
    GOAL_TARGET_WEIGHT,
    GOAL_CURRENT_WEIGHT,
    GOAL_DAYS,
    GOAL_CONFIRM,
    LOG_WORKOUT_DONE,
    LOG_NOTES,
    LOG_WEIGHT,
    LOG_ENERGY,
    LOG_SLEEP,
    MISSED_REASON,
    CHECKIN_HOUR,
) = range(11)

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

# ── /start ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    n = name(update)
    profile = memory.get_profile(uid(update))
    if profile and profile.get("goal_summary"):
        goal = profile["goal_summary"]
        await update.message.reply_text(
            f"Welcome back, {n}! 💪\n\n"
            f"I remember everything — we're still working towards:\n"
            f"🎯 *{goal}*\n\n"
            f"What's on your mind? Just send me a message!\n"
            f"Type /help to see all commands.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            f"Hey {n}! 🏋️ I'm your personal AI fitness coach.\n\n"
            f"I've studied all your fitness documents — workouts, diet plans, "
            f"sleep guides and more. I'll remember *every conversation* and "
            f"adapt your plan as you go.\n\n"
            f"To get started, let's set your goal:\n"
            f"👉 Type /setgoal\n\n"
            f"Or just ask me anything — I'm here!",
            parse_mode=ParseMode.MARKDOWN,
        )

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

    streak = memory.get_streak(uid(update))
    done   = log_data.get("workout_done", 0)

    if done:
        await update.message.reply_text(
            f"✅ Log saved!\n\n"
            f"🔥 Streak: {streak} day{'s' if streak != 1 else ''}\n\n"
            f"Keep crushing it! 💪"
        )
    else:
        await update.message.reply_text(
            "📋 Log saved. Tomorrow's another day — let's get back on track!\n\n"
            "Type /missed if you want me to adjust today's plan."
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

# ── General message handler ───────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorised(update):
        await update.message.reply_text("Sorry, this is a private coach bot.")
        return

    question = update.message.text.strip()
    await typing(update, ctx)
    logger.info(f"[{uid(update)}] {question[:80]}")

    try:
        answer = await run_rag(question, uid(update))
    except Exception as exc:
        logger.error(f"RAG error: {exc}")
        answer = f"⚠️ Something went wrong: {exc}"

    await reply(update, answer)

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

    # ── Goal-setting conversation
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

    # ── Register all handlers
    app.add_handler(goal_conv)
    app.add_handler(log_conv)
    app.add_handler(missed_conv)
    app.add_handler(reminder_conv)

    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("mygoal",      cmd_mygoal))
    app.add_handler(CommandHandler("checkin",     cmd_checkin))
    app.add_handler(CommandHandler("history",     cmd_history))
    app.add_handler(CommandHandler("streak",      cmd_streak))
    app.add_handler(CommandHandler("review",      cmd_review))

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

    logger.info("🤖 Fitness Coach Bot is running on CLOUD … (24/7)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
