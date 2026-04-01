"""
app.py - Interfaz de coaching virtual con Supabase
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
import psycopg2
from psycopg2.extras import RealDictCursor

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

# Configuración de base de datos Supabase
DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    """Retorna conexión a Supabase PostgreSQL"""
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# ============================================
# FUNCIONES DE BASE DE DATOS
# ============================================

def get_coachees():
    """Obtener lista de coachees"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, nombre, rol, empresa, email FROM coachees ORDER BY nombre")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_program_info(coachee_id):
    """Obtener programa activo del coachee"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT cp.id as program_id, cp.estado, cp.fecha_inicio,
               COUNT(s.id) as sesiones_completadas
        FROM coaching_programs cp
        LEFT JOIN sessions s ON cp.id = s.program_id AND s.fecha_realizada IS NOT NULL
        WHERE cp.coachee_id = %s AND cp.estado = 'activo'
        GROUP BY cp.id
    """, (coachee_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result

def create_program(coachee_id):
    """Crear un nuevo programa de coaching"""
    conn = get_db_connection()
    cur = conn.cursor()
    program_id = str(uuid.uuid4())
    cur.execute("""
        INSERT INTO coaching_programs (id, coachee_id, fecha_inicio, estado)
        VALUES (%s, %s, %s, 'activo')
    """, (program_id, coachee_id, datetime.now().isoformat()))
    conn.commit()
    cur.close()
    conn.close()
    return program_id

def get_session_status(program_id):
    """Obtener estado de todas las sesiones"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT numero_sesion, fase_grow, fecha_realizada, mood_antes, mood_despues
        FROM sessions
        WHERE program_id = %s
        ORDER BY numero_sesion
    """, (program_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_session_messages(program_id, session_num):
    """Obtener mensajes de una sesión"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT rol, mensaje, timestamp
        FROM session_messages
        WHERE program_id = %s AND session_num = %s
        ORDER BY timestamp
    """, (program_id, session_num))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def save_message(program_id, session_num, rol, mensaje):
    """Guardar mensaje en la sesión"""
    conn = get_db_connection()
    cur = conn.cursor()
    message_id = str(uuid.uuid4())
    cur.execute("""
        INSERT INTO session_messages (id, program_id, session_num, rol, mensaje, timestamp)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (message_id, program_id, session_num, rol, mensaje, datetime.now().isoformat()))
    conn.commit()
    cur.close()
    conn.close()

def update_session_mood(program_id, session_num, mood_antes, mood_despues):
    """Actualizar mood de la sesión"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE sessions
        SET mood_antes = %s, mood_despues = %s, updated_at = NOW()
        WHERE program_id = %s AND numero_sesion = %s
    """, (mood_antes, mood_despues, program_id, session_num))
    conn.commit()
    cur.close()
    conn.close()

def get_session_summary(program_id):
    """Obtiene resumen de sesiones anteriores del coachee"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT numero_sesion, resumen, criterios_avance
        FROM sessions
        WHERE program_id = %s AND fecha_realizada IS NOT NULL
        ORDER BY numero_sesion DESC
        LIMIT 3
    """, (program_id,))
    sessions_data = cur.fetchall()
    cur.close()
    conn.close()
    
    if not sessions_data:
        return None
    
    summary = "Sesiones anteriores:\n"
    for sesion in sessions_data:
        summary += f"- Sesión {sesion['numero_sesion']}: {sesion['resumen'] or 'Sin resumen'}\n"
        if sesion.get('criterios_avance'):
            try:
                import json
                criterios_dict = json.loads(sesion['criterios_avance']) if isinstance(sesion['criterios_avance'], str) else sesion['criterios_avance']
                summary += f"  Avances: {criterios_dict}\n"
            except:
                pass
    
    return summary

# ============================================
# FUNCIONES DEL AGENTE
# ============================================

def load_question_bank(fase_grow):
    """Cargar preguntas del banco según fase desde Obsidian vault"""
    try:
        vault_path = Path(__file__).parent / "data" / "vault" / "grow-questions" / f"{fase_grow.lower()}.md"
        with open(vault_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Buscar preguntas en formato texto: "..."
        questions = re.findall(r'texto:\s*"([^"]+)"', content)
        return questions if questions else []
    except Exception as e:
        print(f"Error cargando preguntas: {e}")
        # Preguntas por defecto
        default_questions = {
            'goal': [
                "¿Qué te gustaría lograr en esta sesión?",
                "¿Cuál es tu objetivo principal?",
                "¿Cómo sabrás que has alcanzado tu objetivo?"
            ],
            'reality': [
                "¿Cuál es la situación actual?",
                "¿Qué has intentado hasta ahora?",
                "¿Qué funciona y qué no?"
            ],
            'options': [
                "¿Qué opciones tienes?",
                "¿Qué más podrías hacer?",
                "¿Qué harías si no tuvieras miedo?"
            ],
            'will': [
                "¿Qué vas a hacer?",
                "¿Cuándo lo vas a hacer?",
                "¿Qué compromiso asumes?"
            ]
        }
        return default_questions.get(fase_grow.lower(), [])

def agent_response(user_input, fase_grow, question_index, conversation_history, coachee_profile=None, session_summary=None):
    """
    Genera respuesta usando Claude API
    """
    # Cargar preguntas del banco
    questions = load_question_bank(fase_grow)
    current_question = questions[min(question_index, len(questions)-1)] if questions else ""
    
    # Construir contexto del sistema
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
- Si el coachee se desvía, redirige suavemente al tema de la sesión
- Reconoce avances y logros cuando corresponda
- Si el coachee muestra frustración o bloqueo, ofrece validación emocional primero
"""

    # Construir historial de conversación para Claude
    messages = []
    
    # Añadir resumen de sesiones anteriores si existe
    if session_summary:
        messages.append({
            "role": "user",
            "content": f"[Contexto de sesiones anteriores: {session_summary}]"
        })
        messages.append({
            "role": "assistant", 
            "content": "Gracias por el contexto. Lo tendré en cuenta para esta sesión."
        })
    
    # Añadir la conversación actual
    for rol, msg in conversation_history[-10:]:
        messages.append({
            "role": "user" if rol == "user" else "assistant",
            "content": msg
        })
    
    # Añadir la pregunta actual como guía
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
        else:
            return "¿Qué más te gustaría explorar sobre este tema?"

# ============================================
# INTERFAZ PRINCIPAL
# ============================================

def main():
    # Sidebar
    with st.sidebar:
        st.title("🎯 Coaching Virtual")
        st.markdown("---")
        
        # Selector de coachee
        coachees = get_coachees()
        if not coachees:
            st.warning("No hay coachees registrados. Crea uno primero.")
            coachee_names = []
            coachee_data = None
        else:
            coachee_names = [c['nombre'] for c in coachees]
        
        if coachees:
            coachee_selected = st.selectbox(
                "👤 Coachee",
                coachee_names
            )
            coachee_data = next((c for c in coachees if c['nombre'] == coachee_selected), None)
            
            if coachee_data:
                # Info del coachee
                with st.expander("ℹ️ Información", expanded=True):
                    st.write(f"**Rol:** {coachee_data['rol'] or '—'}")
                    st.write(f"**Empresa:** {coachee_data['empresa'] or '—'}")
                    st.write(f"**Email:** {coachee_data['email']}")
                
                # Obtener programa
                program_info = get_program_info(coachee_data['id'])
                
                if program_info is None:
                    st.warning("No hay programa activo")
                    if st.button("🆕 Crear programa"):
                        program_id = create_program(coachee_data['id'])
                        st.success(f"Programa creado: {program_id[:8]}...")
                        st.rerun()
                else:
                    # Progreso visual
                    st.markdown("### 📅 Progreso")
                    sesiones = get_session_status(program_info['program_id'])
                    completadas = len([s for s in sesiones if s.get('fecha_realizada')])
                    st.progress(completadas / 8)
                    st.caption(f"{completadas}/8 sesiones completadas")
                    
                    # Selector de sesión
                    st.markdown("### 🎯 Sesión")
                    session_options = []
                    for i in range(1, 9):
                        if i <= completadas:
                            icon = "✅"
                        elif i == completadas + 1:
                            icon = "▶️"
                        else:
                            icon = "🔒"
                        session_options.append(f"{icon} Sesión {i}")
                    
                    session_selected = st.selectbox(
                        "Seleccionar",
                        session_options,
                        index=min(completadas, 7)
                    )
                    session_num = int(session_selected.split(" ")[-1])
                    
                    # Botón iniciar
                    if st.button("▶️ Iniciar / Retomar sesión", type="primary"):
                        st.session_state['program_id'] = program_info['program_id']
                        st.session_state['session_num'] = session_num
                        st.session_state['messages'] = []
                        st.session_state['question_index'] = 0
                        
                        # Obtener fase GROW de la sesión
                        fases = {1: 'goal', 2: 'reality', 3: 'reality', 4: 'options', 
                                 5: 'will', 6: 'will', 7: 'will', 8: 'will'}
                        st.session_state['fase_grow'] = fases.get(session_num, 'goal')
                        
                        # Mensaje de bienvenida
                        welcome = f"🎯 **Sesión {session_num} - {st.session_state['fase_grow'].upper()}**\n\n"
                        questions = load_question_bank(st.session_state['fase_grow'])
                        welcome += questions[0] if questions else "¿Qué te gustaría lograr en esta sesión?"
                        st.session_state['messages'].append(("agent", welcome))
                        st.rerun()
                    
                    st.markdown("---")
                    
                    # Workers
                    st.markdown("### 🔧 Workers")
                    if st.button("📊 Ejecutar análisis"):
                        st.info("Workers ejecutados (simulado)")
    
    # Main area
    if 'program_id' in st.session_state and coachee_data:
        # Header con info de sesión
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.title(f"🎯 {coachee_data['nombre']}")
            st.caption(f"{coachee_data['rol'] or '—'} · {coachee_data['empresa'] or '—'} · Sesión {st.session_state['session_num']} · {st.session_state['fase_grow'].upper()}")
        
        with col2:
            # Mood selector
            with st.expander("😊 Mood tracking"):
                mood_before = st.slider("Antes de la sesión", 1, 5, 3, key="mood_before")
                mood_after = st.slider("Después de la sesión", 1, 5, 3, key="mood_after")
                if st.button("💾 Guardar mood"):
                    update_session_mood(
                        st.session_state['program_id'],
                        st.session_state['session_num'],
                        mood_before,
                        mood_after
                    )
                    st.success("Mood guardado!")
        
        with col3:
            # Herramientas según sesión
            with st.expander("🛠️ Herramientas"):
                session_num = st.session_state['session_num']
                if session_num == 1:
                    st.info("**Rueda de la Vida**\nEvalúa áreas clave")
                    if st.button("📝 Evaluar Rueda"):
                        st.session_state['messages'].append(("agent", "Vamos a evaluar tu Rueda de la Vida. ¿Cómo calificarías cada área del 1 al 10?"))
                        st.rerun()
                elif session_num == 3:
                    st.info("**Reestructuración Cognitiva**\nIdentifica creencias")
                elif session_num == 5:
                    st.info("**Plan de Acción**\nDefine compromisos")
                elif session_num == 8:
                    st.info("**Certificado**\nGenera certificado")
        
        # Tabs
        tab1, tab2, tab3 = st.tabs(["💬 Chat", "📊 Progreso", "📜 Historial"])
        
        with tab1:
            st.markdown("### 💬 Conversación")
            
            # Mostrar mensajes
            for rol, msg in st.session_state['messages']:
                if rol == "agent":
                    st.chat_message("assistant").write(msg)
                else:
                    st.chat_message("user").write(msg)
            
            # Input del usuario
            user_input = st.chat_input("Escribe tu respuesta...")
            if user_input:
                # Guardar mensaje del usuario
                st.session_state['messages'].append(("user", user_input))
                
                # Obtener perfil del coachee
                coachee_profile = coachee_data.get('rol', '')
                
                # Obtener resumen de sesiones anteriores
                session_summary = get_session_summary(st.session_state['program_id'])
                
                # Generar respuesta del agente
                fase = st.session_state['fase_grow']
                q_idx = st.session_state.get('question_index', 0)
                
                agent_msg = agent_response(
                    user_input=user_input,
                    fase_grow=fase,
                    question_index=q_idx,
                    conversation_history=st.session_state['messages'][-20:],
                    coachee_profile=coachee_profile,
                    session_summary=session_summary
                )
                
                st.session_state['question_index'] = q_idx + 1
                st.session_state['messages'].append(("agent", agent_msg))
                
                # Guardar en BD
                save_message(
                    st.session_state['program_id'],
                    st.session_state['session_num'],
                    'user',
                    user_input
                )
                save_message(
                    st.session_state['program_id'],
                    st.session_state['session_num'],
                    'agent',
                    agent_msg
                )
                
                st.rerun()
        
        with tab2:
            st.markdown("### 📊 Métricas de Progreso")
            
            # Gráfico de moods
            sesiones = get_session_status(st.session_state['program_id'])
            if sesiones:
                df = pd.DataFrame(sesiones)
                if 'mood_antes' in df.columns:
                    fig = px.line(
                        df,
                        x='numero_sesion',
                        y=['mood_antes', 'mood_despues'],
                        title="Evolución de Mood por Sesión",
                        labels={'value': 'Mood', 'numero_sesion': 'Sesión', 'variable': 'Momento'}
                    )
                    st.plotly_chart(fig, use_container_width=True)
            
            # Progreso ponderado
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
        # Pantalla de bienvenida
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
            st.info("No hay coachees registrados. Añade uno desde la base de datos.")

if __name__ == "__main__":
    main()