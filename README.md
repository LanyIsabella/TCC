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

## Inventário e tabela bronze no PostgreSQL

O script `data/bronze_postgres.py` coleta os arquivos de `data/raw/`, incluindo
metadados do sistema de arquivos, metadados internos dos PDFs, texto extraído,
hash SHA-256 e dados disponíveis no manifesto. A execução padrão cria a tabela
e faz o upsert diretamente no banco.

A extração de conteúdo usa o GLM-OCR local via Ollama, conforme
`config/glmocr.yaml`. Antes da carga, deixe o Ollama em execução e baixe o
modelo configurado:

```powershell
ollama pull glm-ocr:latest
```

Na primeira execução, o GLM-OCR também poderá baixar o detector de layout
`PaddlePaddle/PP-DocLayoutV3_safetensors` do Hugging Face. Esse detector está
configurado para CPU em `config/glmocr.yaml`.

Em uma máquina sem GPU, o pipeline oficial pode ficar muito lento no detector
de layout. Nesse caso, o modo direto opcional envia uma imagem por página ao
`/api/generate`, usando o mesmo modelo GLM-OCR, e rejeita respostas truncadas:

```powershell
$env:RAG_GLM_OCR_MODE="direct_ollama"
uv run python data/rag_pipeline.py extract --document-id 8 --extractor glm_ocr
```

O modo padrão continua sendo `package`; selecione `direct_ollama` somente de
forma explícita. O modo direto começa com `GLMOCR_DIRECT_MAX_TOKENS` e, se o
Ollama informar `done_reason=length`, repete a página aumentando o limite até
`GLMOCR_DIRECT_RETRY_MAX_TOKENS` (padrão do projeto: 16384 e 32768). O contexto
usado nessa rota é controlado por `GLMOCR_DIRECT_CONTEXT`. Páginas quase vazias
são identificadas antes da chamada visual e registradas sem texto, evitando loops
de geração em marcas d’água e carimbos.

Nesse modo, o Docling é configurado somente como referência/fallback, com OCR
e análise de layout desativados; assim, o RapidOCR não é carregado novamente
no Bronze e no Silver enquanto o GLM-OCR visual está sendo usado.

Se uma página não puder ser processada visualmente, a extração por página tenta
Docling e depois o texto nativo do PDF quando disponíveis. O fallback fica
registrado em `structured_output`. Em falhas de conexão ou timeout, o texto
nativo é usado quando disponível; caso contrário, o Docling da Bronze continua
como fonte principal. A ocorrência permanece registrada no diagnóstico, sem
ser apresentada como OCR confirmado do GLM. O timeout padrão dessa chamada é
120 s; depois do primeiro timeout no processamento de um PDF, as páginas
restantes não repetem chamadas ao Ollama indisponível.

O pipeline executa os dois extratores. Na tabela bronze, os resultados ficam em
`content_text_docling` e `content_text_glmocr`; `content_text` usa o GLM-OCR
quando a saída passa pela verificação de qualidade e usa Docling como fallback
quando a resposta está vazia, muito curta ou corrompida. O extrator de arquivos
também grava as versões em `data/processed/docling/` e `data/processed/glmocr/`.

```powershell
uv sync
uv run python data/bronze_postgres.py
```

Configure no `.env` as mesmas variáveis de banco documentadas em
`.env.example` (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` e `DB_PASSWORD`). Para
gerar um inventário sem carregar no banco, use opcionalmente:

```powershell
uv run python data/bronze_postgres.py --review-only
```

A tabela padrão é `bronze.documents` e usa `relative_path` como chave única. A
carga normal persiste cada arquivo imediatamente; se um PDF posterior falhar,
os arquivos anteriores permanecem carregados. A carga pode ser repetida:
arquivos novos são inseridos e arquivos já existentes são atualizados sem
duplicidade.

## Pipeline Silver/Gold e RAG vetorial

Para executar o fluxo completo em uma única chamada, use:

```powershell
uv run python data/run_pipeline.py
```

O orquestrador executa, nesta ordem, Bronze, schema, extração, avaliação,
promoção para Gold, embeddings e validação. Como a Bronze já pode estar
carregada, é possível pular somente essa etapa:

```powershell
uv run python data/run_pipeline.py --skip-bronze --direct-glm-ocr
```

Para um documento específico, use `--document-id <record_id>`. O pipeline é
fail-fast: se uma etapa falhar, as seguintes não são executadas. Para retomar
páginas com erro ou interrompidas, acrescente `--retry-errors`; para conferir os comandos sem
executá-los, use `--dry-run`. As etapas também podem ser puladas individualmente
com `--skip-init-db`, `--skip-extract`, `--skip-evaluate`, `--skip-activate`,
`--skip-embed` e `--skip-validate`.

O pipeline usa SQL direto e `psycopg`, sem SQLAlchemy ou migrations. Inicialize
as tabelas, índices e a view de comparação com:

```powershell
uv run python data/rag_pipeline.py init-db
```

Extraia cada documento por página com os dois extratores. Cada página é salva
imediatamente e páginas com sucesso não são repetidas:

```powershell
uv run python data/rag_pipeline.py extract --extractor all
```

Para retomar páginas que falharam ou ficaram interrompidas:

```powershell
uv run python data/rag_pipeline.py extract --extractor all --retry-errors
```

Se o modelo avaliador não devolver JSON válido, a segunda tentativa usa texto
apenas; persistindo a falha, é registrada uma avaliação determinística neutra
com `requires_manual_review=true`, permitindo a continuidade sem declarar uma
avaliação semântica inexistente.

No embedding, páginas que excedem o contexto do Ollama são divididas em trechos
sem truncar o conteúdo; os vetores dos trechos são combinados em um vetor da
página para manter o contrato do índice Gold.

Avalie as extrações página por página e depois ative a melhor variante na Gold:

```powershell
uv run python data/rag_pipeline.py evaluate --extractor all
uv run python data/rag_pipeline.py evaluate --extractor all --retry-errors
uv run python data/rag_pipeline.py activate 1
```

`activate` exige que todas as páginas da variante escolhida estejam avaliadas
com sucesso e que Docling e GLM-OCR estejam completos e avaliados, para que a
comparação seja válida. Para uma promoção experimental sem essa validação,
use explicitamente `activate <record_id> --allow-unvalidated`.

O modelo de embeddings é `nomic-embed-text`, via `POST /api/embed`, sempre com
`truncate=false`. A indexação usa `search_document: ` e as consultas usam
`search_query: ``, com um vetor independente por página:

```powershell
uv run python data/rag_pipeline.py embed
uv run python data/rag_pipeline.py embed --retry-errors
uv run python data/rag_pipeline.py search "como estruturar um resumo acadêmico?"
uv run python data/rag_pipeline.py validate --document-id 8
```

`search` retorna o documento completo de `gold.gold_rag_documents.full_text`,
agrupando as páginas apenas para localizar os documentos relevantes.
O campo `context_warning` registra quando a estimativa de tokens excede
`RAG_CONTEXT_TOKEN_LIMIT`; o conteúdo integral continua sendo retornado, sem
truncamento silencioso.

A mesma consulta combina a busca vetorial nas páginas com PostgreSQL Full-Text
Search em português nas páginas e no documento completo. Para uma busca textual
direta, use `websearch_to_tsquery('portuguese', 'termos ou "expressão exata"')`
contra `gold.gold_rag_documents.search_vector` ou
`gold.gold_rag_page_index.search_vector`.

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
