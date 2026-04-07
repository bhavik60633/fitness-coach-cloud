"""
rag_engine.py — Cloud-ready RAG engine.

Replaces Ollama with Groq API for LLM inference.
ChromaDB stays embedded (runs on Render disk).
"""

import json
import logging
import os
from typing import Generator

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
import chromadb
from sentence_transformers import SentenceTransformer

from memory import CoachMemory
from coach_brain import CoachBrain

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH      = os.getenv("CHROMA_DB_PATH", "./chroma_db")
COLLECTION   = "fitness_docs"
EMBED_MODEL  = "all-MiniLM-L6-v2"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
N_RESULTS    = 3
TEMPERATURE  = 0.8
MAX_TOKENS   = 2048
# ────────────────────────────────────────────────────────────────────────────

BASE_SYSTEM = """You are an elite ETF Personal Coach operating 24/7 via Telegram.

You have TWO response modes. Pick the correct one based on what the user is saying.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE 1 — CONVERSATIONAL (use for most messages)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use this when the user is:
- Asking a question ("explain", "what is", "how do I", "tell me about")
- Requesting information about a lecture, module, recipe, exercise, or concept
- Having a casual chat or greeting
- Asking about nutrition, calories, sleep, exercises, or any factual topic

In this mode:
- Respond like a knowledgeable human coach speaking directly to the person
- NO tags like [DIAGNOSIS], [ETF PRINCIPLE], [ACTION PLAN], etc.
- Be clear, warm, and direct — like a coach explaining something to a client face-to-face
- Match length to the question: short question = short answer, detailed question = full explanation
- End with one brief follow-up question or action only if it genuinely adds value

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE 2 — STRUCTURED COACHING (use only for progress/accountability)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use this ONLY when the user is:
- Sharing a progress update, check-in, or log ("I worked out", "I missed today", "my weight is...")
- Asking for a personalised plan or program adjustment
- Reporting a problem with their compliance, motivation, or consistency
- Explicitly asking for a coaching assessment

In this mode, use this format:

[DIAGNOSIS]
What is actually happening based on user data.

[ETF PRINCIPLE]
The relevant ETF principle (1-3 lines, sharp).

[ACTION PLAN]
1. Step one
2. Step two
3. Step three

[COACH FEEDBACK]
Call out the mistake, gap, or pattern — direct but controlled.

[NEXT CHECK]
- Question or task to assign

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE COACHING PRINCIPLES (always apply):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Use ETF methodology: Module 1 (Mindset), Module 2 (Nutrition/Calories), Module 3 (Hypertrophy), Module 4 (Programming), Module 5 (Fatigue/Recovery)
- When giving personalised coaching, reference the user's actual data — never give generic advice
- Remember everything from conversation history — treat it as your own memory
- Tone: Direct. Clear. No unnecessary fluff.

YOUR CAPABILITIES — what you CAN do proactively:
- You CAN and DO send daily reminders (water, workout, meals, sleep).
- You send a water reminder every 2 hours automatically.
- You send an evening log nudge if the user hasn't logged by 9pm.
- You send a morning check-in at the user's preferred time.
- You send a weekly review every Sunday evening.
- If asked to remind about ANYTHING, say YES confidently — you WILL remind them.

You know the documents: workouts, ETF diet method, 1500-cal vegetarian plans, 62 recipes, sleep guide, exercise science. Use this knowledge confidently."""


