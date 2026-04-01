"""
certification_manager.py
Gestiona la elegibilidad de certificación, generación de certificados PDF
y reportes de progreso final para programas de coaching ejecutivo.
"""

import json
import re
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Wedge
from reportlab.graphics import renderPDF
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

DB_PATH       = Path(__file__).resolve().parents[2] / "data" / "database" / "coaching.db"
VAULT_PATH    = Path(__file__).resolve().parents[2] / "data" / "vault" / "Agente"
TEMPLATE_PATH = VAULT_PATH / "templates" / "certificate.md"
CERTS_PATH    = Path(__file__).resolve().parents[2] / "data" / "certificates"
CERTS_PATH.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("certification_manager")

# Paleta corporativa
COLOR_PRIMARY   = HexColor("#1A237E")   # azul marino
COLOR_SECONDARY = HexColor("#283593")
COLOR_ACCENT    = HexColor("#E8A838")   # dorado
COLOR_LIGHT     = HexColor("#E8EAF6")
COLOR_TEXT      = HexColor("#212121")
COLOR_MUTED     = HexColor("#757575")


# ---------------------------------------------------------------------------
# Helpers de DB
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Base de datos no encontrada: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _load_program_data(program_id: str) -> dict:
    """Carga todos los datos necesarios del programa en una sola función."""
    conn = _get_conn()
    try:
        row = conn.execute(
            """
            SELECT cp.id, cp.estado, cp.fecha_inicio, cp.fecha_fin_estimada,
                   cp.certificado_entregado,
                   c.nombre, c.email, c.rol, c.empresa,
                   co.nombre AS coach_nombre, co.especialidad AS coach_especialidad
            FROM coaching_programs cp
            JOIN coachees c ON c.id = cp.coachee_id
            LEFT JOIN coach_coachee_assignments cca
                   ON cca.coachee_id = c.id AND cca.estado = 'activa'
            LEFT JOIN coaches co ON co.id = cca.coach_id
            WHERE cp.id = ?
            """,
            (program_id,),
        ).fetchone()

        if not row:
            raise ValueError(f"Programa no encontrado: {program_id}")

        data = dict(row)

        # Sesiones completadas
        sesiones = conn.execute(
            """
            SELECT numero_sesion, fase_grow, mood_antes, mood_despues,
                   fecha_realizada, resumen, criterios_avance
            FROM sessions
            WHERE program_id = ? AND fecha_realizada IS NOT NULL
            ORDER BY numero_sesion
            """,
            (program_id,),
        ).fetchall()
        data["sesiones"] = [dict(s) for s in sesiones]
        data["sesiones_completadas"] = len(data["sesiones"])

        # Todas las sesiones (para IDs)
        all_sessions = conn.execute(
            "SELECT id, numero_sesion FROM sessions WHERE program_id = ? ORDER BY numero_sesion",
            (program_id,),
        ).fetchall()
        session_ids = [r["id"] for r in all_sessions]

        # Competencias (todas del programa)
        competencias = []
        if session_ids:
            placeholders = ",".join("?" * len(session_ids))
            competencias = conn.execute(
                f"""
                SELECT ct.competencia, ct.nivel_autoevaluado, ct.nivel_coach,
                       ct.evidencia, s.numero_sesion
                FROM competency_tracking ct
                JOIN sessions s ON s.id = ct.session_id
                WHERE ct.session_id IN ({placeholders})
                ORDER BY s.numero_sesion, ct.competencia
                """,
                session_ids,
            ).fetchall()
        data["competencias"] = [dict(c) for c in competencias]

        # Acciones
        acciones = []
        if session_ids:
            acciones = conn.execute(
                f"""
                SELECT ap.objetivo, ap.estado, ap.fecha_fin
                FROM action_plans ap
                WHERE ap.session_id IN ({placeholders})
                ORDER BY ap.fecha_fin
                """,
                session_ids,
            ).fetchall()
        data["acciones"] = [dict(a) for a in acciones]

        # Creencias trabajadas
        creencias = []
        if session_ids:
            creencias = conn.execute(
                f"""
                SELECT bt.creencia_limitante, bt.creencia_potenciadora_reemplazo, bt.estado
                FROM beliefs_tracker bt
                WHERE bt.session_id IN ({placeholders})
                ORDER BY bt.estado
                """,
                session_ids,
            ).fetchall()
        data["creencias"] = [dict(b) for b in creencias]

        # Feedback del coach (valoración media)
        feedback_row = conn.execute(
            """
            SELECT AVG(cf.valoracion_coach) AS avg_val,
                   COUNT(cf.id) AS n_feedback
            FROM coach_feedback cf
            JOIN coach_coachee_assignments cca ON cca.id = cf.assignment_id
            JOIN coaching_programs cp ON cp.coachee_id = cca.coachee_id
            WHERE cp.id = ?
            """,
            (program_id,),
        ).fetchone()
        data["valoracion_media_coach"] = (
            round(feedback_row["avg_val"], 1) if feedback_row and feedback_row["avg_val"] else None
        )
        data["n_feedback"] = feedback_row["n_feedback"] if feedback_row else 0

    finally:
        conn.close()

    return data


