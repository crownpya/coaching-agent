"""
nudge_scheduler.py
Programa nudges diarios para programas de coaching activos.
Incluye personalización por rol, A/B testing y scheduling inteligente.
"""

import re
import sqlite3
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

DB_PATH            = Path(__file__).resolve().parents[2] / "data" / "database" / "coaching.db"
VAULT_PATH         = Path(__file__).resolve().parents[2] / "data" / "vault" / "Agente"
QUESTION_BANK_PATH = Path(__file__).resolve().parents[1] / "coaching-tools" / "question-bank-grow-es.md"
NUDGE_VAULT_PATH   = VAULT_PATH / "nudges" / "personalizados"

NUDGE_DAYS             = 7
NUDGE_TIPO             = "pregunta_grow"
NUDGE_TIPO_INTELIGENTE = "inteligente"
MIN_AB_WINNER          = 5       # mínimo de tests por versión antes de declarar ganador
HORA_DEFAULT           = 9       # hora de envío por defecto (9am)
DIAS_EXCLUIDOS         = {5, 6}  # weekday(): 5=sábado, 6=domingo
HORAS_BLOQUEADAS       = set(range(0, 7)) | {22, 23}  # madrugada y noche

# Frecuencia de nudges según engagement score
FREQ_ALTA    = 3   # nudges/semana  (score < 40)
FREQ_MEDIA   = 2   # nudges/semana  (40–70)
FREQ_NORMAL  = 1   # nudges/semana  (score > 70)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nudge_scheduler")

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
# Banco de preguntas GROW (original)
# ---------------------------------------------------------------------------

_RE_ENTRY = re.compile(
    r"-\s+fase:\s*(?P<fase>goal|reality|options|will)\s*\n"
    r"\s+texto:\s*\"(?P<texto>[^\"]+)\"",
    re.MULTILINE,
)


def load_question_bank(path: Path = QUESTION_BANK_PATH) -> dict[str, list[str]]:
    """
    Parsea el banco de preguntas GROW y devuelve:
        { "goal": [...], "reality": [...], "options": [...], "will": [...] }
    """
    if not path.exists():
        raise FileNotFoundError(f"Banco de preguntas no encontrado: {path}")
    texto = path.read_text(encoding="utf-8")
    banco: dict[str, list[str]] = {"goal": [], "reality": [], "options": [], "will": []}
    for match in _RE_ENTRY.finditer(texto):
        banco[match.group("fase")].append(match.group("texto").strip())
    total = sum(len(v) for v in banco.values())
    logger.info("Banco GROW cargado: %d preguntas", total)
    return banco


# ---------------------------------------------------------------------------
# 1. Nudges personalizados por rol
# ---------------------------------------------------------------------------

def _rol_slug(rol: str) -> str:
    """'Tech Lead' → 'tech-lead'"""
    return re.sub(r"[\s_/]+", "-", rol.strip().lower())


def load_personalized_nudges(rol: str, context: str) -> dict[str, list[str]]:
    """
    Lee data/vault/Agente/nudges/personalizados/{rol-slug}/{context}.md.
    Devuelve {"a": [nudges versión A], "b": [nudges versión B]}.
    Retorna {"a": [], "b": []} si el archivo no existe.
    """
    slug    = _rol_slug(rol)
    archivo = NUDGE_VAULT_PATH / slug / f"{context}.md"
    if not archivo.exists():
        logger.warning("Nudges personalizados no encontrados: %s", archivo)
        return {"a": [], "b": []}

    texto   = archivo.read_text(encoding="utf-8")
    result  = {"a": [], "b": []}

    # Dividir en secciones ## Version A y ## Version B
    secciones = re.split(r"^## Version ([AB])", texto, flags=re.MULTILINE)
    for i in range(1, len(secciones), 2):
        version = secciones[i].strip().lower()
        bloque  = secciones[i + 1] if i + 1 < len(secciones) else ""
        nudges  = re.findall(r'^nudge:\s*"([^"]+)"', bloque, re.MULTILINE)
        result[version] = nudges

    logger.debug("Nudges personalizados '%s' / '%s': A=%d B=%d",
                 rol, context, len(result["a"]), len(result["b"]))
    return result


