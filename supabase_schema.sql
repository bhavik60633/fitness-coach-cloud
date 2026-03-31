-- ═══════════════════════════════════════════════════════════════════════════
-- Supabase Schema for Fitness Coach RAG
-- Run this in Supabase → SQL Editor → New Query → Run
-- ═══════════════════════════════════════════════════════════════════════════

-- 1. Full conversation history
CREATE TABLE IF NOT EXISTS conversations (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT      NOT NULL,
    role        TEXT      NOT NULL,   -- 'user' | 'coach'
    message     TEXT      NOT NULL,
    timestamp   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_user
    ON conversations (user_id, timestamp DESC);

-- 2. User profile + active goals
CREATE TABLE IF NOT EXISTS user_profile (
    user_id         TEXT PRIMARY KEY,
    name            TEXT,
    current_weight  DOUBLE PRECISION,
    target_weight   DOUBLE PRECISION,
    goal_summary    TEXT,
    goal_start_date TEXT,
    goal_end_date   TEXT,
    goal_days_total INTEGER,
    current_plan    TEXT,
    preferences     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Daily check-in / progress logs
CREATE TABLE IF NOT EXISTS daily_logs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT    NOT NULL,
    log_date        TEXT    NOT NULL,
    workout_done    INTEGER DEFAULT 0,
    workout_notes   TEXT,
    diet_notes      TEXT,
    weight          DOUBLE PRECISION,
    energy_level    INTEGER,
    sleep_hours     DOUBLE PRECISION,
    extra_notes     TEXT,
    plan_adjustment TEXT,
    timestamp       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, log_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_logs_user
    ON daily_logs (user_id, log_date DESC);

-- 4. Scheduled reminders
CREATE TABLE IF NOT EXISTS reminders (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT    NOT NULL,
    reminder_type   TEXT    NOT NULL,
    hour            INTEGER NOT NULL,
    minute          INTEGER NOT NULL,
    enabled         BOOLEAN DEFAULT TRUE,
    UNIQUE(user_id, reminder_type)
);

-- 5. Food / calorie logs (one row per food item eaten)
CREATE TABLE IF NOT EXISTS food_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT    NOT NULL,
    log_date        TEXT    NOT NULL,   -- ISO date "YYYY-MM-DD"
    meal_name       TEXT    NOT NULL,   -- 'Breakfast' | 'Lunch' | 'Dinner' | 'Snack'
    food_description TEXT   NOT NULL,
    calories        INTEGER NOT NULL DEFAULT 0,
    protein_g       DOUBLE PRECISION DEFAULT 0,
    carbs_g         DOUBLE PRECISION DEFAULT 0,
    fat_g           DOUBLE PRECISION DEFAULT 0,
    image_analyzed  BOOLEAN DEFAULT FALSE,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_food_logs_user_date
    ON food_logs (user_id, log_date DESC);

-- ═══════════════════════════════════════════════════════════════════════════
-- Enable Row Level Security (optional but recommended)
-- ═══════════════════════════════════════════════════════════════════════════

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profile  ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_logs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE reminders     ENABLE ROW LEVEL SECURITY;

-- Drop old policies first (safe to re-run)
DROP POLICY IF EXISTS "Service key full access" ON conversations;
DROP POLICY IF EXISTS "Service key full access" ON user_profile;
DROP POLICY IF EXISTS "Service key full access" ON daily_logs;
DROP POLICY IF EXISTS "Service key full access" ON reminders;
DROP POLICY IF EXISTS "Service key full access" ON food_logs;

ALTER TABLE food_logs ENABLE ROW LEVEL SECURITY;

-- Allow the service key (your backend) to do everything
CREATE POLICY "Service key full access" ON conversations
    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service key full access" ON user_profile
    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service key full access" ON daily_logs
    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service key full access" ON reminders
    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service key full access" ON food_logs
    FOR ALL USING (true) WITH CHECK (true);