# ---------------------------------------------------------------------------
# 1. check_certification_eligibility
# ---------------------------------------------------------------------------

def check_certification_eligibility(program_id: str) -> tuple[bool, list[dict]]:
    """
    Verifica si un coachee cumple los criterios para recibir el certificado.

    Criterios evaluados:
    - 8 sesiones completadas (obligatorio)
    - Progreso ponderado >= 80% (obligatorio)
    - Evaluación media del coach >= 3/5 (recomendado, si aplica)
    - Satisfacción del coachee (mood_despues medio) >= 4/5 (recomendado)

    Returns:
        (elegible: bool, criterios: list[dict])
        Cada criterio tiene: {nombre, cumplido, valor, umbral, obligatorio}
    """
    data = _load_program_data(program_id)
    criterios: list[dict] = []

    # ── Criterio 1: Sesiones completadas ──────────────────────────────────
    sesiones_ok = data["sesiones_completadas"] >= 8
    criterios.append({
        "nombre":     "Sesiones completadas",
        "cumplido":   sesiones_ok,
        "valor":      data["sesiones_completadas"],
        "umbral":     8,
        "unidad":     "/ 8",
        "obligatorio": True,
    })

    # ── Criterio 2: Progreso ponderado ────────────────────────────────────
    progreso = _calc_weighted_progress(data)
    progreso_ok = progreso >= 80.0
    criterios.append({
        "nombre":     "Progreso ponderado",
        "cumplido":   progreso_ok,
        "valor":      round(progreso, 1),
        "umbral":     80,
        "unidad":     "%",
        "obligatorio": True,
    })

    # ── Criterio 3: Evaluación del coach ──────────────────────────────────
    val_coach = data.get("valoracion_media_coach")
    if val_coach is not None:
        coach_ok = val_coach >= 3.0
        criterios.append({
            "nombre":     "Evaluación del coach",
            "cumplido":   coach_ok,
            "valor":      val_coach,
            "umbral":     3.0,
            "unidad":     "/ 5",
            "obligatorio": False,
        })
    else:
        criterios.append({
            "nombre":     "Evaluación del coach",
            "cumplido":   True,   # sin coach → no bloquea
            "valor":      "N/A",
            "umbral":     3.0,
            "unidad":     "/ 5",
            "obligatorio": False,
            "nota":       "Sin coach asignado",
        })

    # ── Criterio 4: Satisfacción del coachee (mood_despues medio) ────────
    moods = [
        s["mood_despues"] for s in data["sesiones"]
        if s.get("mood_despues") is not None
    ]
    if moods:
        mood_avg = sum(moods) / len(moods)
        mood_ok  = mood_avg >= 4.0
        criterios.append({
            "nombre":     "Satisfacción media (mood)",
            "cumplido":   mood_ok,
            "valor":      round(mood_avg, 1),
            "umbral":     4.0,
            "unidad":     "/ 5",
            "obligatorio": False,
        })
    else:
        criterios.append({
            "nombre":     "Satisfacción media (mood)",
            "cumplido":   True,
            "valor":      "N/A",
            "umbral":     4.0,
            "unidad":     "/ 5",
            "obligatorio": False,
            "nota":       "Sin datos de mood",
        })

    # ── Decisión final ────────────────────────────────────────────────────
    # Solo los criterios obligatorios bloquean la certificación
    elegible = all(c["cumplido"] for c in criterios if c.get("obligatorio"))

    logger.info(
        "Elegibilidad program_id=%s → %s | criterios: %s",
        program_id,
        "ELEGIBLE" if elegible else "NO ELEGIBLE",
        [(c["nombre"], c["cumplido"]) for c in criterios],
    )
    return elegible, criterios


