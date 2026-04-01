"""
test_data.py
Inserta datos de prueba para validar el sistema completo.
Idempotente: usa INSERT OR IGNORE para no duplicar en ejecuciones repetidas.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "database" / "coaching.db"


def insert_test_data(conn: sqlite3.Connection) -> None:
    # ------------------------------------------------------------------
    # 1. Coachee
    # ------------------------------------------------------------------
    conn.execute("""
        INSERT OR IGNORE INTO coachees
            (id, nombre, email, rol, empresa, idioma_preferido, fecha_registro)
        VALUES
            ('coachee-001', 'Carlos Méndez', 'carlos@techcorp.com',
             'Tech Lead', 'TechCorp', 'es', datetime('now'))
    """)
    print("  [OK] Coachee: Carlos Méndez")

    # ------------------------------------------------------------------
    # 2. Programa de coaching
    # ------------------------------------------------------------------
    conn.execute("""
        INSERT OR IGNORE INTO coaching_programs
            (id, coachee_id, fecha_inicio, fecha_fin_estimada, estado)
        VALUES
            ('prog-001', 'coachee-001',
             date('now', '-60 days'), date('now', '+30 days'), 'activo')
    """)
    print("  [OK] Programa: prog-001 (activo)")

    # ------------------------------------------------------------------
    # 3. Sesión 1 — completada, moods normales
    # ------------------------------------------------------------------
    conn.execute("""
        INSERT OR IGNORE INTO sessions
            (id, program_id, numero_sesion, fase_grow,
             fecha_programada, fecha_realizada,
             mood_antes, mood_despues, resumen)
        VALUES
            ('sess-001', 'prog-001', 1, 'goal',
             date('now', '-50 days'), date('now', '-50 days'),
             4, 4,
             'Diagnóstico inicial. Carlos identificó su objetivo principal: mejorar su capacidad de delegación efectiva.')
    """)
    print("  [OK] Sesión 1: goal | mood_antes=4 | mood_despues=4")

    # ------------------------------------------------------------------
    # 4. Sesión 2 — completada, moods normales
    # ------------------------------------------------------------------
    conn.execute("""
        INSERT OR IGNORE INTO sessions
            (id, program_id, numero_sesion, fase_grow,
             fecha_programada, fecha_realizada,
             mood_antes, mood_despues, resumen)
        VALUES
            ('sess-002', 'prog-001', 2, 'reality',
             date('now', '-35 days'), date('now', '-35 days'),
             3, 4,
             'Exploración de la realidad actual. Identificadas principales fricciones con el equipo.')
    """)
    print("  [OK] Sesión 2: reality | mood_antes=3 | mood_despues=4")

    # ------------------------------------------------------------------
    # 5. Acción planificada con fecha VENCIDA (para session_tracker)
    # ------------------------------------------------------------------
    conn.execute("""
        INSERT OR IGNORE INTO action_plans
            (id, session_id, objetivo, acciones, fecha_inicio, fecha_fin,
             kpis, estado)
        VALUES
            ('action-001', 'sess-002',
             'Implementar reuniones 1:1 semanales con cada miembro del equipo',
             '["Definir agenda tipo para 1:1", "Agendar slots recurrentes en calendario", "Realizar primera ronda de 1:1"]',
             date('now', '-30 days'), date('now', '-5 days'),
             '["% equipo con 1:1 realizado", "NPS interno del equipo"]',
             'pendiente')
    """)
    print("  [OK] Acción vencida: fecha_fin=hace 5 días | estado=pendiente")

    conn.commit()


def verify_data(conn: sqlite3.Connection) -> None:
    print("\n--- Verificación ---")

    row = conn.execute(
        "SELECT nombre, rol, empresa FROM coachees WHERE id = 'coachee-001'"
    ).fetchone()
    print(f"  Coachee:  {row[0]} | {row[1]} | {row[2]}")

    row = conn.execute(
        "SELECT estado, fecha_inicio, fecha_fin_estimada FROM coaching_programs WHERE id = 'prog-001'"
    ).fetchone()
    print(f"  Programa: estado={row[0]} | inicio={row[1]} | fin_est={row[2]}")

    rows = conn.execute(
        "SELECT numero_sesion, fase_grow, mood_antes, mood_despues, fecha_realizada "
        "FROM sessions WHERE program_id = 'prog-001' ORDER BY numero_sesion"
    ).fetchall()
    for r in rows:
        print(f"  Sesión {r[0]}: {r[1]} | mood {r[2]}→{r[3]} | realizada={r[4]}")

    row = conn.execute(
        "SELECT objetivo, fecha_fin, estado FROM action_plans WHERE id = 'action-001'"
    ).fetchone()
    print(f"  Acción:   '{row[0][:50]}...' | vence={row[1]} | estado={row[2]}")


def main() -> None:
    print(f"Base de datos: {DB_PATH}\n")

    if not DB_PATH.exists():
        print("[ERROR] La base de datos no existe.")
        print("        Ejecuta primero: python main.py init-db")
        raise SystemExit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        print("Insertando datos de prueba...")
        insert_test_data(conn)
        verify_data(conn)
        print("\n[OK] Datos de prueba insertados correctamente.")
    except sqlite3.Error as e:
        conn.rollback()
        print(f"\n[ERROR] SQLite: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
