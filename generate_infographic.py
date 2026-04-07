# -*- coding: utf-8 -*-
"""
generate_infographic.py
Creates a system overview infographic and sends it to Telegram.
"""

import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.patheffects as pe
import numpy as np

TELEGRAM_TOKEN  = "8541018711:AAEDFHmPGbRD2T2lkWCpfbOJA8C_RubZhHw"
TELEGRAM_USER_ID = "6660711640"
OUTPUT_FILE = "system_infographic.png"

# ── Colors ────────────────────────────────────────────────────────────────────
BG        = "#0D1117"
CARD_DARK = "#161B22"
CARD_MID  = "#1F2937"
PURPLE    = "#7C3AED"
BLUE      = "#2563EB"
GREEN     = "#10B981"
ORANGE    = "#F59E0B"
RED       = "#EF4444"
PINK      = "#EC4899"
CYAN      = "#06B6D4"
WHITE     = "#F9FAFB"
GREY      = "#6B7280"

def rounded_box(ax, x, y, w, h, color, alpha=1.0, radius=0.015):
    box = FancyBboxPatch((x, y), w, h,
                          boxstyle=f"round,pad=0,rounding_size={radius}",
                          linewidth=0, facecolor=color, alpha=alpha,
                          transform=ax.transAxes, zorder=3)
    ax.add_patch(box)
    return box

def arrow(ax, x1, y1, x2, y2, color=WHITE, lw=1.5):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                xycoords="axes fraction", textcoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color=color,
                                lw=lw, mutation_scale=12),
                zorder=5)

def label(ax, x, y, text, size=9, color=WHITE, bold=False, ha="center", va="center"):
    weight = "bold" if bold else "normal"
    ax.text(x, y, text, transform=ax.transAxes,
            fontsize=size, color=color, ha=ha, va=va,
            fontweight=weight, zorder=6)

# ── Figure ────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(14, 10))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 1); ax.set_ylim(0, 1)
ax.axis("off")

# ── Title ─────────────────────────────────────────────────────────────────────
rounded_box(ax, 0.02, 0.91, 0.96, 0.08, CARD_MID)
label(ax, 0.5, 0.955, "FITNESS COACH AI — How It All Works", size=16, bold=True, color=WHITE)
label(ax, 0.5, 0.925, "From your message to a smart coaching reply — every step explained", size=10, color=GREY)

# ═══════════════════════════════════════════════════════
# ROW 1 — INPUT SOURCES
# ═══════════════════════════════════════════════════════
label(ax, 0.5, 0.895, "KNOWLEDGE SOURCES", size=8, color=GREY, bold=True)

sources = [
    (0.03,  PURPLE, "📄 29 PDFs",       "ETF Cookbook\nLectures 2-21\nSleep Manual\nWorkout Plans"),
    (0.245, BLUE,   "🗒️ Obsidian Notes", "Dalton Wong\nAndrej Karpathy\nYour summaries\nAuto-synced"),
    (0.46,  GREEN,  "💬 Conversations",  "Past chats\nCoach advice\nYour questions\nDaily logs"),
    (0.675, ORANGE, "👤 Your Profile",   "Weight & goal\nCompliance %\nTraining level\nSleep times"),
]

for x, col, title, detail in sources:
    rounded_box(ax, x, 0.755, 0.19, 0.125, col, alpha=0.15)
    rounded_box(ax, x, 0.845, 0.19, 0.032, col, alpha=0.4)
    label(ax, x+0.095, 0.863, title, size=9, bold=True, color=WHITE)
    for i, line in enumerate(detail.split("\n")):
        label(ax, x+0.095, 0.82 - i*0.018, line, size=7.5, color=GREY)

# arrows from sources down to ChromaDB
for x in [0.125, 0.34, 0.555]:
    arrow(ax, x, 0.755, x, 0.695, color=GREY)
arrow(ax, 0.77, 0.755, 0.62, 0.695, color=GREY)

# ═══════════════════════════════════════════════════════
# ChromaDB
# ═══════════════════════════════════════════════════════
rounded_box(ax, 0.25, 0.635, 0.5, 0.055, PURPLE, alpha=0.25)
rounded_box(ax, 0.25, 0.635, 0.5, 0.055, PURPLE, alpha=0.08)
label(ax, 0.5, 0.665, "🧠  ChromaDB — Vector Knowledge Base", size=10, bold=True, color=PURPLE)
label(ax, 0.5, 0.647, "All text converted to vectors • Semantic search • 126+ chunks", size=8, color=GREY)

arrow(ax, 0.5, 0.635, 0.5, 0.58, color=PURPLE)

# ═══════════════════════════════════════════════════════
# ROW 2 — MESSAGE FLOW
# ═══════════════════════════════════════════════════════
label(ax, 0.5, 0.60, "WHEN YOU SEND A MESSAGE", size=8, color=GREY, bold=True)

steps = [
    (0.03,  CYAN,   "1. You Message",    "Telegram bot\nreceives your text\n24/7 on Railway"),
    (0.245, BLUE,   "2. Brain Thinks",   "Detects intent\nReads your state\nPlans follow-ups"),
    (0.46,  PURPLE, "3. RAG Search",     "Finds top 3 chunks\nfrom ChromaDB\nMost relevant docs"),
    (0.675, GREEN,  "4. Builds Prompt",  "Your question +\nProfile + History +\nDoc context"),
]

