"""
coaching_agent.py
Agente principal de coaching ejecutivo. Gestiona el flujo de sesiones,
herramientas disponibles por sesión y persistencia de respuestas.
Incluye memoria contextual: carga historial de sesiones previas, acciones
comprometidas y patrones detectados al iniciar cada sesión.
"""

import json
import re
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "database" / "coaching.db"
VAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "vault" / "Agente" / "coachees"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("coaching_agent")

# ---------------------------------------------------------------------------
# Mapa de sesiones: fase GROW, bienvenida y herramientas disponibles
# ---------------------------------------------------------------------------

SESSION_CONFIG: dict[int, dict] = {
    1: {
        "fase_grow": "goal",
        "welcome": (
            "Bienvenido a la sesión 1: Diagnóstico inicial. "
            "Hoy exploraremos tu situación actual y definiremos hacia dónde quieres llegar."
        ),
        "tools": ["evaluate_wheel_of_life", "set_smart_goal"],
    },
    2: {
        "fase_grow": "reality",
        "welcome": (
            "Sesión 2: Vamos a explorar tu realidad actual. "
            "¿Qué está ocurriendo en este momento en las áreas que más te importan?"
        ),
        "tools": ["evaluate_wheel_of_life"],
    },
    3: {
        "fase_grow": "reality",
        "welcome": (
            "Sesión 3: Identifiquemos creencias limitantes. "
            "Las creencias que nos frenan suelen ser invisibles — hoy las vamos a nombrar."
        ),
        "tools": ["track_belief"],
    },
    4: {
        "fase_grow": "options",
        "welcome": (
            "Sesión 4: Exploremos opciones y recursos. "
            "¿Qué caminos existen que aún no has considerado?"
        ),
        "tools": ["track_belief"],
    },
    5: {
        "fase_grow": "options",
        "welcome": (
            "Sesión 5: Diseñemos tu plan de acción. "
            "Es momento de convertir las opciones en compromisos concretos."
        ),
        "tools": ["create_action"],
    },
    6: {
        "fase_grow": "will",
        "welcome": (
            "Sesión 6: Revisemos avances y ajustemos. "
            "¿Qué has logrado desde la última sesión? ¿Qué necesita ajustarse?"
        ),
        "tools": ["create_action"],
    },
    7: {
        "fase_grow": "will",
        "welcome": (
            "Sesión 7: Consolidemos hábitos. "
            "Los hábitos son los que sostienen el cambio cuando termina el proceso."
        ),
        "tools": ["create_action"],
    },
    8: {
        "fase_grow": "will",
        "welcome": (
            "Sesión 8: Cierre y evaluación final. "
            "Hoy celebramos el camino recorrido y proyectamos los próximos pasos."
        ),
        "tools": ["evaluate_wheel_of_life", "generate_certificate"],
    },
}

# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class CoachingAgent:
    """
    Agente de coaching ejecutivo para un programa específico.

    Attributes:
        program_id      (str):  ID del programa de coaching activo.
        coachee         (dict): Datos del coachee cargados desde la BD.
        current_session (int | None): Número de sesión activa (1–8).
        context_memory  (dict): Historial contextual cargado al iniciar cada sesión.
    """

    def __init__(self, program_id: str) -> None:
        self.program_id      = program_id
        self.coachee: dict   = {}
        self.coach: dict     = {}   # datos del coach asignado (puede estar vacío)
        self.current_session: int | None = None
        self._session_db_id: str | None  = None   # UUID del registro en sessions
        self._assignment_id: str | None  = None   # UUID de coach_coachee_assignments
        self.context_memory: dict        = {}      # historial contextual cargado al iniciar sesión
        self.load_coachee_data()

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        if not DB_PATH.exists():
            raise FileNotFoundError(f"Base de datos no encontrada: {DB_PATH}")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # Carga de datos
    # ------------------------------------------------------------------

    def load_coachee_data(self) -> None:
        """Carga datos del coachee, programa y coach asignado desde la base de datos."""
        logger.info("Cargando datos para program_id=%s", self.program_id)
        conn = self._get_connection()
        try:
            row = conn.execute(
                """
                SELECT c.id, c.nombre, c.email, c.rol, c.empresa, c.idioma_preferido,
                       cp.estado, cp.fecha_inicio, cp.fecha_fin_estimada,
                       co.id          AS coach_id,
                       co.nombre      AS coach_nombre,
                       co.especialidad AS coach_especialidad,
                       co.nivel       AS coach_nivel,
                       cca.id         AS assignment_id
                FROM coaching_programs cp
                JOIN coachees c ON c.id = cp.coachee_id
                LEFT JOIN coach_coachee_assignments cca
                       ON cca.coachee_id = c.id AND cca.estado = 'activa'
                LEFT JOIN coaches co ON co.id = cca.coach_id
                WHERE cp.id = ?
                """,
                (self.program_id,),
            ).fetchone()

            if not row:
                raise ValueError(f"No se encontró el programa: {self.program_id}")

            data = dict(row)

            self.coachee = {k: data[k] for k in (
                "id", "nombre", "email", "rol", "empresa", "idioma_preferido",
                "estado", "fecha_inicio", "fecha_fin_estimada"
            )}
            self._assignment_id = data.get("assignment_id")
            if data.get("coach_id"):
                self.coach = {
                    "id":          data["coach_id"],
                    "nombre":      data["coach_nombre"],
                    "especialidad": data["coach_especialidad"],
                    "nivel":       data["coach_nivel"],
                }
                logger.info(
                    "Coach asignado: %s (especialidad=%s, nivel=%s)",
                    self.coach["nombre"],
                    self.coach["especialidad"],
                    self.coach["nivel"],
                )
            else:
                self.coach = {}
                logger.info("Sin coach asignado para program_id=%s", self.program_id)

            logger.info(
                "Coachee cargado: %s <%s> | programa estado=%s",
                self.coachee["nombre"],
                self.coachee["email"],
                self.coachee["estado"],
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Memoria contextual
    # ------------------------------------------------------------------

    def load_session_context(self) -> dict:
        """
        Carga el contexto histórico del coachee para la sesión actual:
        - Resúmenes de sesiones anteriores (criterios_avance JSON si existe, resumen si no)
        - Acciones comprometidas pendientes
        - Creencias trabajadas durante el proceso

        Returns:
            dict con claves: sesiones_previas, acciones_pendientes, creencias
        """
        if self.current_session is None:
            return {}

        context: dict = {
            "sesiones_previas": [],
            "acciones_pendientes": [],
            "creencias": [],
        }

        conn = self._get_connection()
        try:
            # 1. Sesiones anteriores completadas con sus resúmenes
            rows = conn.execute(
                """
                SELECT numero_sesion, fase_grow, resumen, criterios_avance,
                       mood_antes, mood_despues, fecha_realizada
                FROM sessions
                WHERE program_id = ? AND numero_sesion < ?
                  AND fecha_realizada IS NOT NULL
                ORDER BY numero_sesion
                """,
                (self.program_id, self.current_session),
            ).fetchall()

            for row in rows:
                session_data = dict(row)
                if session_data.get("criterios_avance"):
                    try:
                        session_data["summary"] = json.loads(session_data["criterios_avance"])
                    except (json.JSONDecodeError, TypeError):
                        session_data["summary"] = {}
                else:
                    session_data["summary"] = {}
                context["sesiones_previas"].append(session_data)

            # 2. Acciones pendientes del programa
            rows = conn.execute(
                """
                SELECT ap.objetivo, ap.acciones, ap.fecha_fin, ap.estado
                FROM action_plans ap
                JOIN sessions s ON s.id = ap.session_id
                WHERE s.program_id = ? AND ap.estado = 'pendiente'
                ORDER BY ap.fecha_fin
                """,
                (self.program_id,),
            ).fetchall()

            for row in rows:
                action = dict(row)
                try:
                    action["acciones"] = json.loads(action["acciones"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    action["acciones"] = []
                context["acciones_pendientes"].append(action)

            # 3. Creencias trabajadas en el proceso
            rows = conn.execute(
                """
                SELECT bt.creencia_limitante, bt.creencia_potenciadora_reemplazo, bt.estado
                FROM beliefs_tracker bt
                JOIN sessions s ON s.id = bt.session_id
                WHERE s.program_id = ?
                ORDER BY bt.created_at
                """,
                (self.program_id,),
            ).fetchall()

            for row in rows:
                context["creencias"].append(dict(row))

        finally:
            conn.close()

        self.context_memory = context
        logger.info(
            "Contexto cargado — %d sesiones previas, %d acciones pendientes, %d creencias",
            len(context["sesiones_previas"]),
            len(context["acciones_pendientes"]),
            len(context["creencias"]),
        )
        return context

    def get_context_reference(self, session_num: int) -> str:
        """
        Genera una referencia contextual a una sesión anterior para usar
        en la conversación: "En tu sesión 2 mencionaste que...".

        Args:
            session_num: Número de sesión a referenciar.

        Returns:
            Texto con la referencia o cadena vacía si no hay datos.
        """
        sesiones = self.context_memory.get("sesiones_previas", [])
        session = next(
            (s for s in sesiones if s["numero_sesion"] == session_num), None
        )
        if not session:
            return ""

        fase = (session.get("fase_grow") or "").capitalize()
        summary = session.get("summary", {})

        # Preferir insights del resumen estructurado
        if summary.get("insights"):
            insights = summary["insights"]
            if isinstance(insights, list) and insights:
                texto = insights[0][:180]
                return f"En tu sesión {session_num} ({fase}) mencionaste: \"{texto}\"."

        # Fallback: usar resumen de texto libre
        resumen = (session.get("resumen") or "").strip()
        if resumen:
            # Strip timestamp prefix [2024-01-01T10:00:00]
            resumen_clean = re.sub(r"^\[[\d\-T:]+\]\s*\[OBJETIVO SMART\]\s*", "", resumen)
            resumen_short = resumen_clean[:150].strip()
            if resumen_short:
                return f"En tu sesión {session_num} ({fase}) estableciste: \"{resumen_short}\"."

        return f"En tu sesión {session_num} ({fase}) trabajamos en {fase.lower()}."

    # ------------------------------------------------------------------
    # Sesiones
    # ------------------------------------------------------------------

    def start_session(self, session_number: int) -> str:
        """
        Inicia una sesión, registra o recupera su entrada en la BD,
        carga el contexto histórico y devuelve el mensaje de bienvenida.
        """
        if session_number not in SESSION_CONFIG:
            logger.error("Número de sesión inválido: %d", session_number)
            return "Sesión no válida. Las sesiones van de 1 a 8."

        self.current_session = session_number
        config = SESSION_CONFIG[session_number]

        conn = self._get_connection()
        try:
            existing = conn.execute(
                "SELECT id FROM sessions WHERE program_id = ? AND numero_sesion = ?",
                (self.program_id, session_number),
            ).fetchone()

            if existing:
                self._session_db_id = existing["id"]
                logger.info(
                    "Sesión %d ya existente (id=%s), continuando",
                    session_number,
                    self._session_db_id,
                )
            else:
                conn.execute(
                    """
                    INSERT INTO sessions (program_id, numero_sesion, fase_grow, fecha_programada)
                    VALUES (?, ?, ?, datetime('now'))
                    """,
                    (self.program_id, session_number, config["fase_grow"]),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT id FROM sessions WHERE program_id = ? AND numero_sesion = ?",
                    (self.program_id, session_number),
                ).fetchone()
                self._session_db_id = row["id"]
                logger.info(
                    "Sesión %d creada (id=%s, fase=%s)",
                    session_number,
                    self._session_db_id,
                    config["fase_grow"],
                )
        finally:
            conn.close()

        # Cargar contexto histórico antes de generar la bienvenida
        self.load_session_context()

        return self._get_session_welcome()

    def _get_session_welcome(self) -> str:
        """Devuelve bienvenida personalizada con nombre, énfasis del coach y contexto histórico."""
        if self.current_session not in SESSION_CONFIG:
            return "Sesión no válida."

        base   = SESSION_CONFIG[self.current_session]["welcome"]
        nombre = self.coachee.get("nombre", "")
        msg    = f"Hola, {nombre}. {base}" if nombre else base

        # Énfasis según especialidad del coach
        enfasis = self.get_specialty_emphasis(SESSION_CONFIG[self.current_session]["fase_grow"])
        if enfasis:
            msg += f"\n\n💡 *{enfasis}*"

        # Contexto histórico para sesiones 2+
        if self.current_session > 1 and self.context_memory:
            context_parts: list[str] = []

            # Referencia a la sesión anterior
            sesiones = self.context_memory.get("sesiones_previas", [])
            if sesiones:
                last_session = sesiones[-1]
                ref = self.get_context_reference(last_session["numero_sesion"])
                if ref:
                    context_parts.append(ref)

            # Acciones pendientes
            acciones = self.context_memory.get("acciones_pendientes", [])
            if acciones:
                n = len(acciones)
                s = "s" if n > 1 else ""
                context_parts.append(
                    f"Tienes {n} acción{s} pendiente{s} de sesiones anteriores."
                )

            # Creencias trabajadas (mencionarlo si hay alguna no resuelta)
            creencias = self.context_memory.get("creencias", [])
            abiertas = [c for c in creencias if c.get("estado") != "superada"]
            if abiertas:
                n = len(abiertas)
                s = "s" if n > 1 else ""
                context_parts.append(
                    f"Seguimos trabajando en {n} creencia{s} limitante{s} identificada{s}."
                )

            if context_parts:
                msg += "\n\n📌 *Contexto:* " + " ".join(context_parts)

        return msg

    # Énfasis por especialidad y fase GROW
    _SPECIALTY_EMPHASIS: dict[str, dict[str, str]] = {
        "liderazgo": {
            "goal":    "Enfoque en liderazgo: ¿Cómo impacta este objetivo en tu equipo y en tu capacidad de delegar?",
            "reality": "Enfoque en liderazgo: Reflexiona sobre cómo tu estilo de liderazgo influye en la situación actual.",
            "options": "Enfoque en liderazgo: ¿Qué opciones empoderan a tu equipo al mismo tiempo que avanzas en tu objetivo?",
            "will":    "Enfoque en liderazgo: ¿Cómo comunicarás tus compromisos a tu equipo para generar alineación?",
        },
        "productividad": {
            "goal":    "Enfoque en productividad: Define el resultado con métricas claras y un plazo concreto.",
            "reality": "Enfoque en productividad: Identifica los bloqueadores de tiempo y energía que más te frenan.",
            "options": "Enfoque en productividad: Prioriza las opciones por impacto vs. esfuerzo.",
            "will":    "Enfoque en productividad: Establece un sistema de seguimiento para no perder el hilo.",
        },
        "comunicacion": {
            "goal":    "Enfoque en comunicación: ¿Cómo influye este objetivo en la forma en que te relacionas con otros?",
            "reality": "Enfoque en comunicación: ¿Cómo están percibiendo los demás tu situación actual?",
            "options": "Enfoque en comunicación: ¿Qué conversaciones pendientes desbloquearían el avance?",
            "will":    "Enfoque en comunicación: ¿Cómo y a quién comunicarás tus compromisos?",
        },
    }

    def get_specialty_emphasis(self, fase: str) -> str:
        """
        Devuelve el énfasis temático del coach para la fase GROW indicada.
        Retorna cadena vacía si no hay coach asignado o la especialidad no está mapeada.
        """
        especialidad = self.coach.get("especialidad", "")
        return self._SPECIALTY_EMPHASIS.get(especialidad, {}).get(fase, "")

    # ------------------------------------------------------------------
    # Procesar respuestas
    # ------------------------------------------------------------------

    def process_response(self, user_input: str) -> str:
        """
        Procesa la respuesta del coachee.
        Guarda el input y devuelve acuse de recibo.
        Punto de extensión para lógica conversacional futura.
        """
        if not user_input or not user_input.strip():
            return "No he recibido ningún texto. ¿Quieres compartir algo?"

        self.save_response(user_input)
        logger.info(
            "Respuesta procesada — sesión %s, %d caracteres",
            self.current_session,
            len(user_input),
        )
        return f"He recibido: {user_input}"

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    def save_response(self, user_input: str, campo: str = "notas_agente") -> None:
        """
        Persiste la respuesta del coachee en el campo indicado de la sesión activa.

        Args:
            user_input: Texto del coachee.
            campo:      Columna de `sessions` donde se guarda ('notas_agente' o 'resumen').
        """
        if self._session_db_id is None:
            logger.warning("save_response llamado sin sesión activa, omitiendo")
            return

        allowed = {"notas_agente", "resumen"}
        if campo not in allowed:
            raise ValueError(f"Campo no permitido: {campo!r}. Usa: {allowed}")

        conn = self._get_connection()
        try:
            existing = conn.execute(
                f"SELECT {campo} FROM sessions WHERE id = ?",
                (self._session_db_id,),
            ).fetchone()

            prev = existing[campo] or "" if existing else ""
            separator = "\n---\n" if prev else ""
            nuevo = f"{prev}{separator}[{datetime.now().isoformat(timespec='seconds')}] {user_input}"

            conn.execute(
                f"UPDATE sessions SET {campo} = ?, updated_at = datetime('now') WHERE id = ?",
                (nuevo, self._session_db_id),
            )
            conn.commit()
            logger.debug("Guardado en sessions.%s (session_id=%s)", campo, self._session_db_id)
        finally:
            conn.close()

    def save_mood(self, momento: str, valor: int) -> None:
        """
        Guarda el mood del coachee antes o después de la sesión.

        Args:
            momento: 'antes' o 'despues'
            valor:   Entero entre 1 y 5
        """
        if self._session_db_id is None:
            logger.warning("save_mood llamado sin sesión activa")
            return
        if momento not in ("antes", "despues"):
            raise ValueError("momento debe ser 'antes' o 'despues'")
        if not (1 <= valor <= 5):
            raise ValueError("valor debe estar entre 1 y 5")

        campo = f"mood_{momento}"
        conn  = self._get_connection()
        try:
            conn.execute(
                f"UPDATE sessions SET {campo} = ?, updated_at = datetime('now') WHERE id = ?",
                (valor, self._session_db_id),
            )
            conn.commit()
            logger.info("Mood %s guardado: %d (session_id=%s)", momento, valor, self._session_db_id)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Vault (Obsidian)
    # ------------------------------------------------------------------

    def save_to_vault(self, session_num: int | None = None) -> str:
        """
        Genera el resumen de la sesión indicada (o la actual) y lo guarda
        en el vault de Obsidian. Delega en la función standalone summarize_session.

        Returns:
            Mensaje de confirmación con la ruta del archivo generado.
        """
        target = session_num if session_num is not None else self.current_session
        if target is None:
            return "No hay sesión activa para resumir."

        summary = summarize_session(self.program_id, target)
        if not summary:
            return f"No se encontraron datos para la sesión {target}."

        nombre = summary.get("coachee_nombre", "coachee")
        nombre_slug = re.sub(r"[^\w\s-]", "", nombre.lower())
        nombre_slug = re.sub(r"[\s_]+", "-", nombre_slug.strip())
        vault_file = VAULT_PATH / nombre_slug / f"session-{target}.md"

        return f"Resumen de la sesión {target} guardado en vault: {vault_file}"

    # ------------------------------------------------------------------
    # Herramientas
    # ------------------------------------------------------------------

    def use_tool(self, tool_name: str, params: dict) -> str:
        """
        Ejecuta una herramienta si está disponible en la sesión actual.

        Args:
            tool_name: Nombre de la herramienta.
            params:    Parámetros requeridos por la herramienta.

        Returns:
            Resultado de la herramienta o mensaje de error.
        """
        if self.current_session is None:
            return "No hay sesión activa. Llama a start_session() primero."

        available = SESSION_CONFIG.get(self.current_session, {}).get("tools", [])
        if tool_name not in available:
            logger.warning(
                "Herramienta '%s' no disponible en sesión %d. Disponibles: %s",
                tool_name,
                self.current_session,
                available,
            )
            return (
                f"Herramienta '{tool_name}' no disponible en la sesión {self.current_session}. "
                f"Herramientas disponibles: {', '.join(available) or 'ninguna'}."
            )

        handler = self._tool_handlers.get(tool_name)
        if handler is None:
            logger.error("Herramienta '%s' no tiene handler implementado", tool_name)
            return f"Herramienta '{tool_name}' aún no implementada."

        logger.info("Ejecutando herramienta '%s' en sesión %d", tool_name, self.current_session)
        return handler(self, params)

    # ------------------------------------------------------------------
    # Handlers de herramientas (métodos privados)
    # ------------------------------------------------------------------

    def _tool_evaluate_wheel_of_life(self, params: dict) -> str:
        if self._session_db_id is None:
            return "No hay sesión activa."
        categorias = params.get("categorias")
        if not categorias:
            return "Se requiere el parámetro 'categorias' con las puntuaciones."

        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO wheel_of_life (session_id, categorias) VALUES (?, ?)",
                (self._session_db_id, json.dumps(categorias, ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("Rueda de la vida guardada para session_id=%s", self._session_db_id)
        return f"Rueda de la vida registrada con {len(categorias)} categorías."

    def _tool_set_smart_goal(self, params: dict) -> str:
        objetivo = params.get("objetivo", "").strip()
        if not objetivo:
            return "Se requiere el parámetro 'objetivo'."
        self.save_response(f"[OBJETIVO SMART] {objetivo}", campo="resumen")
        return f"Objetivo registrado: {objetivo}"

    def _tool_track_belief(self, params: dict) -> str:
        limitante = params.get("creencia_limitante", "").strip()
        if not limitante:
            return "Se requiere el parámetro 'creencia_limitante'."
        if self._session_db_id is None:
            return "No hay sesión activa."

        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO beliefs_tracker
                    (session_id, creencia_limitante, creencia_potenciadora_reemplazo,
                     evidencia_contraria, estado)
                VALUES (?, ?, ?, ?, 'identificada')
                """,
                (
                    self._session_db_id,
                    limitante,
                    params.get("creencia_potenciadora", ""),
                    params.get("evidencia_contraria", ""),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("Creencia limitante registrada para session_id=%s", self._session_db_id)
        return f"Creencia registrada: '{limitante}'"

    def _tool_create_action(self, params: dict) -> str:
        objetivo = params.get("objetivo", "").strip()
        if not objetivo:
            return "Se requiere el parámetro 'objetivo'."
        if self._session_db_id is None:
            return "No hay sesión activa."

        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO action_plans
                    (session_id, objetivo, acciones, fecha_inicio, fecha_fin, kpis, estado)
                VALUES (?, ?, ?, ?, ?, ?, 'pendiente')
                """,
                (
                    self._session_db_id,
                    objetivo,
                    json.dumps(params.get("acciones", []), ensure_ascii=False),
                    params.get("fecha_inicio"),
                    params.get("fecha_fin"),
                    json.dumps(params.get("kpis", []), ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("Plan de acción creado para session_id=%s", self._session_db_id)
        return f"Plan de acción registrado: '{objetivo}'"

    def _tool_generate_certificate(self, params: dict) -> str:
        conn = self._get_connection()
        try:
            conn.execute(
                """
                UPDATE coaching_programs
                SET estado = 'completado', certificado_entregado = 1,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (self.program_id,),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("Certificado generado para program_id=%s", self.program_id)
        return (
            f"Certificado generado para {self.coachee.get('nombre', 'el coachee')}. "
            "El programa ha sido marcado como completado."
        )

    def save_session_feedback(
        self,
        feedback_coach: str = "",
        feedback_coachee: str = "",
        valoracion_coach: int | None = None,
    ) -> str:
        """
        Guarda el feedback de cierre de sesión en coach_feedback.
        Solo se ejecuta si hay un coach asignado y una sesión activa.
        """
        if self._session_db_id is None:
            logger.warning("save_session_feedback llamado sin sesión activa")
            return "No hay sesión activa."
        if not self._assignment_id:
            logger.warning("save_session_feedback: sin coach asignado, feedback omitido")
            return "Sin coach asignado. Feedback no guardado."
        if valoracion_coach is not None and not (1 <= valoracion_coach <= 5):
            raise ValueError("valoracion_coach debe estar entre 1 y 5")

        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO coach_feedback
                    (assignment_id, session_id, feedback_coach, feedback_coachee, valoracion_coach)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self._assignment_id,
                    self._session_db_id,
                    feedback_coach or None,
                    feedback_coachee or None,
                    valoracion_coach,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info(
            "Feedback guardado — session_id=%s, assignment_id=%s, valoracion=%s",
            self._session_db_id,
            self._assignment_id,
            valoracion_coach,
        )
        return "Feedback de sesión guardado correctamente."

    # Registro de handlers para use_tool()
    _tool_handlers: dict = {
        "evaluate_wheel_of_life": _tool_evaluate_wheel_of_life,
        "set_smart_goal":         _tool_set_smart_goal,
        "track_belief":           _tool_track_belief,
        "create_action":          _tool_create_action,
        "generate_certificate":   _tool_generate_certificate,
    }


# ---------------------------------------------------------------------------
# Funciones standalone (sin instancia de CoachingAgent)
# ---------------------------------------------------------------------------

def summarize_session(program_id: str, session_num: int) -> dict:
    """
    Genera y persiste un resumen estructurado de una sesión completada.

    Extrae:
    - Insights de notas_agente (entradas separadas por ---)
    - Compromisos de action_plans
    - Bloqueos/creencias de beliefs_tracker

    Guarda el JSON en sessions.criterios_avance y escribe el markdown
    en data/vault/Agente/coachees/{nombre}/session-{num}.md.

    Args:
        program_id:  ID del programa de coaching.
        session_num: Número de la sesión a resumir.

    Returns:
        dict con el resumen generado, o {} si la sesión no existe.
    """
    if not DB_PATH.exists():
        logger.error("Base de datos no encontrada: %s", DB_PATH)
        return {}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        session_row = conn.execute(
            """
            SELECT s.id, s.numero_sesion, s.fase_grow, s.notas_agente, s.resumen,
                   s.mood_antes, s.mood_despues, s.fecha_realizada,
                   c.nombre AS coachee_nombre, c.rol AS coachee_rol
            FROM sessions s
            JOIN coaching_programs cp ON cp.id = s.program_id
            JOIN coachees c ON c.id = cp.coachee_id
            WHERE s.program_id = ? AND s.numero_sesion = ?
            """,
            (program_id, session_num),
        ).fetchone()

        if not session_row:
            logger.warning(
                "summarize_session: sesión %d no encontrada para programa %s",
                session_num, program_id,
            )
            return {}

        session = dict(session_row)
        session_id = session["id"]

        # Extraer insights de notas_agente
        insights: list[str] = []
        if session.get("notas_agente"):
            bloques = session["notas_agente"].split("\n---\n")
            for bloque in bloques:
                texto = re.sub(r"^\[[\d\-T:]+\]\s*", "", bloque.strip())
                if len(texto) > 20:
                    insights.append(texto[:200])

        # Extraer compromisos de action_plans
        compromisos: list[dict] = []
        action_rows = conn.execute(
            "SELECT objetivo, acciones, fecha_fin, estado FROM action_plans WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        for ar in action_rows:
            try:
                acciones_list = json.loads(ar["acciones"] or "[]")
            except (json.JSONDecodeError, TypeError):
                acciones_list = []
            compromisos.append({
                "objetivo": ar["objetivo"],
                "acciones": acciones_list,
                "fecha_fin": ar["fecha_fin"],
                "estado":    ar["estado"],
            })

        # Extraer bloqueos de beliefs_tracker
        bloqueos: list[dict] = []
        belief_rows = conn.execute(
            "SELECT creencia_limitante, creencia_potenciadora_reemplazo, estado "
            "FROM beliefs_tracker WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        for br in belief_rows:
            bloqueos.append({
                "creencia_limitante": br["creencia_limitante"],
                "reemplazo":          br["creencia_potenciadora_reemplazo"],
                "estado":             br["estado"],
            })

        # Delta de mood
        mood_delta = None
        if session.get("mood_antes") and session.get("mood_despues"):
            mood_delta = session["mood_despues"] - session["mood_antes"]

        summary = {
            "session_num":     session_num,
            "fase_grow":       session["fase_grow"],
            "fecha":           session.get("fecha_realizada", ""),
            "insights":        insights,
            "compromisos":     compromisos,
            "bloqueos":        bloqueos,
            "mood_antes":      session.get("mood_antes"),
            "mood_despues":    session.get("mood_despues"),
            "mood_delta":      mood_delta,
            "coachee_nombre":  session["coachee_nombre"],
            "coachee_rol":     session["coachee_rol"],
            "generado_en":     datetime.now().isoformat(timespec="seconds"),
        }

        # Persistir en sessions.criterios_avance
        conn.execute(
            "UPDATE sessions SET criterios_avance = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(summary, ensure_ascii=False), session_id),
        )
        conn.commit()
        logger.info(
            "Resumen persistido en criterios_avance — sesión %d, programa %s",
            session_num, program_id,
        )

    finally:
        conn.close()

    # Guardar en vault
    _save_summary_to_vault(summary)

    return summary


def _save_summary_to_vault(summary: dict) -> None:
    """
    Escribe el resumen de sesión en el vault de Obsidian:
    - data/vault/Agente/coachees/{nombre-slug}/session-{N}.md  (detalle)
    - data/vault/Agente/coachees/{nombre-slug}/historial.md    (acumulado)
    """
    nombre = summary.get("coachee_nombre", "unknown")
    nombre_slug = re.sub(r"[^\w\s-]", "", nombre.lower())
    nombre_slug = re.sub(r"[\s_]+", "-", nombre_slug.strip()) or "coachee"

    coachee_dir = VAULT_PATH / nombre_slug
    coachee_dir.mkdir(parents=True, exist_ok=True)

    session_num = summary["session_num"]
    fase        = (summary.get("fase_grow") or "").capitalize()
    fecha       = summary.get("fecha") or datetime.now().strftime("%Y-%m-%d")
    rol         = summary.get("coachee_rol", "—")
    generado_en = summary.get("generado_en", "")

    # ---- session-N.md -----------------------------------------------
    insights_md = "\n".join(f"- {i}" for i in summary.get("insights", []))
    if not insights_md:
        insights_md = "_Sin notas registradas._"

    compromisos_md = ""
    for c in summary.get("compromisos", []):
        compromisos_md += f"\n### {c['objetivo']}\n"
        for a in c.get("acciones", []):
            compromisos_md += f"- {a}\n"
        if c.get("fecha_fin"):
            compromisos_md += f"_Fecha límite: {c['fecha_fin']}_  \n"
        compromisos_md += f"Estado: **{c.get('estado', '—')}**\n"
    compromisos_md = compromisos_md.strip() or "_Sin compromisos registrados._"

    bloqueos_md = ""
    for b in summary.get("bloqueos", []):
        bloqueos_md += f"\n- **Limitante:** {b['creencia_limitante']}\n"
        if b.get("reemplazo"):
            bloqueos_md += f"  **Reemplazo:** {b['reemplazo']}\n"
        bloqueos_md += f"  Estado: {b.get('estado', '—')}\n"
    bloqueos_md = bloqueos_md.strip() or "_Sin creencias trabajadas._"

    mood_antes   = summary.get("mood_antes") or "—"
    mood_despues = summary.get("mood_despues") or "—"
    mood_delta   = summary.get("mood_delta")
    if mood_delta is not None:
        mood_delta_str = f"+{mood_delta}" if mood_delta > 0 else str(mood_delta)
    else:
        mood_delta_str = "—"

    session_content = f"""# Sesión {session_num} — {fase}

**Coachee:** {nombre}
**Rol:** {rol}
**Fecha:** {fecha}
**Generado:** {generado_en}

---

## Insights clave

{insights_md}

---

## Compromisos

{compromisos_md}

---

## Bloqueos / Creencias trabajadas

{bloqueos_md}

---

## Estado emocional

| Antes | Después | Delta |
|-------|---------|-------|
| {mood_antes}/5 | {mood_despues}/5 | {mood_delta_str} |

---

_Generado automáticamente por CoachingAgent_
"""
    session_file = coachee_dir / f"session-{session_num}.md"
    session_file.write_text(session_content, encoding="utf-8")
    logger.info("Sesión guardada en vault: %s", session_file)

    # ---- historial.md -----------------------------------------------
    historial_file = coachee_dir / "historial.md"

    if historial_file.exists():
        historial_content = historial_file.read_text(encoding="utf-8")
    else:
        historial_content = (
            f"# Historial de coaching — {nombre}\n\n"
            f"**Rol:** {rol}\n\n---\n\n"
        )

    new_entry = (
        f"## Sesión {session_num} — {fase} ({fecha})\n\n"
        f"- **Insights:** {len(summary.get('insights', []))} registrados\n"
        f"- **Compromisos:** {len(summary.get('compromisos', []))} planes de acción\n"
        f"- **Bloqueos:** {len(summary.get('bloqueos', []))} creencias trabajadas\n"
        f"- **Mood:** {mood_antes}/5 → {mood_despues}/5 ({mood_delta_str})\n\n"
    )

    # Reemplaza entrada existente o añade al final
    entry_pattern = rf"## Sesión {session_num} —.*?(?=## Sesión |\Z)"
    if re.search(entry_pattern, historial_content, flags=re.DOTALL):
        historial_content = re.sub(
            entry_pattern, new_entry, historial_content, flags=re.DOTALL
        )
    else:
        historial_content += new_entry

    historial_file.write_text(historial_content, encoding="utf-8")
    logger.info("Historial actualizado: %s", historial_file)


# ---------------------------------------------------------------------------
# Bloque __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    program_id = sys.argv[1] if len(sys.argv) > 1 else "PROGRAM_ID_DE_PRUEBA"

    try:
        agent = CoachingAgent(program_id)

        print("\n--- Sesión 1 ---")
        print(agent.start_session(1))

        agent.save_mood("antes", 4)

        print("\n--- Rueda de la vida ---")
        print(agent.use_tool("evaluate_wheel_of_life", {
            "categorias": {
                "carrera": 6, "salud": 7, "familia": 8,
                "finanzas": 5, "desarrollo": 7, "ocio": 4,
                "relaciones": 8, "proposito": 6,
            }
        }))

        print("\n--- Objetivo SMART ---")
        print(agent.use_tool("set_smart_goal", {
            "objetivo": "Liderar mi equipo con mayor confianza en los próximos 3 meses."
        }))

        print("\n--- Herramienta no disponible en sesión 1 ---")
        print(agent.use_tool("track_belief", {"creencia_limitante": "No soy suficiente"}))

        agent.save_mood("despues", 5)

        print("\n--- Procesar respuesta ---")
        print(agent.process_response("Me ha resultado muy revelador ver mi rueda de la vida."))

        print("\n--- Guardar resumen en vault ---")
        print(agent.save_to_vault())

        print("\n--- Sesión 2 (con contexto cargado) ---")
        print(agent.start_session(2))

    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}")
        print("(Ejecuta con una base de datos y program_id válidos)")
        sys.exit(0)
