"""
progress_analyzer.py
Calcula el progreso ponderado de un programa de coaching y analiza motivación.
"""

import re
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

DB_PATH    = Path(__file__).resolve().parents[2] / "data" / "database" / "coaching.db"
VAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "vault" / "Agente"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("progress_analyzer")

TOTAL_SESIONES = 8

# Pesos del progreso ponderado
PESO_SESIONES     = 0.40
PESO_ACCIONES     = 0.30
PESO_CREENCIAS    = 0.15
PESO_COMPETENCIAS = 0.15

# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base de datos no encontrada: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Helpers de métricas individuales
# ---------------------------------------------------------------------------

def _ratio_sesiones(conn: sqlite3.Connection, program_id: str) -> float:
    """Sesiones con fecha_realizada no nula / TOTAL_SESIONES."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sessions WHERE program_id = ? AND fecha_realizada IS NOT NULL",
        (program_id,),
    ).fetchone()
    completadas = row["n"] if row else 0
    ratio = min(completadas / TOTAL_SESIONES, 1.0)
    logger.debug("Sesiones completadas: %d/%d → %.2f", completadas, TOTAL_SESIONES, ratio)
    return ratio


def _ratio_acciones(conn: sqlite3.Connection, program_id: str) -> float:
    """Acciones completadas / total acciones en el programa."""
    row = conn.execute(
        """
        SELECT
            COUNT(*)                                              AS total,
            SUM(CASE WHEN ap.estado = 'completada' THEN 1 ELSE 0 END) AS completadas
        FROM action_plans ap
        JOIN sessions s ON s.id = ap.session_id
        WHERE s.program_id = ?
        """,
        (program_id,),
    ).fetchone()
    total, completadas = row["total"], row["completadas"] or 0
    if total == 0:
        logger.debug("Sin acciones registradas para program_id=%s", program_id)
        return 0.0
    ratio = completadas / total
    logger.debug("Acciones completadas: %d/%d → %.2f", completadas, total, ratio)
    return ratio


def _ratio_creencias(conn: sqlite3.Connection, program_id: str) -> float:
    """Creencias con estado 'transformada' / total creencias identificadas."""
    row = conn.execute(
        """
        SELECT
            COUNT(*)                                                      AS total,
            SUM(CASE WHEN bt.estado = 'transformada' THEN 1 ELSE 0 END)  AS transformadas
        FROM beliefs_tracker bt
        JOIN sessions s ON s.id = bt.session_id
        WHERE s.program_id = ?
        """,
        (program_id,),
    ).fetchone()
    total, transformadas = row["total"], row["transformadas"] or 0
    if total == 0:
        logger.debug("Sin creencias registradas para program_id=%s", program_id)
        return 0.0
    ratio = transformadas / total
    logger.debug("Creencias transformadas: %d/%d → %.2f", transformadas, total, ratio)
    return ratio


def _ratio_competencias(conn: sqlite3.Connection, program_id: str) -> float:
    """
    Promedio de mejora relativa por competencia:
    mean((nivel_coach - nivel_autoevaluado) / 4) clipped en [0, 1].
    Solo considera registros donde ambos niveles están presentes.
    """
    rows = conn.execute(
        """
        SELECT ct.nivel_autoevaluado, ct.nivel_coach
        FROM competency_tracking ct
        JOIN sessions s ON s.id = ct.session_id
        WHERE s.program_id = ?
          AND ct.nivel_autoevaluado IS NOT NULL
          AND ct.nivel_coach        IS NOT NULL
        """,
        (program_id,),
    ).fetchall()
    if not rows:
        logger.debug("Sin competencias registradas para program_id=%s", program_id)
        return 0.0
    mejoras = [
        max((r["nivel_coach"] - r["nivel_autoevaluado"]) / 4, 0.0)
        for r in rows
    ]
    ratio = min(sum(mejoras) / len(mejoras), 1.0)
    logger.debug("Competencias — %d registros, ratio promedio: %.2f", len(rows), ratio)
    return ratio


# ---------------------------------------------------------------------------
# 1. calculate_progress
# ---------------------------------------------------------------------------

def calculate_progress(program_id: str) -> dict:
    """
    Calcula el progreso ponderado de un programa de coaching.

    Pesos:
        40% sesiones completadas / 8
        30% acciones completadas / total acciones
        15% creencias transformadas / creencias identificadas
        15% competencias mejoradas (promedio de mejora relativa)

    Returns:
        {
            "program_id": str,
            "progreso_total": float (0–100),
            "detalle": {
                "sesiones":     {"valor": float, "peso": 0.40, "aporte": float},
                "acciones":     {"valor": float, "peso": 0.30, "aporte": float},
                "creencias":    {"valor": float, "peso": 0.15, "aporte": float},
                "competencias": {"valor": float, "peso": 0.15, "aporte": float},
            },
            "timestamp": str
        }
    """
    logger.info("Calculando progreso para program_id=%s", program_id)
    conn = get_connection()
    try:
        metricas = {
            "sesiones":     (_ratio_sesiones(conn, program_id),     PESO_SESIONES),
            "acciones":     (_ratio_acciones(conn, program_id),     PESO_ACCIONES),
            "creencias":    (_ratio_creencias(conn, program_id),    PESO_CREENCIAS),
            "competencias": (_ratio_competencias(conn, program_id), PESO_COMPETENCIAS),
        }
    finally:
        conn.close()

    detalle = {
        nombre: {
            "valor":  round(valor, 4),
            "peso":   peso,
            "aporte": round(valor * peso, 4),
        }
        for nombre, (valor, peso) in metricas.items()
    }
    progreso_total = round(sum(d["aporte"] for d in detalle.values()) * 100, 2)

    logger.info("Progreso total: %.2f%%", progreso_total)
    return {
        "program_id":    program_id,
        "progreso_total": progreso_total,
        "detalle":        detalle,
        "timestamp":      datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# 2. analyze_motivation
# ---------------------------------------------------------------------------

_NUDGES = {
    "mood_bajo": [
        "Recuerda por qué empezaste este proceso. ¿Cuál era tu motivación inicial?",
        "Es normal tener momentos difíciles. ¿Qué pequeño paso podrías dar hoy?",
        "Reconoce cada avance, por pequeño que sea. ¿Qué has logrado esta semana?",
    ],
    "acciones_vencidas": [
        "Tienes compromisos pendientes. ¿Cuál es el más sencillo de retomar ahora?",
        "Revisar tus acciones puede ayudarte a recuperar el impulso. ¿Cuándo agendamos una revisión?",
        "A veces las metas necesitan ajustarse. ¿Alguna acción requiere replanteo?",
    ],
    "combinado": [
        "Tu energía y tus compromisos están desalineados. ¿Qué está bloqueando el avance?",
        "Parece un momento clave para reflexionar. ¿Qué necesitas para recuperar el ritmo?",
    ],
}


def _ultimo_mood(conn: sqlite3.Connection, program_id: str) -> int | None:
    """Devuelve el mood_antes de la sesión más reciente con dato registrado."""
    row = conn.execute(
        """
        SELECT mood_antes
        FROM sessions
        WHERE program_id = ?
          AND mood_antes IS NOT NULL
          AND fecha_realizada IS NOT NULL
        ORDER BY numero_sesion DESC
        LIMIT 1
        """,
        (program_id,),
    ).fetchone()
    return row["mood_antes"] if row else None


def _acciones_vencidas_count(conn: sqlite3.Connection, program_id: str) -> int:
    """Cuenta action_plans vencidos y no completados del programa."""
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM action_plans ap
        JOIN sessions s ON s.id = ap.session_id
        WHERE s.program_id = ?
          AND ap.fecha_fin < date('now')
          AND ap.estado   != 'completada'
        """,
        (program_id,),
    ).fetchone()
    return row["n"] if row else 0


