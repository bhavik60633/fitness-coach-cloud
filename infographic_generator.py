# -*- coding: utf-8 -*-
"""
infographic_generator.py
Generates topic-based fitness infographics as PNG bytes.
"""

import io
import re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import numpy as np

# ── Palette ────────────────────────────────────────────────────────────────
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
YELLOW    = "#FBBF24"


def _rbox(ax, x, y, w, h, color, alpha=1.0, radius=0.015):
    box = FancyBboxPatch((x, y), w, h,
                          boxstyle=f"round,pad=0,rounding_size={radius}",
                          linewidth=0, facecolor=color, alpha=alpha,
                          transform=ax.transAxes, zorder=3)
    ax.add_patch(box)


def _txt(ax, x, y, text, size=9, color=WHITE, bold=False, ha="center", va="center"):
    ax.text(x, y, text, transform=ax.transAxes,
            fontsize=size, color=color, ha=ha, va=va,
            fontweight="bold" if bold else "normal", zorder=6)


def _arrow(ax, x1, y1, x2, y2, color=WHITE, lw=1.5):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                xycoords="axes fraction", textcoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw, mutation_scale=12),
                zorder=5)


# ─────────────────────────────────────────────────────────────────────────────
# TOPIC DETECTORS
# ─────────────────────────────────────────────────────────────────────────────

TOPICS = {
    "nutrition_muscle": [
        r"food.*muscle", r"muscle.*food", r"eat.*muscle", r"muscle.*eat",
        r"nutrition.*muscle", r"muscle.*nutrition", r"build.*muscle",
        r"muscle.*build", r"protein.*muscle", r"muscle.*protein",
        r"diet.*muscle", r"muscle.*gain",
    ],
    "macros": [
        r"macro", r"protein.*carb", r"carb.*fat", r"protein.*fat",
        r"calories.*breakdown", r"calorie.*split",
    ],
    "workout_plan": [
        r"workout.*plan", r"training.*plan", r"exercise.*program",
        r"gym.*routine", r"strength.*plan",
    ],
    "fat_loss": [
        r"fat.*loss", r"lose.*fat", r"weight.*loss", r"lose.*weight",
        r"calorie.*deficit", r"burn.*fat",
    ],
    "sleep": [
        r"sleep.*recover", r"recover.*sleep", r"sleep.*muscle",
        r"rest.*recover", r"sleep.*quality",
    ],
}


def detect_topic(text: str) -> str:
    text_lower = text.lower()
    for topic, patterns in TOPICS.items():
        for p in patterns:
            if re.search(p, text_lower):
                return topic
    return "nutrition_muscle"   # default


# ─────────────────────────────────────────────────────────────────────────────
# INFOGRAPHIC 1 — Nutrition for Muscle Building
# ─────────────────────────────────────────────────────────────────────────────

