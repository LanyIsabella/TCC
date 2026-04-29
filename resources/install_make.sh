#!/usr/bin/env bash
set -euo pipefail

OS_FAMILY=""

log() {
  printf "[install_make] %s\n" "$*"
}

fail() {
  printf "[install_make][erro] %s\n" "$*" >&2
  exit 1
}

has_make() {
  command -v make >/dev/null 2>&1
}

make_version_line() {
  make --version 2>/dev/null | head -n 1 || true
}

get_windows_shell() {
  if command -v powershell.exe >/dev/null 2>&1; then
    printf "%s" "powershell.exe"
    return
  fi

  if command -v pwsh.exe >/dev/null 2>&1; then
    printf "%s" "pwsh.exe"
    return
  fi

  fail "PowerShell nao encontrado no Windows."
}

is_windows_admin() {
  local ps
  ps="$(get_windows_shell)"
  local out
  out="$("${ps}" -NoProfile -ExecutionPolicy Bypass -Command "([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)" 2>/dev/null | tr -d '\r' | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  [[ "${out}" == "true" ]]
}

run_as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return
  fi

  fail "Privilegios de root necessarios para executar: $*"
}

detect_os_family() {
  local os
  os="$(uname -s 2>/dev/null || true)"

  case "${os}" in
    Linux*)
      OS_FAMILY="linux"
      ;;
    Darwin*)
      OS_FAMILY="macos"
      ;;
    MINGW*|MSYS*|CYGWIN*)
      OS_FAMILY="windows"
      ;;
    *)
      fail "Sistema operacional nao suportado: ${os:-desconhecido}"
      ;;
  esac
}

install_make_linux() {
  if command -v apt-get >/dev/null 2>&1; then
    log "Instalando make via apt-get..."
    run_as_root apt-get update
    run_as_root apt-get install -y make
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    log "Instalando make via dnf..."
    run_as_root dnf install -y make
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    log "Instalando make via yum..."
    run_as_root yum install -y make
    return
  fi

  if command -v pacman >/dev/null 2>&1; then
    log "Instalando make via pacman..."
    run_as_root pacman -Sy --noconfirm make
    return
  fi

  if command -v zypper >/dev/null 2>&1; then
    log "Instalando make via zypper..."
    run_as_root zypper --non-interactive install make
    return
  fi

  if command -v apk >/dev/null 2>&1; then
    log "Instalando make via apk..."
    run_as_root apk add --no-cache make
    return
  fi

  fail "Nao foi encontrado um gerenciador de pacotes suportado para Linux."
}

install_make_macos() {
  if has_make; then
    log "make ja esta disponivel no macOS: $(make_version_line)"
    return
  fi

  if command -v brew >/dev/null 2>&1; then
    log "Instalando make via Homebrew..."
    brew install make
    return
  fi

  fail "Nao foi possivel instalar make automaticamente no macOS. Instale o Homebrew ou execute: xcode-select --install"
}

try_winget_install() {
  local package_id="$1"
  winget install --id "${package_id}" -e --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
}

install_chocolatey_windows() {
  if command -v choco >/dev/null 2>&1; then
    log "Chocolatey ja esta instalado."
    return
  fi

  if ! is_windows_admin; then
    fail "Para instalar Chocolatey e make no Windows, execute este script em terminal com permissao de Administrador."
  fi

  local ps
  ps="$(get_windows_shell)"
  log "Instalando Chocolatey..."
  "${ps}" -NoProfile -ExecutionPolicy Bypass -Command "Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))"

  # Chocolatey geralmente instala em C:/ProgramData/chocolatey/bin.
  if [[ -d "C:/ProgramData/chocolatey/bin" && ":${PATH}:" != *":C:/ProgramData/chocolatey/bin:"* ]]; then
    PATH="C:/ProgramData/chocolatey/bin:${PATH}"
  fi

  if command -v choco >/dev/null 2>&1; then
    log "Chocolatey instalado com sucesso."
    return
  fi

  fail "Chocolatey foi instalado, mas nao esta no PATH atual. Feche e abra o terminal e execute novamente."
}

install_make_windows() {
  if has_make; then
    log "make ja esta disponivel no Windows: $(make_version_line)"
    return
  fi

  install_chocolatey_windows

  if command -v choco >/dev/null 2>&1; then
    log "Instalando make via Chocolatey..."
    choco install make -y
    return
  fi

  # Fallbacks de contingencia, caso o ambiente bloqueie o Chocolatey.
  if command -v winget >/dev/null 2>&1; then
    log "Chocolatey indisponivel nesta sessao. Tentando winget (ezwinports.make)..."
    if try_winget_install "ezwinports.make"; then
      log "Instalacao via winget concluida."
      return
    fi
    log "Falha com ezwinports.make. Tentando GnuWin32.Make..."
    if try_winget_install "GnuWin32.Make"; then
      log "Instalacao via winget concluida."
      return
    fi
  fi

  if command -v scoop >/dev/null 2>&1; then
    log "Tentando instalar make via Scoop..."
    scoop install make
    return
  fi

  fail "Nao foi possivel instalar make no Windows (Chocolatey/winget/scoop)."
}

add_windows_common_paths() {
  local path_candidates=()

  if [[ -n "${LOCALAPPDATA:-}" ]]; then
    path_candidates+=("${LOCALAPPDATA}/Microsoft/WinGet/Links")
    path_candidates+=("${LOCALAPPDATA}/Microsoft/WinGet/Packages/ezwinports.make_Microsoft.Winget.Source_8wekyb3d8bbwe/bin")
    path_candidates+=("${LOCALAPPDATA}/Microsoft/WinGet/Packages/GnuWin32.Make_Microsoft.Winget.Source_8wekyb3d8bbwe/bin")
    path_candidates+=("${LOCALAPPDATA}/scoop/shims")
  fi

  if [[ -n "${USERPROFILE:-}" ]]; then
    path_candidates+=("${USERPROFILE}/scoop/shims")
  fi

  path_candidates+=("C:/ProgramData/chocolatey/bin")
  path_candidates+=("C:/Program Files/GnuWin32/bin")

  local candidate
  for candidate in "${path_candidates[@]}"; do
    if [[ -d "${candidate}" && ":${PATH}:" != *":${candidate}:"* ]]; then
      PATH="${candidate}:${PATH}"
    fi
  done
}

validate_installation() {
  if has_make; then
    log "Instalacao concluida: $(make_version_line)"
    return
  fi

  if [[ "${OS_FAMILY}" == "windows" ]]; then
    add_windows_common_paths
    if has_make; then
      log "Instalacao concluida apos atualizar PATH da sessao: $(make_version_line)"
      return
    fi

    fail "make foi instalado, mas ainda nao esta no PATH desta sessao. Feche e abra o terminal e execute novamente."
  fi

  fail "A instalacao terminou, mas o comando 'make' nao esta no PATH atual."
}

main() {
  detect_os_family

  if has_make; then
    log "make ja esta instalado: $(make_version_line)"
    exit 0
  fi

  case "${OS_FAMILY}" in
    linux)
      log "Sistema identificado: Linux"
      install_make_linux
      ;;
    macos)
      log "Sistema identificado: macOS"
      install_make_macos
      ;;
    windows)
      log "Sistema identificado: Windows"
      install_make_windows
      ;;
  esac

  validate_installation
}

main "$@"
