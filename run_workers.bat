@echo off
cd /d C:\Users\TSSC\Desktop\Coaching\coaching-agent

REM Crear carpeta logs si no existe
if not exist logs mkdir logs

echo === Ejecutando workers de coaching === >> logs\workers.log
echo %date% %time% - Iniciando workers >> logs\workers.log

echo [Session Tracker] >> logs\workers.log
python -c "from docs.scripts.session_tracker import generar_reporte_diario; import json; print(json.dumps(generar_reporte_diario(), indent=2))" >> logs\workers.log 2>&1

echo [Progress Analyzer] >> logs\workers.log
python -c "from docs.scripts.progress_analyzer import generar_reporte_completo; import json; print(json.dumps(generar_reporte_completo(), indent=2))" >> logs\workers.log 2>&1

echo [Nudge Scheduler] >> logs\workers.log
python -c "from docs.scripts.nudge_scheduler import schedule_intelligent_nudges, send_pending_nudges; print('Programando nudges...'); schedule_intelligent_nudges(); print('Enviando nudges pendientes...'); send_pending_nudges()" >> logs\workers.log 2>&1

echo %date% %time% - Workers completados >> logs\workers.log
echo --- >> logs\workers.log