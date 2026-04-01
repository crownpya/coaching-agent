"""
coach_dashboard.py
Dashboard Streamlit exclusivo para coaches.

Lanzar: streamlit run coach_dashboard.py --server.port 8502
"""

import sys
import sqlite3
from datetime import datetime
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
sys.path.append(str(ROOT / "docs" / "scripts"))

DB_PATH = ROOT / "data" / "database" / "coaching.db"

from progress_analyzer import (
    calculate_progress,
    analyze_motivation,
    benchmark_comparison,
    predict_completion_date,
)
from session_tracker import (
    analyze_engagement_patterns,
    suggest_coach_intervention,
)
from nudge_scheduler import schedule_intelligent_nudges

# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Coach Dashboard",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .card {
        background: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 12px;
        padding: 1.2rem 1.4rem;
        margin-bottom: 1rem;
    }
    .card-critical { border-left: 5px solid #e53935; }
    .card-warning  { border-left: 5px solid #fb8c00; }
    .card-ok       { border-left: 5px solid #43a047; }
    .badge-red    { background:#fdecea; color:#c62828; padding:2px 8px; border-radius:20px; font-size:.8rem; }
    .badge-orange { background:#fff3e0; color:#e65100; padding:2px 8px; border-radius:20px; font-size:.8rem; }
    .badge-green  { background:#e8f5e9; color:#2e7d32; padding:2px 8px; border-radius:20px; font-size:.8rem; }
    .section-title { font-size:1.1rem; font-weight:600; color:#37474f; margin-bottom:.5rem; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def db_ok() -> bool:
    return DB_PATH.exists()


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


@st.cache_data(ttl=20)
def load_coaches() -> list[dict]:
    if not db_ok():
        return []
    c = conn()
    rows = c.execute(
        "SELECT id, nombre, email, especialidad, nivel FROM coaches ORDER BY nombre"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


@st.cache_data(ttl=15)
def load_coachees_de_coach(coach_id: str) -> list[dict]:
    c = conn()
    rows = c.execute("""
        SELECT c.id AS coachee_id, c.nombre, c.email, c.rol, c.empresa,
               cp.id AS program_id, cp.fecha_inicio,
               cca.id AS assignment_id
        FROM coach_coachee_assignments cca
        JOIN coachees c  ON c.id  = cca.coachee_id
        JOIN coaching_programs cp ON cp.coachee_id = c.id AND cp.estado = 'activo'
        WHERE cca.coach_id = ? AND cca.estado = 'activa'
        ORDER BY c.nombre
    """, (coach_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@st.cache_data(ttl=15)
def load_sessions_coachee(program_id: str) -> list[dict]:
    c = conn()
    rows = c.execute("""
        SELECT numero_sesion, fase_grow, fecha_programada, fecha_realizada,
               mood_antes, mood_despues, resumen
        FROM sessions WHERE program_id = ? ORDER BY numero_sesion
    """, (program_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


@st.cache_data(ttl=15)
def load_sesiones_sin_feedback(coach_id: str) -> list[dict]:
    c = conn()
    rows = c.execute("""
        SELECT s.id AS session_id, s.numero_sesion, s.fase_grow,
               s.fecha_realizada, s.resumen,
               co.nombre AS coachee_nombre, cp.id AS program_id,
               cca.id AS assignment_id
        FROM sessions s
        JOIN coaching_programs cp ON cp.id = s.program_id
        JOIN coachees co ON co.id = cp.coachee_id
        JOIN coach_coachee_assignments cca ON cca.coachee_id = co.id
        WHERE cca.coach_id = ?
          AND s.fecha_realizada IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM coach_feedback cf WHERE cf.session_id = s.id
          )
        ORDER BY s.fecha_realizada DESC
    """, (coach_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def save_coach_feedback(assignment_id: str, session_id: str,
                        feedback_coach: str, feedback_coachee: str,
                        valoracion: int) -> None:
    c = conn()
    c.execute("""
        INSERT INTO coach_feedback
            (assignment_id, session_id, feedback_coach, feedback_coachee, valoracion_coach)
        VALUES (?, ?, ?, ?, ?)
    """, (assignment_id, session_id, feedback_coach, feedback_coachee, valoracion))
    c.commit()
    c.close()
    load_sesiones_sin_feedback.clear()


def save_extra_session(program_id: str, numero: int, fecha: str) -> None:
    from session_tracker import get_connection as _gc
    fases = {1:"goal",2:"reality",3:"reality",4:"options",
             5:"will",6:"will",7:"will",8:"will"}
    c = conn()
    c.execute("""
        INSERT OR IGNORE INTO sessions
            (program_id, numero_sesion, fase_grow, fecha_programada)
        VALUES (?, ?, ?, ?)
    """, (program_id, numero, fases.get(numero, "will"), fecha))
    c.commit()
    c.close()
    load_sessions_coachee.clear()


def create_coach(nombre: str, email: str, especialidad: str, nivel: str,
                 biografia: str) -> None:
    c = conn()
    c.execute("""
        INSERT INTO coaches (nombre, email, especialidad, nivel, biografia)
        VALUES (?, ?, ?, ?, ?)
    """, (nombre, email, especialidad, nivel, biografia))
    c.commit()
    c.close()
    load_coaches.clear()


def assign_coachee_to_coach(coach_id: str, coachee_id: str) -> None:
    c = conn()
    c.execute("""
        INSERT OR IGNORE INTO coach_coachee_assignments
            (coach_id, coachee_id, estado)
        VALUES (?, ?, 'activa')
    """, (coach_id, coachee_id))
    c.commit()
    c.close()
    load_coachees_de_coach.clear()


@st.cache_data(ttl=30)
def load_todos_coachees() -> list[dict]:
    c = conn()
    rows = c.execute(
        "SELECT id, nombre, rol, empresa FROM coachees ORDER BY nombre"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Cálculo de métricas (con caché por program_id)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60)
def get_metrics(program_id: str) -> dict:
    try:
        progreso    = calculate_progress(program_id)
        motivacion  = analyze_motivation(program_id)
        engagement  = analyze_engagement_patterns(program_id)
        prediccion  = predict_completion_date(program_id)
    except Exception as e:
        return {"error": str(e)}
    return {
        "progreso":   progreso,
        "motivacion": motivacion,
        "engagement": engagement,
        "prediccion": prediccion,
    }


def severity(metrics: dict) -> str:
    """Devuelve 'critical', 'warning' o 'ok' según las métricas."""
    if "error" in metrics:
        return "warning"
    score = metrics["engagement"]["engagement_score"]
    alerta_mot = metrics["motivacion"]["alerta"]
    if score < 40 or (alerta_mot and score < 60):
        return "critical"
    if score < 60 or alerta_mot:
        return "warning"
    return "ok"


# ---------------------------------------------------------------------------
# Componentes UI
# ---------------------------------------------------------------------------

SEVERITY_ICON  = {"critical": "🔴", "warning": "🟠", "ok": "🟢"}
SEVERITY_CLASS = {"critical": "card-critical", "warning": "card-warning", "ok": "card-ok"}
SEVERITY_LABEL = {"critical": "Crítico", "warning": "Atención", "ok": "Al día"}


def render_coachee_card(coachee: dict, metrics: dict) -> None:
    sev      = severity(metrics)
    score    = metrics.get("engagement", {}).get("engagement_score", 0) if "error" not in metrics else 0
    progreso = metrics.get("progreso", {}).get("progreso_total", 0) if "error" not in metrics else 0
    prediccion = metrics.get("prediccion", {})

    with st.container():
        st.markdown(
            f'<div class="card {SEVERITY_CLASS[sev]}">',
            unsafe_allow_html=True,
        )
        col1, col2, col3 = st.columns([3, 2, 2])

        with col1:
            st.markdown(f"**{coachee['nombre']}**")
            st.caption(f"{coachee['rol']} · {coachee['empresa']}")
            st.caption(f"📧 {coachee['email']}")

        with col2:
            st.markdown("**Progreso**")
            st.progress(progreso / 100)
            st.caption(f"{progreso:.1f}%")
            fin = prediccion.get("fecha_predicha_fin")
            if fin:
                st.caption(f"🏁 Fin estimado: {fin}")

        with col3:
            st.markdown("**Engagement**")
            color_score = (
                "🔴" if score < 40 else "🟠" if score < 60 else "🟢"
            )
            st.metric("Score", f"{color_score} {score:.0f}/100")
            st.markdown(
                f'<span class="badge-{"red" if sev=="critical" else "orange" if sev=="warning" else "green"}">'
                f'{SEVERITY_ICON[sev]} {SEVERITY_LABEL[sev]}</span>',
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)


def render_tab_coachees(coachees: list[dict]) -> None:
    st.subheader("👥 Mis coachees")

    if not coachees:
        st.info("No tienes coachees asignados aún. Usa el panel lateral para asignar uno.")
        return

    for coachee in coachees:
        pid     = coachee["program_id"]
        metrics = get_metrics(pid)

        render_coachee_card(coachee, metrics)

        with st.expander(f"📋 Detalle — {coachee['nombre']}", expanded=False):
            tab_ses, tab_acc, tab_int = st.tabs(["Sesiones", "Acciones", "Intervenciones"])

            with tab_ses:
                sesiones = load_sessions_coachee(pid)
                if sesiones:
                    df = pd.DataFrame(sesiones)
                    df["completada"] = df["fecha_realizada"].notna()
                    df["estado"]     = df["completada"].map({True: "✅", False: "🔒"})
                    st.dataframe(
                        df[["estado", "numero_sesion", "fase_grow",
                            "mood_antes", "mood_despues", "fecha_realizada"]],
                        use_container_width=True, hide_index=True,
                    )
                else:
                    st.caption("Sin sesiones registradas.")

                # Programar sesión extra
                with st.form(f"extra_ses_{pid}"):
                    st.caption("Programar sesión extra")
                    n_sesion = st.number_input("Número de sesión", 1, 8, value=1)
                    fecha_ex = st.date_input("Fecha")
                    if st.form_submit_button("Programar"):
                        save_extra_session(pid, int(n_sesion), str(fecha_ex))
                        st.success(f"Sesión {n_sesion} programada para {fecha_ex}")

            with tab_acc:
                c = conn()
                acc_rows = c.execute("""
                    SELECT ap.objetivo, ap.estado, ap.fecha_fin
                    FROM action_plans ap
                    JOIN sessions s ON s.id = ap.session_id
                    WHERE s.program_id = ? ORDER BY ap.fecha_fin
                """, (pid,)).fetchall()
                c.close()
                if acc_rows:
                    icons = {"completada": "✅", "pendiente": "🕐", "en_progreso": "🔄"}
                    for a in acc_rows:
                        vencida = (a["fecha_fin"] and
                                   a["fecha_fin"] < datetime.now().strftime("%Y-%m-%d") and
                                   a["estado"] != "completada")
                        icon = icons.get(a["estado"], "📋")
                        txt  = f"{icon} {a['objetivo']} — `{a['fecha_fin'] or 'sin fecha'}`"
                        st.write(txt + (" ⚠️" if vencida else ""))
                else:
                    st.caption("Sin planes de acción.")

            with tab_int:
                try:
                    inter = suggest_coach_intervention(pid)
                    if inter["intervenciones_sugeridas"]:
                        for sug in inter["intervenciones_sugeridas"]:
                            prioridad_color = (
                                "🔴" if sug["prioridad"] == "Alta"
                                else "🟠" if sug["prioridad"] == "Media" else "🟡"
                            )
                            st.markdown(
                                f"**{prioridad_color} {sug['tipo']}** — {sug['razon']}"
                            )
                            st.caption(sug["descripcion"])
                    else:
                        st.success("Sin intervenciones necesarias.")
                except Exception as e:
                    st.caption(f"Sin datos suficientes: {e}")

        st.divider()


def render_tab_alertas(coachees: list[dict]) -> None:
    st.subheader("🚨 Alertas activas")

    criticas:  list[tuple] = []
    atenciones: list[tuple] = []

    for coachee in coachees:
        metrics = get_metrics(coachee["program_id"])
        sev = severity(metrics)
        if sev == "critical":
            criticas.append((coachee, metrics))
        elif sev == "warning":
            atenciones.append((coachee, metrics))

    if not criticas and not atenciones:
        st.success("✅ No hay alertas activas. Todos los coachees están al día.")
        return

    if criticas:
        st.markdown("#### 🔴 Crítico")
        for coachee, metrics in criticas:
            score = metrics["engagement"]["engagement_score"]
            motivos = metrics["motivacion"].get("motivos", [])
            sug = []
            try:
                inter = suggest_coach_intervention(coachee["program_id"])
                sug   = [s["tipo"] for s in inter["intervenciones_sugeridas"]]
            except Exception:
                pass

            with st.container():
                st.markdown(
                    f'<div class="card card-critical">'
                    f'<b>🔴 {coachee["nombre"]}</b> — Engagement: {score:.0f}/100<br>'
                    + ("".join(f"<br>• {m}" for m in motivos))
                    + (f"<br>💡 Intervención: {', '.join(sug)}" if sug else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )

    if atenciones:
        st.markdown("#### 🟠 Atención")
        for coachee, metrics in atenciones:
            score   = metrics["engagement"]["engagement_score"]
            motivos = metrics["motivacion"].get("motivos", [])
            with st.container():
                st.markdown(
                    f'<div class="card card-warning">'
                    f'<b>🟠 {coachee["nombre"]}</b> — Engagement: {score:.0f}/100<br>'
                    + ("".join(f"<br>• {m}" for m in motivos))
                    + "</div>",
                    unsafe_allow_html=True,
                )


def render_tab_feedback(coach_id: str, coachees: list[dict]) -> None:
    st.subheader("📝 Feedback pendiente")
    pendientes = load_sesiones_sin_feedback(coach_id)

    if not pendientes:
        st.success("✅ No hay sesiones pendientes de feedback.")
        return

    st.caption(f"{len(pendientes)} sesión(es) sin feedback de coach.")

    for s in pendientes:
        label = (f"Sesión {s['numero_sesion']} — {s['coachee_nombre']} "
                 f"({s['fase_grow'].upper()}) · {s['fecha_realizada'][:10]}")
        with st.expander(label):
            if s["resumen"]:
                st.caption("Resumen de sesión:")
                st.write(s["resumen"][:300] + ("…" if len(s["resumen"] or "") > 300 else ""))

            # Buscar assignment_id del coach → coachee
            assignment_id = next(
                (c["assignment_id"] for c in coachees
                 if c["program_id"] == s["program_id"]),
                s.get("assignment_id", ""),
            )

            with st.form(f"feedback_{s['session_id']}"):
                fb_coach    = st.text_area("Tu feedback como coach", height=80)
                fb_coachee  = st.text_area("Valoración del coachee (observada)", height=60)
                valoracion  = st.slider("Valoración de la sesión (1–5)", 1, 5, 4)
                if st.form_submit_button("Guardar feedback", type="primary"):
                    if fb_coach.strip():
                        save_coach_feedback(
                            assignment_id, s["session_id"],
                            fb_coach, fb_coachee, valoracion,
                        )
                        st.success("Feedback guardado.")
                        st.rerun()
                    else:
                        st.warning("Escribe tu feedback antes de guardar.")


def render_tab_benchmarks(coachees: list[dict]) -> None:
    st.subheader("📊 Comparativa entre coachees")

    if not coachees:
        st.info("Sin coachees asignados.")
        return

    # Recolectar datos para gráficos
    nombres, progresos, engagements, dias_restantes = [], [], [], []
    for c in coachees:
        m = get_metrics(c["program_id"])
        if "error" in m:
            continue
        nombres.append(c["nombre"].split()[0])   # primer nombre para etiqueta corta
        progresos.append(m["progreso"]["progreso_total"])
        engagements.append(m["engagement"]["engagement_score"])
        dr = m["prediccion"].get("dias_restantes_estimados")
        dias_restantes.append(dr if dr else 0)

    if not nombres:
        st.info("Sin métricas disponibles.")
        return

    col1, col2 = st.columns(2)

    with col1:
        fig_prog = go.Figure(go.Bar(
            x=nombres,
            y=progresos,
            marker_color=[
                "#43a047" if p >= 60 else "#fb8c00" if p >= 30 else "#e53935"
                for p in progresos
            ],
            text=[f"{p:.0f}%" for p in progresos],
            textposition="outside",
        ))
        fig_prog.update_layout(
            title="Progreso del programa (%)",
            yaxis=dict(range=[0, 110]),
            showlegend=False,
            height=350,
        )
        st.plotly_chart(fig_prog, use_container_width=True)

    with col2:
        fig_eng = go.Figure(go.Bar(
            x=nombres,
            y=engagements,
            marker_color=[
                "#43a047" if e >= 60 else "#fb8c00" if e >= 40 else "#e53935"
                for e in engagements
            ],
            text=[f"{e:.0f}" for e in engagements],
            textposition="outside",
        ))
        fig_eng.update_layout(
            title="Engagement score (0–100)",
            yaxis=dict(range=[0, 110]),
            showlegend=False,
            height=350,
        )
        st.plotly_chart(fig_eng, use_container_width=True)

    # Radar: comparativa multidimensional
    st.divider()
    st.markdown("#### Radar multidimensional")
    fig_radar = go.Figure()
    categorias = ["Progreso", "Engagement", "Días restantes (inv.)"]
    for i, nombre in enumerate(nombres):
        dias_inv = max(0, 100 - min(dias_restantes[i], 100)) if dias_restantes[i] else 50
        fig_radar.add_trace(go.Scatterpolar(
            r=[progresos[i], engagements[i], dias_inv],
            theta=categorias,
            fill="toself",
            name=nombre,
        ))
    fig_radar.update_layout(
        polar=dict(radialaxis=dict(range=[0, 100])),
        height=400,
    )
    st.plotly_chart(fig_radar, use_container_width=True)

    # Tabla resumen
    st.divider()
    st.caption("Tabla resumen")
    df = pd.DataFrame({
        "Coachee":    [c["nombre"] for c in coachees[:len(nombres)]],
        "Rol":        [c["rol"] for c in coachees[:len(nombres)]],
        "Progreso %": progresos,
        "Engagement": engagements,
        "Fin est.":   [m.get("prediccion", {}).get("fecha_predicha_fin", "—")
                       for c in coachees[:len(nombres)]
                       for m in [get_metrics(c["program_id"])]
                       if "error" not in m],
    })
    st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> dict | None:
    with st.sidebar:
        st.title("🏆 Coach Dashboard")
        st.caption("Vista exclusiva para coaches")
        st.divider()

        if not db_ok():
            st.error("Base de datos no encontrada.\nEjecuta: `python main.py init-db`")
            return None

        coaches = load_coaches()

        # Crear coach si no hay ninguno
        if not coaches:
            st.warning("No hay coaches registrados.")
            with st.expander("➕ Crear coach", expanded=True):
                with st.form("form_nuevo_coach"):
                    nombre     = st.text_input("Nombre")
                    email      = st.text_input("Email")
                    esp        = st.selectbox("Especialidad",
                                             ["liderazgo", "productividad", "comunicacion", "otro"])
                    nivel      = st.selectbox("Nivel", ["junior", "senior", "master"])
                    bio        = st.text_area("Biografía", height=80)
                    if st.form_submit_button("Crear coach", type="primary"):
                        if nombre and email:
                            try:
                                create_coach(nombre, email, esp, nivel, bio)
                                st.success("Coach creado.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                        else:
                            st.warning("Nombre y email son obligatorios.")
            return None

        # Selector de coach
        opciones = {f"{c['nombre']} ({c['especialidad']})": c for c in coaches}
        sel      = st.selectbox("👤 Coach", list(opciones.keys()))
        coach    = opciones[sel]

        # Info del coach
        with st.expander("Perfil", expanded=False):
            st.write(f"**Especialidad:** {coach['especialidad']}")
            st.write(f"**Nivel:** {coach['nivel']}")
            st.write(f"**Email:** {coach['email']}")

        st.divider()

        # Asignar coachee
        with st.expander("➕ Asignar coachee", expanded=False):
            todos = load_todos_coachees()
            asignados_ids = {c["coachee_id"] for c in load_coachees_de_coach(coach["id"])}
            disponibles   = [c for c in todos if c["id"] not in asignados_ids]
            if disponibles:
                opts = {f"{c['nombre']} ({c['rol']})": c for c in disponibles}
                sel_coachee = st.selectbox("Coachee", list(opts.keys()))
                if st.button("Asignar", type="primary"):
                    assign_coachee_to_coach(coach["id"], opts[sel_coachee]["id"])
                    st.success(f"{opts[sel_coachee]['nombre']} asignado.")
                    st.rerun()
            else:
                st.caption("Todos los coachees ya están asignados a este coach.")

        st.divider()

        # Quick stats
        coachees = load_coachees_de_coach(coach["id"])
        n_criticos = sum(
            1 for c in coachees
            if severity(get_metrics(c["program_id"])) == "critical"
        )
        st.metric("Coachees activos", len(coachees))
        if n_criticos:
            st.metric("Alertas críticas", n_criticos, delta=f"-{n_criticos}", delta_color="inverse")

        st.divider()

        # Nudges
        if st.button("📬 Programar nudges inteligentes", use_container_width=True):
            with st.spinner("Programando nudges…"):
                try:
                    for c in coachees:
                        schedule_intelligent_nudges(c["program_id"])
                    st.success(f"{len(coachees)} programa(s) actualizados.")
                except Exception as e:
                    st.error(f"Error: {e}")

    return coach


# ---------------------------------------------------------------------------
# App principal
# ---------------------------------------------------------------------------

def main() -> None:
    if not db_ok():
        st.title("🏆 Coach Dashboard")
        st.error("""
        **Base de datos no encontrada.**
        ```
        python main.py init-db
        python test_data.py
        ```
        """)
        return

    coach = render_sidebar()
    if not coach:
        st.title("🏆 Coach Dashboard")
        st.info("Crea un coach en el panel lateral para comenzar.")
        return

    # Header
    st.title(f"🏆 {coach['nombre']}")
    st.caption(
        f"Especialidad: **{coach['especialidad']}** · Nivel: **{coach['nivel']}** · {coach['email']}"
    )
    st.divider()

    coachees = load_coachees_de_coach(coach["id"])
    pending  = load_sesiones_sin_feedback(coach["id"])

    # Tabs principales
    tab_labels = [
        f"👥 Mis coachees ({len(coachees)})",
        "🚨 Alertas",
        f"📝 Feedback ({len(pending)})",
        "📊 Benchmarks",
    ]
    t1, t2, t3, t4 = st.tabs(tab_labels)

    with t1:
        render_tab_coachees(coachees)
    with t2:
        render_tab_alertas(coachees)
    with t3:
        render_tab_feedback(coach["id"], coachees)
    with t4:
        render_tab_benchmarks(coachees)


if __name__ == "__main__":
    main()
