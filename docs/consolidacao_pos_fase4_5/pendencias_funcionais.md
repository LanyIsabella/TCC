# Pendências funcionais

1. **Matriz histórica:** F7–F9 e F14–F16 não aparecem como linhas numeradas na
   baseline original; as correspondências e o grau de confirmação estão em
   `matriz_f1_f16.md`. Não tratar essa recuperação documental como correção.
2. **Edição/vigência:** confirmar humanamente a divergência NBR6034 e decidir se
   haverá atualização versionada, sem sobrescrever o legado.
3. **Proveniência operacional:** manter migrações e novas execuções em cluster
   isolado até haver autorização explícita para o banco produtivo.
4. **Compactação:** avaliar, em amostra controlada, condições que atravessem
   páginas e unidades tabulares sem transformar páginas em chunks obrigatórios.
5. **Grounding:** a política agora sinaliza omissões, mas não consegue inferir
   qual condição ausente existe; a limitação é deliberadamente conservadora.
6. **Bypass:** `allow_unvalidated` precisa de controle operacional e auditoria
   de autorização antes de qualquer uso fora de testes/administradores.
7. **F14:** decidir se API e terminal devem devolver evidências estruturadas,
   com compatibilidade explícita, antes de alterar esses contratos.
8. **F9:** definir uma rotina operacional de validação de digest/modelo de
   embedding; os checks estruturais atuais não medem qualidade vetorial.