def _calc_weighted_progress(data: dict) -> float:
    """Progreso ponderado: 40% sesiones + 30% acciones + 15% creencias + 15% competencias."""
    # Sesiones
    p_sesiones = min(data["sesiones_completadas"] / 8, 1.0)

    # Acciones
    acciones = data.get("acciones", [])
    if acciones:
        completadas = sum(1 for a in acciones if a.get("estado") == "completada")
        p_acciones  = completadas / len(acciones)
    else:
        p_acciones = 0.0

    # Creencias (superadas vs total)
    creencias = data.get("creencias", [])
    if creencias:
        superadas   = sum(1 for b in creencias if b.get("estado") == "superada")
        p_creencias = superadas / len(creencias)
    else:
        p_creencias = 0.0

    # Competencias (nivel promedio autoevaluado, normalizado a 1)
    competencias = data.get("competencias", [])
    if competencias:
        niveles = [c["nivel_autoevaluado"] for c in competencias if c.get("nivel_autoevaluado")]
        p_competencias = (sum(niveles) / len(niveles) / 5) if niveles else 0.0
    else:
        p_competencias = 0.0

    progreso = (
        p_sesiones     * 0.40
        + p_acciones   * 0.30
        + p_creencias  * 0.15
        + p_competencias * 0.15
    ) * 100
    return round(progreso, 1)


# ---------------------------------------------------------------------------
# 2. generate_certificate
# ---------------------------------------------------------------------------

def generate_certificate(program_id: str) -> Path:
    """
    Genera el certificado PDF del programa.

    Lee la plantilla de data/vault/templates/certificate.md,
    completa los datos del coachee y genera un PDF con diseño formal.

    Returns:
        Path al archivo PDF generado.

    Raises:
        ValueError: Si el coachee no es elegible o el programa no existe.
    """
    elegible, criterios = check_certification_eligibility(program_id)
    if not elegible:
        pendientes = [c["nombre"] for c in criterios if not c["cumplido"] and c.get("obligatorio")]
        raise ValueError(
            f"El coachee no cumple los criterios obligatorios: {', '.join(pendientes)}"
        )

    data = _load_program_data(program_id)
    nombre        = data["nombre"]
    rol           = data.get("rol", "—")
    empresa       = data.get("empresa", "—")
    coach_nombre  = data.get("coach_nombre") or "Sistema de Coaching Virtual"
    fecha_emision = datetime.now().strftime("%d de %B de %Y")
    fecha_inicio  = data.get("fecha_inicio", "")[:10] if data.get("fecha_inicio") else "—"
    fecha_fin     = datetime.now().strftime("%Y-%m-%d")
    progreso      = _calc_weighted_progress(data)

    # Nombre de archivo
    nombre_slug = re.sub(r"[^\w\s-]", "", nombre.lower())
    nombre_slug = re.sub(r"[\s_]+", "-", nombre_slug.strip())
    fecha_str   = datetime.now().strftime("%Y%m%d")
    pdf_path    = CERTS_PATH / f"{nombre_slug}_{fecha_str}_certificado.pdf"

    # Competencias logradas (últimas evaluadas o listado de competencias del rol)
    competencias_data = data.get("competencias", [])
    if competencias_data:
        # Agrupar por competencia, tomar nivel más reciente
        comp_map: dict[str, dict] = {}
        for c in competencias_data:
            comp_map[c["competencia"]] = c
        competencias_logradas = list(comp_map.values())
    else:
        competencias_logradas = []

    # Logros: acciones completadas
    logros = [
        a["objetivo"] for a in data.get("acciones", [])
        if a.get("estado") == "completada"
    ]

    # Valoración
    val_coach = data.get("valoracion_media_coach")
    satisfaccion = str(val_coach) if val_coach else "—"

    # Generar PDF
    _render_certificate_pdf(
        pdf_path      = pdf_path,
        nombre        = nombre,
        rol           = rol,
        empresa       = empresa,
        coach_nombre  = coach_nombre,
        fecha_emision = fecha_emision,
        fecha_inicio  = fecha_inicio,
        fecha_fin     = fecha_fin,
        progreso      = progreso,
        satisfaccion  = satisfaccion,
        sesiones_completadas = data["sesiones_completadas"],
        competencias  = competencias_logradas,
        logros        = logros,
    )

    # Marcar en BD
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE coaching_programs SET certificado_entregado = 1, estado = 'completado', "
            "updated_at = datetime('now') WHERE id = ?",
            (program_id,),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info("Certificado generado: %s", pdf_path)
    return pdf_path


