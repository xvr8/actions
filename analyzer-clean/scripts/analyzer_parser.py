#!/usr/bin/env python3
"""
SCRIPT: analyzer_parser.py
RUTA: scripts/analyzer_parser.py

PROPOSITO:
    Transformar el texto plano de analyzer_clean.log en un JSON estructurado
    (analyzer_structured.json) que pueda ser consumido por build_captured_logs.py.

POR QUE ESTE SCRIPT:
    El texto del analyzer sigue un formato legible para humanos pero no es
    procesable por máquinas. Este parser produce un JSON que puede ser auditado,
    graficado y almacenado en Data Lake con esquema predecible.

FORMATO DE ENTRADA ESPERADO (analyzer_clean.log):
    === VISTA POR CATEGORIAS ===

    CATEGORIA: CALIDAD DE DATOS
      [PASS] R001 - Validación de nulos en columna 'id': OK
      [FAIL] R002 - Validación de tipos: columna 'fecha' esperaba DATE, encontró STRING
      [WARN] R003 - Valores fuera de rango en 'monto': 3 registros afectados

    CATEGORIA: ESTRUCTURA DE TABLAS
      [PASS] R004 - TABLA FUENTE existe: OK
      [FAIL] R005 - Columna requerida 'cod_cliente' no encontrada

FORMATO DE SALIDA (analyzer_structured.json):
    {
      "categories": [
        {
          "name": "CALIDAD DE DATOS",
          "rules": [
            {
              "rule_id": "R001",
              "result": "PASS",
              "description": "Validación de nulos en columna 'id'",
              "detail": "OK"
            },
            ...
          ],
          "summary": { "pass": 1, "fail": 1, "warn": 1 }
        }
      ],
      "total_summary": { "pass": 2, "fail": 2, "warn": 1 }
    }

USO:
    python scripts/analyzer_parser.py \
        --input  logs/analyzer_clean.log \
        --output artifacts/analyzer_structured.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Patrones de regex
# POR QUE REGEX Y NO SPLIT:
#   Las líneas del analyzer pueden tener variaciones de espacios y caracteres
#   especiales. Los regex son más robustos a esas variaciones.
# ---------------------------------------------------------------------------
CATEGORY_PATTERN = re.compile(r"^CATEGORIA:\s*(.+)$", re.IGNORECASE)
RULE_PATTERN = re.compile(
    r"^\s*\[(PASS|FAIL|WARN|ERROR|INFO)\]\s*(R\d+)?\s*[-–]?\s*(.+?)(?::\s*(.+))?$",
    re.IGNORECASE,
)

# Mapeo de resultado a severidad (schema de annotations)
RESULT_TO_SEVERITY = {
    "PASS": "notice",
    "INFO": "notice",
    "WARN": "warning",
    "WARNING": "warning",
    "FAIL": "failure",
    "ERROR": "failure",
}


def parse_analyzer_log(input_path: Path) -> dict:
    """
    Lee el log limpio del analyzer y produce la estructura de categorías y reglas.
    """
    categories = []
    current_category = None

    with open(input_path, encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            line = raw_line.rstrip()

            if not line or line.startswith("===") or line.startswith("---"):
                continue

            # Detectar inicio de categoría
            cat_match = CATEGORY_PATTERN.match(line)
            if cat_match:
                current_category = {
                    "name": cat_match.group(1).strip(),
                    "rules": [],
                    "summary": {"pass": 0, "fail": 0, "warn": 0},
                }
                categories.append(current_category)
                continue

            # Detectar regla
            rule_match = RULE_PATTERN.match(line)
            if rule_match and current_category is not None:
                result_raw = rule_match.group(1).upper()
                rule_id    = rule_match.group(2) or f"L{line_num:04d}"
                description = rule_match.group(3).strip() if rule_match.group(3) else ""
                detail      = rule_match.group(4).strip() if rule_match.group(4) else ""

                result_normalized = result_raw if result_raw in ("PASS", "FAIL", "WARN") else "FAIL"
                severity = RESULT_TO_SEVERITY.get(result_raw, "failure")

                rule = {
                    "rule_id": rule_id,
                    "result": result_normalized,
                    "severity": severity,
                    "description": description,
                    "detail": detail,
                    "raw_line": line.strip(),
                    "line_number": line_num,
                }
                current_category["rules"].append(rule)

                # Actualizar summary de la categoría
                if result_normalized == "PASS":
                    current_category["summary"]["pass"] += 1
                elif result_normalized == "FAIL":
                    current_category["summary"]["fail"] += 1
                else:
                    current_category["summary"]["warn"] += 1

            # Si no matchea ningún patrón pero hay texto, lo guardamos como nota
            elif current_category is not None and line.strip():
                current_category["rules"].append({
                    "rule_id": f"NOTE-L{line_num:04d}",
                    "result": "INFO",
                    "severity": "notice",
                    "description": line.strip(),
                    "detail": "",
                    "raw_line": line.strip(),
                    "line_number": line_num,
                })

    # Calcular total_summary
    total = {"pass": 0, "fail": 0, "warn": 0}
    for cat in categories:
        for k in total:
            total[k] += cat["summary"][k]

    return {
        "categories": categories,
        "total_summary": total,
        "parsed_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Parse analyzer clean log to structured JSON")
    parser.add_argument("--input",  required=True, help="Path to analyzer_clean.log")
    parser.add_argument("--output", required=True, help="Path to output analyzer_structured.json")
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Si el archivo está vacío, generar estructura mínima válida
    if input_path.stat().st_size == 0:
        print("WARN: Input file is empty. Generating minimal valid structure.")
        structured = {
            "categories": [],
            "total_summary": {"pass": 0, "fail": 0, "warn": 0},
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "warning": "Input file was empty — no analyzer data available",
        }
    else:
        structured = parse_analyzer_log(input_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(structured, f, indent=2, ensure_ascii=False)

    total = structured["total_summary"]
    print(f"OK: {len(structured['categories'])} categorías parseadas")
    print(f"    PASS={total['pass']} FAIL={total['fail']} WARN={total['warn']}")
    print(f"    Output: {output_path}")


if __name__ == "__main__":
    main()
