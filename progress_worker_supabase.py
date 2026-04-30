import os
import requests
from datetime import datetime, timedelta
from supabase import create_client

# Obtener credenciales de variables de entorno (GitHub Secrets)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_telegram(msg):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
            print("📨 Nudge enviado a Telegram")
        except Exception as e:
            print(f"❌ Error Telegram: {e}")
    else:
        print(f"📢 {msg}")

def run():
    print(f"🔍 Progress Worker iniciado a las {datetime.now()}")
    try:
        progs = supabase.table("coaching_programs").select("id, coachee_id").eq("estado", "activo").execute()
    except Exception as e:
        print(f"❌ Error conectando a Supabase: {e}")
        return
    for prog in progs.data:
        prog_id = prog["id"]
        # Sesiones completadas
        ses = supabase.table("sessions").select("id", count="exact").eq("program_id", prog_id).not_.is_("fecha_realizada", "null").execute()
        sessions_done = ses.count or 0
        progress = round((sessions_done / 8) * 100, 1)
        # Última sesión
        last = supabase.table("sessions").select("fecha_realizada").eq("program_id", prog_id).not_.is_("fecha_realizada", "null").order("fecha_realizada", desc=True).limit(1).execute()
        if last.data:
            last_date = datetime.fromisoformat(last.data[0]["fecha_realizada"].replace(" ", "T"))
            days = (datetime.now() - last_date).days
            if days > 7:
                send_telegram(f"⚠️ Inactivo {days} días. Progreso: {progress}% - {prog_id[:8]}")
        elif progress < 30:
            send_telegram(f"📉 Progreso bajo ({progress}%) para {prog_id[:8]}")
        else:
            print(f"✅ {prog_id[:8]}... progreso {progress}%")
    print("🏁 Progress Worker finalizado")

if __name__ == "__main__":
    run()