def _render_certificate_pdf(
    pdf_path: Path,
    nombre: str,
    rol: str,
    empresa: str,
    coach_nombre: str,
    fecha_emision: str,
    fecha_inicio: str,
    fecha_fin: str,
    progreso: float,
    satisfaccion: str,
    sesiones_completadas: int,
    competencias: list[dict],
    logros: list[str],
) -> None:
    """Renderiza el certificado como PDF con diseño formal usando ReportLab."""

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.0 * cm,
        title=f"Certificado — {nombre}",
        author="Sistema de Coaching Virtual",
    )

    styles = getSampleStyleSheet()
    story: list = []

    # ── Estilos personalizados ─────────────────────────────────────────
    s_title = ParagraphStyle(
        "CertTitle",
        parent=styles["Title"],
        fontSize=28,
        textColor=COLOR_PRIMARY,
        spaceAfter=6,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    s_subtitle = ParagraphStyle(
        "CertSubtitle",
        parent=styles["Normal"],
        fontSize=13,
        textColor=COLOR_SECONDARY,
        spaceAfter=4,
        alignment=TA_CENTER,
        fontName="Helvetica",
    )
    s_name = ParagraphStyle(
        "CertName",
        parent=styles["Normal"],
        fontSize=24,
        textColor=COLOR_ACCENT,
        spaceBefore=8,
        spaceAfter=8,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    s_body = ParagraphStyle(
        "CertBody",
        parent=styles["Normal"],
        fontSize=11,
        textColor=COLOR_TEXT,
        spaceAfter=4,
        alignment=TA_CENTER,
        leading=16,
    )
    s_section = ParagraphStyle(
        "CertSection",
        parent=styles["Normal"],
        fontSize=12,
        textColor=COLOR_PRIMARY,
        spaceBefore=10,
        spaceAfter=4,
        fontName="Helvetica-Bold",
        alignment=TA_LEFT,
    )
    s_item = ParagraphStyle(
        "CertItem",
        parent=styles["Normal"],
        fontSize=10,
        textColor=COLOR_TEXT,
        spaceAfter=2,
        leftIndent=12,
        alignment=TA_LEFT,
    )
    s_footer = ParagraphStyle(
        "CertFooter",
        parent=styles["Normal"],
        fontSize=9,
        textColor=COLOR_MUTED,
        alignment=TA_CENTER,
    )

    # ── Encabezado ────────────────────────────────────────────────────
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("CERTIFICADO DE COACHING EJECUTIVO", s_title))
    story.append(Paragraph("Programa de Desarrollo Profesional · Modelo GROW", s_subtitle))
    story.append(HRFlowable(width="100%", thickness=3, color=COLOR_ACCENT, spaceAfter=10))

    # ── Texto principal ───────────────────────────────────────────────
    story.append(Paragraph("Se certifica que", s_body))
    story.append(Paragraph(nombre.upper(), s_name))
    story.append(Paragraph(
        f"en su rol de <b>{rol}</b> en <b>{empresa}</b>,<br/>"
        f"ha completado satisfactoriamente el programa de<br/>"
        f"<b>Coaching Ejecutivo Virtual</b> de 8 sesiones.",
        s_body,
    ))
    story.append(Spacer(1, 0.5 * cm))

    # ── Tabla de métricas ────────────────────────────────────────────
    metrics_data = [
        ["Período", f"{fecha_inicio} — {fecha_fin}"],
        ["Sesiones completadas", f"{sesiones_completadas} / 8"],
        ["Progreso ponderado", f"{progreso}%"],
        ["Satisfacción", f"{satisfaccion} / 5"],
        ["Coach", coach_nombre],
    ]
    metrics_table = Table(metrics_data, colWidths=[5 * cm, 10 * cm])
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (0, -1), COLOR_LIGHT),
        ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",    (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",    (0, 0), (-1, -1), 10),
        ("TEXTCOLOR",   (0, 0), (0, -1), COLOR_PRIMARY),
        ("TEXTCOLOR",   (1, 0), (1, -1), COLOR_TEXT),
        ("ALIGN",       (0, 0), (0, -1), "RIGHT"),
        ("ALIGN",       (1, 0), (1, -1), "LEFT"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [white, HexColor("#F5F5F5")]),
        ("GRID",        (0, 0), (-1, -1), 0.5, HexColor("#BDBDBD")),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(metrics_table)
    story.append(Spacer(1, 0.5 * cm))

    # ── Competencias ─────────────────────────────────────────────────
    if competencias:
        story.append(HRFlowable(width="100%", thickness=1, color=COLOR_LIGHT, spaceAfter=4))
        story.append(Paragraph("Competencias desarrolladas", s_section))
        comp_rows = [["Competencia", "Nivel (1-5)", "Evidencia"]]
        for c in competencias:
            nivel = c.get("nivel_autoevaluado") or c.get("nivel_coach") or "—"
            evidencia = (c.get("evidencia") or "")[:60]
            comp_rows.append([
                c["competencia"].replace("_", " ").title(),
                str(nivel),
                evidencia,
            ])
        comp_table = Table(comp_rows, colWidths=[6 * cm, 3 * cm, 6 * cm])
        comp_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), COLOR_PRIMARY),
            ("TEXTCOLOR",    (0, 0), (-1, 0), white),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE",     (0, 0), (-1, -1), 9),
            ("ALIGN",        (1, 0), (1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, COLOR_LIGHT]),
            ("GRID",         (0, 0), (-1, -1), 0.5, HexColor("#BDBDBD")),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ]))
        story.append(comp_table)
        story.append(Spacer(1, 0.3 * cm))

    # ── Logros ───────────────────────────────────────────────────────
    if logros:
        story.append(HRFlowable(width="100%", thickness=1, color=COLOR_LIGHT, spaceAfter=4))
        story.append(Paragraph("Logros destacados", s_section))
        for logro in logros[:5]:   # máx 5 para no desbordar página
            story.append(Paragraph(f"• {logro}", s_item))
        story.append(Spacer(1, 0.3 * cm))

    # ── Pie de página ────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=2, color=COLOR_ACCENT, spaceBefore=10))
    story.append(Paragraph(
        f"Emitido el {fecha_emision} · Sistema de Coaching Virtual",
        s_footer,
    ))

    doc.build(story)


