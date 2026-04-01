"""
supabase_client.py - Cliente para conexión a Supabase
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_DB_URL = os.getenv("DATABASE_URL")

def get_supabase_client() -> Client:
    """Retorna cliente de Supabase para operaciones REST"""
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def get_db_connection():
    """Retorna conexión directa a PostgreSQL"""
    return psycopg2.connect(SUPABASE_DB_URL, cursor_factory=RealDictCursor)

def test_connection():
    """Prueba la conexión a Supabase"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM coachees")
        result = cur.fetchone()
        print(f"✅ Conexión exitosa! Total coachees: {result['count']}")
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        return False

if __name__ == "__main__":
    test_connection()