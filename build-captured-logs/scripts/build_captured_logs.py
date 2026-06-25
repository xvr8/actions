#!/usr/bin/env python3
"""
SCRIPT: build_captured_logs.py
RUTA: scripts/build_captured_logs.py

PROPOSITO:
    Construir el captured_logs.json — el JSON central de cada job.
    Consolida las annotations de analyzer, logger y pyspark (o xray)
    en un único documento con esquema homogéneo.

POR QUE ESTE SCRIPT ES CLAVE:
    La homogeneidad del esquema es lo que permite que capture-logs consolide
    los outputs de qa-prepare y qa-xray sin conocer sus diferencias internas.
    Si cada job produce un formato distinto, la consolidación se vuelve frágil.

ESQUEMA DE SALIDA (captured_logs.json):
    {
      "schema_version": "1.0",
      "job": "qa-prepare",
      "run_id": "12345678",
      "timestamp": "2026-06-25T10:00:00Z",
      "steps": [
        {
          "name": "analyzer",
          "status": "failure",       // success | failure | warning
          "source": "analyzer",
          "annotations": [
            {
              "line": "[FAIL] R002 - Validación de tipos: ...",
              "severity": "failure",  // failure | warning | notice
              "message": "Validación de tipos: columna 'fecha' esperaba DATE",
              "rule_id": "R002",
              "category": "CALIDAD DE DATOS",
              "source": "analyzer"
            }
          ],
          "summary": { "failure": 1, "warning": 0, "notice": 2 }
        },
        {
          "name": "logger",
          "status": "success",
          "source": "logger",
          "annotations": [ ... ]
        }
      ],
      "metadata": {
        "app": "mi-app-databricks",
        "env": "desa",
        "run_id": "12345678",
        "date": "2026-06-25",
        "artifact_path": "desa/bcp/lht/tntd/log/app=.../run_id=....json"
      },
      "total_summary": { "failure": 1, "warning": 2, "notice": 5 }
    }

USO:
    # Para qa-prepare:
    python scripts/build_captured_logs.py \
        --job      qa-prepare \
        --app      mi-app \
        --env      desa \
        --run-id   12345678 \
        --analyzer artifacts/analyzer_structured.json \
        --logger   logs/logger_raw.log \
        --pyspark  logs/pyspark_raw.log \
        --output   artifacts/captured_logs.json

    # Para qa-xray:
    python scripts/build_captured_logs.py \
        --job    qa-xray \
        --app    mi-app \
        --env    desa \
        --run-id 12345678 \
        --xray   artifacts/xray_structured.json \
        --output artifacts/captured_logs.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Helpers para parsear logs de texto plano (logger, pyspark)
# ---------------------------------------------------------------------------

LOG_LEVEL_PATTERN = re.compile(
    r"\b(ERROR|WARN(?:ING)?|INFO|DEBUG|CRITICAL|FATAL)\b", re.IGNORECASE
)

LOG_LEVEL_TO_SEVERITY = {
    "ERROR":    "failure",
    "CRITICAL": "failure",
    "FATAL":    "failure",
    "WARN":     "warning",
    "WARNING":  "warning",
    "INFO":     "notice",
    "DEBUG":    "notice",
}


def parse_text_log(log_path: Path, source_name: str) -> dict:
    """
    Parsea un log de texto plano (logger o pyspark) y produce un step con annotations.
    Detecta severidad por palabras clave en cada línea.
    """
    if not log_path or not log_path.exists() or log_path.stat().st_size == 0:
        return _empty_step(source_name)

    annotations = []
    summary = {"failure": 0, "warning": 0, "notice": 0}

    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue

            # Detectar nivel de log en la línea
            match = LOG_LEVEL_PATTERN.search(line)
            level = match.group(1).upper() if match else "INFO"
            severity = LOG_LEVEL_TO_SEVERITY.get(level, "notice")

            annotations.append({
                "line": line,
                "severity": severity,
                "message": line,
                "source": source_name,
            })
            summary[severity] += 1

    status = "failure" if summary["failure"] > 0 else (
        "warning" if summary["warning"] > 0 else "success"
    )

    return {
        "name": source_name,
        "status": status,
        "source": source_name,
        "annotations": annotations,
        "summary": summary,
    }


def _empty_step(name: str) -> dict:
    """Genera un step vacío válido cuando no hay datos disponibles."""
    return {
        "name": name,
        "status": "success",
        "source": name,
        "annotations": [],
        "summary": {"failure": 0, "warning": 0, "notice": 0},
        "note": f"No log data available for {name}",
    }


def parse_analyzer_structured(analyzer_path: Path) -> dict:
    """
    Convierte analyzer_structured.json en un step con annotations.
    Cada regla del analyzer se convierte en una annotation.
    """
    if not analyzer_path or not analyzer_path.exists():
        return _empty_step("analyzer")

    with open(analyzer_path, encoding="utf-8") as f:
        structured = json.load(f)

    annotations = []
    summary = {"failure": 0, "warning": 0, "notice": 0}

    for category in structured.get("categories", []):
        cat_name = category.get("name", "UNKNOWN")
        for rule in category.get("rules", []):
            severity = rule.get("severity", "notice")
            annotation = {
                "line": rule.get("raw_line", ""),
                "severity": severity,
                "message": rule.get("description", ""),
                "detail": rule.get("detail", ""),
                "rule_id": rule.get("rule_id", ""),
                "category": cat_name,
                "result": rule.get("result", ""),
                "source": "analyzer",
            }
            annotations.append(annotation)
            summary[severity] = summary.get(severity, 0) + 1

    status = "failure" if summary["failure"] > 0 else (
        "warning" if summary["warning"] > 0 else "success"
    )

    return {
        "name": "analyzer",
        "status": status,
        "source": "analyzer",
        "annotations": annotations,
        "summary": summary,
        "analyzer_total": structured.get("total_summary", {}),
    }


def parse_xray_structured(xray_path: Path) -> dict:
    """
    Convierte xray_structured.json en un step con annotations.
    Xray usa CVEs con severidades propias (critical/high/medium/low).
    """
    if not xray_path or not xray_path.exists():
        return _empty_step("xray")

    with open(xray_path, encoding="utf-8") as f:
        structured = json.load(f)

    annotations = []
    summary = {"failure": 0, "warning": 0, "notice": 0}

    XRAY_SEVERITY_MAP = {
        "critical": "failure",
        "high":     "failure",
        "medium":   "warning",
        "low":      "notice",
        "info":     "notice",
    }

    for vuln in structured.get("vulnerabilities", []):
        xray_sev = vuln.get("severity", "low").lower()
        severity = XRAY_SEVERITY_MAP.get(xray_sev, "notice")

        annotation = {
            "line": f"[{xray_sev.upper()}] {vuln.get('cve', 'NO-CVE')} - {vuln.get('package', '')}@{vuln.get('version', '')}",
            "severity": severity,
            "message": vuln.get("description", ""),
            "cve": vuln.get("cve", ""),
            "package": vuln.get("package", ""),
            "version": vuln.get("version", ""),
            "fixed_version": vuln.get("fixed_version", ""),
            "source": "xray",
        }
        annotations.append(annotation)
        summary[severity] += 1

    status = "failure" if summary["failure"] > 0 else (
        "warning" if summary["warning"] > 0 else "success"
    )

    return {
        "name": "xray",
        "status": status,
        "source": "xray",
        "annotations": annotations,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Main: construir el documento final captured_logs.json
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build captured_logs.json with annotations schema")
    parser.add_argument("--job",      required=True)
    parser.add_argument("--app",      required=True)
    parser.add_argument("--env",      required=True)
    parser.add_argument("--run-id",   required=True)
    parser.add_argument("--output",   required=True)
    # Fuentes opcionales (cada job usa las suyas)
    parser.add_argument("--analyzer", default=None)
    parser.add_argument("--logger",   default=None)
    parser.add_argument("--pyspark",  default=None)
    parser.add_argument("--xray",     default=None)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    steps = []

    # Procesar fuentes según las que estén disponibles
    if args.analyzer:
        steps.append(parse_analyzer_structured(Path(args.analyzer)))

    if args.logger:
        steps.append(parse_text_log(Path(args.logger), "logger"))

    if args.pyspark:
        steps.append(parse_text_log(Path(args.pyspark), "pyspark"))

    if args.xray:
        steps.append(parse_xray_structured(Path(args.xray)))

    if not steps:
        print("ERROR: No se proporcionó ninguna fuente de datos (--analyzer/--logger/--pyspark/--xray)",
              file=sys.stderr)
        sys.exit(1)

    # Calcular total_summary agregando todos los steps
    total_summary = {"failure": 0, "warning": 0, "notice": 0}
    for step in steps:
        for sev, count in step.get("summary", {}).items():
            total_summary[sev] = total_summary.get(sev, 0) + count

    # Path que tendrá en ADLS (informativo, para trazabilidad)
    date_str = now.strftime("%Y-%m-%d")
    artifact_path = f"desa/bcp/lht/tntd/log/app={args.app}/env={args.env}/date={date_str}/run_id={args.run_id}.json"

    document = {
        "schema_version": SCHEMA_VERSION,
        "job": args.job,
        "run_id": args.run_id,
        "timestamp": now.isoformat(),
        "steps": steps,
        "metadata": {
            "app": args.app,
            "env": args.env,
            "run_id": args.run_id,
            "date": date_str,
            "artifact_path": artifact_path,
        },
        "total_summary": total_summary,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)

    total_annotations = sum(len(s.get("annotations", [])) for s in steps)
    print(f"OK: captured_logs.json generado")
    print(f"    Job: {args.job} | Steps: {len(steps)} | Annotations: {total_annotations}")
    print(f"    FAILURE={total_summary['failure']} WARNING={total_summary['warning']} NOTICE={total_summary['notice']}")
    print(f"    Output: {output_path}")


if __name__ == "__main__":
    main()
