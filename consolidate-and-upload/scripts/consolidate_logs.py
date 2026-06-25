#!/usr/bin/env python3
"""
SCRIPT: consolidate_logs.py
RUTA: scripts/consolidate_logs.py

PROPOSITO:
    Leer todos los captured_logs.json de los diferentes jobs y consolidarlos
    en un único final_logs.json válido. Maneja los casos problemáticos:
    - Arrays vacíos
    - JSONs malformados (los omite con warning)
    - Archivos inexistentes

POR QUE PYTHON Y NO jq/bash:
    La consolidación con bash + jq requiere manejar manualmente las comas
    y es frágil ante arrays vacíos. Python con json.load/json.dump garantiza
    siempre un JSON válido como output sin importar la cantidad de archivos.

FORMATO DE SALIDA (final_logs.json):
    {
      "schema_version": "1.0",
      "consolidated_at": "2026-06-25T10:05:00Z",
      "run_id": "12345678",
      "app": "mi-app-databricks",
      "env": "desa",
      "jobs": [
        { ... captured_logs de qa-prepare ... },
        { ... captured_logs de qa-xray    ... }
      ],
      "global_summary": {
        "total_jobs": 2,
        "jobs_with_failures": 1,
        "failure": 3,
        "warning": 2,
        "notice": 10
      }
    }

USO:
    python scripts/consolidate_logs.py \
        --files-list /tmp/log_files.txt \
        --output     artifacts/final_logs.json \
        --run-id     12345678 \
        --app        mi-app \
        --env        desa
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"


def load_captured_log(file_path: Path) -> dict | None:
    """
    Carga un captured_logs.json. Retorna None si el archivo está vacío o malformado.
    POR QUE retornar None en lugar de lanzar excepción:
        Un job secundario con logs malformados no debe impedir la consolidación
        del resto. Lo omitimos con warning.
    """
    if not file_path.exists():
        print(f"WARN: Archivo no encontrado: {file_path}")
        return None

    if file_path.stat().st_size == 0:
        print(f"WARN: Archivo vacío: {file_path}")
        return None

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        # Validación mínima de estructura
        if "job" not in data:
            print(f"WARN: JSON sin campo 'job': {file_path} — omitiendo")
            return None

        return data

    except json.JSONDecodeError as e:
        print(f"WARN: JSON malformado en {file_path}: {e} — omitiendo")
        return None


def main():
    parser = argparse.ArgumentParser(description="Consolidate all captured_logs.json into final_logs.json")
    parser.add_argument("--files-list", required=True, help="Archivo con rutas, una por línea")
    parser.add_argument("--output",     required=True)
    parser.add_argument("--run-id",     required=True)
    parser.add_argument("--app",        required=True)
    parser.add_argument("--env",        required=True)
    args = parser.parse_args()

    # Leer lista de archivos
    files_list_path = Path(args.files_list)
    if not files_list_path.exists():
        print(f"ERROR: Lista de archivos no encontrada: {files_list_path}", file=sys.stderr)
        sys.exit(1)

    with open(files_list_path) as f:
        file_paths = [Path(line.strip()) for line in f if line.strip()]

    if not file_paths:
        print("ERROR: La lista de archivos está vacía", file=sys.stderr)
        sys.exit(1)

    print(f"INFO: Procesando {len(file_paths)} archivos...")

    # Cargar todos los JSONs válidos
    jobs = []
    skipped = 0
    for path in file_paths:
        print(f"  Cargando: {path}")
        data = load_captured_log(path)
        if data is not None:
            jobs.append(data)
        else:
            skipped += 1

    if not jobs:
        print("ERROR: No se pudo cargar ningún captured_logs.json válido", file=sys.stderr)
        sys.exit(1)

    print(f"INFO: Cargados {len(jobs)} jobs ({skipped} omitidos)")

    # Calcular global_summary
    global_summary = {
        "total_jobs": len(jobs),
        "jobs_with_failures": 0,
        "failure": 0,
        "warning": 0,
        "notice": 0,
    }

    for job in jobs:
        job_total = job.get("total_summary", {})
        if job_total.get("failure", 0) > 0:
            global_summary["jobs_with_failures"] += 1
        for sev in ("failure", "warning", "notice"):
            global_summary[sev] += job_total.get(sev, 0)

    # Construir documento final
    now = datetime.now(timezone.utc)
    final_document = {
        "schema_version": SCHEMA_VERSION,
        "consolidated_at": now.isoformat(),
        "run_id": args.run_id,
        "app": args.app,
        "env": args.env,
        "jobs": jobs,
        "global_summary": global_summary,
    }

    # Escribir output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_document, f, indent=2, ensure_ascii=False)

    file_size = output_path.stat().st_size
    print(f"OK: final_logs.json generado")
    print(f"    Jobs consolidados: {len(jobs)} | Tamaño: {file_size} bytes")
    print(f"    FAILURE={global_summary['failure']} WARNING={global_summary['warning']} NOTICE={global_summary['notice']}")
    print(f"    Jobs con fallos: {global_summary['jobs_with_failures']}")
    print(f"    Output: {output_path}")


if __name__ == "__main__":
    main()
