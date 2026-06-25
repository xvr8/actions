#!/usr/bin/env python3
"""
SCRIPT: summary_report.py
RUTA: scripts/summary_report.py

PROPOSITO:
    Generar un resumen en formato Markdown para el GitHub Actions Step Summary.
    Se invoca al final de cada job para dar visibilidad sin abrir ADLS.

POR QUE ESTE SCRIPT:
    $GITHUB_STEP_SUMMARY permite mostrar tablas y resúmenes directamente en la
    UI de GitHub Actions. Sin este script, el único lugar donde ver los resultados
    sería descargando el artefacto o abriendo ADLS.

USO:
    python scripts/summary_report.py artifacts/captured_logs.json >> $GITHUB_STEP_SUMMARY
    python scripts/summary_report.py artifacts/final_logs.json    >> $GITHUB_STEP_SUMMARY
"""

import json
import sys
from pathlib import Path


SEVERITY_EMOJI = {
    "failure": ":red_circle:",
    "warning": ":yellow_circle:",
    "notice":  ":green_circle:",
}


def report_captured_logs(data: dict) -> str:
    lines = []
    job   = data.get("job", "unknown")
    ts    = data.get("timestamp", "")
    total = data.get("total_summary", {})

    lines.append(f"#### Job: `{job}`")
    lines.append(f"Timestamp: `{ts}`")
    lines.append("")
    lines.append("| Severidad | Count |")
    lines.append("|-----------|-------|")
    for sev in ("failure", "warning", "notice"):
        emoji = SEVERITY_EMOJI.get(sev, "")
        lines.append(f"| {emoji} {sev} | {total.get(sev, 0)} |")

    lines.append("")
    lines.append("**Steps:**")
    for step in data.get("steps", []):
        name   = step.get("name", "")
        status = step.get("status", "")
        count  = len(step.get("annotations", []))
        emoji  = ":white_check_mark:" if status == "success" else ":x:"
        lines.append(f"- {emoji} `{name}` — {count} annotations")

    return "\n".join(lines)


def report_final_logs(data: dict) -> str:
    lines = []
    gs    = data.get("global_summary", {})
    jobs  = data.get("jobs", [])

    lines.append(f"#### Consolidation Summary")
    lines.append(f"Run ID: `{data.get('run_id', 'N/A')}` | App: `{data.get('app', 'N/A')}` | Env: `{data.get('env', 'N/A')}`")
    lines.append("")
    lines.append("| Métrica | Valor |")
    lines.append("|---------|-------|")
    lines.append(f"| Total Jobs | {gs.get('total_jobs', len(jobs))} |")
    lines.append(f"| Jobs con fallos | {gs.get('jobs_with_failures', 0)} |")
    lines.append(f"| :red_circle: failure | {gs.get('failure', 0)} |")
    lines.append(f"| :yellow_circle: warning | {gs.get('warning', 0)} |")
    lines.append(f"| :green_circle: notice | {gs.get('notice', 0)} |")

    lines.append("")
    lines.append("**Jobs consolidados:**")
    for job in jobs:
        job_name = job.get("job", "unknown")
        job_total = job.get("total_summary", {})
        has_fail = job_total.get("failure", 0) > 0
        icon = ":x:" if has_fail else ":white_check_mark:"
        lines.append(f"- {icon} `{job_name}` — F:{job_total.get('failure',0)} W:{job_total.get('warning',0)} N:{job_total.get('notice',0)}")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("USO: summary_report.py <path/to/json>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Archivo no encontrado: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Detectar tipo de documento por campo "jobs" (final) vs "job" (captured)
    if "jobs" in data:
        print(report_final_logs(data))
    else:
        print(report_captured_logs(data))


if __name__ == "__main__":
    main()
