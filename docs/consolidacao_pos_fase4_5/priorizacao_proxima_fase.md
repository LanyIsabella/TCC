# Priorização das próximas atividades

## Ordem recomendada

1. **Fechar o contrato F14.** Decidir e testar a forma de exposição de
   evidências na API/terminal sem quebrar clientes ou confundir eventos internos.
2. **Liberar somente o split de desenvolvimento.** Confirmar Ollama, digests,
   banco somente leitura e registrar novas saídas; manter os 80 casos reservados
   intocados.
3. **Concluir revisão humana amostral do pacote documental.** Confirmar texto, edição,
   números, tabelas, condições e páginas problemáticas; preservar hashes e não
   promover automaticamente durante a revisão.
4. **Calibrar indicadores e Gold com referências independentes/humanas.**
   Separar integridade técnica, fidelidade textual e suporte factual; não usar
   o texto nativo como ground truth.
5. **Reavaliar as limitações de compactação e grounding** com casos humanos de
   condições, listas e tabelas, sem alterar RRF ou a unidade de página.
6. **Somente depois**, decidir se há necessidade de backfill/migração produtiva
   e preparar uma fase específica, com plano de rollback e autorização.

## Dependências

O inventário F1–F16 foi atualizado nesta consolidação. Revisão humana precede
calibração; calibração precede promoção Gold confiável; identidade/proveniência
F2 precede qualquer persistência nova. Nenhuma avaliação experimental foi
iniciada nesta consolidação.