# ---------------------------------------------------------------------------
# 3. generate_progress_report
# ---------------------------------------------------------------------------

def generate_progress_report(program_id: str) -> tuple[Path, Path]:
    """
    Genera el reporte de progreso final en PDF y en Obsidian (Markdown).

    Incluye:
    - Evolución de competencias (tabla + gráfico de barras)
    - Logros destacados
    - Recomendaciones post-programa

    Returns:
        (pdf_path, md_path) — rutas de ambos archivos generados.
    """
    data = _load_program_data(program_id)
    nombre       = data["nombre"]
    rol          = data.get("rol", "—")
    empresa      = data.get("empresa", "—")
    fecha_str    = datetime.now().strftime("%Y%m%d")

    nombre_slug = re.sub(r"[^\w\s-]", "", nombre.lower())
    nombre_slug = re.sub(r"[\s_]+", "-", nombre_slug.strip()) or "coachee"

    pdf_path = CERTS_PATH / f"{nombre_slug}_{fecha_str}_reporte.pdf"
    md_path  = VAULT_PATH / "coachees" / nombre_slug / "reporte-final.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)

    progreso  = _calc_weighted_progress(data)
    recomendaciones = _build_recommendations(data)
    logros    = [a["objetivo"] for a in data.get("acciones", []) if a.get("estado") == "completada"]

    # Mapa de competencias: nombre → (sesion_inicial, sesion_final)
    comp_evolucion = _build_competency_evolution(data)

    # ── PDF ──────────────────────────────────────────────────────────
    _render_report_pdf(
        pdf_path      = pdf_path,
        nombre        = nombre,
        rol           = rol,
        empresa       = empresa,
        progreso      = progreso,
        data          = data,
        comp_evolucion = comp_evolucion,
        logros        = logros,
        recomendaciones = recomendaciones,
    )

    # ── Markdown / Obsidian ──────────────────────────────────────────
    _render_report_md(
        md_path        = md_path,
        nombre         = nombre,
        rol            = rol,
        empresa        = empresa,
        progreso       = progreso,
        data           = data,
        comp_evolucion = comp_evolucion,
        logros         = logros,
        recomendaciones = recomendaciones,
    )

    logger.info("Reporte generado — PDF: %s | MD: %s", pdf_path, md_path)
    return pdf_path, md_path