for x, col, title, detail in steps:
    rounded_box(ax, x, 0.47, 0.19, 0.12, col, alpha=0.15)
    rounded_box(ax, x, 0.555, 0.19, 0.032, col, alpha=0.4)
    label(ax, x+0.095, 0.573, title, size=9, bold=True, color=WHITE)
    for i, line in enumerate(detail.split("\n")):
        label(ax, x+0.095, 0.535 - i*0.019, line, size=7.5, color=GREY)

# arrows between steps
for x in [0.22, 0.435, 0.65]:
    arrow(ax, x, 0.515, x+0.025, 0.515, color=WHITE)

arrow(ax, 0.865, 0.515, 0.895, 0.515, color=WHITE)

# ═══════════════════════════════════════════════════════
# OpenAI
# ═══════════════════════════════════════════════════════
rounded_box(ax, 0.895, 0.44, 0.085, 0.145, ORANGE, alpha=0.2)
label(ax, 0.9375, 0.525, "OpenAI", size=8, bold=True, color=ORANGE)
label(ax, 0.9375, 0.507, "GPT-4o", size=7.5, color=GREY)
label(ax, 0.9375, 0.490, "mini", size=7.5, color=GREY)
label(ax, 0.9375, 0.470, "API", size=7.5, color=GREY)

arrow(ax, 0.9375, 0.44, 0.9375, 0.39, color=ORANGE)

# ═══════════════════════════════════════════════════════
# ROW 3 — OUTPUT
# ═══════════════════════════════════════════════════════
rounded_box(ax, 0.25, 0.31, 0.5, 0.07, GREEN, alpha=0.15)
rounded_box(ax, 0.25, 0.31, 0.5, 0.07, GREEN, alpha=0.08)
label(ax, 0.5, 0.35, "✅  Smart Coaching Reply Sent to Telegram", size=11, bold=True, color=GREEN)
label(ax, 0.5, 0.328, "Personalised • Based on YOUR data • References YOUR documents", size=8, color=GREY)

arrow(ax, 0.9375, 0.31, 0.76, 0.345, color=GREEN)

# ═══════════════════════════════════════════════════════
# ROW 4 — SAVE LOOP
# ═══════════════════════════════════════════════════════
label(ax, 0.5, 0.295, "AFTER EVERY REPLY", size=8, color=GREY, bold=True)

saves = [
    (0.03,  BLUE,  "💾 Saved to\nSupabase",    "Permanent storage\nNever lost"),
    (0.245, CYAN,  "📝 Every 10 msgs\nExport notes", "Structured daily\nconversation notes"),
    (0.46,  PURPLE,"🔄 Re-indexed\nin ChromaDB", "Bot learns from\npast chats"),
    (0.675, GREEN, "📱 Reminders\nScheduled",   "Water / workout\nWeekly review"),
]

for x, col, title, detail in saves:
    rounded_box(ax, x, 0.175, 0.19, 0.105, col, alpha=0.12)
    for i, line in enumerate(title.split("\n")):
        label(ax, x+0.095, 0.262 - i*0.02, line, size=8.5, bold=True, color=col)
    for i, line in enumerate(detail.split("\n")):
        label(ax, x+0.095, 0.218 - i*0.018, line, size=7.5, color=GREY)

# ═══════════════════════════════════════════════════════
# BOTTOM — EXAMPLE
# ═══════════════════════════════════════════════════════
rounded_box(ax, 0.02, 0.02, 0.96, 0.14, CARD_MID)
label(ax, 0.06, 0.135, "EXAMPLE:", size=8, bold=True, color=ORANGE, ha="left")
label(ax, 0.06, 0.113, "You say:", size=8, color=GREY, ha="left")
label(ax, 0.18, 0.113, '"What should I eat today? I trained legs and burned 500 kcal"', size=8.5, color=WHITE, ha="left")
label(ax, 0.06, 0.088, "Bot finds:", size=8, color=GREY, ha="left")
label(ax, 0.18, 0.088, "ETF Cookbook (PDF)  +  1500 Cal Plan (PDF)  +  Your goal: fat loss  +  Yesterday: skipped workout", size=8, color=CYAN, ha="left")
label(ax, 0.06, 0.063, "Bot replies:", size=8, color=GREY, ha="left")
label(ax, 0.18, 0.063, '"Hey! Great leg session. You need ~1500 kcal today. Have dal + rice post workout for carb refuel..."', size=8.5, color=GREEN, ha="left")
label(ax, 0.06, 0.038, "Saved:", size=8, color=GREY, ha="left")
label(ax, 0.18, 0.038, "Conversation stored in Supabase  →  Exported to Obsidian  →  Re-indexed in ChromaDB", size=8, color=PURPLE, ha="left")

plt.tight_layout(pad=0)
plt.savefig(OUTPUT_FILE, dpi=150, bbox_inches="tight",
            facecolor=BG, edgecolor="none")
plt.close()
print(f"Saved: {OUTPUT_FILE}")

# ── Send to Telegram ──────────────────────────────────────────────────────────
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
caption = (
    "Here's how your Fitness Coach AI works end-to-end!\n\n"
    "Everything connects — your PDFs, Obsidian notes, past conversations "
    "and your profile — all working together to give you personalised coaching 24/7."
)
with open(OUTPUT_FILE, "rb") as img:
    resp = requests.post(url, data={"chat_id": TELEGRAM_USER_ID, "caption": caption},
                         files={"photo": img})

if resp.status_code == 200:
    print("Sent to Telegram!")
else:
    print(f"Telegram error: {resp.text}")
