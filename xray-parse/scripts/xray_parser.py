#!/usr/bin/env python3
"""
SCRIPT: xray_parser.py
RUTA: scripts/xray_parser.py

PROPOSITO:
    Parsear el output de Xray (análisis de dependencias/vulnerabilidades)
    y producir xray_structured.json con un esquema normalizado.

FORMATO DE ENTRADA SOPORTADO:
    El script soporta dos formatos comunes de Xray/dependency scanners:

    Formato 1 — texto tabulado:
        [HIGH]   CVE-2023-1234   log4j:2.14.0        Remote code execution via JNDI
        [MEDIUM] CVE-2023-5678   jackson-databind:2.9 Deserialization vulnerability
        [LOW]    CVE-2022-9999   commons-text:1.9     String interpolation issue

    Formato 2 — JSON nativo (JFrog Xray, OWASP dependency-check):
        {"vulnerabilities": [{"cve": "...", "severity": "...", ...}]}

FORMATO DE SALIDA (xray_structured.json):
    {
      "vulnerabilities": [
        {
          "cve": "CVE-2023-1234",
          "severity": "high",
          "package": "log4j",
          "version": "2.14.0",
          "description": "Remote code execution via JNDI",
          "fixed_version": ""
        }
      ],
      "summary": { "critical": 0, "high": 1, "medium": 1, "low": 1 },
      "parsed_at": "..."
    }

USO:
    python scripts/xray_parser.py \
        --input  logs/xray_raw.log \
        --output artifacts/xray_structured.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# Regex para formato texto tabulado
TEXT_LINE_PATTERN = re.compile(
    r"\[(CRITICAL|HIGH|MEDIUM|LOW|INFO)\]\s+(CVE-[\w-]+|NO-CVE|N/A)?\s*"
    r"([\w.-]+):([\w.-]+)?\s*(.*)?",
    re.IGNORECASE,
)

VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}


def parse_text_format(content: str) -> list[dict]:
    vulnerabilities = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        match = TEXT_LINE_PATTERN.match(line)
        if match:
            sev     = match.group(1).lower()
            cve     = match.group(2) or "NO-CVE"
            package = match.group(3) or "unknown"
            version = match.group(4) or ""
            desc    = match.group(5).strip() if match.group(5) else ""

            vulnerabilities.append({
                "cve": cve,
                "severity": sev,
                "package": package,
                "version": version,
                "description": desc,
                "fixed_version": "",
            })

    return vulnerabilities


def parse_json_format(content: str) -> list[dict]:
    """Parsea formato JSON nativo de JFrog Xray u OWASP dependency-check."""
    data = json.loads(content)

    # Soporte para múltiples formatos JSON
    # Formato JFrog Xray
    if "vulnerabilities" in data:
        raw_vulns = data["vulnerabilities"]
    # Formato OWASP dependency-check
    elif "dependencies" in data:
        raw_vulns = []
        for dep in data.get("dependencies", []):
            for vuln in dep.get("vulnerabilities", []):
                vuln["package"] = dep.get("fileName", "unknown")
                raw_vulns.append(vuln)
    else:
        return []

    normalized = []
    for vuln in raw_vulns:
        sev_raw = (vuln.get("severity") or vuln.get("cvssv3", {}).get("baseSeverity", "low")).lower()
        sev = sev_raw if sev_raw in VALID_SEVERITIES else "low"

        normalized.append({
            "cve": vuln.get("cve") or vuln.get("name") or "NO-CVE",
            "severity": sev,
            "package": vuln.get("package") or vuln.get("component", "unknown"),
            "version": vuln.get("version", ""),
            "description": vuln.get("description", ""),
            "fixed_version": vuln.get("fixedVersions", [""])[0] if isinstance(
                vuln.get("fixedVersions"), list
            ) else vuln.get("fixed_version", ""),
        })

    return normalized


def calculate_summary(vulnerabilities: list[dict]) -> dict:
    summary = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for vuln in vulnerabilities:
        sev = vuln.get("severity", "low")
        summary[sev] = summary.get(sev, 0) + 1
    return summary


def main():
    parser = argparse.ArgumentParser(description="Parse Xray output to structured JSON")
    parser.add_argument("--input",  required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists() or input_path.stat().st_size == 0:
        print("WARN: Xray input vacío. Generando estructura mínima.")
        result = {
            "vulnerabilities": [],
            "summary": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "warning": "No Xray data available",
        }
    else:
        content = input_path.read_text(encoding="utf-8", errors="replace")

        # Detectar formato: intentar JSON primero, luego texto
        vulnerabilities = []
        try:
            vulnerabilities = parse_json_format(content)
            print("INFO: Formato detectado: JSON")
        except (json.JSONDecodeError, KeyError):
            vulnerabilities = parse_text_format(content)
            print("INFO: Formato detectado: texto tabulado")

        result = {
            "vulnerabilities": vulnerabilities,
            "summary": calculate_summary(vulnerabilities),
            "parsed_at": datetime.now(timezone.utc).isoformat(),
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    s = result["summary"]
    print(f"OK: xray_structured.json generado — {len(result['vulnerabilities'])} vulnerabilidades")
    print(f"    CRITICAL={s['critical']} HIGH={s['high']} MEDIUM={s['medium']} LOW={s['low']}")
    print(f"    Output: {output_path}")


if __name__ == "__main__":
    main()
