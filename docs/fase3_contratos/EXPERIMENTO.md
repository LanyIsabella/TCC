# Avaliação limitada do verificador com modelo real

O serviço local foi iniciado pelo usuário após o bloqueio da inicialização pelo
agente. O modelo já estava instalado; não houve download, ingestão, OCR,
embeddings ou acesso ao banco de produção nesta avaliação.

Foi exercitado o **verificador semântico real junto da política de fundamentação**,
com fontes e respostas sintéticas conhecidas. A geração da resposta inicial,
a recuperação documental e a fidelidade ao corpus ABNT não foram avaliadas aqui.
As fixtures são de desenvolvimento, sem holdout independente; não representam
uma amostra estatística dos usuários nem uma referência humana do corpus.

## Configuração e resultados observados

- Modelo: `gemma4:e2b`, digest
  `7fbdbf8f5e45a75bb122155ed546e765b4d9c53a1285f62fd9f506baa1c5a47e`.
- Temperatura **0,7**, preservada da configuração existente. Não foi ajustada
  para melhorar o resultado do ensaio. Seed e demais opções não configuradas
  não foram sobrescritas; repetir os mesmos insumos pode produzir outra saída.
- Ollama `0.30.11`, Python `3.13.13`; dependências e opções registradas em
  [experiment_runtime.json](artifacts/experiment_runtime.json).

| Execução | Versão avaliada | Cenários | Status conforme a expectativa |
|---|---|---:|---:|
| [Antes](artifacts/experiment_before.jsonl) | Versão intermediária da Fase 3 que passara nos 251 testes, antes do ensaio real | 18 | 9 |
| [Após correções iniciais](artifacts/experiment_after_1.jsonl) | Parser, unidades equivalentes e limites negados corrigidos | Os mesmos 18 | 18 |
| [Segunda repetição](artifacts/experiment_after_2.jsonl) | Também aceita metadados nulos de avaliações negativas sem descartar a parte sustentada | 18 + 1 parcial | 19 |
| [Terceira versão](artifacts/experiment_after_3.jsonl) | Inclui unidades singulares; recusa indevida preservada | 19 + 2 casos de unidade | **20 de 21** |
| [Quarta versão](artifacts/experiment_after_4.jsonl) | Prova dirigida de uso opcional para permissão | Os mesmos 21 | **21 de 21** |
| [Última inferência real](artifacts/experiment_final.jsonl) | Acrescenta controles de reescrita e pergunta implícita | 21 + 3 controles | **24 de 24** |

Cada JSONL preserva perguntas, afirmações, fontes sintéticas, saídas brutas do
modelo, decisão da aplicação, expectativa, tempos observados e hashes do código.
O [resumo estruturado](artifacts/experiment_summary.json) inclui a matriz por caso.
Os protocolos [v1](artifacts/experiment_protocol.json),
[v2](artifacts/experiment_protocol_v2.json) e
[v3](artifacts/experiment_protocol_v3.json),
[v4](artifacts/experiment_protocol_v4.json) e
[v5](artifacts/experiment_protocol_v5.json) preservam as fixtures e parâmetros.
Os 18 casos originais não foram alterados entre as execuções; as extensões estão
identificadas separadamente. Não se alegam ganhos gerais de latência a partir
dos tempos: carregamento, aquecimento e amostragem não foram controlados para
um benchmark de desempenho.

## Defeitos encontrados e correções por TDD

O modelo produziu JSON dentro de cercas Markdown. O parser original rejeitava
essa forma, causando recusas em afirmações sustentadas. Agora aceita somente
uma cerca JSON envolvendo a resposta inteira; prosa externa, JSON inválido e
campos indevidos continuam rejeitados pela validação estrita.

O avaliador também recusou uma conversão equivalente de unidades. Uma alteração
somente de quantidade/unidade pode agora ser comprovada deterministicamente
quando **o restante da sentença inteira coincide**, preservando dimensões e
valores. Isso não transforma sobreposição de palavras em prova. Formas
singulares e números por extenso já suportados também são reconhecidos.

“Não deve conter menos de 150 palavras” deixou de ser interpretado como negação
contraditória de “no mínimo 150 palavras”. Os testes também exigem rejeição de
limites opostos, preservando a distinção mínimo/máximo.

Em lotes de afirmações, avaliações negativas podem retornar ID/citação `null`.
Essas entradas não autorizam nenhuma afirmação e não devem invalidar outra
entrada positiva com prova válida. Uma avaliação positiva com prova nula
continua insuficiente.

Evidências Red–Green:

- [4 falhas e 3 aprovações](artifacts/real_model_regressions_red.xml) →
  [regressões aprovadas no conjunto ampliado](artifacts/real_model_regressions_green.xml).
- [1 falha e 5 aprovações](artifacts/null_assessment_red.xml) →
  [conjunto ampliado aprovado](artifacts/null_assessment_green.xml).
- [7 falhas em unidades](artifacts/singular_units_red.xml) →
  [conjunto ampliado aprovado](artifacts/singular_units_green.xml).
- [3 falhas de permissão opcional](artifacts/optional_permission_red.xml) →
  [conjunto ampliado aprovado](artifacts/optional_permission_green.xml).
- [4 falhas de intenção](artifacts/intent_edges_red.xml) →
  [conjunto ampliado aprovado](artifacts/intent_edges_green.xml).
