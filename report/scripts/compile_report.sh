#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPORT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$REPORT_DIR/outputs"
LOG_DIR="$OUT_DIR/logs"
BUILD_LOG="$LOG_DIR/build.log"
WATCH_LOG="$LOG_DIR/watch.log"
PDF_PATH="$OUT_DIR/Thesis.pdf"
ROOT_TEX="Thesis.tex"

usage() {
  cat <<USAGE
Usage:
  bash scripts/compile_report.sh [build|watch]

Commands:
  build   Compile Thesis.tex once into outputs/Thesis.pdf (default)
  watch   Recompile automatically when report sources change
USAGE
}

have() {
  command -v "$1" >/dev/null 2>&1
}

require_toolchain() {
  if have latexmk; then
    echo "latexmk"
    return 0
  fi

  if have pdflatex && have bibtex; then
    echo "pdflatex"
    return 0
  fi

  cat >&2 <<'MSG'
No supported LaTeX toolchain found on PATH.

Install or activate one of:
  - latexmk
  - pdflatex and bibtex

Expected output path after a successful build:
  outputs/Thesis.pdf
MSG
  return 1
}

run_latexmk() {
  latexmk \
    -pdf \
    -g \
    -interaction=nonstopmode \
    -halt-on-error \
    -outdir="$OUT_DIR" \
    "$ROOT_TEX"
}

run_pdflatex_bibtex() {
  pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$OUT_DIR" "$ROOT_TEX"
  if grep -q '\\bibliography{' "$ROOT_TEX"; then
    (cd "$OUT_DIR" && bibtex Thesis)
  fi
  pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$OUT_DIR" "$ROOT_TEX"
  pdflatex -interaction=nonstopmode -halt-on-error -output-directory="$OUT_DIR" "$ROOT_TEX"
}

build_once() {
  mkdir -p "$OUT_DIR" "$LOG_DIR"
  cd "$REPORT_DIR"

  local toolchain
  toolchain="$(require_toolchain)"

  echo "Building report with $toolchain"
  echo "Log: $BUILD_LOG"

  if [[ "$toolchain" == "latexmk" ]]; then
    if run_latexmk >"$BUILD_LOG" 2>&1; then
      echo "PDF ready: $PDF_PATH"
      return 0
    fi
  else
    if run_pdflatex_bibtex >"$BUILD_LOG" 2>&1; then
      echo "PDF ready: $PDF_PATH"
      return 0
    fi
  fi

  echo "Build failed. See log: $BUILD_LOG" >&2
  return 1
}

source_fingerprint() {
  find "$REPORT_DIR" \
    -maxdepth 2 \
    \( -name '*.tex' -o -name '*.bib' -o -name '*.bst' -o -name '*.cls' -o -path "$REPORT_DIR/figures/*" \) \
    -type f \
    -printf '%T@ %p\n' \
    | sort
}

watch_loop() {
  mkdir -p "$OUT_DIR" "$LOG_DIR"
  cd "$REPORT_DIR"

  if have latexmk; then
    echo "Starting latexmk watcher"
    echo "Log: $WATCH_LOG"
    latexmk \
      -pdf \
      -pvc \
      -interaction=nonstopmode \
      -halt-on-error \
      -outdir="$OUT_DIR" \
      "$ROOT_TEX" \
      >"$WATCH_LOG" 2>&1
    return $?
  fi

  require_toolchain >/dev/null
  echo "Starting polling watcher"
  echo "Build log: $BUILD_LOG"
  echo "Watch log: $WATCH_LOG"
  echo "Polling watcher started at $(date -Is)" >"$WATCH_LOG"

  local previous current
  previous=""
  while true; do
    current="$(source_fingerprint)"
    if [[ "$current" != "$previous" ]]; then
      previous="$current"
      {
        echo "[$(date -Is)] Change detected. Rebuilding."
        if build_once; then
          echo "[$(date -Is)] Build succeeded: $PDF_PATH"
        else
          echo "[$(date -Is)] Build failed: $BUILD_LOG"
        fi
      } | tee -a "$WATCH_LOG"
    fi
    sleep 2
  done
}

main() {
  local command="${1:-build}"
  case "$command" in
    build)
      build_once
      ;;
    watch)
      watch_loop
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      usage >&2
      return 2
      ;;
  esac
}

main "$@"