# ---------------------------------------------------------------------------
# 2. Helpers de scheduling inteligente
# ---------------------------------------------------------------------------

def _engagement_score(conn: sqlite3.Connection, program_id: str) -> float:
    """Calcula un engagement score simplificado (0–100) directamente en SQL."""
    nudge_row = conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN estado = 'enviado' THEN 1 ELSE 0 END) AS enviados
        FROM nudge_schedule WHERE program_id = ?
    """, (program_id,)).fetchone()
    r_nudge = ((nudge_row["enviados"] or 0) / nudge_row["total"]
               if nudge_row["total"] else 0)

    action_row = conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN ap.estado = 'completada' THEN 1 ELSE 0 END) AS completadas
        FROM action_plans ap JOIN sessions s ON s.id = ap.session_id
        WHERE s.program_id = ?
    """, (program_id,)).fetchone()
    r_acc = ((action_row["completadas"] or 0) / action_row["total"]
             if action_row["total"] else 0)

    session_row = conn.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN fecha_realizada IS NOT NULL THEN 1 ELSE 0 END) AS realizadas
        FROM sessions WHERE program_id = ?
    """, (program_id,)).fetchone()
    r_ses = ((session_row["realizadas"] or 0) / session_row["total"]
             if session_row["total"] else 0)

    return round(r_nudge * 30 + r_acc * 40 + r_ses * 30, 1)


def _nudges_per_week(score: float) -> int:
    """Devuelve la frecuencia semanal según engagement score."""
    if score < 40:
        return FREQ_ALTA
    if score < 70:
        return FREQ_MEDIA
    return FREQ_NORMAL


def _preferred_hour(conn: sqlite3.Connection, program_id: str) -> int:
    """
    Infiere la hora preferida del coachee analizando cuándo envía mensajes
    en session_messages. Si no hay datos suficientes, devuelve HORA_DEFAULT.
    """
    rows = conn.execute("""
        SELECT timestamp FROM session_messages
        WHERE program_id = ? ORDER BY timestamp DESC LIMIT 50
    """, (program_id,)).fetchall()

    if len(rows) < 3:
        return HORA_DEFAULT

    hora_counts: dict[int, int] = {}
    for r in rows:
        try:
            dt   = datetime.fromisoformat(r["timestamp"][:19])
            hora = dt.hour
            if hora not in HORAS_BLOQUEADAS:
                hora_counts[hora] = hora_counts.get(hora, 0) + 1
        except (ValueError, TypeError):
            continue

    if not hora_counts:
        return HORA_DEFAULT
    return max(hora_counts, key=hora_counts.get)


def _weekdays_in_window(start_date: datetime.date, days: int,
                        n_nudges: int) -> list[datetime.date]:
    """
    Selecciona `n_nudges` días hábiles distribuidos uniformemente dentro
    de una ventana de `days` días a partir de `start_date`.
    Excluye los días en DIAS_EXCLUIDOS.
    """
    laborables = [
        start_date + timedelta(days=i)
        for i in range(days)
        if (start_date + timedelta(days=i)).weekday() not in DIAS_EXCLUIDOS
    ]
    if not laborables:
        return []
    step  = max(len(laborables) // n_nudges, 1)
    return laborables[::step][:n_nudges]


# ---------------------------------------------------------------------------
# 3. A/B testing
# ---------------------------------------------------------------------------

def _get_or_create_ab_test(
    conn: sqlite3.Connection,
    rol: str,
    context: str,
) -> dict | None:
    """
    Recupera el registro de A/B test activo para (rol, context).
    Si no existe, lo crea con versiones del vault.
    Devuelve None si no hay nudges personalizados disponibles.
    """
    row = conn.execute("""
        SELECT * FROM nudge_ab_tests WHERE rol = ? AND nudge_context = ?
        ORDER BY created_at DESC LIMIT 1
    """, (rol, context)).fetchone()

    if row:
        return dict(row)

    # Cargar versiones del vault
    versions = load_personalized_nudges(rol, context)
    if not versions["a"] or not versions["b"]:
        return None

    conn.execute("""
        INSERT INTO nudge_ab_tests (nudge_context, rol, version_a, version_b)
        VALUES (?, ?, ?, ?)
    """, (context, rol,
          random.choice(versions["a"]),
          random.choice(versions["b"])))
    conn.commit()

    return dict(conn.execute("""
        SELECT * FROM nudge_ab_tests WHERE rol = ? AND nudge_context = ?
        ORDER BY created_at DESC LIMIT 1
    """, (rol, context)).fetchone())


def _pick_ab_version(test: dict) -> tuple[str, str]:
    """
    Elige la versión a enviar y devuelve (contenido, "a"|"b").
    Si hay ganador, siempre usa el ganador.
    Si no, balancea aleatoriamente priorizando la versión con menos tests.
    """
    if test["winner"]:
        version  = test["winner"]
        contenido = test[f"version_{version}"]
        return contenido, version

    # Asignar la versión menos probada
    if test["tests_a"] < test["tests_b"]:
        return test["version_a"], "a"
    if test["tests_b"] < test["tests_a"]:
        return test["version_b"], "b"
    version = random.choice(["a", "b"])
    return test[f"version_{version}"], version


def _update_ab_counts(conn: sqlite3.Connection, test_id: str, version: str) -> None:
    """Incrementa el contador de tests para la versión elegida."""
    col = f"tests_{version}"
    conn.execute(f"""
        UPDATE nudge_ab_tests SET {col} = {col} + 1, updated_at = datetime('now')
        WHERE id = ?
    """, (test_id,))


def _evaluate_ab_winner(conn: sqlite3.Connection, test_id: str) -> str | None:
    """
    Declara ganador si alguna versión supera MIN_AB_WINNER tests con
    tasa de respuesta significativamente mejor. Devuelve 'a', 'b' o None.
    """
    row = conn.execute(
        "SELECT * FROM nudge_ab_tests WHERE id = ?", (test_id,)
    ).fetchone()
    if not row or row["winner"]:
        return row["winner"] if row else None

    ta, ra = row["tests_a"], row["respuestas_a"]
    tb, rb = row["tests_b"], row["respuestas_b"]

    if ta < MIN_AB_WINNER or tb < MIN_AB_WINNER:
        return None

    rate_a = ra / ta if ta else 0
    rate_b = rb / tb if tb else 0
    winner = None
    if abs(rate_a - rate_b) >= 0.15:   # diferencia mínima del 15%
        winner = "a" if rate_a > rate_b else "b"
        conn.execute("""
            UPDATE nudge_ab_tests SET winner = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (winner, test_id))
        conn.commit()
        logger.info("A/B test %s: ganador versión '%s' (%.0f%% vs %.0f%%)",
                    test_id, winner, rate_a * 100, rate_b * 100)
    return winner


