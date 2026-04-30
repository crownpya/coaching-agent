import os
import requests
from datetime import datetime, timedelta
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def send_telegram(msg):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": msg}, timeout=5)
            print("📨 Nudge enviado")
        except Exception as e:
            print(f"❌ Error Telegram: {e}")
    else:
        print(f"📢 {msg}")

def run():
    print(f"🔍 Progress Worker iniciado a las {datetime.now()}")
    progs = supabase.table("coaching_programs").select("id, coachee_id").eq("estado", "activo").execute()
    for prog in progs.data:
        prog_id = prog["id"]
        ses = supabase.table("sessions").select("id", count="exact").eq("program_id", prog_id).not_.is_("fecha_realizada", "null").execute()
        sessions_done = ses.count or 0
        progress = round((sessions_done / 8) * 100, 1)
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
