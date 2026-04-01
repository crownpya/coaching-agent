-- SQLite Schema for Coaching Agent
-- UUID helper (reusable expression, referenced inline in each table)

CREATE TABLE IF NOT EXISTS coachees (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    nombre      TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    rol         TEXT,
    empresa     TEXT,
    idioma_preferido TEXT NOT NULL DEFAULT 'es',
    fecha_registro   TEXT NOT NULL DEFAULT (datetime('now')),
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coaching_programs (
    id                   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    coachee_id           TEXT NOT NULL REFERENCES coachees(id),
    fecha_inicio         TEXT NOT NULL,
    fecha_fin_estimada   TEXT,
    estado               TEXT NOT NULL DEFAULT 'activo',
    certificado_entregado INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    program_id        TEXT NOT NULL REFERENCES coaching_programs(id),
    numero_sesion     INTEGER NOT NULL CHECK (numero_sesion BETWEEN 1 AND 8),
    fase_grow         TEXT NOT NULL CHECK (fase_grow IN ('goal', 'reality', 'options', 'will')),
    fecha_programada  TEXT,
    fecha_realizada   TEXT,
    mood_antes        INTEGER CHECK (mood_antes BETWEEN 1 AND 5),
    mood_despues      INTEGER CHECK (mood_despues BETWEEN 1 AND 5),
    resumen           TEXT,
    criterios_avance  TEXT,   -- JSON
    notas_agente      TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS competency_tracking (
    id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    session_id          TEXT NOT NULL REFERENCES sessions(id),
    competencia         TEXT NOT NULL,
    nivel_autoevaluado  INTEGER CHECK (nivel_autoevaluado BETWEEN 1 AND 5),
    nivel_coach         INTEGER CHECK (nivel_coach BETWEEN 1 AND 5),
    evidencia           TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS wheel_of_life (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    categorias      TEXT NOT NULL,  -- JSON
    fecha_registro  TEXT NOT NULL DEFAULT (datetime('now')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS beliefs_tracker (
    id                               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    session_id                       TEXT NOT NULL REFERENCES sessions(id),
    creencia_limitante               TEXT,
    creencia_potenciadora_reemplazo  TEXT,
    evidencia_contraria              TEXT,
    estado                           TEXT,
    created_at                       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS action_plans (
    id            TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    objetivo      TEXT,
    acciones      TEXT,   -- JSON
    fecha_inicio  TEXT,
    fecha_fin     TEXT,
    kpis          TEXT,   -- JSON
    estado        TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nudge_schedule (
    id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    program_id        TEXT NOT NULL REFERENCES coaching_programs(id),
    fecha_programada  TEXT,
    fecha_enviada     TEXT,
    tipo              TEXT,
    contenido         TEXT,
    estado            TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS session_messages (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    program_id  TEXT NOT NULL REFERENCES coaching_programs(id),
    session_num INTEGER NOT NULL,
    rol         TEXT NOT NULL CHECK (rol IN ('user', 'agent')),
    mensaje     TEXT NOT NULL,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coaches (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    nombre      TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    especialidad TEXT,   -- ej: 'liderazgo', 'productividad', 'comunicacion'
    nivel       TEXT CHECK (nivel IN ('junior', 'senior', 'master')),
    biografia   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coach_coachee_assignments (
    id               TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    coach_id         TEXT NOT NULL REFERENCES coaches(id),
    coachee_id       TEXT NOT NULL REFERENCES coachees(id),
    fecha_asignacion TEXT NOT NULL DEFAULT (datetime('now')),
    estado           TEXT NOT NULL DEFAULT 'activa' CHECK (estado IN ('activa', 'finalizada', 'pausada')),
    notas            TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS coach_feedback (
    id                TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    assignment_id     TEXT NOT NULL REFERENCES coach_coachee_assignments(id),
    session_id        TEXT NOT NULL REFERENCES sessions(id),
    feedback_coach    TEXT,
    feedback_coachee  TEXT,
    valoracion_coach  INTEGER CHECK (valoracion_coach BETWEEN 1 AND 5),
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nudge_ab_tests (
    id             TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' || substr(lower(hex(randomblob(2))),2) || '-' || substr('89ab',abs(random()) % 4 + 1, 1) || substr(lower(hex(randomblob(2))),2) || '-' || lower(hex(randomblob(6)))),
    nudge_context  TEXT NOT NULL,   -- "motivation-low", "post-session", etc.
    rol            TEXT NOT NULL,
    version_a      TEXT NOT NULL,
    version_b      TEXT NOT NULL,
    winner         TEXT,            -- 'a', 'b', o NULL si aún sin resultado
    tests_a        INTEGER NOT NULL DEFAULT 0,
    tests_b        INTEGER NOT NULL DEFAULT 0,
    respuestas_a   INTEGER NOT NULL DEFAULT 0,
    respuestas_b   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sessions_program_id     ON sessions(program_id);
CREATE INDEX IF NOT EXISTS idx_sessions_numero_sesion  ON sessions(numero_sesion);
CREATE INDEX IF NOT EXISTS idx_action_plans_estado     ON action_plans(estado);
CREATE INDEX IF NOT EXISTS idx_nudge_schedule_fecha         ON nudge_schedule(fecha_programada);
CREATE INDEX IF NOT EXISTS idx_assignments_coach_id         ON coach_coachee_assignments(coach_id);
CREATE INDEX IF NOT EXISTS idx_assignments_coachee_id       ON coach_coachee_assignments(coachee_id);
CREATE INDEX IF NOT EXISTS idx_coach_feedback_assignment_id ON coach_feedback(assignment_id);
