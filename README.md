# Setup Automatizado do Projeto

Este projeto possui scripts na pasta `resources` para instalar as dependencias de ambiente:

- `resources/install_make.sh`
- `resources/install_uv.sh`
- `resources/install_ollama.sh`

## 1) Instalar o `make` (detecta Win/macOS/Linux automaticamente)

```bash
bash resources/install_make.sh
```

## 2) Executar todos os scripts de setup automaticamente

```bash
make setup
```

O alvo `setup` executa todos os scripts `install_*.sh` da pasta `resources` em ordem.

## Comandos uteis

Listar scripts encontrados:

```bash
make scripts
```

Executar apenas um script especifico:

```bash
make run script=resources/install_uv.sh
```

## Fluxo manual (sem Makefile)

Se preferir rodar sem `make`:

```bash
bash resources/install_make.sh
bash resources/install_uv.sh
bash resources/install_ollama.sh
```