def _build_nutrition_muscle() -> bytes:
    fig = plt.figure(figsize=(14, 11))
    fig.patch.set_facecolor(BG)

    # ── Title
    ax_title = fig.add_axes([0, 0.92, 1, 0.08])
    ax_title.set_facecolor(CARD_MID)
    ax_title.axis("off")
    ax_title.text(0.5, 0.65, "HOW FOOD BUILDS MUSCLE", fontsize=18, color=WHITE,
                  ha="center", va="center", fontweight="bold", transform=ax_title.transAxes)
    ax_title.text(0.5, 0.2, "Your complete nutrition guide — protein, carbs, fats, timing & meal plan",
                  fontsize=10, color=GREY, ha="center", va="center", transform=ax_title.transAxes)

    # ── Main axes
    ax = fig.add_axes([0, 0, 1, 0.92])
    ax.set_facecolor(BG)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis("off")

    # ══════════════════════════════════════════════════════
    # ROW 1 — THE 3 MACROS
    # ══════════════════════════════════════════════════════
    _txt(ax, 0.5, 0.965, "THE 3 PILLARS OF MUSCLE NUTRITION", size=8, color=GREY, bold=True)

    macros = [
        (0.02,  BLUE,   "PROTEIN",   "2.2g per kg body weight",
         ["Chicken, Fish, Eggs",
          "Paneer, Dal, Curd",
          "Whey protein shake",
          "Repairs muscle fibres",
          "Builds new muscle tissue"]),
        (0.36,  ORANGE, "CARBS",     "3-5g per kg body weight",
         ["Rice, Oats, Banana",
          "Sweet potato, Roti",
          "Fruits, Whole grains",
          "Fuels your workouts",
          "Replenishes glycogen"]),
        (0.70,  CYAN,   "FATS",      "0.8-1g per kg body weight",
         ["Nuts, Seeds, Avocado",
          "Olive oil, Ghee",
          "Fatty fish (omega-3)",
          "Hormone production",
          "Joint & cell health"]),
    ]

    for x, col, title, sub, points in macros:
        _rbox(ax, x, 0.72, 0.30, 0.22, col, alpha=0.12)
        _rbox(ax, x, 0.905, 0.30, 0.038, col, alpha=0.45)
        _txt(ax, x+0.15, 0.926, title,  size=10, bold=True, color=WHITE)
        _txt(ax, x+0.15, 0.902, sub,    size=7.5, color=col)
        for i, pt in enumerate(points):
            _txt(ax, x+0.15, 0.875 - i*0.025, f"• {pt}", size=8, color=GREY)

    # ══════════════════════════════════════════════════════
    # ROW 2 — MUSCLE-BUILDING MECHANISM (visual flow)
    # ══════════════════════════════════════════════════════
    _txt(ax, 0.5, 0.71, "HOW PROTEIN ACTUALLY BUILDS MUSCLE", size=8, color=GREY, bold=True)

    steps = [
        (0.02,  GREEN,  "EAT\nPROTEIN",  "Chicken / eggs\ndal / whey"),
        (0.22,  BLUE,   "DIGEST\nAMINO\nACIDS",  "Broken down\nby stomach"),
        (0.42,  PURPLE, "BLOOD\nCARRIES\nAMINOs", "To muscles\nvia bloodstream"),
        (0.62,  ORANGE, "MUSCLE\nPROTEIN\nSYNTH.", "New fibres\nbuilt (MPS)"),
        (0.82,  CYAN,   "MUSCLE\nGROWTH",  "Bigger &\nstronger"),
    ]

    for x, col, title, sub in steps:
        _rbox(ax, x, 0.575, 0.175, 0.12, col, alpha=0.15)
        _rbox(ax, x, 0.665, 0.175, 0.032, col, alpha=0.4)
        _txt(ax, x+0.0875, 0.683, title, size=8, bold=True, color=WHITE)
        for i, line in enumerate(sub.split("\n")):
            _txt(ax, x+0.0875, 0.638 - i*0.02, line, size=7.5, color=GREY)

    for xi in [0.195, 0.395, 0.595, 0.795]:
        _arrow(ax, xi, 0.63, xi+0.025, 0.63, color=WHITE)

    # ══════════════════════════════════════════════════════
    # ROW 3 — TIMING & PIE
    # ══════════════════════════════════════════════════════
    _txt(ax, 0.25, 0.565, "NUTRIENT TIMING", size=8, color=GREY, bold=True)
    _txt(ax, 0.74, 0.565, "DAILY CALORIE SPLIT", size=8, color=GREY, bold=True)

    # Timing boxes
    timing = [
        (0.02,  GREEN,  "Pre-Workout\n(1-2 hrs before)",
         "Rice + Chicken\nor Oats + Banana\n~40g carbs  20g protein"),
        (0.27,  ORANGE, "Post-Workout\n(within 45 min)",
         "Whey shake + Rice\nor Dal + Roti\n~50g carbs  30g protein"),
    ]
    for x, col, title, detail in timing:
        _rbox(ax, x, 0.40, 0.225, 0.145, col, alpha=0.12)
        _rbox(ax, x, 0.51, 0.225, 0.035, col, alpha=0.4)
        for i, line in enumerate(title.split("\n")):
            _txt(ax, x+0.1125, 0.525 - i*0.02, line, size=8.5, bold=True if i==0 else False, color=WHITE)
        for i, line in enumerate(detail.split("\n")):
            _txt(ax, x+0.1125, 0.47 - i*0.022, line, size=8, color=GREY)

    # Pie chart
    ax_pie = fig.add_axes([0.55, 0.35, 0.22, 0.22])
    ax_pie.set_facecolor(BG)
    sizes  = [35, 45, 20]
    colors = [BLUE, ORANGE, CYAN]
    labels = ["Protein\n35%", "Carbs\n45%", "Fats\n20%"]
    wedges, _ = ax_pie.pie(sizes, colors=colors, startangle=90,
                            wedgeprops=dict(width=0.55, edgecolor=BG, linewidth=2))
    ax_pie.text(0, 0, "Macros", ha="center", va="center", fontsize=8,
                color=WHITE, fontweight="bold")

    legend_patches = [mpatches.Patch(color=c, label=l) for c, l in zip(colors, labels)]
    ax_pie.legend(handles=legend_patches, loc="lower right", bbox_to_anchor=(1.6, -0.1),
                  fontsize=7, framealpha=0, labelcolor=WHITE)

    # Calorie target box
    _rbox(ax, 0.79, 0.40, 0.20, 0.145, GREEN, alpha=0.12)
    _txt(ax, 0.89, 0.52, "Target Calories", size=8.5, bold=True, color=WHITE)
    _txt(ax, 0.89, 0.495, "Muscle Gain:", size=8, color=GREY)
    _txt(ax, 0.89, 0.47, "TDEE + 300-500 kcal", size=8, color=GREEN, bold=True)
    _txt(ax, 0.89, 0.445, "Lean Bulk = slow gain,", size=7.5, color=GREY)
    _txt(ax, 0.89, 0.427, "less fat storage", size=7.5, color=GREY)

    # ══════════════════════════════════════════════════════
    # ROW 4 — SAMPLE MEAL PLAN
    # ══════════════════════════════════════════════════════
    _rbox(ax, 0.02, 0.02, 0.96, 0.36, CARD_MID, alpha=0.6)
    _txt(ax, 0.5, 0.362, "SAMPLE DAY MEAL PLAN  (75 kg male, muscle gain)", size=9, bold=True, color=ORANGE)

    meals = [
        ("Breakfast\n7 AM",      ORANGE, "Oats 80g + 4 boiled eggs + Banana",       "~600 kcal  |  35g P  |  70g C  |  12g F"),
        ("Mid-Morning\n10 AM",   BLUE,   "Paneer 100g + 2 roti + veggies",           "~450 kcal  |  25g P  |  50g C  |  15g F"),
        ("Lunch\n1 PM",          GREEN,  "Rice 150g + Dal 1 cup + Chicken 150g",     "~700 kcal  |  55g P  |  80g C  |  10g F"),
        ("Pre-Workout\n4 PM",    PURPLE, "Rice 100g + Chicken 100g",                 "~400 kcal  |  30g P  |  55g C  |  5g F"),
        ("Post-Workout\n7 PM",   CYAN,   "Whey shake 30g + Banana + Rice 100g",      "~450 kcal  |  35g P  |  60g C  |  5g F"),
        ("Dinner\n9 PM",         PINK,   "Dal + 2 Roti + Curd 200g + Salad",         "~500 kcal  |  30g P  |  55g C  |  12g F"),
    ]

    meal_y = [0.315, 0.27, 0.225, 0.18, 0.135, 0.09]
    for (meal_time, col, food, macros_str), y in zip(meals, meal_y):
        _rbox(ax, 0.03, y-0.01, 0.935, 0.035, col, alpha=0.1)
        _txt(ax, 0.10, y+0.01, meal_time, size=7.5, bold=True, color=col, ha="center")
        _txt(ax, 0.52, y+0.01, food, size=8.5, color=WHITE, ha="center")
        _txt(ax, 0.88, y+0.01, macros_str, size=7.5, color=GREY, ha="center")

    # header
    _txt(ax, 0.10, 0.345, "Meal", size=7.5, bold=True, color=GREY, ha="center")
    _txt(ax, 0.52, 0.345, "Food", size=7.5, bold=True, color=GREY, ha="center")
    _txt(ax, 0.88, 0.345, "Calories & Macros", size=7.5, bold=True, color=GREY, ha="center")

    # total
    _txt(ax, 0.5, 0.048, "TOTAL: ~3,100 kcal  |  ~210g Protein  |  ~370g Carbs  |  ~59g Fat",
         size=8.5, bold=True, color=YELLOW)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=BG, edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# INFOGRAPHIC 2 — Macros Breakdown