def _build_competency_evolution(data: dict) -> dict[str, dict]:
    """
    Agrupa las evaluaciones de competencias por nombre y extrae
    nivel inicial (primera sesión) y final (última sesión).
    """
    by_comp: dict[str, list] = {}
    for c in data.get("competencias", []):
        name = c["competencia"]
        by_comp.setdefault(name, []).append(c)

    evolution: dict[str, dict] = {}
    for name, registros in by_comp.items():
        # Ordenar por número de sesión
        registros.sort(key=lambda x: x.get("numero_sesion", 0))
        nivel_inicial = registros[0].get("nivel_autoevaluado") or registros[0].get("nivel_coach")
        nivel_final   = registros[-1].get("nivel_autoevaluado") or registros[-1].get("nivel_coach")
        evolution[name] = {
            "inicial": nivel_inicial,
            "final":   nivel_final,
            "delta":   (nivel_final - nivel_inicial) if (nivel_inicial and nivel_final) else None,
        }
    return evolution


def _build_recommendations(data: dict) -> list[str]:
    """Genera recomendaciones post-programa basadas en los datos del coachee."""
    recs: list[str] = []

    # Acciones pendientes → continuar compromisos
    pendientes = [a for a in data.get("acciones", []) if a.get("estado") == "pendiente"]
    if pendientes:
        recs.append(
            f"Completar las {len(pendientes)} acciones comprometidas pendientes "
            f"para consolidar el cambio iniciado en el programa."
        )

    # Creencias no superadas
    creencias_abiertas = [
        b for b in data.get("creencias", []) if b.get("estado") != "superada"
    ]
    if creencias_abiertas:
        recs.append(
            f"Continuar trabajando en {len(creencias_abiertas)} creencia(s) limitante(s) "
            f"identificadas pero aún no completamente superadas."
        )

    # Competencias con nivel bajo
    for name, ev in _build_competency_evolution(data).items():
        if ev.get("final") and ev["final"] <= 2:
            recs.append(
                f"Reforzar la competencia '{name.replace('_', ' ')}' "
                f"(nivel actual: {ev['final']}/5) con prácticas específicas."
            )

    # Mood final
    moods_final = [s["mood_despues"] for s in data.get("sesiones", []) if s.get("mood_despues")]
    if moods_final and moods_final[-1] < 4:
        recs.append(
            "Considerar un programa de seguimiento o sesiones de mantenimiento "
            "para consolidar el bienestar alcanzado."
        )

    if not recs:
        recs.append(
            "Mantener los hábitos de reflexión y revisión periódica de objetivos "
            "desarrollados durante el programa."
        )
        recs.append(
            "Compartir aprendizajes con el equipo para multiplicar el impacto del proceso."
        )

    return recs


