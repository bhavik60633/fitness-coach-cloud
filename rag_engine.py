"""
rag_engine.py — Cloud-ready RAG engine.

Replaces Ollama with Groq API for LLM inference.
ChromaDB stays embedded (runs on Render disk).
"""

import json
import os
from typing import Generator

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
import chromadb
from sentence_transformers import SentenceTransformer

from memory import CoachMemory

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH      = os.getenv("CHROMA_DB_PATH", "./chroma_db")
COLLECTION   = "fitness_docs"
EMBED_MODEL  = "all-MiniLM-L6-v2"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
N_RESULTS    = 3
TEMPERATURE  = 0.8
MAX_TOKENS   = 2048
# ────────────────────────────────────────────────────────────────────────────

BASE_SYSTEM = """You are Bhavik's personal fitness coach. You text him like a real trainer would — casual, direct, warm. No corporate tone.

Rules you NEVER break:
- Match answer length to the question. Simple question = 2-3 sentences. If he asks for a plan, diet breakdown, exercise list, or anything detailed — give the FULL complete answer, don't cut it short.
- Sound like a human texting, not a chatbot generating a report.
- Never use [X] or placeholder text. If you don't know a value, skip it or ask him.
- Never repeat yourself or restate what he just said back to him.
- ALWAYS reference his weight, goal, and recent logs when relevant — treat this info as facts you know.
- For plans/lists, use simple numbered points.
- Remember everything from the conversation history — treat it as your own memory.

You know his documents well: workouts, diet (ETF method, 1500-cal veg plans, 62 recipes), sleep guide, exercise science lectures. Use that knowledge confidently."""


class FitnessCoachRAG:
    def __init__(
        self,
        db_path: str = DB_PATH,
        model: str = OPENAI_MODEL,
        memory: CoachMemory | None = None,
    ) -> None:
        self.model   = model
        self.memory  = memory or CoachMemory()

        # OpenAI client
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set!")
        self.client = OpenAI(api_key=api_key)

        # ChromaDB
        self.client     = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_collection(COLLECTION)

        # Embedder
        self.embedder = SentenceTransformer(EMBED_MODEL)

        count = self.collection.count()
        print(f"✅  RAG engine ready — {count:,} chunks in knowledge base")

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
    ) -> list[dict]:

        system_parts = [BASE_SYSTEM]

        if include_memory and user_id:
            context_lines = []

            # Goal + progress
            profile = self.memory.get_profile(user_id)
            if profile and profile.get("goal_summary") and profile.get("goal_start_date"):
                goal_ctx = self.memory.format_goal_context(user_id)
                context_lines.append(f"Bhavik's goal: {goal_ctx}")

            # Recent logs — last 7 days
            logs = self.memory.format_recent_logs(user_id, days=7)
            if logs and logs != "No recent logs.":
                context_lines.append(f"Recent logs:\n{logs}")

            # Conversation history — last 20 messages with timestamps
            history = self.memory.get_recent_history(user_id, limit=20)
            if history:
                hist_lines = []
                for h in history:
                    role = "Bhavik" if h["role"] == "user" else "Coach"
                    ts = h.get("timestamp", "")[:16] if h.get("timestamp") else ""
                    msg = h["message"][:600] + "…" if len(h["message"]) > 600 else h["message"]
                    hist_lines.append(f"[{ts}] {role}: {msg}")
                context_lines.append("Conversation history (oldest first):\n" + "\n".join(hist_lines))

            if context_lines:
                system_parts.append(
                    "--- Context ---\n" + "\n\n".join(context_lines) + "\n--- End Context ---"
                )

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
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=MAX_TOKENS,
            top_p=0.9,
        )
        return response.choices[0].message.content.strip()

    # ── Synchronous query ─────────────────────────────────────────────────

    def query(self, question: str, user_id: str = "default") -> str:
        context  = self._retrieve(question)
        messages = self._build_messages(question, context, user_id)
        answer   = self._call_groq(messages)

        # Save to memory
        if user_id:
            self.memory.save_message(user_id, "user",  question)
            self.memory.save_message(user_id, "coach", answer)

        return answer

    # ── Streaming query ───────────────────────────────────────────────────

    def stream_query(
        self,
        question: str,
        user_id: str = "default",
    ) -> Generator[str, None, None]:
        context  = self._retrieve(question)
        messages = self._build_messages(question, context, user_id)

        stream = self.client.chat.completions.create(
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
            response = self.client.chat.completions.create(
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