# ─────────────────────────────────────────────────────────────────────────────

def _build_macros() -> bytes:
    fig, ax = plt.subplots(figsize=(14, 9))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis("off")

    _rbox(ax, 0.02, 0.91, 0.96, 0.08, CARD_MID)
    _txt(ax, 0.5, 0.957, "MACRONUTRIENTS — Complete Breakdown", size=15, bold=True, color=WHITE)
    _txt(ax, 0.5, 0.926, "Protein · Carbohydrates · Fats — what they do and how much you need", size=10, color=GREY)

    data = [
        (BLUE,   "PROTEIN",        "4 kcal/g",
         ["Builds and repairs muscle",
          "Makes enzymes & hormones",
          "Immune system support",
          "Keeps you full (high satiety)"],
         "Muscle gain: 2.2g/kg\nFat loss: 2.5g/kg\nMaintenance: 1.6g/kg",
         ["Chicken breast", "Eggs & egg whites", "Fish & seafood",
          "Paneer, Curd, Milk", "Dal, Chickpeas", "Whey protein"]),

        (ORANGE, "CARBOHYDRATES",  "4 kcal/g",
         ["Primary fuel for brain",
          "Muscle glycogen storage",
          "Powers high-intensity work",
          "Protein-sparing effect"],
         "Active/bulking: 4-6g/kg\nFat loss: 2-3g/kg\nRest days: reduce 20%",
         ["Rice & whole grain roti", "Oats & poha", "Sweet potato",
          "Banana & fruits", "Vegetables", "Legumes & dal"]),

        (CYAN,   "FATS",           "9 kcal/g",
         ["Testosterone production",
          "Fat-soluble vitamins (A,D,E,K)",
          "Joint lubrication",
          "Cell membrane structure"],
         "All goals: 0.8-1g/kg\nKeep > 20% total cals\nNever go below 40g/day",
         ["Nuts & seeds", "Olive oil, Ghee", "Avocado",
          "Fatty fish (salmon)", "Coconut oil (moderate)", "Dark chocolate"]),
    ]

    for i, (col, name, kcal, functions, target, sources) in enumerate(data):
        x = 0.02 + i * 0.33
        _rbox(ax, x, 0.08, 0.305, 0.80, col, alpha=0.07)
        _rbox(ax, x, 0.845, 0.305, 0.04, col, alpha=0.45)
        _txt(ax, x+0.1525, 0.868, name, size=11, bold=True, color=WHITE)
        _txt(ax, x+0.1525, 0.846, kcal, size=8, color=col)

        _txt(ax, x+0.1525, 0.815, "What it does:", size=8, bold=True, color=WHITE)
        for j, fn in enumerate(functions):
            _txt(ax, x+0.1525, 0.793 - j*0.023, f"- {fn}", size=7.5, color=GREY)

        _txt(ax, x+0.1525, 0.685, "Daily Target:", size=8, bold=True, color=col)
        for j, line in enumerate(target.split("\n")):
            _txt(ax, x+0.1525, 0.663 - j*0.023, line, size=7.5, color=WHITE)

        _txt(ax, x+0.1525, 0.59, "Best Sources:", size=8, bold=True, color=WHITE)
        for j, src in enumerate(sources):
            _txt(ax, x+0.1525, 0.568 - j*0.025, f"+ {src}", size=7.5, color=GREY)

        # bar representing proportion
        proportion = [35, 45, 20][i]
        bar_w = proportion / 100 * 0.27
        _rbox(ax, x + (0.305 - bar_w)/2, 0.10, bar_w, 0.025, col, alpha=0.7)
        _txt(ax, x+0.1525, 0.115, f"{proportion}% of calories", size=8, bold=True, color=col)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=BG, edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# INFOGRAPHIC 3 — Fat Loss
