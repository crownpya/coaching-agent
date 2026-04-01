"""
main.py
Punto de entrada del Sistema de Coaching Virtual.
"""

import sys
import json
import sqlite3
from pathlib import Path

# Añadir docs/scripts al path
sys.path.append(str(Path(__file__).parent / "docs" / "scripts"))

from coaching_agent import CoachingAgent

DB_PATH    = Path(__file__).parent / "data" / "database" / "coaching.db"
SCHEMA_PATH = Path(__file__).parent / "database" / "schema.sql"

HELP_TEXT = """\
=== Sistema de Coaching Virtual ===

Comandos disponibles:

  init-db
      Inicializar (o reinicializar) la base de datos desde database/schema.sql

  start-session <program_id> <session_num>
      Iniciar o retomar una sesión de coaching
      Ejemplo: python main.py start-session abc-123 1

  run-workers
      Ejecutar todos los workers de análisis:
        · session_tracker  → sesiones estancadas y compromisos vencidos
        · progress_analyzer → progreso y motivación de cada programa activo
        · nudge_scheduler  → programar nudges y enviar los pendientes

  test-agent
      Probar el flujo completo del agente con datos de ejemplo
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_active_program_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM coaching_programs WHERE estado = 'activo'"
    ).fetchall()
    return [row[0] for row in rows]


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------

def cmd_init_db() -> None:
    if not SCHEMA_PATH.exists():
        print(f"[ERROR] No se encontró el schema en: {SCHEMA_PATH}")
        sys.exit(1)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
        print(f"Base de datos inicializada correctamente en: {DB_PATH}")
    finally:
        conn.close()


def cmd_start_session(program_id: str, session_num: int) -> None:
    agent = CoachingAgent(program_id)
    welcome = agent.start_session(session_num)
    print(welcome)


def cmd_run_workers() -> None:
    print("=== Ejecutando workers ===\n")

    # 1. session_tracker
    print("--- session_tracker ---")
    from session_tracker import generar_reporte
    reporte = generar_reporte()
    print(json.dumps(reporte, ensure_ascii=False, indent=2))

    # 2. progress_analyzer (por cada programa activo)
    print("\n--- progress_analyzer ---")
    from progress_analyzer import calculate_progress, analyze_motivation
    if not DB_PATH.exists():
        print("[AVISO] Base de datos no encontrada, omitiendo progress_analyzer")
    else:
        conn = sqlite3.connect(DB_PATH)
        program_ids = _get_active_program_ids(conn)
        conn.close()
        if not program_ids:
            print("Sin programas activos.")
        for pid in program_ids:
            progreso   = calculate_progress(pid)
            motivacion = analyze_motivation(pid)
            print(json.dumps({"progreso": progreso, "motivacion": motivacion},
                             ensure_ascii=False, indent=2))

    # 3. nudge_scheduler
    print("\n--- nudge_scheduler ---")
    from nudge_scheduler import schedule_nudges, send_pending_nudges
    nuevos  = schedule_nudges()
    print(f"Nudges programados: {len(nuevos)}")
    enviados = send_pending_nudges()
    print(json.dumps(enviados, ensure_ascii=False, indent=2))

    print("\n=== Workers completados ===")


def cmd_test_agent() -> None:
    print("=== Probando agente con datos de ejemplo ===\n")

    if not DB_PATH.exists():
        print("[AVISO] Base de datos no encontrada. Ejecuta primero: python main.py init-db")
        sys.exit(1)

    # Crear coachee y programa de prueba
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO coachees (id, nombre, email, rol, empresa)
            VALUES ('coachee-test-001', 'Ana García', 'ana@ejemplo.com',
                    'Directora de Operaciones', 'TechCorp')
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO coaching_programs
                (id, coachee_id, fecha_inicio, estado)
            VALUES ('program-test-001', 'coachee-test-001', date('now'), 'activo')
            """
        )
        conn.commit()
    finally:
        conn.close()

    program_id = "program-test-001"
    agent = CoachingAgent(program_id)

    print("--- start_session(1) ---")
    print(agent.start_session(1))

    print("\n--- save_mood('antes', 4) ---")
    agent.save_mood("antes", 4)
    print("Mood guardado: 4/5")

    print("\n--- use_tool: evaluate_wheel_of_life ---")
    print(agent.use_tool("evaluate_wheel_of_life", {
        "categorias": {
            "carrera": 6, "salud": 7, "familia": 8,
            "finanzas": 5, "desarrollo": 7, "ocio": 4,
            "relaciones": 8, "proposito": 6,
        }
    }))

    print("\n--- use_tool: set_smart_goal ---")
    print(agent.use_tool("set_smart_goal", {
        "objetivo": "Liderar mi equipo con mayor confianza en los próximos 3 meses."
    }))

    print("\n--- use_tool no disponible en sesión 1 ---")
    print(agent.use_tool("track_belief", {"creencia_limitante": "No soy suficiente"}))

    print("\n--- process_response ---")
    print(agent.process_response("Ver mi rueda de la vida ha sido muy revelador."))

    print("\n--- save_mood('despues', 5) ---")
    agent.save_mood("despues", 5)
    print("Mood guardado: 5/5")

    print("\n=== Test completado ===")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(HELP_TEXT)
        return

    command = sys.argv[1]

    if command == "init-db":
        cmd_init_db()

    elif command == "start-session":
        if len(sys.argv) < 4:
            print("Uso: python main.py start-session <program_id> <session_num>")
            sys.exit(1)
        try:
            session_num = int(sys.argv[3])
        except ValueError:
            print("[ERROR] session_num debe ser un entero entre 1 y 8")
            sys.exit(1)
        cmd_start_session(sys.argv[2], session_num)

    elif command == "run-workers":
        cmd_run_workers()

    elif command == "test-agent":
        cmd_test_agent()

    else:
        print(f"Comando desconocido: '{command}'\n")
        print(HELP_TEXT)
        sys.exit(1)


if __name__ == "__main__":
    main()