def _render_report_pdf(
    pdf_path: Path,
    nombre: str,
    rol: str,
    empresa: str,
    progreso: float,
    data: dict,
    comp_evolucion: dict,
    logros: list[str],
    recomendaciones: list[str],
) -> None:
    """Renderiza el reporte de progreso final como PDF."""

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.0 * cm,
        title=f"Reporte Final — {nombre}",
    )

    styles = getSampleStyleSheet()
    story: list = []

    s_h1 = ParagraphStyle("RH1", parent=styles["Heading1"],
                           textColor=COLOR_PRIMARY, fontSize=18, spaceAfter=6)
    s_h2 = ParagraphStyle("RH2", parent=styles["Heading2"],
                           textColor=COLOR_SECONDARY, fontSize=13, spaceBefore=10, spaceAfter=4)
    s_body = ParagraphStyle("RBody", parent=styles["Normal"],
                             fontSize=10, textColor=COLOR_TEXT, spaceAfter=3, leading=14)
    s_item = ParagraphStyle("RItem", parent=styles["Normal"],
                             fontSize=10, textColor=COLOR_TEXT, spaceAfter=2,
                             leftIndent=14)
    s_caption = ParagraphStyle("RCaption", parent=styles["Normal"],
                                fontSize=8, textColor=COLOR_MUTED, alignment=TA_CENTER)

    # Encabezado
    story.append(Paragraph(f"Reporte de Progreso Final", s_h1))
    story.append(Paragraph(f"{nombre} · {rol} · {empresa}", s_body))
    story.append(Paragraph(
        f"Fecha: {datetime.now().strftime('%d/%m/%Y')} &nbsp;|&nbsp; "
        f"Sesiones: {data['sesiones_completadas']}/8 &nbsp;|&nbsp; "
        f"Progreso: {progreso}%",
        s_body,
    ))
    story.append(HRFlowable(width="100%", thickness=2, color=COLOR_ACCENT, spaceAfter=8))

    # Evolución de estado emocional (tabla de moods)
    sesiones = data.get("sesiones", [])
    mood_rows = [s for s in sesiones if s.get("mood_antes") or s.get("mood_despues")]
    if mood_rows:
        story.append(Paragraph("Evolución del Estado Emocional", s_h2))
        table_data = [["Sesión", "Fase GROW", "Mood antes", "Mood después", "Delta"]]
        for s in mood_rows:
            ma = s.get("mood_antes", "—")
            md_ = s.get("mood_despues", "—")
            delta = (md_ - ma) if isinstance(ma, int) and isinstance(md_, int) else "—"
            delta_str = f"+{delta}" if isinstance(delta, int) and delta > 0 else str(delta)
            table_data.append([
                str(s["numero_sesion"]),
                (s.get("fase_grow") or "").capitalize(),
                f"{ma}/5" if isinstance(ma, int) else ma,
                f"{md_}/5" if isinstance(md_, int) else md_,
                delta_str,
            ])
        mood_table = Table(table_data, colWidths=[2*cm, 3.5*cm, 3*cm, 3.5*cm, 2.5*cm])
        mood_table.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), COLOR_PRIMARY),
            ("TEXTCOLOR",    (0, 0), (-1, 0), white),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 9),
            ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, COLOR_LIGHT]),
            ("GRID",         (0, 0), (-1, -1), 0.5, HexColor("#BDBDBD")),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(mood_table)
        story.append(Spacer(1, 0.3 * cm))

    # Evolución de competencias
    if comp_evolucion:
        story.append(Paragraph("Evolución de Competencias", s_h2))
        comp_table_data = [["Competencia", "Nivel inicial", "Nivel final", "Avance"]]
        for comp_name, ev in comp_evolucion.items():
            ini   = ev.get("inicial") or "—"
            fin   = ev.get("final")   or "—"
            delta = ev.get("delta")
            if delta is not None:
                avance = f"+{delta}" if delta > 0 else str(delta)
            else:
                avance = "—"
            comp_table_data.append([
                comp_name.replace("_", " ").title(),
                f"{ini}/5" if isinstance(ini, int) else ini,
                f"{fin}/5" if isinstance(fin, int) else fin,
                avance,
            ])
        ct = Table(comp_table_data, colWidths=[7*cm, 3*cm, 3*cm, 2.5*cm])
        ct.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), COLOR_SECONDARY),
            ("TEXTCOLOR",    (0, 0), (-1, 0), white),
            ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",     (0, 0), (-1, -1), 9),
            ("ALIGN",        (1, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, COLOR_LIGHT]),
            ("GRID",         (0, 0), (-1, -1), 0.5, HexColor("#BDBDBD")),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
        ]))
        story.append(ct)
        story.append(Spacer(1, 0.3 * cm))

    # Logros
    if logros:
        story.append(Paragraph("Logros Destacados", s_h2))
        for logro in logros:
            story.append(Paragraph(f"✓ {logro}", s_item))
        story.append(Spacer(1, 0.3 * cm))

    # Recomendaciones
    story.append(Paragraph("Recomendaciones Post-Programa", s_h2))
    for i, rec in enumerate(recomendaciones, 1):
        story.append(Paragraph(f"{i}. {rec}", s_item))

    # Footer
    story.append(HRFlowable(width="100%", thickness=1, color=COLOR_ACCENT, spaceBefore=12))
    story.append(Paragraph(
        f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
        "Sistema de Coaching Virtual",
        s_caption,
    ))

    doc.build(story)


