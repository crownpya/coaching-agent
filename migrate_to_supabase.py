"""
migrate_to_supabase.py - Migra datos de SQLite a Supabase
"""

import sqlite3
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import uuid
from datetime import datetime

load_dotenv()

# Configuración
SQLITE_DB = "data/database/coaching.db"
DATABASE_URL = os.getenv("DATABASE_URL")

def get_sqlite_connection():
    """Conecta a SQLite local"""
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn

def get_supabase_connection():
    """Conecta a Supabase PostgreSQL"""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def migrate_table(sqlite_conn, pg_conn, table_name, columns, transform=None):
    """
    Migra una tabla de SQLite a PostgreSQL
    """
    print(f"Migrando {table_name}...")
    
    # Leer datos de SQLite
    cursor_sqlite = sqlite_conn.cursor()
    cursor_sqlite.execute(f"SELECT {', '.join(columns)} FROM {table_name}")
    rows = cursor_sqlite.fetchall()
    
    if not rows:
        print(f"  → {table_name}: sin datos")
        return 0
    
    # Insertar en PostgreSQL
    cursor_pg = pg_conn.cursor()
    count = 0
    
    for row in rows:
        data = dict(row)
        
        # Transformar si es necesario
        if transform:
            data = transform(data)
        
        # Construir INSERT
        placeholders = ', '.join(['%s'] * len(data.keys()))
        columns_str = ', '.join(data.keys())
        
        try:
            query = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            cursor_pg.execute(query, list(data.values()))
            count += 1
        except Exception as e:
            print(f"  → Error insertando en {table_name}: {e}")
    
    pg_conn.commit()
    print(f"  → {count} registros migrados")
    return count

def main():
    print("=== Migración de SQLite a Supabase ===\n")
    
    # Verificar que SQLite existe
    if not os.path.exists(SQLITE_DB):
        print(f"❌ Base de datos SQLite no encontrada: {SQLITE_DB}")
        return
    
    # Conectar a bases de datos
    sqlite_conn = get_sqlite_connection()
    pg_conn = get_supabase_connection()
    
    try:
        # Verificar que hay datos en SQLite
        cursor = sqlite_conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"Tablas en SQLite: {[t[0] for t in tables]}\n")
        
        # Migrar coachees
        migrate_table(sqlite_conn, pg_conn, "coachees", 
                      ["id", "nombre", "email", "rol", "empresa", "idioma_preferido", 
                       "fecha_registro", "created_at", "updated_at"])
        
        # Migrar coaching_programs
        migrate_table(sqlite_conn, pg_conn, "coaching_programs",
                      ["id", "coachee_id", "fecha_inicio", "fecha_fin_estimada", 
                       "estado", "certificado_entregado", "created_at", "updated_at"])
        
        # Migrar sessions
        migrate_table(sqlite_conn, pg_conn, "sessions",
                      ["id", "program_id", "numero_sesion", "fase_grow", 
                       "fecha_programada", "fecha_realizada", "mood_antes", 
                       "mood_despues", "resumen", "criterios_avance", "notas_agente",
                       "created_at", "updated_at"])
        
        # Migrar action_plans
        migrate_table(sqlite_conn, pg_conn, "action_plans",
                      ["id", "session_id", "objetivo", "acciones", "fecha_inicio", 
                       "fecha_fin", "kpis", "estado", "created_at", "updated_at"])
        
        # Migrar beliefs_tracker
        migrate_table(sqlite_conn, pg_conn, "beliefs_tracker",
                      ["id", "session_id", "creencia_limitante", "creencia_potenciadora_reemplazo",
                       "evidencia_contraria", "estado", "created_at", "updated_at"])
        
        # Migrar wheel_of_life
        migrate_table(sqlite_conn, pg_conn, "wheel_of_life",
                      ["id", "session_id", "categorias", "fecha_registro", "created_at", "updated_at"])
        
        # Migrar competency_tracking
        migrate_table(sqlite_conn, pg_conn, "competency_tracking",
                      ["id", "session_id", "competencia", "nivel_autoevaluado", 
                       "nivel_coach", "evidencia", "created_at", "updated_at"])
        
        # Migrar nudge_schedule
        migrate_table(sqlite_conn, pg_conn, "nudge_schedule",
                      ["id", "program_id", "fecha_programada", "fecha_enviada", 
                       "tipo", "contenido", "estado", "created_at", "updated_at"])
        
        # Migrar session_messages
        migrate_table(sqlite_conn, pg_conn, "session_messages",
                      ["id", "program_id", "session_num", "rol", "mensaje", "timestamp", "created_at"])
        
        print("\n✅ Migración completada!")
        
        # Verificar resultados
        cursor_pg = pg_conn.cursor()
        cursor_pg.execute("SELECT COUNT(*) as count FROM coachees")
        result = cursor_pg.fetchone()
        print(f"\n📊 Total coachees en Supabase: {result['count']}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    
    finally:
        sqlite_conn.close()
        pg_conn.close()

if __name__ == "__main__":
    main()