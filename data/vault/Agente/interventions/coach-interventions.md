# Coach Interventions — Guía de Intervenciones

Cada intervención se activa según las condiciones detectadas por el sistema.
El agente lee este archivo para sugerir el tipo de intervención adecuado.

---

## type: 1:1_extra

**Descripción:** Sesión adicional de 30-45 min con el coach antes de la siguiente sesión programada.

**Activar cuando:**
- Engagement score < 40
- Mood bajo en 2 sesiones consecutivas + acciones vencidas > 2

**Objetivo:** Restablecer la conexión, identificar bloqueos emocionales o situacionales no expresados en las sesiones regulares.

**Guión sugerido para el coach:**
1. Abre con una pregunta de estado: "¿Cómo te has sentido desde nuestra última sesión?"
2. Explora obstáculos no verbalizado: "¿Hay algo que no hemos podido tocar en las sesiones?"
3. Renegociar objetivos si es necesario.

**Prioridad:** Alta

---

## type: nudge_intensive

**Descripción:** Aumentar la frecuencia de nudges de 1 a 3 por semana durante 2 semanas.

**Activar cuando:**
- Engagement score entre 40–60
- Tasa de acciones completadas < 30%
- Abandono detectado (sin actividad > 10 días)

**Objetivo:** Mantener la presencia del proceso de coaching en el día a día del coachee sin sobrecargar.

**Tipos de nudge a enviar:**
- Preguntas de reflexión breve (1 por semana)
- Recordatorio de compromisos pendientes (1 por semana)
- Mensaje de ánimo o reconocimiento de avances (1 por semana)

**Prioridad:** Media

---

## type: profile_review

**Descripción:** Revisión del perfil del coachee: competencias, objetivo original y ajuste del plan de coaching.

**Activar cuando:**
- Han pasado más de 3 sesiones sin avance en competencias
- El objetivo SMART definido en sesión 1 ya no es relevante
- Engagement score < 50 y tasa de asistencia < 50%

**Objetivo:** Asegurar que el programa sigue siendo pertinente para el coachee en su contexto actual.

**Pasos:**
1. Revisar `competency_tracking` para identificar estancamiento.
2. Releer el resumen de la sesión 1 (objetivo SMART).
3. Proponer ajuste de objetivos o competencias con el coachee.

**Prioridad:** Media

---

## type: accountability_partner

**Descripción:** Asignar un compañero de accountability (peer coaching) del mismo grupo o empresa.

**Activar cuando:**
- Coachee tiene patrón consistente de no completar acciones (> 3 semanas)
- Engagement score < 60 y el coach ya ha hecho 1:1_extra sin mejora
- El coachee ha manifestado necesitar apoyo externo entre sesiones

**Objetivo:** Crear una red de apoyo entre pares que sostenga el cambio más allá de las sesiones.

**Cómo implementar:**
1. Identificar otro coachee del mismo programa o empresa con perfil complementario.
2. Proponer check-ins semanales de 15 min entre ellos.
3. Definir un formato simple: "¿Qué te comprometiste? ¿Qué lograste? ¿Qué necesitas?"

**Prioridad:** Baja — usar cuando otras intervenciones no han funcionado

---

## Matriz de decisión rápida

| Condición                              | Intervención sugerida     |
|----------------------------------------|---------------------------|
| Score < 40 + mood bajo 2 sesiones      | 1:1_extra                 |
| Score 40–60 + acciones sin completar   | nudge_intensive           |
| Score < 50 + sin avance en objetivos   | profile_review            |
| Patrón crónico + 1:1_extra sin efecto  | accountability_partner    |