def _render_report_md(
    md_path: Path,
    nombre: str,
    rol: str,
    empresa: str,
    progreso: float,
    data: dict,
    comp_evolucion: dict,
    logros: list[str],
    recomendaciones: list[str],
) -> None:
    """Guarda el reporte de progreso como markdown en el vault de Obsidian."""

    sesiones = data.get("sesiones", [])
    fecha = datetime.now().strftime("%Y-%m-%d")

    # Sección de moods
    mood_md = ""
    for s in sesiones:
        if s.get("mood_antes") or s.get("mood_despues"):
            ma  = s.get("mood_antes", "—")
            md_ = s.get("mood_despues", "—")
            delta = (md_ - ma) if isinstance(ma, int) and isinstance(md_, int) else "—"
            mood_md += f"| {s['numero_sesion']} | {(s.get('fase_grow') or '').capitalize()} | {ma}/5 | {md_}/5 | {delta} |\n"

    if mood_md:
        mood_section = (
            "## Evolución del Estado Emocional\n\n"
            "| Sesión | Fase | Mood antes | Mood después | Delta |\n"
            "|--------|------|-----------|--------------|-------|\n"
            + mood_md
        )
    else:
        mood_section = "## Evolución del Estado Emocional\n\n_Sin datos de mood registrados._\n"

    # Sección de competencias
    comp_md = ""
    for name, ev in comp_evolucion.items():
        ini = ev.get("inicial") or "—"
        fin = ev.get("final") or "—"
        delta = ev.get("delta")
        avance = f"+{delta}" if delta and delta > 0 else str(delta) if delta is not None else "—"
        comp_md += f"| {name.replace('_', ' ').title()} | {ini}/5 | {fin}/5 | {avance} |\n"

    if comp_md:
        comp_section = (
            "## Evolución de Competencias\n\n"
            "| Competencia | Nivel inicial | Nivel final | Avance |\n"
            "|-------------|--------------|------------|--------|\n"
            + comp_md
        )
    else:
        comp_section = "## Evolución de Competencias\n\n_Sin competencias registradas._\n"

    # Logros
    logros_md = "\n".join(f"- ✓ {l}" for l in logros) if logros else "_Sin logros registrados._"

    # Recomendaciones
    recs_md = "\n".join(f"{i}. {r}" for i, r in enumerate(recomendaciones, 1))

    content = f"""# Reporte de Progreso Final — {nombre}

**Rol:** {rol}
**Empresa:** {empresa}
**Fecha:** {fecha}
**Sesiones completadas:** {data['sesiones_completadas']}/8
**Progreso ponderado:** {progreso}%

---

{mood_section}

---

{comp_section}

---

## Logros Destacados

{logros_md}

---

## Recomendaciones Post-Programa

{recs_md}

---

_Generado automáticamente por el Sistema de Coaching Virtual_
"""
    md_path.write_text(content, encoding="utf-8")
    logger.info("Reporte Markdown guardado: %s", md_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    def _usage():
        print(
            "Uso:\n"
            "  python certification_manager.py elegibilidad <program_id>\n"
            "  python certification_manager.py certificado  <program_id>\n"
            "  python certification_manager.py reporte      <program_id>\n"
        )
        sys.exit(1)

    if len(sys.argv) < 3:
        _usage()

    cmd, pid = sys.argv[1], sys.argv[2]

    if cmd == "elegibilidad":
        elegible, criterios = check_certification_eligibility(pid)
        print(f"\n{'✅ ELEGIBLE' if elegible else '❌ NO ELEGIBLE'}\n")
        for c in criterios:
            icon = "✅" if c["cumplido"] else "❌"
            oblig = " (obligatorio)" if c.get("obligatorio") else ""
            nota  = f" — {c['nota']}" if c.get("nota") else ""
            print(f"  {icon} {c['nombre']}: {c['valor']}{c['unidad']}{oblig}{nota}")

    elif cmd == "certificado":
        try:
            path = generate_certificate(pid)
            print(f"\n✅ Certificado generado:\n  {path}")
        except ValueError as e:
            print(f"\n❌ {e}")

    elif cmd == "reporte":
        pdf, md = generate_progress_report(pid)
        print(f"\n✅ Reporte generado:\n  PDF: {pdf}\n  MD:  {md}")

    else:
        _usage()