- [2 falhas de flexão](artifacts/rewrite_inflection_red.xml) →
  [6 casos aprovados](artifacts/rewrite_inflection_green.xml).

Os fontes de cada versão foram preservados como texto, com manifests e hashes:
[antes](artifacts/source_before_experiment/manifest.json),
[após a primeira correção](artifacts/source_after_experiment_1/manifest.json),
[segunda repetição](artifacts/source_after_experiment_2/manifest.json),
[terceira versão](artifacts/source_after_experiment_3/manifest.json),
[quarta versão](artifacts/source_after_experiment_4/manifest.json),
[última inferência real](artifacts/source_after_experiment_5/manifest.json) e
[código final](artifacts/source_final/manifest.json).

## Limitação efetivamente observada

Na terceira versão (20/21), o modelo afirmou `supported=false` para “Você pode
usar negrito”, apesar da fonte “O uso de negrito é opcional”. A aplicação informou
insuficiência: uma recusa indevida do avaliador probabilístico, que havia aceitado
o mesmo cenário nas duas execuções anteriores. O parser aceitou o JSON.
O registro adverso permanece em `experiment_after_3.jsonl`.

A correção seguinte comprova uma implicação dirigida e genérica: uso opcional
de um objeto permite seu uso. Ela exige a mesma identidade do objeto e mantém
os controles de negação, condição e exceção. Permissão não comprova automaticamente
opcionalidade. Os testes cobrem negrito, itálico e caixa alta, além de objetos
distintos e escopos restritos. Não foi criada regra específica para “negrito”.
O ensaio seguinte avaliou código alterado e explicitamente versionado: 21/21.
A última execução real ampliou o protocolo para 24 controles: 24/24. Não houve
mudança de temperatura nem descarte de resultados adversos.

Uma correção posterior reconhece “margem” e “citação” no singular no detector
que impede reescritas normativas sem prova. Foram observadas duas falhas Red,
seguidas de seis aprovações Green. O código final reproduziu deterministicamente
as 24 decisões usando as saídas brutas da última execução real, com os mesmos
argumentos e quantidade de chamadas. Esse
[replay](artifacts/experiment_final_code_replay.json) não é nova inferência.
Os hashes do código real v5 e do código final são mantidos separadamente.

Não houve publicação de regra sem suporte nos casos negativos deste ensaio.
Isso é uma observação limitada às fixtures, não prova de ausência de alucinações
no sistema completo. O verificador ainda pode produzir outras recusas indevidas.

A revisão humana e a avaliação representativa do RAG completo permanecem como
trabalho posterior. A temperatura e a capacidade do modelo podem afetar as
recusas; alterar a configuração exigiria outro experimento controlado. Não se
iniciou essa alteração nem outra fase nesta entrega.

## Reprodução na versão entregue

Com o Ollama já disponível e o ambiente do projeto, a partir da raiz, o trecho
abaixo exercita as mesmas fixtures sem acessar o recuperador ou o banco. Cria
um novo arquivo, preservando as execuções originais. O protocolo v6 tem os
mesmos 24 cenários com hashes do código final; ainda não representa nova execução
real registrada. Para reproduzir versões
anteriores, use seus fontes arquivados em uma cópia isolada do projeto.

```powershell
@'
import hashlib, json, time, urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from src.app.agente import ScopedAgent
from src.app.client import Client
from src.app.grounding import ground_answer

art = Path('docs/fase3_contratos/artifacts')
protocol = json.loads((art/'experiment_protocol_v6.json').read_text(encoding='utf-8'))
for name, expected in protocol['source_sha256'].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name
client = Client()
assert client.model_name == protocol['model']
assert client.ollama_temperature == protocol['temperature']
with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=3) as response:
    models = json.load(response)['models']
assert next(m for m in models if m['name'] == client.model_name)['digest'] == protocol['model_digest']
checker = ScopedAgent(None, client.return_model())
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
output = art/f'experiment_reproduction_{stamp}.jsonl'
header = {'record_type': 'run', 'model': client.model_name,
          'temperature': client.ollama_temperature,
          'source_sha256': protocol['source_sha256']}
output.write_text(json.dumps(header)+'\n', encoding='utf-8')
for case in protocol['cases']:
    calls = []
    def verify(question, claims, evidence):
        raw = checker._verify_claims(question, claims, evidence)
        calls.append({'question': question, 'claims': claims,
                      'evidences': evidence, 'raw': raw})
        return raw
    evidence = {} if case['source'] is None else {
        'synthetic:e1': {'evidence_id': 'synthetic:e1', 'text': case['source']}}
    start = time.monotonic()
    decision = ground_answer(case['answer'], evidence, case['question'], verify,
                             normative_context=case.get('normative_context', False))
    record = {'record_type': 'case', 'id': case['id'], 'decision': asdict(decision),
              'expected_status': case['expected_status'], 'verifier_calls': calls,
              'matches_expected': decision.status == case['expected_status'],
              'seconds': time.monotonic()-start}
    with output.open('a', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(record, ensure_ascii=False)+'\n')
print(output)
'@ | .\.venv\Scripts\python.exe -B -
```

O exemplo de reprodução não exige resultado idêntico de um modelo estocástico.
Os critérios determinísticos e os registros brutos permitem investigar diferenças.
