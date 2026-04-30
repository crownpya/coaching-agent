import os
from datetime import datetime
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def run():
    print(f"📚 Knowledge Worker iniciado a las {datetime.now()}")
    try:
        res = supabase.table("coach_knowledge").update({"last_updated": datetime.now().isoformat()}).eq("active", True).execute()
        print(f"✅ Actualizados {len(res.data)} registros activos")
    except Exception as e:
        print(f"❌ Error actualizando knowledge: {e}")
    print("🏁 Knowledge Worker finalizado")

if __name__ == "__main__":
    run()
