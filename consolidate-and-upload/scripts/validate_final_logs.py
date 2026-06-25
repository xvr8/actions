#!/usr/bin/env python3
"""
SCRIPT: validate_final_logs.py
RUTA: scripts/validate_final_logs.py

PROPOSITO:
    Validar la estructura de final_logs.json antes de subirlo a ADLS.
    Si el archivo es inválido o incompleto, falla el step con un mensaje claro.

POR QUE ESTE STEP EXISTE:
    Azure CLI sube el archivo sin importar su contenido. Si el JSON está
    malformado, el error se descubre recién cuando el consumidor (Databricks,
    Grafana) intenta leerlo — potencialmente horas después. Mejor fallar
    aquí con un mensaje claro que hacer un upload silencioso de basura.

VALIDACIONES:
    1. El archivo existe y no está vacío
    2. Es JSON válido (parseable)
    3. Tiene los campos requeridos (schema_version, jobs, global_summary)
    4. Tiene al menos un job
    5. Cada job tiene el esquema mínimo (job, steps, metadata)
    6. Cada step tiene annotations con severidad válida

USO:
    python scripts/validate_final_logs.py --input artifacts/final_logs.json
"""

import argparse
import json
import sys
from pathlib import Path

REQUIRED_TOP_FIELDS = {"schema_version", "run_id", "jobs", "global_summary"}
REQUIRED_JOB_FIELDS = {"job", "run_id", "steps", "metadata"}
VALID_SEVERITIES    = {"failure", "warning", "notice"}
VALID_STEP_STATUSES = {"success", "failure", "warning"}


def error(msg: str):
    print(f"::error::{msg}", flush=True)
    sys.exit(1)


def warn(msg: str):
    print(f"::warning::{msg}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    input_path = Path(args.input)

    # Validación 1: existencia y tamaño
    if not input_path.exists():
        error(f"final_logs.json no encontrado: {input_path}")

    file_size = input_path.stat().st_size
    if file_size == 0:
        error("final_logs.json está vacío (0 bytes)")

    if file_size < 50:
        error(f"final_logs.json sospechosamente pequeño: {file_size} bytes")

    print(f"OK: Archivo existe — {file_size} bytes")

    # Validación 2: JSON válido
    try:
        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        error(f"JSON malformado: {e}")

    print("OK: JSON válido y parseable")

    # Validación 3: campos requeridos en el top level
    missing_top = REQUIRED_TOP_FIELDS - set(data.keys())
    if missing_top:
        error(f"Campos requeridos faltantes en el top level: {missing_top}")

    print(f"OK: Top-level fields presentes: {list(REQUIRED_TOP_FIELDS)}")

    # Validación 4: al menos un job
    jobs = data.get("jobs", [])
    if not jobs:
        error("El array 'jobs' está vacío — no hay datos para subir")

    print(f"OK: {len(jobs)} job(s) encontrados")

    # Validación 5: estructura de cada job
    validation_errors = []
    for i, job in enumerate(jobs):
        job_name = job.get("job", f"job_{i}")
        missing = REQUIRED_JOB_FIELDS - set(job.keys())
        if missing:
            validation_errors.append(f"Job '{job_name}': campos faltantes {missing}")

        # Validar steps
        for j, step in enumerate(job.get("steps", [])):
            step_name = step.get("name", f"step_{j}")

            # Validar status
            status = step.get("status", "")
            if status not in VALID_STEP_STATUSES:
                warn(f"Job '{job_name}', step '{step_name}': status inválido '{status}'")

            # Validar severidades de annotations
            for k, ann in enumerate(step.get("annotations", [])):
                sev = ann.get("severity", "")
                if sev not in VALID_SEVERITIES:
                    validation_errors.append(
                        f"Job '{job_name}', step '{step_name}', annotation {k}: "
                        f"severity inválida '{sev}' (válidas: {VALID_SEVERITIES})"
                    )

    if validation_errors:
        for err in validation_errors:
            print(f"::error::{err}")
        sys.exit(1)

    print("OK: Estructura de todos los jobs validada")

    # Validación 6: global_summary coherente
    gs = data.get("global_summary", {})
    total_from_jobs = sum(
        sum(step.get("summary", {}).values())
        for job in jobs
        for step in job.get("steps", [])
    )
    if total_from_jobs == 0:
        warn("global_summary.total es 0 — puede indicar logs vacíos")

    print(f"OK: global_summary — FAILURE={gs.get('failure',0)} WARNING={gs.get('warning',0)} NOTICE={gs.get('notice',0)}")
    print(f"OK: Validación completa. final_logs.json listo para upload.")


if __name__ == "__main__":
    main()