def _seleccionar_nudge(mood_bajo: bool, vencidas_exceso: bool) -> str:
    """Selecciona el mensaje de nudge según el tipo de alerta."""
    import random
    if mood_bajo and vencidas_exceso:
        pool = _NUDGES["combinado"]
    elif mood_bajo:
        pool = _NUDGES["mood_bajo"]
    else:
        pool = _NUDGES["acciones_vencidas"]
    return random.choice(pool)


def analyze_motivation(program_id: str) -> dict:
    """
    Detecta señales de baja motivación y genera un nudge personalizado.

    Criterios de alerta:
        - mood_bajo:         último mood_antes < 3
        - acciones_vencidas: action_plans vencidos y no completados > 2

    Returns:
        {
            "program_id": str,
            "alerta": bool,
            "motivos": list[str],
            "nudge": str | None,
            "detalle": {
                "ultimo_mood": int | None,
                "acciones_vencidas": int
            },
            "timestamp": str
        }
    """
    logger.info("Analizando motivación para program_id=%s", program_id)
    conn = get_connection()
    try:
        ultimo_mood     = _ultimo_mood(conn, program_id)
        n_vencidas      = _acciones_vencidas_count(conn, program_id)
    finally:
        conn.close()

    mood_bajo        = ultimo_mood is not None and ultimo_mood < 3
    vencidas_exceso  = n_vencidas > 2

    motivos = []
    if mood_bajo:
        motivos.append(f"Último mood registrado: {ultimo_mood}/5 (umbral: 3)")
    if vencidas_exceso:
        motivos.append(f"Acciones vencidas: {n_vencidas} (umbral: 2)")

    alerta = bool(motivos)
    nudge  = _seleccionar_nudge(mood_bajo, vencidas_exceso) if alerta else None

    if alerta:
        logger.warning("Alerta de motivación en program_id=%s — %s", program_id, "; ".join(motivos))
    else:
        logger.info("Sin alertas de motivación para program_id=%s", program_id)

    return {
        "program_id": program_id,
        "alerta":     alerta,
        "motivos":    motivos,
        "nudge":      nudge,
        "detalle": {
            "ultimo_mood":       ultimo_mood,
            "acciones_vencidas": n_vencidas,
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Helper: progreso con conexión existente (evita abrir N conexiones)
# ---------------------------------------------------------------------------

def _calc_progress_with_conn(conn: sqlite3.Connection, program_id: str) -> float:
    """Calcula el progreso ponderado (0–100) reutilizando una conexión abierta."""
    r_s = _ratio_sesiones(conn, program_id)
    r_a = _ratio_acciones(conn, program_id)
    r_c = _ratio_creencias(conn, program_id)
    r_k = _ratio_competencias(conn, program_id)
    return round((r_s * PESO_SESIONES + r_a * PESO_ACCIONES +
                  r_c * PESO_CREENCIAS + r_k * PESO_COMPETENCIAS) * 100, 2)


# ---------------------------------------------------------------------------
# 3. benchmark_comparison
# ---------------------------------------------------------------------------

def _percentil(mi_score: float, otros_scores: list[float]) -> int:
    """Posición percentil del score propio dentro del grupo (0–100)."""
    todos = sorted(otros_scores + [mi_score])
    pos   = sum(1 for s in todos if s <= mi_score)
    return round((pos / len(todos)) * 100)


def _grupo_stats(mi_score: float, scores: list[float]) -> dict:
    """Estadísticas del grupo: n, promedio, diferencia, percentil."""
    if not scores:
        return {"n": 0, "promedio": None, "diferencia": None, "percentil": None, "posicion": None}
    promedio  = round(sum(scores) / len(scores), 1)
    percentil = _percentil(mi_score, scores)
    return {
        "n":          len(scores),
        "promedio":   promedio,
        "diferencia": round(mi_score - promedio, 1),
        "percentil":  percentil,
        "posicion":   f"Top {100 - percentil}%" if percentil >= 50 else f"Bajo media ({percentil}° percentil)",
    }


def benchmark_comparison(program_id: str) -> dict:
    """
    Compara el progreso del coachee contra tres grupos de referencia:
        - Coachees con el mismo rol
        - Coachees con el mismo coach asignado
        - Coachees de la misma empresa

    Returns:
        {
            "program_id": str,
            "mi_score": float,
            "vs_mismo_rol":     {"n", "promedio", "diferencia", "percentil", "posicion"},
            "vs_mismo_coach":   {...},
            "vs_misma_empresa": {...},
            "timestamp": str
        }
    """
    logger.info("Calculando benchmark para program_id=%s", program_id)
    conn = get_connection()
    try:
        meta = conn.execute("""
            SELECT c.rol, c.empresa, cca.coach_id
            FROM coaching_programs cp
            JOIN coachees c ON c.id = cp.coachee_id
            LEFT JOIN coach_coachee_assignments cca
                   ON cca.coachee_id = c.id AND cca.estado = 'activa'
            WHERE cp.id = ?
        """, (program_id,)).fetchone()

        if not meta:
            raise ValueError(f"Programa no encontrado: {program_id}")

        rol, empresa, coach_id = meta["rol"], meta["empresa"], meta["coach_id"]
        mi_score = _calc_progress_with_conn(conn, program_id)

        def scores_for(rows) -> list[float]:
            return [_calc_progress_with_conn(conn, r["id"]) for r in rows]

        # Mismo rol
        rol_rows = conn.execute("""
            SELECT cp.id FROM coaching_programs cp
            JOIN coachees c ON c.id = cp.coachee_id
            WHERE c.rol = ? AND cp.estado = 'activo' AND cp.id != ?
        """, (rol, program_id)).fetchall()

        # Mismo coach
        coach_rows = conn.execute("""
            SELECT DISTINCT cp.id FROM coaching_programs cp
            JOIN coachees c ON c.id = cp.coachee_id
            JOIN coach_coachee_assignments cca ON cca.coachee_id = c.id
            WHERE cca.coach_id = ? AND cp.estado = 'activo' AND cp.id != ?
        """, (coach_id, program_id)).fetchall() if coach_id else []

        # Misma empresa
        empresa_rows = conn.execute("""
            SELECT cp.id FROM coaching_programs cp
            JOIN coachees c ON c.id = cp.coachee_id
            WHERE c.empresa = ? AND cp.estado = 'activo' AND cp.id != ?
        """, (empresa, program_id)).fetchall()

        vs_rol     = _grupo_stats(mi_score, scores_for(rol_rows))
        vs_coach   = _grupo_stats(mi_score, scores_for(coach_rows))
        vs_empresa = _grupo_stats(mi_score, scores_for(empresa_rows))

    finally:
        conn.close()

    logger.info("Benchmark — score=%.1f | vs_rol=%s | vs_empresa=%s",
                mi_score,
                vs_rol.get("posicion", "N/A"),
                vs_empresa.get("posicion", "N/A"))
    return {
        "program_id":       program_id,
        "mi_score":         mi_score,
        "vs_mismo_rol":     vs_rol,
        "vs_mismo_coach":   vs_coach,
        "vs_misma_empresa": vs_empresa,
        "timestamp":        datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# 4. predict_completion_date
# ---------------------------------------------------------------------------

def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Regresión lineal mínimos cuadrados. Devuelve (pendiente, intercepto)."""
    n      = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom  = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0, mean_y
    slope     = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
    intercept = mean_y - slope * mean_x
    return slope, intercept


def predict_completion_date(program_id: str) -> dict:
    """
    Predice la fecha probable de finalización usando regresión lineal simple
    sobre el ritmo histórico de sesiones completadas.

    Variables:
        x: número de sesión (1, 2, 3, …)
        y: días transcurridos desde el inicio del programa

    Devuelve None en fecha si hay menos de 2 sesiones completadas.

    Returns:
        {
            "program_id": str,
            "sesiones_completadas": int,
            "fecha_inicio": str,
            "fecha_predicha_fin": str | None,
            "dias_restantes_estimados": int | None,
            "ritmo_dias_por_sesion": float | None,
            "confianza": "alta" | "media" | "baja" | "insuficiente",
            "timestamp": str
        }
    """
    logger.info("Prediciendo fecha de finalización para program_id=%s", program_id)
    conn = get_connection()
    try:
        inicio_row = conn.execute(
            "SELECT fecha_inicio FROM coaching_programs WHERE id = ?", (program_id,)
        ).fetchone()
        if not inicio_row:
            raise ValueError(f"Programa no encontrado: {program_id}")
        fecha_inicio_str = inicio_row["fecha_inicio"][:10]
        fecha_inicio     = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()

        sesiones = conn.execute("""
            SELECT numero_sesion, fecha_realizada
            FROM sessions
            WHERE program_id = ? AND fecha_realizada IS NOT NULL
            ORDER BY numero_sesion
        """, (program_id,)).fetchall()
    finally:
        conn.close()

    n_completadas = len(sesiones)

    if n_completadas == 0:
        return {
            "program_id":              program_id,
            "sesiones_completadas":    0,
            "fecha_inicio":            fecha_inicio_str,
            "fecha_predicha_fin":      None,
            "dias_restantes_estimados": None,
            "ritmo_dias_por_sesion":   None,
            "confianza":               "insuficiente",
            "timestamp":               datetime.now().isoformat(timespec="seconds"),
        }

    xs = [float(s["numero_sesion"]) for s in sesiones]
    ys = [
        float((datetime.strptime(s["fecha_realizada"][:10], "%Y-%m-%d").date() - fecha_inicio).days)
        for s in sesiones
    ]

    if n_completadas == 1:
        # Ritmo lineal desde inicio
        dias_por_sesion = ys[0] / xs[0] if xs[0] > 0 else 14.0
        dias_restantes  = round(dias_por_sesion * (TOTAL_SESIONES - xs[0]))
        confianza       = "baja"
    else:
        slope, intercept = _linear_regression(xs, ys)
        dias_predichos   = slope * TOTAL_SESIONES + intercept
        dias_actuales    = ys[-1]
        dias_restantes   = max(round(dias_predichos - dias_actuales), 1)
        dias_por_sesion  = round(slope, 1)
        confianza        = "alta" if n_completadas >= 4 else "media"

    fecha_predicha = datetime.now().date() + timedelta(days=dias_restantes)

    logger.info("Predicción: fin=%s | %d días restantes | confianza=%s",
                fecha_predicha, dias_restantes, confianza)
    return {
        "program_id":              program_id,
        "sesiones_completadas":    n_completadas,
        "fecha_inicio":            fecha_inicio_str,
        "fecha_predicha_fin":      fecha_predicha.isoformat(),
        "dias_restantes_estimados": dias_restantes,
        "ritmo_dias_por_sesion":   round(ys[-1] / xs[-1], 1) if n_completadas >= 1 else None,
        "confianza":               confianza,
        "timestamp":               datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# 5. skill_gap_analysis
# ---------------------------------------------------------------------------

def _load_role_requirements(rol: str) -> list[dict]:
    """
    Parsea data/vault/Agente/profiles/{rol}-requirements.md.
    Devuelve lista de {"competencia", "nivel_requerido", "descripcion", "herramienta_vault"}.
    """
    # Normalizar rol a nombre de archivo: "Tech Lead" → "tech-lead"
    slug    = re.sub(r"[\s_/]+", "-", rol.strip().lower())
    archivo = VAULT_PATH / "profiles" / f"{slug}-requirements.md"

    if not archivo.exists():
        logger.warning("Archivo de requisitos no encontrado: %s", archivo)
        return []

    texto       = archivo.read_text(encoding="utf-8")
    requisitos  = []
    # Cada bloque empieza con "competencia: <nombre>"
    bloques = re.split(r"(?=^competencia:)", texto, flags=re.MULTILINE)
    for bloque in bloques:
        m_comp = re.search(r"^competencia:\s*(.+)", bloque, re.MULTILINE)
        if not m_comp:
            continue
        m_nivel = re.search(r"^nivel_requerido:\s*(\d+)", bloque, re.MULTILINE)
        m_desc  = re.search(r"^descripcion:\s*(.+)",      bloque, re.MULTILINE)
        m_tool  = re.search(r"^herramienta_vault:\s*(.+)", bloque, re.MULTILINE)
        requisitos.append({
            "competencia":      m_comp.group(1).strip(),
            "nivel_requerido":  int(m_nivel.group(1)) if m_nivel else 7,
            "descripcion":      m_desc.group(1).strip() if m_desc else "",
            "herramienta_vault": m_tool.group(1).strip() if m_tool else "",
        })

    logger.debug("Requisitos cargados para rol '%s': %d competencias", rol, len(requisitos))
    return requisitos


def skill_gap_analysis(program_id: str) -> dict:
    """
    Compara las competencias actuales del coachee vs. los requisitos del rol,
    identifica gaps y sugiere herramientas del vault.

    Returns:
        {
            "program_id": str,
            "rol": str,
            "nivel_esperado": int,
            "gaps": [
                {
                    "competencia": str,
                    "nivel_actual": float | None,
                    "nivel_requerido": int,
                    "gap": float,
                    "prioridad": "alta" | "media" | "baja",
                    "herramienta_vault": str,
                    "descripcion": str
                }
            ],
            "competencias_cubiertas": [str],
            "sin_datos": [str],
            "timestamp": str
        }
    """
    logger.info("Analizando skill gaps para program_id=%s", program_id)
    conn = get_connection()
    try:
        meta = conn.execute("""
            SELECT c.rol, cp.fecha_inicio
            FROM coaching_programs cp
            JOIN coachees c ON c.id = cp.coachee_id
            WHERE cp.id = ?
        """, (program_id,)).fetchone()
        if not meta:
            raise ValueError(f"Programa no encontrado: {program_id}")
        rol = meta["rol"] or ""

        # Promedios de nivel_autoevaluado por competencia en el programa
        rows = conn.execute("""
            SELECT ct.competencia,
                   AVG(ct.nivel_autoevaluado) AS nivel_actual,
                   AVG(ct.nivel_coach)        AS nivel_coach_avg
            FROM competency_tracking ct
            JOIN sessions s ON s.id = ct.session_id
            WHERE s.program_id = ?
              AND ct.nivel_autoevaluado IS NOT NULL
            GROUP BY ct.competencia
        """, (program_id,)).fetchall()
    finally:
        conn.close()

    niveles_actuales: dict[str, float] = {
        r["competencia"].lower(): round(r["nivel_actual"], 2) for r in rows
    }

    requisitos    = _load_role_requirements(rol)
    gaps          = []
    cubiertas     = []
    sin_datos     = []

    # Escala competency_tracking es 1–5; escala requirements es 1–10
    # Normalizamos el nivel actual de 1-5 → 1-10 multiplicando x2
    for req in requisitos:
        comp     = req["competencia"].lower()
        nivel_r  = req["nivel_requerido"]

        if comp in niveles_actuales:
            nivel_actual_normalizado = round(niveles_actuales[comp] * 2, 2)
            gap = round(nivel_r - nivel_actual_normalizado, 2)

            if gap <= 0:
                cubiertas.append(req["competencia"])
            else:
                prioridad = "alta" if gap >= 3 else ("media" if gap >= 1.5 else "baja")
                gaps.append({
                    "competencia":      req["competencia"],
                    "nivel_actual":     nivel_actual_normalizado,
                    "nivel_requerido":  nivel_r,
                    "gap":              gap,
                    "prioridad":        prioridad,
                    "herramienta_vault": req["herramienta_vault"],
                    "descripcion":      req["descripcion"],
                })
        else:
            sin_datos.append(req["competencia"])

    # Ordenar por gap descendente (gaps más grandes primero)
    gaps.sort(key=lambda g: g["gap"], reverse=True)

    logger.info("Skill gap — rol=%s | gaps=%d | cubiertas=%d | sin_datos=%d",
                rol, len(gaps), len(cubiertas), len(sin_datos))
    return {
        "program_id":            program_id,
        "rol":                   rol,
        "gaps":                  gaps,
        "competencias_cubiertas": cubiertas,
        "sin_datos":             sin_datos,
        "timestamp":             datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# 6. Dashboard semanal
# ---------------------------------------------------------------------------

def generar_dashboard_semanal(program_id: str) -> dict:
    """
    Dashboard completo semanal para un programa de coaching.

    Combina: progreso, motivación, benchmark, predicción de fin y skill gaps.

    Returns:
        {
            "program_id": str,
            "semana": str (ISO week YYYY-Www),
            "progreso":    {...},
            "motivacion":  {...},
            "benchmark":   {...},
            "prediccion":  {...},
            "skill_gaps":  {...},
            "resumen_ejecutivo": {
                "score_global": float,
                "alertas": [str],
                "recomendaciones_prioritarias": [str]
            },
            "timestamp": str
        }
    """
    logger.info("=== Generando dashboard semanal para program_id=%s ===", program_id)

    progreso   = calculate_progress(program_id)
    motivacion = analyze_motivation(program_id)
    benchmark  = benchmark_comparison(program_id)
    prediccion = predict_completion_date(program_id)
    gaps       = skill_gap_analysis(program_id)

    # Resumen ejecutivo
    alertas: list[str] = []
    recomendaciones: list[str] = []

    if motivacion["alerta"]:
        for m in motivacion["motivos"]:
            alertas.append(f"Motivación: {m}")

    if benchmark["vs_mismo_rol"].get("percentil") is not None:
        p = benchmark["vs_mismo_rol"]["percentil"]
        if p < 30:
            alertas.append(f"Progreso por debajo del {p}° percentil vs compañeros del mismo rol.")

    gaps_altos = [g for g in gaps["gaps"] if g["prioridad"] == "alta"]
    if gaps_altos:
        alertas.append(f"{len(gaps_altos)} competencia(s) con gap de prioridad alta.")
        for g in gaps_altos[:2]:
            recomendaciones.append(
                f"Trabajar '{g['competencia']}' (gap={g['gap']:.1f}) → {g['herramienta_vault'] or 'consultar vault'}"
            )

    if prediccion["confianza"] in ("alta", "media") and prediccion["fecha_predicha_fin"]:
        recomendaciones.append(
            f"Ritmo actual → finalización estimada: {prediccion['fecha_predicha_fin']} "
            f"({prediccion['dias_restantes_estimados']} días, confianza {prediccion['confianza']})"
        )

    if motivacion["nudge"]:
        recomendaciones.append(f"Nudge sugerido: {motivacion['nudge']}")

    semana = datetime.now().strftime("%G-W%V")

    logger.info("Dashboard semanal generado — alertas=%d | recomendaciones=%d",
                len(alertas), len(recomendaciones))
    return {
        "program_id":  program_id,
        "semana":      semana,
        "progreso":    progreso,
        "motivacion":  motivacion,
        "benchmark":   benchmark,
        "prediccion":  prediccion,
        "skill_gaps":  gaps,
        "resumen_ejecutivo": {
            "score_global":                  progreso["progreso_total"],
            "alertas":                       alertas,
            "recomendaciones_prioritarias":  recomendaciones,
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# 3. Tabla temporal de resultados (opcional)
# ---------------------------------------------------------------------------

CREATE_TEMP_TABLE = """
CREATE TEMPORARY TABLE IF NOT EXISTS analysis_results (
    program_id      TEXT NOT NULL,
    progreso_total  REAL,
    alerta          INTEGER,
    nudge           TEXT,
    timestamp       TEXT
)
"""


def guardar_en_temporal(
    conn: sqlite3.Connection,
    progreso: dict,
    motivacion: dict,
) -> None:
    """
    Persiste los resultados del análisis en una tabla temporal SQLite
    (solo vive durante la conexión activa).
    """
    conn.execute(CREATE_TEMP_TABLE)
    conn.execute(
        "INSERT INTO analysis_results (program_id, progreso_total, alerta, nudge, timestamp) VALUES (?, ?, ?, ?, ?)",
        (
            progreso["program_id"],
            progreso["progreso_total"],
            int(motivacion["alerta"]),
            motivacion["nudge"],
            progreso["timestamp"],
        ),
    )
    conn.commit()
    logger.debug("Resultado guardado en tabla temporal para program_id=%s", progreso["program_id"])


# ---------------------------------------------------------------------------
# Bloque __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    comando    = sys.argv[1] if len(sys.argv) > 1 else "dashboard"
    program_id = sys.argv[2] if len(sys.argv) > 2 else "PROGRAM_ID_DE_PRUEBA"

    comandos = {
        "progreso":    lambda: calculate_progress(program_id),
        "motivacion":  lambda: analyze_motivation(program_id),
        "benchmark":   lambda: benchmark_comparison(program_id),
        "prediccion":  lambda: predict_completion_date(program_id),
        "gaps":        lambda: skill_gap_analysis(program_id),
        "dashboard":   lambda: generar_dashboard_semanal(program_id),
    }

    if comando not in comandos:
        print("Uso:")
        for cmd in comandos:
            print(f"  python progress_analyzer.py {cmd} <program_id>")
        sys.exit(1)

    try:
        resultado = comandos[comando]()
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
