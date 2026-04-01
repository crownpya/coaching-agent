"""
test_supabase.py - Prueba de conexión a Supabase
"""

import os
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor

# Cargar variables de entorno
load_dotenv()

# Obtener credenciales
DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

print("=== Prueba de conexión a Supabase ===\n")

# Verificar que las variables existen
if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL no está definida en .env")
    print("   Asegúrate de que el archivo .env contiene la línea:")
    print("   DATABASE_URL=postgresql://...")
    exit(1)

if not SUPABASE_URL:
    print("⚠️  SUPABASE_URL no está definida (no es crítica para esta prueba)")

print(f"✅ DATABASE_URL encontrada: {DATABASE_URL[:50]}...\n")

def test_connection():
    """Prueba la conexión directa a PostgreSQL"""
    try:
        print("Conectando a Supabase PostgreSQL...")
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        # Verificar tablas
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = cur.fetchall()
        
        print(f"✅ Conexión exitosa!")
        print(f"\n📊 Tablas encontradas en la base de datos:")
        for table in tables:
            print(f"   - {table['table_name']}")
        
        # Contar coachees si existe la tabla
        try:
            cur.execute("SELECT COUNT(*) FROM coachees")
            count = cur.fetchone()
            print(f"\n👥 Total coachees: {count['count']}")
        except:
            print("\n⚠️  Tabla 'coachees' no encontrada (aún no has migrado los datos)")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        print("\nPosibles causas:")
        print("   - La contraseña es incorrecta")
        print("   - La URL de conexión es incorrecta")
        print("   - El proyecto de Supabase no está activo")
        return False

if __name__ == "__main__":
    test_connection()