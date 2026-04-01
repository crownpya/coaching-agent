"""
session_tracker.py
Detecta sesiones estancadas, compromisos vencidos, patrones de engagement
y genera reportes diarios con intervenciones sugeridas para el coach.
"""

import re
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

DB_PATH       = Path(__file__).resolve().parents[2] / "data" / "database" / "coaching.db"
VAULT_PATH    = Path(__file__).resolve().parents[2] / "data" / "vault" / "Agente"
INTERVENTIONS = VAULT_PATH / "interventions" / "coach-interventions.md"

ABANDONO_DIAS          = 10   # días sin actividad para detectar abandono
ENGAGEMENT_ALERTA      = 40   # score mínimo antes de alerta temprana
MOOD_BAJO_UMBRAL       = 3    # mood_antes < umbral = sesión con bajo ánimo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("session_tracker")

# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    """Abre la conexión a la base de datos y activa foreign keys."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base de datos no encontrada: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    logger.debug("Conexión abierta: %s", DB_PATH)
    return conn


# ---------------------------------------------------------------------------
# Detección: sesiones estancadas (función original)
# ---------------------------------------------------------------------------

QUERY_SESIONES_ESTANCADAS = """
WITH sesiones_ordenadas AS (
    SELECT
        s.id            AS session_id,
        s.program_id,
        s.numero_sesion,
        s.mood_antes,
        ROW_NUMBER() OVER (
            PARTITION BY s.program_id
            ORDER BY s.numero_sesion DESC
        ) AS rn
    FROM sessions s
    WHERE s.mood_antes IS NOT NULL
),
ultimas_dos AS (
    SELECT program_id, mood_antes
    FROM sesiones_ordenadas
    WHERE rn <= 2
),
programas_estancados AS (
    SELECT program_id
    FROM ultimas_dos
    GROUP BY program_id
    HAVING COUNT(*) = 2
       AND SUM(CASE WHEN mood_antes < 3 THEN 1 ELSE 0 END) = 2
)
SELECT DISTINCT pe.program_id,
       c.nombre  AS coachee_nombre,
       c.email   AS coachee_email
FROM programas_estancados pe
JOIN coaching_programs cp ON cp.id = pe.program_id
JOIN coachees c            ON c.id = cp.coachee_id
"""


def detectar_sesiones_estancadas(conn: sqlite3.Connection) -> list[dict]:
    """Programas donde las últimas 2 sesiones tienen mood_antes < 3."""
    logger.info("Buscando sesiones estancadas...")
    rows = conn.execute(QUERY_SESIONES_ESTANCADAS).fetchall()
    resultados = [dict(r) for r in rows]
    logger.info("Sesiones estancadas encontradas: %d", len(resultados))
    return resultados


# ---------------------------------------------------------------------------
# Detección: compromisos vencidos (función original)
# ---------------------------------------------------------------------------

QUERY_COMPROMISOS_VENCIDOS = """
SELECT
    ap.id           AS action_plan_id,
    ap.session_id,
    ap.objetivo,
    ap.fecha_fin,
    ap.estado,
    c.nombre        AS coachee_nombre,
    c.email         AS coachee_email,
    cp.id           AS program_id
FROM action_plans ap
JOIN sessions s        ON s.id  = ap.session_id
JOIN coaching_programs cp ON cp.id = s.program_id
JOIN coachees c        ON c.id  = cp.coachee_id
WHERE ap.fecha_fin < date('now')
  AND ap.estado   != 'completada'
ORDER BY ap.fecha_fin ASC
"""


def detectar_compromisos_vencidos(conn: sqlite3.Connection) -> list[dict]:
    """action_plans cuya fecha_fin ya pasó y no están completados."""
    logger.info("Buscando compromisos vencidos...")
    rows = conn.execute(QUERY_COMPROMISOS_VENCIDOS).fetchall()
    resultados = [dict(r) for r in rows]
    logger.info("Compromisos vencidos encontrados: %d", len(resultados))
    return resultados


