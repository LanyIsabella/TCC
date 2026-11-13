# Smoke test real da interface V2 — 2026-11-13

Execução manual pelo navegador Playwright contra `streamlit run
src/app/agente_v2/streamlit_app.py --server.headless true --server.port 8502`,
com Ollama local e PostgreSQL de desenvolvimento disponíveis. Nenhum dado
produtivo foi alterado.

| Cenário | Entrada observada | Resultado | Evidência |
|---|---|---|---|
| Geral | `O que é literatura?` | **PASS** — resposta limitada sem documento de suporte; a tela não apresentou evidência normativa. | `general.png` |
| Normativo fundamentado | `Como formatar uma citação direta longa segundo a ABNT?` | **PASS** — resposta parcial com limitação explícita, documento ABNT NBR 10520 (2023), página 16 e trecho expansível. | `normative-grounded.png`, `normative-evidence-expanded.png` |
| Continuidade | follow-up sobre o recuo na mesma conversa | **FAIL conhecido/P2** — a nova recuperação selecionou página posterior e o grounding recusou publicar; não houve publicação sem suporte. | snapshots Playwright da sessão; limitação registrada em `docs/agente_v2/correcao_final_pr14.md` |
| Ambiguidade e esclarecimento | `Qual é a formatação certa?` → `Citações diretas longas` | **PASS** — primeiro turno pediu esclarecimento; segundo recuperou NBR 10520, publicou resposta e evidência. | `clarification-resolved.png` |
| Resposta parcial | mesma consulta normativa longa | **PASS** — somente a parte sustentada foi publicada e a limitação ficou visível. | `normative-grounded.png` |
| Nova conversa/isolation | botão `Nova conversa` após a resposta | **PASS** — histórico e contador foram limpos (`Nenhuma pergunta feita ainda.`). | `new-conversation.png` |

O bootstrap e a renderização foram confirmados no navegador real. A sessão não
apresentou erros de console no estado final (`console-errors.log`). O caso de
continuidade permanece explicitamente pendente porque sua correção exigiria
uma decisão de recuperação fora do escopo desta estabilização; o fail-closed
impede que a resposta seja exibida como fundamentada.