class FitnessCoachRAG:
    def __init__(
        self,
        db_path: str = DB_PATH,
        model: str = OPENAI_MODEL,
        memory: CoachMemory | None = None,
    ) -> None:
        self.model   = model
        self.memory  = memory or CoachMemory()

        # 🧠 Brain — multi-step reasoning engine (Claw Code integration)
        self.brain = CoachBrain(self.memory)

        # OpenAI client
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set!")
        self.openai = OpenAI(api_key=api_key)

        # Embedder (load before ChromaDB so it's ready for auto-ingest)
        self.embedder = SentenceTransformer(EMBED_MODEL)

        # ChromaDB — auto-ingest if collection missing
        self.chroma = chromadb.PersistentClient(path=db_path)
        try:
            self.collection = self.chroma.get_collection(COLLECTION)
        except Exception:
            print("ChromaDB collection not found — running ingest now...")
            self._auto_ingest(db_path)
            self.collection = self.chroma.get_collection(COLLECTION)

        count = self.collection.count()
        print(f"RAG engine ready -- {count:,} chunks in knowledge base (brain active)")

    def _auto_ingest(self, db_path: str) -> None:
        """Run ingest automatically if ChromaDB collection is missing."""
        from ingest import ingest
        from pathlib import Path
        script_dir = Path(__file__).parent.resolve()
        docs_dir   = script_dir / "docs"
        obsidian   = os.getenv("OBSIDIAN_VAULT_PATH", "")
        dirs = [str(docs_dir)] if docs_dir.exists() else []
        ingest(dirs, db_path=db_path, obsidian_vault=obsidian)

    # ── Retrieval ─────────────────────────────────────────────────────────

    def _retrieve(self, question: str) -> str:
        q_emb   = self.embedder.encode(question).tolist()
        results = self.collection.query(
            query_embeddings=[q_emb],
            n_results=N_RESULTS,
            include=["documents", "metadatas"],
        )
        parts = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            source = meta.get("source", "Unknown")
            parts.append(f"[{source}]\n{doc}")
        return "\n\n---\n\n".join(parts)

    # ── Build messages for Groq chat API ──────────────────────────────────

    def _build_messages(
        self,
        question: str,
        context: str,
        user_id: str,
        include_memory: bool = True,
        brain_context: str = "",
    ) -> list[dict]:

        system_parts = [BASE_SYSTEM]

        # 🧠 Brain's situational awareness (NEW — Claw Code integration)
        if brain_context:
            system_parts.append(brain_context)

        if include_memory and user_id:
            context_lines = []

            # Full ETF user state model (compliance, flags, training level, obstacles, etc.)
            user_state = self.memory.get_user_state_for_prompt(user_id)
            if user_state and user_state != "No profile yet — new user.":
                context_lines.append(f"=== USER STATE ===\n{user_state}\n=== END ===")

            # Recent logs — last 7 days
            logs = self.memory.format_recent_logs(user_id, days=7)
            if logs and logs != "No recent logs.":
                context_lines.append(f"=== RECENT LOGS ===\n{logs}\n=== END ===")

            # Conversation history — last 20 messages with timestamps
            history = self.memory.get_recent_history(user_id, limit=20)
            if history:
                hist_lines = []
                for h in history:
                    role = "User" if h["role"] == "user" else "Coach"
                    ts = h.get("timestamp", "")[:16] if h.get("timestamp") else ""
                    msg = h["message"][:600] + "…" if len(h["message"]) > 600 else h["message"]
                    hist_lines.append(f"[{ts}] {role}: {msg}")
                context_lines.append("=== CONVERSATION HISTORY ===\n" + "\n".join(hist_lines) + "\n=== END ===")

            if context_lines:
                system_parts.append("\n\n".join(context_lines))

        # Document excerpts
        if context.strip():
            system_parts.append(
                f"--- Relevant info from Bhavik's documents ---\n{context}\n--- End ---"
            )

        system_message = "\n\n".join(system_parts)

        return [
            {"role": "system", "content": system_message},
            {"role": "user", "content": question},
        ]

    # ── Call Groq API ─────────────────────────────────────────────────────

    def _call_groq(self, messages: list[dict], temperature: float = TEMPERATURE) -> str:
        response = self.openai.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=MAX_TOKENS,
            top_p=0.9,
        )
        return response.choices[0].message.content.strip()

    # ── Synchronous query ─────────────────────────────────────────────────

    def query(self, question: str, user_id: str = "default") -> str:
        # 🧠 Step 1: Brain reasons through the situation
        brain_ctx = ""
        reasoning_chain = None
        try:
            brain_ctx = self.brain.build_brain_context(question, user_id)
            reasoning_chain = self.brain.reason(question, user_id)
            logger.info(
                f"Brain: intents={reasoning_chain.detected_intents}, "
                f"decision={reasoning_chain.final_decision}, "
                f"followups={len(reasoning_chain.followup_actions)}"
            )
        except Exception as exc:
            logger.warning(f"Brain reasoning failed (falling back): {exc}")

        # Step 2: Retrieve document context
        context  = self._retrieve(question)

        # Step 3: Build messages WITH brain context
        messages = self._build_messages(question, context, user_id, brain_context=brain_ctx)
        answer   = self._call_groq(messages)

        # Step 4: Save to memory
        if user_id:
            self.memory.save_message(user_id, "user",  question)
            self.memory.save_message(user_id, "coach", answer)

        # Step 5: Return answer + reasoning chain for follow-up scheduling
        self._last_reasoning_chain = reasoning_chain
        return answer

    def get_last_reasoning_chain(self):
        """Get the reasoning chain from the last query (for follow-up scheduling)."""
        return getattr(self, "_last_reasoning_chain", None)

    # ── Streaming query ───────────────────────────────────────────────────

    def stream_query(
        self,
        question: str,
        user_id: str = "default",
    ) -> Generator[str, None, None]:
        # 🧠 Brain thinks first
        brain_ctx = ""
        reasoning_chain = None
        try:
            brain_ctx = self.brain.build_brain_context(question, user_id)
            reasoning_chain = self.brain.reason(question, user_id)
        except Exception as exc:
            logger.warning(f"Brain reasoning failed in stream (falling back): {exc}")

        context  = self._retrieve(question)
        messages = self._build_messages(question, context, user_id, brain_context=brain_ctx)

        stream = self.openai.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            top_p=0.9,
            stream=True,
        )

        full_answer = ""
        for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                full_answer += token
                yield token

        if user_id and full_answer:
            self.memory.save_message(user_id, "user",  question)
            self.memory.save_message(user_id, "coach", full_answer)

        self._last_reasoning_chain = reasoning_chain

    # ── Adaptive plan query ───────────────────────────────────────────────

    def adjust_plan_query(self, reason: str, user_id: str) -> str:
        context  = self._retrieve(f"workout plan adjustment {reason}")
        profile  = self.memory.get_profile(user_id)
        logs     = self.memory.format_recent_logs(user_id, days=14)
        goal_ctx = self.memory.format_goal_context(user_id)

        plan_str = ""
        if profile and profile.get("current_plan"):
            try:
                plan = json.loads(profile["current_plan"])
                plan_str = f"\nCurrent plan: {json.dumps(plan, indent=2)}"
            except Exception:
                pass

        system = (
            f"{BASE_SYSTEM}\n\n"
            f"=== BHAVIK'S GOAL ===\n{goal_ctx}\n=== END ===\n\n"
            f"=== RECENT LOGS ===\n{logs}\n=== END ===\n\n"
            f"=== FITNESS DOCUMENT CONTEXT ===\n{context}\n=== END ===\n\n"
            f"{plan_str}"
        )

        user_msg = (
            f"Situation: I could not complete today's session. Reason: {reason}\n\n"
            f"As my coach, acknowledge the situation with empathy, then:\n"
            f"1. Adjust today's plan (or reschedule the session)\n"
            f"2. Suggest any active recovery or lighter alternative if relevant\n"
            f"3. Reassure me the goal is still on track\n"
            f"Keep it short, warm, and motivating."
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]

        answer = self._call_groq(messages, temperature=0.7)
        self.memory.save_message(user_id, "user",  f"[Missed session] {reason}")
        self.memory.save_message(user_id, "coach", answer)
        return answer

    # ── Daily check-in prompt ─────────────────────────────────────────────

    def generate_daily_checkin(self, user_id: str) -> str:
        from datetime import date as date_cls
        today    = date_cls.today().strftime("%A, %d %B")
        context  = self._retrieve("daily workout plan nutrition check-in")
        goal_ctx = self.memory.format_goal_context(user_id)
        logs     = self.memory.format_recent_logs(user_id, days=5)
        streak   = self.memory.get_streak(user_id)

        system = (
            f"{BASE_SYSTEM}\n\n"
            f"=== BHAVIK'S GOAL ===\n{goal_ctx}\n=== END ===\n\n"
            f"=== RECENT ACTIVITY ===\n{logs}\n=== END ===\n\n"
            f"=== DOCUMENT CONTEXT ===\n{context}\n=== END ==="
        )

        user_msg = (
            f"Today is {today}. Current workout streak: {streak} days.\n\n"
            f"Send me a brief, personalised morning check-in message:\n"
            f"1. Greet me and reference my streak / recent progress\n"
            f"2. Tell me what today's focus should be (workout + nutrition)\n"
            f"3. Give one specific tip from my documents relevant to today\n"
            f"4. Ask me to log back after my session\n"
            f"Keep it punchy and motivating — like a real coach texting in the morning."
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]
        return self._call_groq(messages, temperature=0.75)

    # ── Weekly review ─────────────────────────────────────────────────────

    def generate_weekly_review(self, user_id: str) -> str:
        context  = self._retrieve("weekly progress review training nutrition")
        goal_ctx = self.memory.format_goal_context(user_id)
        logs     = self.memory.format_recent_logs(user_id, days=7)
        streak   = self.memory.get_streak(user_id)

        system = (
            f"{BASE_SYSTEM}\n\n"
            f"=== BHAVIK'S GOAL ===\n{goal_ctx}\n=== END ===\n\n"
            f"=== THIS WEEK'S LOGS ===\n{logs}\n=== END ===\n\n"
            f"=== DOCUMENT CONTEXT ===\n{context}\n=== END ==="
        )

        user_msg = (
            f"Current streak: {streak} days.\n\n"
            f"Write my weekly review:\n"
            f"1. Celebrate wins from this week\n"
            f"2. Identify one area to improve next week\n"
            f"3. Adjust next week's plan if needed based on performance\n"
            f"4. Project whether I'm on track for my goal\n"
            f"5. Give me clear targets for next week\n"
            f"Keep it structured but warm."
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ]
        return self._call_groq(messages, temperature=0.7)

    # ── Food image analysis (Groq vision) ────────────────────────────────

    def analyze_food_image(self, image_base64: str) -> dict:
        """
        Analyze a food photo using Groq vision model.
        Returns a dict: food_description, calories, protein_g, carbs_g, fat_g, meal_name, confidence, notes.
        """
        prompt = (
            "You are a certified nutritionist. Analyze this food image carefully.\n\n"
            "Identify every food item visible, estimate the portion size, and calculate total nutrition.\n"
            "Use standard Indian/Asian food nutrition data where applicable.\n\n"
            "Respond ONLY in this exact JSON format (no extra text, no markdown):\n"
            "{\n"
            '  "food_description": "specific food name and description",\n'
            '  "calories": 450,\n'
            '  "protein_g": 25.0,\n'
            '  "carbs_g": 40.0,\n'
            '  "fat_g": 15.0,\n'
            '  "meal_name": "Breakfast",\n'
            '  "confidence": "high",\n'
            '  "notes": "any important notes about the estimate"\n'
            "}\n\n"
            "meal_name must be one of: Breakfast, Lunch, Dinner, Snack.\n"
            "Be realistic — do NOT underestimate calories. Account for oil, sauces, and hidden calories."
        )

        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                temperature=0.1,
                max_tokens=512,
            )
            raw = response.choices[0].message.content.strip()
            # Extract JSON robustly
            import re as _re
            match = _re.search(r"\{.*\}", raw, _re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as exc:
            print(f"Vision analysis error: {exc}")

        return {
            "food_description": "Could not identify food",
            "calories": 0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
            "meal_name": "Snack",
            "confidence": "low",
            "notes": "Image analysis failed — please log manually.",
        }

    # ── Health check (always True for cloud — no Ollama dependency) ───────

    def is_ollama_running(self) -> bool:
        """Always returns True in cloud mode (OpenAI API is always available)."""
        return True