# ---------------------------------------------------------------------------
# 1. analyze_engagement_patterns
# ---------------------------------------------------------------------------

def _score_nudges(conn: sqlite3.Connection, program_id: str) -> float:
    """Tasa de nudges enviados / programados (peso 30%). Devuelve 0–1."""
    row = conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN estado = 'enviado' THEN 1 ELSE 0 END) AS enviados
        FROM nudge_schedule
        WHERE program_id = ?
    """, (program_id,)).fetchone()
    total = row["total"] or 0
    return (row["enviados"] or 0) / total if total > 0 else 0.0


def _score_acciones(conn: sqlite3.Connection, program_id: str) -> float:
    """Tasa de acciones completadas / total (peso 40%). Devuelve 0–1."""
    row = conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN ap.estado = 'completada' THEN 1 ELSE 0 END) AS completadas
        FROM action_plans ap
        JOIN sessions s ON s.id = ap.session_id
        WHERE s.program_id = ?
    """, (program_id,)).fetchone()
    total = row["total"] or 0
    return (row["completadas"] or 0) / total if total > 0 else 0.0


def _score_asistencia(conn: sqlite3.Connection, program_id: str) -> float:
    """Tasa de sesiones realizadas / creadas (peso 30%). Devuelve 0–1."""
    row = conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN fecha_realizada IS NOT NULL THEN 1 ELSE 0 END) AS realizadas
        FROM sessions
        WHERE program_id = ?
    """, (program_id,)).fetchone()
    total = row["total"] or 0
    return (row["realizadas"] or 0) / total if total > 0 else 0.0


def _detectar_abandono(conn: sqlite3.Connection, program_id: str) -> dict:
    """
    Detecta abandono: sin sesión realizada en los últimos ABANDONO_DIAS días.
    Devuelve {"detectado": bool, "dias_sin_actividad": int | None}.
    """
    row = conn.execute("""
        SELECT fecha_realizada
        FROM sessions
        WHERE program_id = ?
          AND fecha_realizada IS NOT NULL
        ORDER BY fecha_realizada DESC
        LIMIT 1
    """, (program_id,)).fetchone()

    if not row:
        return {"detectado": True, "dias_sin_actividad": None}

    ultima = row["fecha_realizada"][:10]   # YYYY-MM-DD
    hoy    = datetime.now().date()
    delta  = (hoy - datetime.strptime(ultima, "%Y-%m-%d").date()).days
    return {"detectado": delta > ABANDONO_DIAS, "dias_sin_actividad": delta}


def analyze_engagement_patterns(program_id: str) -> dict:
    """
    Calcula el engagement score (0–100) de un programa activo.

    Pesos:
        30%  tasa de nudges enviados / programados
        40%  tasa de acciones completadas / total
        30%  tasa de asistencia a sesiones

    Genera alerta_temprana si score < ENGAGEMENT_ALERTA (40).

    Returns:
        {
            "program_id": str,
            "engagement_score": float,
            "alerta_temprana": bool,
            "abandono": {"detectado": bool, "dias_sin_actividad": int | None},
            "detalle": {
                "nudge_rate":            float (0–100),
                "action_completion_rate": float (0–100),
                "session_attendance_rate": float (0–100),
            },
            "timestamp": str
        }
    """
    logger.info("Analizando engagement para program_id=%s", program_id)
    conn = get_connection()
    try:
        r_nudge    = _score_nudges(conn, program_id)
        r_acciones = _score_acciones(conn, program_id)
        r_sesiones = _score_asistencia(conn, program_id)
        abandono   = _detectar_abandono(conn, program_id)
    finally:
        conn.close()

    score = round(r_nudge * 30 + r_acciones * 40 + r_sesiones * 30, 1)
    alerta = score < ENGAGEMENT_ALERTA

    if alerta:
        logger.warning("Alerta temprana de engagement — program_id=%s score=%.1f", program_id, score)
    else:
        logger.info("Engagement OK — program_id=%s score=%.1f", program_id, score)

    return {
        "program_id":      program_id,
        "engagement_score": score,
        "alerta_temprana": alerta,
        "abandono":        abandono,
        "detalle": {
            "nudge_rate":             round(r_nudge    * 100, 1),
            "action_completion_rate": round(r_acciones * 100, 1),
            "session_attendance_rate": round(r_sesiones * 100, 1),
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# 2. suggest_coach_intervention
# ---------------------------------------------------------------------------

def _load_interventions() -> dict[str, dict]:
    """
    Parsea coach-interventions.md y devuelve dict:
        { "1:1_extra": {"descripcion": ..., "prioridad": ...}, ... }
    """
    if not INTERVENTIONS.exists():
        logger.warning("Archivo de intervenciones no encontrado: %s", INTERVENTIONS)
        return {}

    texto = INTERVENTIONS.read_text(encoding="utf-8")
    bloques: dict[str, dict] = {}

    # Cada bloque empieza con "## type: <nombre>"
    for bloque in re.split(r"(?=^## type:)", texto, flags=re.MULTILINE):
        m_tipo = re.match(r"## type:\s*(\S+)", bloque)
        if not m_tipo:
            continue
        tipo = m_tipo.group(1)

        # Descripción: primera línea después de **Descripción:**
        m_desc = re.search(r"\*\*Descripción:\*\*\s*(.+)", bloque)
        desc = m_desc.group(1).strip() if m_desc else ""

        # Prioridad
        m_prio = re.search(r"\*\*Prioridad:\*\*\s*(.+)", bloque)
        prio = m_prio.group(1).strip() if m_prio else "Media"

        bloques[tipo] = {"descripcion": desc, "prioridad": prio}

    logger.debug("Intervenciones cargadas: %s", list(bloques.keys()))
    return bloques


def _mood_bajo_consecutivo(conn: sqlite3.Connection, program_id: str) -> bool:
    """True si las últimas 2 sesiones con mood registrado tienen mood_antes < umbral."""
    rows = conn.execute("""
        SELECT mood_antes
        FROM sessions
        WHERE program_id   = ?
          AND mood_antes   IS NOT NULL
        ORDER BY numero_sesion DESC
        LIMIT 2
    """, (program_id,)).fetchall()
    if len(rows) < 2:
        return False
    return all(r["mood_antes"] < MOOD_BAJO_UMBRAL for r in rows)


def _acciones_vencidas_count(conn: sqlite3.Connection, program_id: str) -> int:
    """Número de action_plans vencidos y no completados."""
    row = conn.execute("""
        SELECT COUNT(*) AS n
        FROM action_plans ap
        JOIN sessions s ON s.id = ap.session_id
        WHERE s.program_id = ?
          AND ap.fecha_fin < date('now')
          AND ap.estado   != 'completada'
    """, (program_id,)).fetchone()
    return row["n"] if row else 0


def suggest_coach_intervention(program_id: str) -> dict:
    """
    Analiza el estado del programa y sugiere el tipo de intervención más adecuado.
    Lee la guía desde data/vault/Agente/interventions/coach-interventions.md.

    Lógica de decisión (en orden de prioridad):
        1. Score < 40  +  mood bajo 2 sesiones  → 1:1_extra
        2. Score < 40                            → 1:1_extra
        3. Score 40–60 + acciones sin completar  → nudge_intensive
        4. Sin avance en objetivos (sin acciones) → profile_review
        5. Cualquier otro bajo engagement         → accountability_partner

    Returns:
        {
            "program_id": str,
            "intervenciones_sugeridas": [
                {"tipo": str, "razon": str, "prioridad": str, "descripcion": str}
            ],
            "condiciones_detectadas": {
                "mood_bajo_consecutivo": bool,
                "engagement_score": float,
                "acciones_vencidas": int,
            },
            "timestamp": str
        }
    """
    logger.info("Generando sugerencias de intervención para program_id=%s", program_id)

    catalogo    = _load_interventions()
    conn        = get_connection()
    try:
        mood_bajo   = _mood_bajo_consecutivo(conn, program_id)
        n_vencidas  = _acciones_vencidas_count(conn, program_id)
        r_nudge     = _score_nudges(conn, program_id)
        r_acciones  = _score_acciones(conn, program_id)
        r_sesiones  = _score_asistencia(conn, program_id)
    finally:
        conn.close()

    score = round(r_nudge * 30 + r_acciones * 40 + r_sesiones * 30, 1)

    sugeridas: list[dict] = []

    def _add(tipo: str, razon: str) -> None:
        info = catalogo.get(tipo, {})
        sugeridas.append({
            "tipo":        tipo,
            "razon":       razon,
            "prioridad":   info.get("prioridad", "Media"),
            "descripcion": info.get("descripcion", ""),
        })

    # Reglas de decisión
    if score < ENGAGEMENT_ALERTA and mood_bajo:
        _add("1:1_extra",
             f"Score crítico ({score}) con mood bajo en 2 sesiones consecutivas.")

    elif score < ENGAGEMENT_ALERTA:
        _add("1:1_extra",
             f"Engagement score bajo ({score}), por debajo del umbral {ENGAGEMENT_ALERTA}.")

    if score < 60 and r_acciones * 100 < 30:
        _add("nudge_intensive",
             f"Tasa de acciones completadas baja ({r_acciones*100:.0f}%) con score {score}.")

    if r_acciones == 0.0 and r_sesiones > 0:
        _add("profile_review",
             "Sin ninguna acción completada pese a tener sesiones realizadas.")

    if score < 60 and not sugeridas:
        _add("accountability_partner",
             f"Engagement moderado ({score}) sin otras alertas específicas.")

    if not sugeridas:
        logger.info("Sin intervenciones necesarias para program_id=%s", program_id)

    return {
        "program_id":              program_id,
        "intervenciones_sugeridas": sugeridas,
        "condiciones_detectadas": {
            "mood_bajo_consecutivo": mood_bajo,
            "engagement_score":      score,
            "acciones_vencidas":     n_vencidas,
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Reporte básico (compatible con versiones anteriores)
# ---------------------------------------------------------------------------

def generar_reporte() -> dict:
    """Reporte básico: sesiones estancadas + compromisos vencidos."""
    logger.info("=== Iniciando session_tracker (reporte básico) ===")
    reporte = {
        "sesiones_estancadas": [],
        "compromisos_vencidos": [],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        conn = get_connection()
        try:
            reporte["sesiones_estancadas"] = detectar_sesiones_estancadas(conn)
            reporte["compromisos_vencidos"] = detectar_compromisos_vencidos(conn)
        finally:
            conn.close()
    except FileNotFoundError as exc:
        logger.error("No se pudo abrir la base de datos: %s", exc)
        reporte["error"] = str(exc)
    except sqlite3.Error as exc:
        logger.error("Error de SQLite: %s", exc)
        reporte["error"] = str(exc)

    logger.info(
        "=== Reporte básico — estancadas: %d | vencidos: %d ===",
        len(reporte["sesiones_estancadas"]),
        len(reporte["compromisos_vencidos"]),
    )
    return reporte


# ---------------------------------------------------------------------------
# 3. Reporte diario completo
# ---------------------------------------------------------------------------

def generar_reporte_diario() -> dict:
    """
    Genera el reporte diario completo con engagement scores,
    coachees en riesgo e intervenciones sugeridas por coach.

    Returns:
        {
            "fecha": "YYYY-MM-DD",
            "coachees_en_riesgo": [
                {
                    "program_id": str,
                    "coachee_nombre": str,
                    "coachee_email": str,
                    "engagement_score": float,
                    "abandono_detectado": bool,
                    "intervenciones": [...]
                }
            ],
            "engagement_por_coachee": [
                {"program_id": str, "coachee_nombre": str, "engagement_score": float}
            ],
            "acciones_recomendadas_coach": [
                {"coachee_nombre": str, "tipo_intervencion": str, "prioridad": str, "razon": str}
            ],
            "resumen": {
                "total_programas": int,
                "en_riesgo": int,
                "engagement_promedio": float,
            },
            "timestamp": str
        }
    """
    logger.info("=== Generando reporte diario completo ===")

    try:
        conn = get_connection()
        programas = conn.execute("""
            SELECT cp.id AS program_id, c.nombre AS coachee_nombre, c.email AS coachee_email
            FROM coaching_programs cp
            JOIN coachees c ON c.id = cp.coachee_id
            WHERE cp.estado = 'activo'
        """).fetchall()
        conn.close()
    except (FileNotFoundError, sqlite3.Error) as exc:
        logger.error("Error al obtener programas activos: %s", exc)
        return {"error": str(exc), "timestamp": datetime.now().isoformat(timespec="seconds")}

    coachees_en_riesgo:        list[dict] = []
    engagement_por_coachee:    list[dict] = []
    acciones_recomendadas:     list[dict] = []
    scores: list[float] = []

    for programa in programas:
        pid     = programa["program_id"]
        nombre  = programa["coachee_nombre"]
        email   = programa["coachee_email"]

        engagement  = analyze_engagement_patterns(pid)
        score       = engagement["engagement_score"]
        scores.append(score)

        engagement_por_coachee.append({
            "program_id":      pid,
            "coachee_nombre":  nombre,
            "engagement_score": score,
        })

        # Solo analizar intervenciones para programas en riesgo
        if engagement["alerta_temprana"] or engagement["abandono"]["detectado"]:
            intervencion = suggest_coach_intervention(pid)
            sugeridas    = intervencion["intervenciones_sugeridas"]

            coachees_en_riesgo.append({
                "program_id":        pid,
                "coachee_nombre":    nombre,
                "coachee_email":     email,
                "engagement_score":  score,
                "abandono_detectado": engagement["abandono"]["detectado"],
                "dias_sin_actividad": engagement["abandono"]["dias_sin_actividad"],
                "intervenciones":    sugeridas,
            })

            for sug in sugeridas:
                acciones_recomendadas.append({
                    "coachee_nombre":    nombre,
                    "tipo_intervencion": sug["tipo"],
                    "prioridad":         sug["prioridad"],
                    "razon":             sug["razon"],
                })

    engagement_promedio = round(sum(scores) / len(scores), 1) if scores else 0.0

    logger.info(
        "=== Reporte diario completado — %d programas | %d en riesgo | promedio %.1f ===",
        len(programas), len(coachees_en_riesgo), engagement_promedio,
    )

    return {
        "fecha":                    datetime.now().strftime("%Y-%m-%d"),
        "coachees_en_riesgo":       coachees_en_riesgo,
        "engagement_por_coachee":   engagement_por_coachee,
        "acciones_recomendadas_coach": acciones_recomendadas,
        "resumen": {
            "total_programas":     len(programas),
            "en_riesgo":           len(coachees_en_riesgo),
            "engagement_promedio": engagement_promedio,
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Bloque __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    comando    = sys.argv[1] if len(sys.argv) > 1 else "diario"
    program_id = sys.argv[2] if len(sys.argv) > 2 else None

    if comando == "basico":
        print(json.dumps(generar_reporte(), ensure_ascii=False, indent=2))

    elif comando == "engagement" and program_id:
        print(json.dumps(analyze_engagement_patterns(program_id), ensure_ascii=False, indent=2))

    elif comando == "intervencion" and program_id:
        print(json.dumps(suggest_coach_intervention(program_id), ensure_ascii=False, indent=2))

    elif comando == "diario":
        print(json.dumps(generar_reporte_diario(), ensure_ascii=False, indent=2))

    else:
        print("Uso:")
        print("  python session_tracker.py diario")
        print("  python session_tracker.py basico")
        print("  python session_tracker.py engagement <program_id>")
        print("  python session_tracker.py intervencion <program_id>")
        sys.exit(1)
