"""
app.py - Interfaz de coaching virtual con Supabase (versión REST)
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import sys
import os
from pathlib import Path
import uuid
import re
import anthropic
from dotenv import load_dotenv
from supabase import create_client

# Cargar variables de entorno
load_dotenv()

# Configuración de página
st.set_page_config(
    page_title="Coaching Virtual",
    page_icon="🎯",
    layout="wide"
)

# Inicializar cliente de Claude
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Inicializar cliente de Supabase (REST)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================
# FUNCIONES DE BASE DE DATOS (REST)
# ============================================

def get_coachees():
    """Obtener lista de coachees"""
    try:
        response = supabase.table("coachees").select("*").order("nombre").execute()
        return response.data
    except Exception as e:
        st.error(f"Error al obtener coachees: {e}")
        return []

def get_program_info(coachee_id):
    """Obtener programa activo del coachee"""
    try:
        response = supabase.table("coaching_programs").select("id, estado, fecha_inicio").eq("coachee_id", coachee_id).eq("estado", "activo").execute()
        if response.data:
            program = response.data[0]
            # Contar sesiones completadas
            sessions_response = supabase.table("sessions").select("id").eq("program_id", program["id"]).not_.is_("fecha_realizada", "null").execute()
            program["sesiones_completadas"] = len(sessions_response.data)
            return program
        return None
    except Exception as e:
        st.error(f"Error al obtener programa: {e}")
        return None

def create_program(coachee_id):
    """Crear un nuevo programa de coaching"""
    try:
        program_id = str(uuid.uuid4())
        data = {
            "id": program_id,
            "coachee_id": coachee_id,
            "fecha_inicio": datetime.now().isoformat(),
            "estado": "activo"
        }
        supabase.table("coaching_programs").insert(data).execute()
        return program_id
    except Exception as e:
        st.error(f"Error al crear programa: {e}")
        return None

def get_session_status(program_id):
    """Obtener estado de todas las sesiones"""
    try:
        response = supabase.table("sessions").select("*").eq("program_id", program_id).order("numero_sesion").execute()
        return response.data
    except Exception as e:
        st.error(f"Error al obtener sesiones: {e}")
        return []

def get_session_messages(program_id, session_num):
    """Obtener mensajes de una sesión"""
    try:
        response = supabase.table("session_messages").select("*").eq("program_id", program_id).eq("session_num", session_num).order("timestamp").execute()
        return response.data
    except Exception as e:
        return []

def save_message(program_id, session_num, rol, mensaje):
    """Guardar mensaje en la sesión"""
    try:
        message_id = str(uuid.uuid4())
        data = {
            "id": message_id,
            "program_id": program_id,
            "session_num": session_num,
            "rol": rol,
            "mensaje": mensaje,
            "timestamp": datetime.now().isoformat()
        }
        supabase.table("session_messages").insert(data).execute()
    except Exception as e:
        st.error(f"Error al guardar mensaje: {e}")

def update_session_mood(program_id, session_num, mood_antes, mood_despues):
    """Actualizar mood de la sesión"""
    try:
        supabase.table("sessions").update({
            "mood_antes": mood_antes,
            "mood_despues": mood_despues
        }).eq("program_id", program_id).eq("numero_sesion", session_num).execute()
    except Exception as e:
        st.error(f"Error al actualizar mood: {e}")

def get_session_summary(program_id):
    """Obtiene resumen de sesiones anteriores del coachee"""
    try:
        response = supabase.table("sessions").select("*").eq("program_id", program_id).not_.is_("fecha_realizada", "null").order("numero_sesion", desc=True).limit(3).execute()
        if not response.data:
            return None
        
        summary = "Sesiones anteriores:\n"
        for sesion in response.data:
            summary += f"- Sesión {sesion['numero_sesion']}: {sesion.get('resumen', 'Sin resumen')}\n"
        return summary
    except Exception as e:
        return None

# ============================================
# FUNCIONES DEL AGENTE
# ============================================

def load_question_bank(fase_grow):
    """Cargar preguntas del banco según fase desde Obsidian vault"""
    try:
        vault_path = Path(__file__).parent / "data" / "vault" / "grow-questions" / f"{fase_grow.lower()}.md"
        with open(vault_path, 'r', encoding='utf-8') as f:
            content = f.read()
        questions = re.findall(r'texto:\s*"([^"]+)"', content)
        return questions if questions else []
    except Exception as e:
        print(f"Error cargando preguntas: {e}")
        default_questions = {
            'goal': ["¿Qué te gustaría lograr en esta sesión?", "¿Cuál es tu objetivo principal?", "¿Cómo sabrás que has alcanzado tu objetivo?"],
            'reality': ["¿Cuál es la situación actual?", "¿Qué has intentado hasta ahora?", "¿Qué funciona y qué no?"],
            'options': ["¿Qué opciones tienes?", "¿Qué más podrías hacer?", "¿Qué harías si no tuvieras miedo?"],
            'will': ["¿Qué vas a hacer?", "¿Cuándo lo vas a hacer?", "¿Qué compromiso asumes?"]
        }
        return default_questions.get(fase_grow.lower(), [])

def agent_response(user_input, fase_grow, question_index, conversation_history, coachee_profile=None, session_summary=None):
    """Genera respuesta usando Claude API"""
    questions = load_question_bank(fase_grow)
    current_question = questions[min(question_index, len(questions)-1)] if questions else ""
    
    system_prompt = f"""Eres un coach ejecutivo especializado en managers de tecnología. 
