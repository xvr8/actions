#!/usr/bin/env python3
"""
SCRIPT: generate_ai_report.py
RUTA: ai-report/scripts/generate_ai_report.py

PROPOSITO:
    Genera ai_report.json — un JSON limpio y estructurado para consumo por IA
    a partir del final_logs.json consolidado del pipeline.

    Extrae únicamente:
      - Vista por categorías del analyzer (categoría → reglas con PASS/FAIL/WARN)
      - Vulnerabilidades de Xray (CVE, package, severidad)

    Omite ruido: logs crudos de logger/pyspark, raw_lines, line_numbers, etc.

FORMATO DE SALIDA (ai_report.json):
    {
      "schema_version": "ai-1.0",
      "generated_at": "2026-06-25T10:05:00Z",
      "app": "demo-lhcl",
      "env": "desa",
      "run_id": "12345678",
      "overall_status": "failure",
      "analyzer": {
        "categories": [
          {
            "name": "CALIDAD DE DATOS",
            "summary": { "pass": 1, "fail": 1, "warn": 1 },
            "rules": [
              { "rule_id": "R001", "result": "PASS", "description": "...", "detail": "OK" },
              { "rule_id": "R002", "result": "FAIL", "description": "...", "detail": "..." }
            ]
          }
        ],
        "total_summary": { "pass": 3, "fail": 2, "warn": 2 }
      },
      "vulnerabilities": [
        { "severity": "HIGH", "cve": "CVE-2021-44228", "package": "log4j-core:2.14.1", "description": "..." }
      ],
      "global_summary": { "failure": 3, "warning": 4, "notice": 10 }
    }

USO:
    python scripts/generate_ai_report.py \
        --input  artifacts/final_logs.json \
        --output artifacts/ai_report.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

AI_SCHEMA_VERSION = "ai-1.0"


def extract_analyzer_data(jobs: list) -> dict:
    """Extrae categories_view y total_summary del step 'analyzer' en qa-prepare."""
    for job in jobs:
        if job.get("job") == "qa-prepare":
            for step in job.get("steps", []):
                if step.get("name") == "analyzer":
                    return {
                        "categories":    step.get("categories_view", []),
                        "total_summary": step.get("analyzer_total", {}),
                    }
    return {"categories": [], "total_summary": {}}


def extract_vulnerabilities(jobs: list) -> list:
    """Extrae vulnerabilidades del step 'xray' en qa-xray."""
    for job in jobs:
        if job.get("job") == "qa-xray":
            for step in job.get("steps", []):
                if step.get("name") == "xray":
                    vulns = []
                    for ann in step.get("annotations", []):
                        # Extraer severidad desde el campo 'line': "[HIGH] CVE-... ..."
                        raw_line = ann.get("line", "")
                        sev = raw_line.split("]")[0].lstrip("[").strip() if "]" in raw_line else "UNKNOWN"
                        vulns.append({
                            "severity":    sev,
                            "cve":         ann.get("cve", ""),
                            "package":     f"{ann.get('package', '')}:{ann.get('version', '')}",
                            "description": ann.get("message", ""),
                        })
                    return vulns
    return []


def determine_overall_status(global_summary: dict) -> str:
    if global_summary.get("failure", 0) > 0:
        return "failure"
    if global_summary.get("warning", 0) > 0:
        return "warning"
    return "success"


def main():
    parser = argparse.ArgumentParser(description="Generate AI-optimized report from final_logs.json")
    parser.add_argument("--input",  required=True, help="Path a final_logs.json")
    parser.add_argument("--output", required=True, help="Path de salida ai_report.json")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: {input_path} no encontrado", file=sys.stderr)
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        final_logs = json.load(f)

    jobs           = final_logs.get("jobs", [])
    global_summary = final_logs.get("global_summary", {})

    analyzer        = extract_analyzer_data(jobs)
    vulnerabilities = extract_vulnerabilities(jobs)
    overall_status  = determine_overall_status(global_summary)

    report = {
        "schema_version": AI_SCHEMA_VERSION,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "app":            final_logs.get("app", ""),
        "env":            final_logs.get("env", ""),
        "run_id":         final_logs.get("run_id", ""),
        "overall_status": overall_status,
        "analyzer":       analyzer,
        "vulnerabilities": vulnerabilities,
        "global_summary": {
            "failure": global_summary.get("failure", 0),
            "warning": global_summary.get("warning", 0),
            "notice":  global_summary.get("notice", 0),
        },
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"OK: ai_report.json generado")
    print(f"    Status:           {overall_status}")
    print(f"    Categorías:       {len(analyzer['categories'])}")
    print(f"    Vulnerabilidades: {len(vulnerabilities)}")
    print(f"    Output:           {output_path}")


if __name__ == "__main__":
    main()
