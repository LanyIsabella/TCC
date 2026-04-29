#!/usr/bin/env bash
set -euo pipefail

log() {
  printf "[install_uv] %s\n" "$*"
}

fail() {
  printf "[install_uv][erro] %s\n" "$*" >&2
  exit 1
}

install_uv_unix() {
  if command -v curl >/dev/null 2>&1; then
    log "Instalando uv com curl..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    return
  fi

  if command -v wget >/dev/null 2>&1; then
    log "Instalando uv com wget..."
    wget -qO- https://astral.sh/uv/install.sh | sh
    return
  fi

  fail "Nem curl nem wget estao disponiveis para instalar o uv."
}

install_uv_windows() {
  if command -v powershell.exe >/dev/null 2>&1; then
    log "Instalando uv via PowerShell (Windows)..."
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    return
  fi

  if command -v pwsh.exe >/dev/null 2>&1; then
    log "Instalando uv via PowerShell Core (Windows)..."
    pwsh.exe -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
    return
  fi

  fail "PowerShell nao encontrado para instalar uv no Windows."
}

detect_os_and_install() {
  local os
  os="$(uname -s 2>/dev/null || true)"

  case "${os}" in
    Linux*)
      log "Sistema identificado: Linux"
      install_uv_unix
      ;;
    Darwin*)
      log "Sistema identificado: macOS"
      install_uv_unix
      ;;
    MINGW*|MSYS*|CYGWIN*)
      log "Sistema identificado: Windows (${os})"
      install_uv_windows
      ;;
    *)
      fail "Sistema operacional nao suportado por este script: ${os:-desconhecido}"
      ;;
  esac
}

main() {
  detect_os_and_install
  log "Instalacao finalizada."
  log "Se o comando 'uv' nao estiver disponivel nesta sessao, abra um novo terminal."
}

main "$@"