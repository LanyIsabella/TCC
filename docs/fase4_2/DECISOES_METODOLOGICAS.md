# Decisões metodológicas

1. O gate continua booleano para os chamadores existentes, mas a decisão
   auditável é calculada por `assess_promotion` e expõe estado e razões.
2. Não foi criado limiar numérico para score ou métricas. A política usa apenas
   presença, identidade, estados e flags críticas já persistidas.
3. `allow_unvalidated` permanece uma exceção explícita para operações
   administrativas e fixtures. Não representa validação científica.
4. O pacote de 12 páginas da revisão humana não foi convertido em rótulo: como
   não há anotações, ele permanece pendente.
5. A tabela de revisões é append-only para impedir que uma decisão seja
   substituída silenciosamente após publicação.
6. `requires_manual_review` conduz a uma transição automática de retry ou
   quarentena, não a uma fila humana obrigatória.
7. A promoção automática exige métricas determinísticas de extração, evitando
   depender somente do score do avaliador LLM.
