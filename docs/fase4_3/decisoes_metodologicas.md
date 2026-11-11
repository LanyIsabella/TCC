# Decisões metodológicas

1. O manifesto é uma observação de carga, não ground truth jurídico.
2. O texto nativo do PDF e o título extraído não substituem confirmação humana da edição.
3. O identificador canônico é normalizado deterministicamente; o sufixo `:AAAA` vira edição, não data de vigência.
4. Campos legados permanecem intactos. A migração `0003_normative_metadata` é aditiva, nullable e reversível apenas quando vazia; rollback com dados falha para evitar perda.
5. A Gold continua com histórico por `(document_id, extraction_id)`. Metadado descritivo não invalida resultados de extração nem altera F2.
6. Não foram definidos limiares científicos de confiança. Calibração e decisão de promoção adaptativa ficam fora da Fase 4.3.
