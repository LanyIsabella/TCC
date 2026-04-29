#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"
DEFAULT_MODEL="gemma4:e2b"

log() {
  printf "[install_ollama] %s\n" "$*"
}

fail() {
  printf "[install_ollama][erro] %s\n" "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Comando obrigatorio ausente: $1"
}

resolve_model() {
  if [[ -n "${OLLAMA_MODEL:-}" ]]; then
    printf "%s" "${OLLAMA_MODEL}"
    return
  fi

  if [[ -f "${ENV_FILE}" ]]; then
    local line
    line="$(
      grep -E '^[[:space:]]*OLLAMA_MODEL=' "${ENV_FILE}" \
        | tail -n 1 \
        | cut -d '=' -f 2- \
        | tr -d '\r'
    )"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    line="${line%\"}"
    line="${line#\"}"
    line="${line%\'}"
    line="${line#\'}"

    if [[ -n "${line}" ]]; then
      printf "%s" "${line}"
      return
    fi
  fi

  printf "%s" "${DEFAULT_MODEL}"
}

install_ollama_unix() {
  require_cmd curl
  log "Instalando Ollama via script oficial para Linux/macOS..."
  curl -fsSL https://ollama.com/install.sh | sh
}

install_ollama_windows() {
  if command -v powershell.exe >/dev/null 2>&1; then
    log "Instalando Ollama via PowerShell (Windows)..."
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://ollama.com/install.ps1 | iex"
    return
  fi

  if command -v pwsh.exe >/dev/null 2>&1; then
    log "Instalando Ollama via PowerShell Core (Windows)..."
    pwsh.exe -NoProfile -Command "irm https://ollama.com/install.ps1 | iex"
    return
  fi

  fail "PowerShell nao encontrado para instalar no Windows."
}

detect_os_and_install() {
  local os
  os="$(uname -s 2>/dev/null || true)"

  case "${os}" in
    Linux*)
      log "Sistema identificado: Linux"
      install_ollama_unix
      ;;
    Darwin*)
      log "Sistema identificado: macOS"
      install_ollama_unix
      ;;
    MINGW*|MSYS*|CYGWIN*)
      log "Sistema identificado: Windows (${os})"
      install_ollama_windows
      ;;
    *)
      fail "Sistema operacional nao suportado por este script: ${os:-desconhecido}"
      ;;
  esac
}

pull_model() {
  require_cmd ollama
  local model
  model="$(resolve_model)"

  log "Baixando modelo: ${model}"
  ollama pull "${model}"
  log "Modelo pronto: ${model}"
}

main() {
  if command -v ollama >/dev/null 2>&1; then
    log "Ollama ja esta instalado: $(ollama --version)"
  else
    detect_os_and_install
  fi

  pull_model
}

main "$@"
