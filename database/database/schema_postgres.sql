-- Habilitar extensión para UUID
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tabla 1: Coachees
CREATE TABLE IF NOT EXISTS coachees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    rol TEXT,
    empresa TEXT,
    idioma_preferido TEXT DEFAULT 'es',
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 2: Coaching Programs
CREATE TABLE IF NOT EXISTS coaching_programs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coachee_id UUID NOT NULL REFERENCES coachees(id) ON DELETE CASCADE,
    fecha_inicio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_fin_estimada TIMESTAMP,
    estado TEXT DEFAULT 'activo',
    certificado_entregado BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 3: Sessions
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id UUID NOT NULL REFERENCES coaching_programs(id) ON DELETE CASCADE,
    numero_sesion INTEGER CHECK(numero_sesion BETWEEN 1 AND 8),
    fase_grow TEXT CHECK(fase_grow IN ('goal', 'reality', 'options', 'will')),
    fecha_programada TIMESTAMP,
    fecha_realizada TIMESTAMP,
    mood_antes INTEGER CHECK(mood_antes BETWEEN 1 AND 5),
    mood_despues INTEGER CHECK(mood_despues BETWEEN 1 AND 5),
    resumen TEXT,
    criterios_avance JSONB,
    notas_agente TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 4: Competency Tracking
CREATE TABLE IF NOT EXISTS competency_tracking (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    competencia TEXT NOT NULL,
    nivel_autoevaluado INTEGER CHECK(nivel_autoevaluado BETWEEN 1 AND 5),
    nivel_coach INTEGER CHECK(nivel_coach BETWEEN 1 AND 5),
    evidencia TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 5: Wheel of Life
CREATE TABLE IF NOT EXISTS wheel_of_life (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    categorias JSONB NOT NULL,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 6: Beliefs Tracker
CREATE TABLE IF NOT EXISTS beliefs_tracker (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    creencia_limitante TEXT NOT NULL,
    creencia_potenciadora_reemplazo TEXT,
    evidencia_contraria TEXT,
    estado TEXT DEFAULT 'identificada',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 7: Action Plans
CREATE TABLE IF NOT EXISTS action_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    objetivo TEXT NOT NULL,
    acciones JSONB NOT NULL,
    fecha_inicio DATE,
    fecha_fin DATE,
    kpis JSONB,
    estado TEXT DEFAULT 'pendiente',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 8: Nudge Schedule
CREATE TABLE IF NOT EXISTS nudge_schedule (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id UUID NOT NULL REFERENCES coaching_programs(id) ON DELETE CASCADE,
    fecha_programada TIMESTAMP NOT NULL,
    fecha_enviada TIMESTAMP,
    tipo TEXT CHECK(tipo IN ('reflexion', 'seguimiento', 'motivacion', 'ab_test', 'inteligente')),
    contenido TEXT NOT NULL,
    estado TEXT DEFAULT 'pendiente',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 9: Session Messages
CREATE TABLE IF NOT EXISTS session_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id UUID NOT NULL REFERENCES coaching_programs(id) ON DELETE CASCADE,
    session_num INTEGER,
    rol TEXT CHECK(rol IN ('user', 'agent')),
    mensaje TEXT NOT NULL,
    timestamp TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 10: Coaches
CREATE TABLE IF NOT EXISTS coaches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    especialidad TEXT,
    nivel TEXT,
    biografia TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 11: Coach Coachee Assignments
CREATE TABLE IF NOT EXISTS coach_coachee_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id UUID NOT NULL REFERENCES coaches(id) ON DELETE CASCADE,
    coachee_id UUID NOT NULL REFERENCES coachees(id) ON DELETE CASCADE,
    fecha_asignacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    estado TEXT DEFAULT 'activa',
    notas TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 12: Coach Feedback
CREATE TABLE IF NOT EXISTS coach_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id UUID NOT NULL REFERENCES coach_coachee_assignments(id) ON DELETE CASCADE,
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    feedback_coach TEXT,
    feedback_coachee TEXT,
    valoracion_coach INTEGER CHECK(valoracion_coach BETWEEN 1 AND 5),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabla 13: Nudge AB Tests
CREATE TABLE IF NOT EXISTS nudge_ab_tests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nudge_context TEXT NOT NULL,
    rol TEXT NOT NULL,
    version_a TEXT,
    version_b TEXT,
    tests_a INTEGER DEFAULT 0,
    tests_b INTEGER DEFAULT 0,
    respuestas_a INTEGER DEFAULT 0,
    respuestas_b INTEGER DEFAULT 0,
    winner TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_sessions_program_id ON sessions(program_id);
CREATE INDEX IF NOT EXISTS idx_sessions_numero_sesion ON sessions(numero_sesion);
CREATE INDEX IF NOT EXISTS idx_action_plans_estado ON action_plans(estado);
CREATE INDEX IF NOT EXISTS idx_nudge_schedule_fecha_programada ON nudge_schedule(fecha_programada);
CREATE INDEX IF NOT EXISTS idx_coaching_programs_coachee_id ON coaching_programs(coachee_id);