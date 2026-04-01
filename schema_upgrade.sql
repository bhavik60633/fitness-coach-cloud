-- ═══════════════════════════════════════════════════════════════════════════
-- SCHEMA UPGRADE: Claw Code Brain Integration
-- Run this AFTER the original supabase_schema.sql
-- ═══════════════════════════════════════════════════════════════════════════

-- 1. Coach's internal thought chain (inspired by Claw Code's TranscriptStore)
CREATE TABLE IF NOT EXISTS coach_thoughts (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT      NOT NULL,
    thought_type    TEXT      NOT NULL,  -- 'reasoning' | 'observation' | 'decision' | 'followup_plan'
    content         TEXT      NOT NULL,
    context_snapshot TEXT,               -- JSON: what the coach knew at this moment
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_thoughts_user
    ON coach_thoughts (user_id, created_at DESC);

-- 2. Proactive follow-up queue (inspired by Claw Code's ExecutionRegistry)
CREATE TABLE IF NOT EXISTS followup_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT      NOT NULL,
    followup_type   TEXT      NOT NULL,  -- 'streak_check' | 'soreness_check' | 'meal_reminder' | 'motivation' | 'weigh_in' | 'water' | 'sleep'
    message         TEXT      NOT NULL,
    scheduled_at    TIMESTAMPTZ NOT NULL,
    sent            BOOLEAN   DEFAULT FALSE,
    sent_at         TIMESTAMPTZ,
    trigger_reason  TEXT,                -- why this followup was created
    priority        INTEGER   DEFAULT 5, -- 1=critical, 10=nice-to-have
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_followup_pending
    ON followup_queue (user_id, sent, scheduled_at);

-- 3. User behavioral patterns (learned over time)
CREATE TABLE IF NOT EXISTS user_patterns (
    id              BIGSERIAL PRIMARY KEY,
    user_id         TEXT      NOT NULL,
    pattern_type    TEXT      NOT NULL,  -- 'workout_time' | 'skip_day' | 'energy_trend' | 'meal_pattern' | 'sleep_pattern'
    pattern_data    TEXT      NOT NULL,  -- JSON: the learned pattern
    confidence      DOUBLE PRECISION DEFAULT 0.5,  -- 0.0 to 1.0
    last_updated    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, pattern_type)
);

CREATE INDEX IF NOT EXISTS idx_patterns_user
    ON user_patterns (user_id);

-- 4. Multiple reminder types (upgrade existing reminders table)
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS message_template TEXT;
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS adaptive BOOLEAN DEFAULT FALSE;
ALTER TABLE reminders ADD COLUMN IF NOT EXISTS last_sent TIMESTAMPTZ;

-- RLS for new tables
ALTER TABLE coach_thoughts ENABLE ROW LEVEL SECURITY;
ALTER TABLE followup_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_patterns  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service key full access" ON coach_thoughts;
DROP POLICY IF EXISTS "Service key full access" ON followup_queue;
DROP POLICY IF EXISTS "Service key full access" ON user_patterns;

CREATE POLICY "Service key full access" ON coach_thoughts
    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service key full access" ON followup_queue
    FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service key full access" ON user_patterns
    FOR ALL USING (true) WITH CHECK (true);
