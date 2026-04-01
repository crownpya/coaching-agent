"""
add_test_data.py - Añadir datos de prueba a Supabase
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import uuid
from datetime import datetime, timedelta

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def add_test_data():
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        cur = conn.cursor()
        
        print("=== Añadiendo datos de prueba a Supabase ===\n")
        
        # 1. Insertar coachee
        coachee_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO coachees (id, nombre, email, rol, empresa, idioma_preferido)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (coachee_id, 'Carlos Méndez', 'carlos@techcorp.com', 'Tech Lead', 'TechCorp', 'es'))
        print(f"✅ Coachee añadido: Carlos Méndez (ID: {coachee_id[:8]}...)")
        
        # 2. Insertar programa activo
        program_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO coaching_programs (id, coachee_id, fecha_inicio, estado)
            VALUES (%s, %s, %s, 'activo')
        """, (program_id, coachee_id, datetime.now().isoformat()))
        print(f"✅ Programa añadido: {program_id[:8]}...")
        
        # 3. Insertar sesiones
        for i in range(1, 3):
            session_id = str(uuid.uuid4())
            fase = 'goal' if i == 1 else 'reality'
            fecha = (datetime.now() - timedelta(days=30 - i*15)).isoformat()
            cur.execute("""
                INSERT INTO sessions (id, program_id, numero_sesion, fase_grow, fecha_realizada, mood_antes, mood_despues)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (session_id, program_id, i, fase, fecha, 4, 4))
            print(f"✅ Sesión {i} añadida")
        
        # 4. Insertar acción vencida
        session_id = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO sessions (id, program_id, numero_sesion, fase_grow)
            VALUES (%s, %s, %s, %s)
        """, (session_id, program_id, 1, 'goal'))
        
        action_id = str(uuid.uuid4())
        fecha_vencida = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
        cur.execute("""
            INSERT INTO action_plans (id, session_id, objetivo, acciones, fecha_fin, estado)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (action_id, session_id, 'Implementar reuniones 1:1 semanales', '["Agendar reuniones", "Preparar agenda"]', fecha_vencida, 'pendiente'))
        print(f"✅ Acción vencida añadida (fecha: {fecha_vencida})")
        
        conn.commit()
        
        # Verificar
        cur.execute("SELECT COUNT(*) as count FROM coachees")
        result = cur.fetchone()
        print(f"\n📊 Total coachees en Supabase: {result['count']}")
        
        cur.execute("SELECT nombre, rol, email FROM coachees")
        print("\nCoachees:")
        for row in cur.fetchall():
            print(f"   - {row['nombre']} | {row['rol']} | {row['email']}")
        
        cur.close()
        conn.close()
        
        print("\n✅ Datos de prueba añadidos correctamente!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    add_test_data()