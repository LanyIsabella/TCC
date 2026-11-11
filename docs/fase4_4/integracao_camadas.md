# Integração Bronze/Silver/Gold

Bronze e os PDFs originais permanecem imutáveis. A Silver continua armazenando
cada execução e página; a nova tabela `page_extraction_selections` guarda uma
decisão append-only por execução de seleção, incluindo candidatos e motivo em
JSONB.

A Gold recebe `selection_run_id`. Promoção normal exige avaliação/proveniência
F2 e cobertura de todas as páginas selecionadas. Uma seleção mista reconstrói o
texto apenas com páginas `selected`; páginas ausentes ou em quarentena abortam
a promoção antes da desativação da Gold ativa.

Rollback da migração é protegido: a tabela de seleção não é removida enquanto
existirem registros. Nenhuma migração foi aplicada ao PostgreSQL produtivo.