Tu estilo es empático, directo y basado en el modelo GROW.

Fase GROW actual: {fase_grow.upper()}
{f'Perfil del coachee: {coachee_profile}' if coachee_profile else ''}

Reglas:
- Usa preguntas poderosas que inviten a la reflexión
- No des consejos directamente, guía al coachee a encontrar sus propias soluciones
- Mantén un tono profesional pero cercano
- Respeta el código deontológico de ICF
- Basa tus preguntas en el banco de preguntas pero adáptalas al contexto
"""

    messages = []
    if session_summary:
        messages.append({"role": "user", "content": f"[Contexto de sesiones anteriores: {session_summary}]"})
        messages.append({"role": "assistant", "content": "Gracias por el contexto. Lo tendré en cuenta para esta sesión."})
    
    for rol, msg in conversation_history[-10:]:
        messages.append({"role": "user" if rol == "user" else "assistant", "content": msg})
    
    messages.append({
        "role": "user",
        "content": f"La siguiente pregunta que debo hacer según la fase GROW es: '{current_question}'. El coachee acaba de decir: '{user_input}'. ¿Cómo respondo como coach?"
    })
    
    try:
        response = client.messages.create(
            model=os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022"),
            max_tokens=int(os.getenv("CLAUDE_MAX_TOKENS", 500)),
            temperature=float(os.getenv("CLAUDE_TEMPERATURE", 0.7)),
            system=system_prompt,
            messages=messages
        )
        return response.content[0].text
    except Exception as e:
        print(f"Error con Claude API: {e}")
        if question_index < len(questions):
            return questions[question_index]
        return "¿Qué más te gustaría explorar sobre este tema?"

# ============================================
# INTERFAZ PRINCIPAL
# ============================================

def main():
    with st.sidebar:
        st.title("🎯 Coaching Virtual")
        st.markdown("---")
        
        coachees = get_coachees()
        if not coachees:
            st.warning("No hay coachees registrados. Añade uno desde Supabase.")
            coachee_names = []
            coachee_data = None
        else:
            coachee_names = [c['nombre'] for c in coachees]
        
        if coachees:
            coachee_selected = st.selectbox("👤 Coachee", coachee_names)
            coachee_data = next((c for c in coachees if c['nombre'] == coachee_selected), None)
            
            if coachee_data:
                with st.expander("ℹ️ Información", expanded=True):
                    st.write(f"**Rol:** {coachee_data.get('rol', '—')}")
                    st.write(f"**Empresa:** {coachee_data.get('empresa', '—')}")
                    st.write(f"**Email:** {coachee_data.get('email', '—')}")
                
                program_info = get_program_info(coachee_data['id'])
                
                if program_info is None:
                    st.warning("No hay programa activo")
                    if st.button("🆕 Crear programa"):
                        program_id = create_program(coachee_data['id'])
                        if program_id:
                            st.success(f"Programa creado: {program_id[:8]}...")
                            st.rerun()
                else:
                    st.markdown("### 📅 Progreso")
                    sesiones = get_session_status(program_info['id'])
                    completadas = len([s for s in sesiones if s.get('fecha_realizada')])
                    st.progress(completadas / 8)
                    st.caption(f"{completadas}/8 sesiones completadas")
                    
                    st.markdown("### 🎯 Sesión")
                    session_options = []
                    for i in range(1, 9):
                        icon = "✅" if i <= completadas else ("▶️" if i == completadas + 1 else "🔒")
                        session_options.append(f"{icon} Sesión {i}")
                    
                    session_selected = st.selectbox("Seleccionar", session_options, index=min(completadas, 7))
                    session_num = int(session_selected.split(" ")[-1])
                    
                    if st.button("▶️ Iniciar / Retomar sesión", type="primary"):
                        st.session_state['program_id'] = program_info['id']
                        st.session_state['session_num'] = session_num
                        st.session_state['messages'] = []
                        st.session_state['question_index'] = 0
                        
                        fases = {1: 'goal', 2: 'reality', 3: 'reality', 4: 'options', 5: 'will', 6: 'will', 7: 'will', 8: 'will'}
                        st.session_state['fase_grow'] = fases.get(session_num, 'goal')
                        
                        welcome = f"🎯 **Sesión {session_num} - {st.session_state['fase_grow'].upper()}**\n\n"
                        questions = load_question_bank(st.session_state['fase_grow'])
                        welcome += questions[0] if questions else "¿Qué te gustaría lograr en esta sesión?"
                        st.session_state['messages'].append(("agent", welcome))
                        st.rerun()
    
    if 'program_id' in st.session_state and coachee_data:
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.title(f"🎯 {coachee_data['nombre']}")
            st.caption(f"{coachee_data.get('rol', '—')} · {coachee_data.get('empresa', '—')} · Sesión {st.session_state['session_num']} · {st.session_state['fase_grow'].upper()}")
        
        with col2:
            with st.expander("😊 Mood tracking"):
                mood_before = st.slider("Antes de la sesión", 1, 5, 3, key="mood_before")
                mood_after = st.slider("Después de la sesión", 1, 5, 3, key="mood_after")
                if st.button("💾 Guardar mood"):
                    update_session_mood(st.session_state['program_id'], st.session_state['session_num'], mood_before, mood_after)
                    st.success("Mood guardado!")
        
        with col3:
            with st.expander("🛠️ Herramientas"):
                if st.session_state['session_num'] == 1:
                    st.info("**Rueda de la Vida**\nEvalúa áreas clave")
        
        tab1, tab2, tab3 = st.tabs(["💬 Chat", "📊 Progreso", "📜 Historial"])
        
        with tab1:
            st.markdown("### 💬 Conversación")
            for rol, msg in st.session_state['messages']:
                st.chat_message("assistant" if rol == "agent" else "user").write(msg)
            
            user_input = st.chat_input("Escribe tu respuesta...")
            if user_input:
                st.session_state['messages'].append(("user", user_input))
                coachee_profile = coachee_data.get('rol', '')
                session_summary = get_session_summary(st.session_state['program_id'])
                fase = st.session_state['fase_grow']
                q_idx = st.session_state.get('question_index', 0)
                
                agent_msg = agent_response(user_input, fase, q_idx, st.session_state['messages'][-20:], coachee_profile, session_summary)
                st.session_state['question_index'] = q_idx + 1
                st.session_state['messages'].append(("agent", agent_msg))
                
                save_message(st.session_state['program_id'], st.session_state['session_num'], 'user', user_input)
                save_message(st.session_state['program_id'], st.session_state['session_num'], 'agent', agent_msg)
                st.rerun()
        
        with tab2:
            st.markdown("### 📊 Métricas de Progreso")
            sesiones = get_session_status(st.session_state['program_id'])
            if sesiones:
                df = pd.DataFrame(sesiones)
                if 'mood_antes' in df.columns:
                    fig = px.line(df, x='numero_sesion', y=['mood_antes', 'mood_despues'], title="Evolución de Mood por Sesión")
                    st.plotly_chart(fig, use_container_width=True)
            completadas = len([s for s in sesiones if s.get('fecha_realizada')])
            st.metric("Progreso total", f"{completadas * 12.5:.0f}%")
        
        with tab3:
            st.markdown("### 📜 Historial de Sesiones")
            for i in range(1, st.session_state['session_num'] + 1):
                with st.expander(f"Sesión {i}"):
                    messages = get_session_messages(st.session_state['program_id'], i)
                    if messages:
                        for msg in messages:
                            icon = "🤖" if msg['rol'] == 'agent' else "👤"
                            st.write(f"{icon} **{msg['rol']}:** {msg['mensaje'][:100]}...")
    else:
        st.title("🎯 Coaching Virtual para Managers")
        st.markdown("""
        ### Bienvenido al sistema de coaching
        
        **Selecciona un coachee en el menú lateral para comenzar.**
        
        #### Flujo de 8 sesiones basado en modelo GROW:
        - S1: Diagnóstico inicial y objetivos SMART
        - S2-3: Exploración de realidad actual
        - S4: Opciones y recursos
        - S5-8: Plan de acción, seguimiento y cierre
        """)
        if not coachees:
            st.info("No hay coachees registrados. Añade uno desde Supabase.")

if __name__ == "__main__":
    main()