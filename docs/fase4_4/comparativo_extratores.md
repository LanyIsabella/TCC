# Comparação dos extratores

| Fonte | Papel na decisão | Risco conhecido |
|---|---|---|
| PDF reader | candidato e referência diagnóstica auxiliar | texto nativo pode conter PUA/ordem incorreta |
| Docling | candidato estruturado | tabelas/listas podem divergir do layout |
| GLM-OCR | candidato OCR | depende do serviço/modelo e pode truncar |

Nenhum extrator é tratado como verdade por identidade, presença de hash,
similaridade lexical ou concordância entre pares. O piloto controlado de três
páginas está registrado em `piloto_real.md`; ele não substitui um comparativo
estatístico maior nem uma revisão humana.
