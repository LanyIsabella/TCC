# Setup Automatizado do Projeto

Este projeto possui scripts na pasta `resources` para instalar as dependencias de ambiente:

- `resources/install_make.sh`
- `resources/install_uv.sh`
- `resources/install_ollama.sh`

## 1) Instalar o `make` (detecta Win/macOS/Linux automaticamente)

Linux/macOS:

```bash
./resources/install_make.sh
```
 
## Teste de acesso ao GEDWeb com Playwright

O teste é executado somente quando solicitado, pois depende da VPN/restrição de IP do GEDWeb:

```powershell
uv sync
uv run playwright install chromium
$env:RUN_GEDWEB_PLAYWRIGHT="1"
uv run pytest -q tests/test_gedweb_playwright.py
```

Para testar outro endereço, configure `GEDWEB_PLAYWRIGHT_URL`.

Windows (PowerShell em modo Administrador, sem `bash`):

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1')); choco install make -y
```

## 2) Executar todos os scripts de setup automaticamente

```bash
make setup
```

Esse comando executa automaticamente todos os scripts `install_*.sh` da pasta `resources` em ordem.

Tambem e aceito:

```bash
make install
```

## Setup em Um Comando

```bash
make install
```

## API Key da WebSearch (LangSearch)

Para criar a conta e obter sua API Key da tool de WebSearch, acesse:

- https://langsearch.com/login

Depois, configure no `.env`:

```env
LANGSEARCH_API_KEY=sua_api_key_aqui
```

## Fluxo manual (sem Makefile)

Linux/macOS:

```bash
./resources/install_make.sh
./resources/install_uv.sh
./resources/install_ollama.sh
```

## Observacao (Windows)

Se o `make` ainda nao estiver disponivel apos instalacao, feche e abra o terminal para atualizar o `PATH`, depois rode:

```bash
make install
```
