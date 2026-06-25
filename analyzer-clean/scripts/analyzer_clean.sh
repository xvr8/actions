#!/usr/bin/env bash
# =============================================================================
# SCRIPT: analyzer_clean.sh
# RUTA: scripts/analyzer_clean.sh
#
# PROPOSITO:
#   Extraer la sección relevante del output raw del analyzer.
#   El analyzer de Databricks produce mucho ruido (headers de Spark, timestamps,
#   logs internos de JVM). Solo nos interesa lo que viene después de un patrón
#   específico como "VISTA POR CATEGORIAS".
#
# POR QUE ESTE SCRIPT Y NO INLINE EN EL WORKFLOW:
#   - El workflow YAML se vuelve ilegible con lógica bash compleja.
#   - Este script es testeable localmente antes de hacer push.
#   - El fallback y la lógica de detección de patrones están centralizados aquí.
#
# USO:
#   bash scripts/analyzer_clean.sh \
#     --input  logs/analyzer_raw.log \
#     --output logs/analyzer_clean.log \
#     --pattern "VISTA POR CATEGORIAS"
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Parseo de argumentos
# ---------------------------------------------------------------------------
INPUT_FILE=""
OUTPUT_FILE=""
PATTERN="VISTA POR CATEGORIAS"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)   INPUT_FILE="$2";  shift 2 ;;
    --output)  OUTPUT_FILE="$2"; shift 2 ;;
    --pattern) PATTERN="$2";     shift 2 ;;
    *) echo "Argumento desconocido: $1"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Validaciones de entrada
# ---------------------------------------------------------------------------
if [[ -z "$INPUT_FILE" || -z "$OUTPUT_FILE" ]]; then
  echo "ERROR: --input y --output son requeridos"
  exit 1
fi

if [[ ! -f "$INPUT_FILE" ]]; then
  echo "ERROR: El archivo de input no existe: $INPUT_FILE"
  exit 1
fi

if [[ ! -s "$INPUT_FILE" ]]; then
  echo "WARN: El archivo de input está vacío: $INPUT_FILE"
  # Crear output vacío para que el siguiente step no falle por archivo faltante
  touch "$OUTPUT_FILE"
  exit 0
fi

# ---------------------------------------------------------------------------
# Extracción de la sección relevante
#
# LOGICA:
#   sed -n '/PATRON/,$ p'
#   - -n          : no imprimir por defecto
#   - /PATRON/,$  : desde la línea que matchea PATRON hasta fin de archivo
#   - p           : imprimir esas líneas
#
# POR QUE sed Y NO grep/awk:
#   sed con rango de dirección es la forma más portable de hacer "desde aquí
#   hasta el final". grep -A no tiene conteo infinito en todos los sistemas.
# ---------------------------------------------------------------------------
echo "INFO: Buscando patrón: '$PATTERN' en $INPUT_FILE"

PATTERN_LINE=$(grep -n "$PATTERN" "$INPUT_FILE" | head -1 | cut -d: -f1)

if [[ -z "$PATTERN_LINE" ]]; then
  echo "WARN: Patrón '$PATTERN' no encontrado en $INPUT_FILE"
  echo "WARN: Aplicando fallback — usando archivo completo como output"
  cp "$INPUT_FILE" "$OUTPUT_FILE"
  echo "::warning::Patrón '$PATTERN' no encontrado. Se usó el log completo como fallback."
else
  echo "INFO: Patrón encontrado en línea $PATTERN_LINE"
  sed -n "${PATTERN_LINE},\$ p" "$INPUT_FILE" > "$OUTPUT_FILE"
  echo "INFO: Sección extraída: $(wc -l < "$OUTPUT_FILE") líneas"
fi

# ---------------------------------------------------------------------------
# Verificación final
# ---------------------------------------------------------------------------
if [[ ! -s "$OUTPUT_FILE" ]]; then
  echo "WARN: El output quedó vacío. Aplicando fallback completo."
  cp "$INPUT_FILE" "$OUTPUT_FILE"
fi

echo "OK: analyzer_clean.log generado → $OUTPUT_FILE ($(wc -l < "$OUTPUT_FILE") líneas)"
