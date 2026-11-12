# Limitações e fora de escopo

- Não houve alteração no modelo, cliente, banco, corpus, PDFs, OCR, embeddings, RRF ou ingestão.
- Não houve migração, reprocessamento, avaliação de holdout ou nova tool.
- A qualidade semântica da síntese continua limitada ao modelo local e à política determinística de grounding.
- O Ollama pode selecionar uma página inadequada mesmo quando a recuperação encontra o trecho correto; nesses casos, o grounding mantém a resposta como `unsupported`.
- A síntese depende da saída estruturada do modelo local; falhas de contrato ou validação também resultam em `unsupported`.
- A recuperação alternativa melhora consultas específicas, mas não garante que todas as perguntas encontrem o documento ou a página ideais.
- Respostas parcialmente sustentadas são marcadas e incluem limitação; uma resposta sem evidência é `unsupported`.
- O histórico em memória não é adequado para persistência operacional sem uma decisão futura de privacidade e retenção.
- A validação ub-mode permanece inconclusiva: Crapper excedeu o limite de CRAP, Dryer apontou duplicações e Mutator foi interrompido por timeout; esses gates não são considerados aprovados.
