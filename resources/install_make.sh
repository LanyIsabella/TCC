#!/usr/bin/env bash
set -euo pipefail

log() {
  printf "[install_make] %s\n" "$*"
}

fail() {
  printf "[install_make][erro] %s\n" "$*" >&2
  exit 1
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
  if command -v make >/dev/null 2>&1; then
    log "make ja esta disponivel no macOS."
    return
  fi

  if ! command -v brew >/dev/null 2>&1; then
    fail "Homebrew nao encontrado. Instale o Homebrew ou as Command Line Tools (xcode-select --install)."
  fi

  log "Instalando GNU Make via Homebrew..."
  brew install make

  # O Homebrew instala como gmake e oferece um diretorio gnubin com o comando make.
  local brew_prefix
  brew_prefix="$(brew --prefix)"
  local gnubin_dir="${brew_prefix}/opt/make/libexec/gnubin"
  if [[ -d "${gnubin_dir}" ]]; then
    export PATH="${gnubin_dir}:${PATH}"
  fi
}

install_make_windows() {
  if command -v winget >/dev/null 2>&1; then
    log "Instalando make via winget (ezwinports.make)..."
    winget install --id ezwinports.make -e --accept-package-agreements --accept-source-agreements --disable-interactivity
    return
  fi

  if command -v choco >/dev/null 2>&1; then
    log "Instalando make via Chocolatey..."
    choco install make -y
    return
  fi

  if command -v scoop >/dev/null 2>&1; then
    log "Instalando make via Scoop..."
    scoop install make
    return
  fi

  fail "Nao foi encontrado winget, choco ou scoop para instalar make no Windows."
}

detect_os_and_install() {
  local os
  os="$(uname -s 2>/dev/null || true)"

  case "${os}" in
    Linux*)
      log "Sistema identificado: Linux"
      install_make_linux
      ;;
    Darwin*)
      log "Sistema identificado: macOS"
      install_make_macos
      ;;
    MINGW*|MSYS*|CYGWIN*)
      log "Sistema identificado: Windows (${os})"
      install_make_windows
      ;;
    *)
      fail "Sistema operacional nao suportado: ${os:-desconhecido}"
      ;;
  esac
}

validate_installation() {
  if command -v make >/dev/null 2>&1; then
    log "Instalacao concluida: $(make --version | head -n 1)"
    return
  fi

  fail "A instalacao terminou, mas o comando 'make' nao esta no PATH atual. Abra um novo terminal e tente novamente."
}

main() {
  if command -v make >/dev/null 2>&1; then
    log "make ja esta instalado: $(make --version | head -n 1)"
    exit 0
  fi

  detect_os_and_install
  validate_installation
}

main "$@"