# ─────────────────────────────────────────────────────────────────────────────

def _build_fat_loss() -> bytes:
    fig, ax = plt.subplots(figsize=(14, 10))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis("off")

    _rbox(ax, 0.02, 0.91, 0.96, 0.08, CARD_MID)
    _txt(ax, 0.5, 0.957, "FAT LOSS — Science-Based Complete Guide", size=15, bold=True, color=WHITE)
    _txt(ax, 0.5, 0.926, "Calorie deficit + right foods + training = sustainable fat loss", size=10, color=GREY)

    # Energy balance
    _rbox(ax, 0.02, 0.78, 0.96, 0.115, ORANGE, alpha=0.08)
    _txt(ax, 0.5, 0.88, "THE FAT LOSS EQUATION", size=10, bold=True, color=ORANGE)
    _txt(ax, 0.18, 0.845, "CALORIES IN", size=13, bold=True, color=RED)
    _txt(ax, 0.18, 0.817, "What you eat", size=9, color=GREY)
    _txt(ax, 0.5, 0.845, "<", size=20, bold=True, color=YELLOW)
    _txt(ax, 0.80, 0.845, "CALORIES OUT", size=13, bold=True, color=GREEN)
    _txt(ax, 0.80, 0.817, "TDEE (what you burn)", size=9, color=GREY)
    _txt(ax, 0.5, 0.797, "Deficit of 300-500 kcal/day = 0.3-0.5 kg fat loss per week  |  Sustainable & muscle-preserving", size=8.5, color=WHITE)

    # 4 pillars
    _txt(ax, 0.5, 0.768, "4 PILLARS OF FAT LOSS", size=8, color=GREY, bold=True)
    pillars = [
        (0.02,  RED,    "CALORIE\nDEFICIT",
         ["300-500 kcal below TDEE",
          "Track with MyFitnessPal",
          "Weigh food for accuracy",
          "Adjust every 2 weeks"]),
        (0.26,  BLUE,   "HIGH\nPROTEIN",
         ["2.5g per kg body weight",
          "Preserves muscle mass",
          "Very high satiety",
          "Chicken, eggs, paneer"]),
        (0.50,  GREEN,  "STRENGTH\nTRAINING",
         ["3-4x per week lifting",
          "Builds/keeps muscle",
          "Raises resting metabolism",
          "Progressive overload"]),
        (0.74,  PURPLE, "SLEEP &\nSTRESS",
         ["7-9 hrs sleep/night",
          "High cortisol = fat storage",
          "Poor sleep = more hunger",
          "Stress management"]),
    ]

    for x, col, title, pts in pillars:
        _rbox(ax, x, 0.565, 0.22, 0.19, col, alpha=0.12)
        _rbox(ax, x, 0.725, 0.22, 0.035, col, alpha=0.4)
        _txt(ax, x+0.11, 0.744, title, size=9, bold=True, color=WHITE)
        for j, pt in enumerate(pts):
            _txt(ax, x+0.11, 0.7 - j*0.027, f"• {pt}", size=7.5, color=GREY)

    # Foods section
    _txt(ax, 0.5, 0.552, "BEST FAT LOSS FOODS", size=8, color=GREY, bold=True)
    food_groups = [
        (0.02,  GREEN, "High Volume\n(eat a lot)",
         "Cucumber, Lettuce\nBroccoli, Spinach\nWatermelon, Berries"),
        (0.26,  BLUE,  "High Protein\n(keep muscle)",
         "Chicken breast\nEgg whites, Fish\nLow-fat curd, Dal"),
        (0.50,  ORANGE,"Complex Carbs\n(sustain energy)",
         "Oats, Sweet potato\nBrown rice, Roti\nBanana (pre-workout)"),
        (0.74,  RED,   "AVOID\n(spike insulin)",
         "Sugary drinks\nUltra-processed food\nDeep fried snacks"),
    ]

    for x, col, title, foods in food_groups:
        _rbox(ax, x, 0.385, 0.22, 0.155, col, alpha=0.12)
        _rbox(ax, x, 0.510, 0.22, 0.033, col, alpha=0.4)
        _txt(ax, x+0.11, 0.528, title, size=8.5, bold=True, color=WHITE)
        for j, line in enumerate(foods.split("\n")):
            _txt(ax, x+0.11, 0.480 - j*0.025, line, size=8, color=GREY)

    # Myth busters
    _rbox(ax, 0.02, 0.02, 0.96, 0.345, CARD_MID, alpha=0.6)
    _txt(ax, 0.5, 0.353, "FAT LOSS MYTHS vs FACTS", size=9, bold=True, color=YELLOW)
    myths = [
        ("Eating fat makes you fat",            "Fat is essential. Excess CALORIES make you fat — from any source."),
        ("Carbs are the enemy",                 "Carbs fuel your workouts. Reduce them but don't eliminate them."),
        ("Cardio is the best for fat loss",     "Strength training preserves muscle and raises metabolism long-term."),
        ("Eat 6 meals/day to boost metabolism", "Total calories matter most. Meal timing has minimal effect."),
        ("Spot reduction works (crunches)",     "You can't choose where you lose fat. Deficit burns fat overall."),
    ]
    for j, (myth, fact) in enumerate(myths):
        y = 0.31 - j * 0.054
        _rbox(ax, 0.03, y-0.018, 0.935, 0.042, RED, alpha=0.06)
        _txt(ax, 0.07, y+0.005, "MYTH:", size=7.5, bold=True, color=RED, ha="left")
        _txt(ax, 0.18, y+0.005, myth, size=8, color=WHITE, ha="left")
        _txt(ax, 0.07, y-0.012, "FACT:", size=7.5, bold=True, color=GREEN, ha="left")
        _txt(ax, 0.18, y-0.012, fact, size=7.5, color=GREY, ha="left")

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor=BG, edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

BUILDERS = {
    "nutrition_muscle": _build_nutrition_muscle,
    "macros":           _build_macros,
    "fat_loss":         _build_fat_loss,
    "workout_plan":     _build_nutrition_muscle,   # fallback to nutrition for now
    "sleep":            _build_nutrition_muscle,
}


def is_graphic_request(text: str) -> bool:
    """Returns True if the user asked for a visual/graphic/picture response."""
    keywords = [
        "graphic", "picture", "visual", "infographic",
        "chart", "diagram", "image", "show me",
        "illustrate", "draw", "graph", "poster",
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def generate_infographic(question: str) -> bytes:
    """Detect topic from question and return PNG bytes of the infographic."""
    topic = detect_topic(question)
    builder = BUILDERS.get(topic, _build_nutrition_muscle)
    return builder()