def ab_test_nudges(program_id: str, context: str = "motivation-low") -> dict:
    """
    Crea o reutiliza un A/B test de nudges para el rol del coachee y el
    contexto dado. Selecciona la versión apropiada y la inserta en
    nudge_schedule para el día de hoy.

    Returns:
        {
            "program_id": str,
            "context": str,
            "version_elegida": "a" | "b",
            "contenido": str,
            "winner_actual": str | None,
            "test_id": str,
            "timestamp": str
        }
    """
    logger.info("A/B test nudge — program_id=%s context=%s", program_id, context)
    conn = get_connection()
    try:
        meta = conn.execute("""
            SELECT c.rol FROM coaching_programs cp
            JOIN coachees c ON c.id = cp.coachee_id WHERE cp.id = ?
        """, (program_id,)).fetchone()
        if not meta:
            raise ValueError(f"Programa no encontrado: {program_id}")
        rol = meta["rol"] or "generic"

        test = _get_or_create_ab_test(conn, rol, context)
        if not test:
            return {
                "program_id": program_id,
                "context":    context,
                "error":      f"Sin nudges personalizados para rol='{rol}' context='{context}'",
                "timestamp":  datetime.now().isoformat(timespec="seconds"),
            }

        contenido, version = _pick_ab_version(test)
        _update_ab_counts(conn, test["id"], version)
        winner = _evaluate_ab_winner(conn, test["id"])

        # Insertar en nudge_schedule para hoy
        hoy = datetime.now().date().isoformat()
        conn.execute("""
            INSERT OR IGNORE INTO nudge_schedule
                (program_id, fecha_programada, tipo, contenido, estado)
            VALUES (?, ?, 'ab_test', ?, 'pendiente')
        """, (program_id, hoy, contenido))
        conn.commit()
    finally:
        conn.close()

    logger.info("A/B nudge — versión=%s | ganador=%s", version, winner)
    return {
        "program_id":      program_id,
        "context":         context,
        "version_elegida": version,
        "contenido":       contenido,
        "winner_actual":   winner,
        "test_id":         test["id"],
        "timestamp":       datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# 4. Scheduling inteligente
# ---------------------------------------------------------------------------

def schedule_intelligent_nudges(
    program_id: str | None = None,
    days: int = NUDGE_DAYS,
) -> list[dict]:
    """
    Programa nudges inteligentes para programas activos (o uno específico):
        - Frecuencia ajustada al engagement score (1–3 nudges/semana)
        - Solo días laborables (sin fines de semana)
        - Hora de envío inferida del historial de actividad del coachee
        - Contenido personalizado por rol (vault) + GROW como fallback
        - Idempotente: omite fechas ya programadas

    Returns:
        Lista de nudges insertados como dicts.
    """
    banco    = load_question_bank()
    conn     = get_connection()
    insertados: list[dict] = []

    try:
        query  = """
            SELECT cp.id AS program_id, c.nombre AS coachee_nombre,
                   c.email AS coachee_email, c.rol, c.idioma_preferido
            FROM coaching_programs cp JOIN coachees c ON c.id = cp.coachee_id
            WHERE cp.estado = 'activo'
        """
        params: tuple = ()
        if program_id:
            query  += " AND cp.id = ?"
            params  = (program_id,)

        programas = conn.execute(query, params).fetchall()
        logger.info("Programas activos: %d", len(programas))

        hoy = datetime.now().date()
        for programa in programas:
            pid  = programa["program_id"]
            rol  = programa["rol"] or "generic"

            # Engagement y frecuencia
            score   = _engagement_score(conn, pid)
            n_nudge = _nudges_per_week(score)
            hora    = _preferred_hour(conn, pid)
            logger.info("program_id=%s score=%.1f freq=%d/week hora=%dh",
                        pid, score, n_nudge, hora)

            # Fase GROW de la próxima sesión pendiente
            fase_row = conn.execute("""
                SELECT fase_grow FROM sessions
                WHERE program_id = ? AND fecha_realizada IS NULL
                ORDER BY numero_sesion ASC LIMIT 1
            """, (pid,)).fetchone()
            fase = fase_row["fase_grow"] if fase_row else "goal"

            # Contenido: nudges personalizados > GROW genérico
            context = "motivation-low" if score < 40 else "post-session"
            custom  = load_personalized_nudges(rol, context)
            pool    = custom["a"] + custom["b"] if (custom["a"] or custom["b"]) else banco.get(fase, banco["goal"])
            if not pool:
                pool = ["¿Qué pequeño paso puedes dar hoy hacia tu objetivo?"]
            random.shuffle(pool)

            # Fechas en ventana (sin fines de semana)
            fechas = _weekdays_in_window(hoy, days, n_nudge)

            # Fechas ya programadas (cualquier tipo)
            inicio_str = hoy.isoformat()
            fin_str    = (hoy + timedelta(days=days - 1)).isoformat()
            ya = {r["fecha_programada"][:10] for r in conn.execute("""
                SELECT fecha_programada FROM nudge_schedule
                WHERE program_id = ? AND fecha_programada BETWEEN ? AND ?
            """, (pid, inicio_str, fin_str)).fetchall()}

            pool_cycle  = pool * ((n_nudge // len(pool)) + 2)
            pool_idx    = 0
            for fecha in fechas:
                fecha_str = fecha.isoformat()
                if fecha_str in ya:
                    logger.debug("Fecha ya ocupada %s para %s, omitiendo", fecha_str, pid)
                    continue
                contenido = pool_cycle[pool_idx % len(pool_cycle)]
                pool_idx += 1

                # Guardar con fecha+hora como string datetime
                fecha_hora = f"{fecha_str} {hora:02d}:00:00"
                conn.execute("""
                    INSERT INTO nudge_schedule
                        (program_id, fecha_programada, tipo, contenido, estado)
                    VALUES (?, ?, ?, ?, 'pendiente')
                """, (pid, fecha_hora, NUDGE_TIPO_INTELIGENTE, contenido))

                insertados.append({
                    "program_id":       pid,
                    "coachee_nombre":   programa["coachee_nombre"],
                    "coachee_email":    programa["coachee_email"],
                    "rol":              rol,
                    "fase_grow":        fase,
                    "engagement_score": score,
                    "fecha_programada": fecha_hora,
                    "hora_preferida":   hora,
                    "contenido":        contenido,
                })
                logger.debug("Nudge inteligente: %s → %s @%dh", pid, fecha_str, hora)

        conn.commit()
        logger.info("Nudges inteligentes programados: %d", len(insertados))
    finally:
        conn.close()

    return insertados


# ---------------------------------------------------------------------------
# 5. schedule_nudges original (mantenida para compatibilidad)
# ---------------------------------------------------------------------------

QUERY_PROGRAMAS_ACTIVOS = """
SELECT cp.id AS program_id, c.nombre AS coachee_nombre,
       c.email AS coachee_email, c.idioma_preferido
FROM coaching_programs cp JOIN coachees c ON c.id = cp.coachee_id
WHERE cp.estado = 'activo'
"""

INSERT_NUDGE = """
INSERT INTO nudge_schedule (program_id, fecha_programada, tipo, contenido, estado)
VALUES (?, ?, ?, ?, 'pendiente')
"""


def schedule_nudges(
    program_id: str | None = None,
    days: int = NUDGE_DAYS,
) -> list[dict]:
    """Versión original: un nudge/día por fase GROW, sin personalización."""
    banco = load_question_bank()
    conn  = get_connection()
    insertados: list[dict] = []
    try:
        query  = QUERY_PROGRAMAS_ACTIVOS
        params: tuple = ()
        if program_id:
            query  += " AND cp.id = ?"
            params  = (program_id,)
        programas = conn.execute(query, params).fetchall()
        hoy       = datetime.now().date()
        inicio    = hoy.isoformat()
        fin       = (hoy + timedelta(days=days - 1)).isoformat()

        for programa in programas:
            pid  = programa["program_id"]
            fase_row = conn.execute("""
                SELECT fase_grow FROM sessions
                WHERE program_id = ? AND fecha_realizada IS NULL
                ORDER BY numero_sesion ASC LIMIT 1
            """, (pid,)).fetchone()
            fase  = fase_row["fase_grow"] if fase_row else "goal"
            pool  = banco.get(fase, banco["goal"])
            if not pool:
                continue
            ya    = {r["fecha_programada"][:10] for r in conn.execute("""
                SELECT fecha_programada FROM nudge_schedule
                WHERE program_id = ? AND tipo = ? AND fecha_programada BETWEEN ? AND ?
            """, (pid, NUDGE_TIPO, inicio, fin)).fetchall()}

            random.shuffle(pool)
            pool_cycle = pool * ((days // len(pool)) + 1)
            idx = 0
            for d in range(days):
                fecha = (hoy + timedelta(days=d)).isoformat()
                if fecha in ya:
                    continue
                contenido = pool_cycle[idx]
                idx += 1
                conn.execute(INSERT_NUDGE, (pid, fecha, NUDGE_TIPO, contenido))
                insertados.append({
                    "program_id":       pid,
                    "coachee_nombre":   programa["coachee_nombre"],
                    "coachee_email":    programa["coachee_email"],
                    "fase_grow":        fase,
                    "fecha_programada": fecha,
                    "contenido":        contenido,
                })
        conn.commit()
        logger.info("Nudges básicos programados: %d", len(insertados))
    finally:
        conn.close()
    return insertados


# ---------------------------------------------------------------------------
# 6. Enviar nudges pendientes
# ---------------------------------------------------------------------------

def _simular_envio(nudge: sqlite3.Row) -> bool:
    logger.info(
        "  [SIMULADO] → program_id=%s | fecha=%s | '%s'",
        nudge["program_id"],
        nudge["fecha_programada"],
        nudge["contenido"][:60] + ("…" if len(nudge["contenido"]) > 60 else ""),
    )
    return True


def send_pending_nudges() -> dict:
    """Marca como enviados los nudges pendientes cuya fecha ya llegó."""
    logger.info("=== Procesando nudges pendientes ===")
    conn     = get_connection()
    enviados = 0
    fallidos = 0
    detalles: list[dict] = []
    try:
        pendientes = conn.execute("""
            SELECT id, program_id, fecha_programada, contenido
            FROM nudge_schedule
            WHERE estado = 'pendiente' AND fecha_programada <= datetime('now')
            ORDER BY fecha_programada ASC
        """).fetchall()
        logger.info("Pendientes: %d", len(pendientes))

        for nudge in pendientes:
            if _simular_envio(nudge):
                conn.execute("""
                    UPDATE nudge_schedule
                    SET estado = 'enviado', fecha_enviada = datetime('now'),
                        updated_at = datetime('now')
                    WHERE id = ?
                """, (nudge["id"],))
                enviados += 1
                detalles.append({
                    "id":               nudge["id"],
                    "program_id":       nudge["program_id"],
                    "fecha_programada": nudge["fecha_programada"],
                })
            else:
                fallidos += 1
                logger.error("Fallo en nudge id=%s", nudge["id"])
        conn.commit()
    finally:
        conn.close()

    logger.info("Enviados: %d | Fallidos: %d", enviados, fallidos)
    return {
        "enviados":  enviados,
        "fallidos":  fallidos,
        "detalles":  detalles,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Bloque __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    comando    = sys.argv[1] if len(sys.argv) > 1 else "inteligente"
    program_id = sys.argv[2] if len(sys.argv) > 2 else None
    context    = sys.argv[3] if len(sys.argv) > 3 else "motivation-low"

    if comando == "inteligente":
        print(json.dumps(schedule_intelligent_nudges(program_id), ensure_ascii=False, indent=2))

    elif comando == "schedule":
        print(json.dumps(schedule_nudges(program_id), ensure_ascii=False, indent=2))

    elif comando == "ab" and program_id:
        print(json.dumps(ab_test_nudges(program_id, context), ensure_ascii=False, indent=2))

    elif comando == "send":
        print(json.dumps(send_pending_nudges(), ensure_ascii=False, indent=2))

    elif comando == "banco":
        print(json.dumps(load_question_bank(), ensure_ascii=False, indent=2))

    elif comando == "custom" and program_id:
        rol = sys.argv[3] if len(sys.argv) > 3 else "Tech Lead"
        ctx = sys.argv[4] if len(sys.argv) > 4 else "motivation-low"
        print(json.dumps(load_personalized_nudges(rol, ctx), ensure_ascii=False, indent=2))

    else:
        print("Uso:")
        print("  python nudge_scheduler.py inteligente [program_id]")
        print("  python nudge_scheduler.py schedule    [program_id]")
        print("  python nudge_scheduler.py ab          <program_id> [context]")
        print("  python nudge_scheduler.py send")
        print("  python nudge_scheduler.py banco")
        print("  python nudge_scheduler.py custom      <program_id> <rol> [context]")
        sys.exit(1)
