# Matriz de inconsistências observadas

| Caso | Evidência | Risco | Decisão |
|---|---|---|---|
| NBR15287, NBR6024 e NBR6027 | Gold ativa tem `title`/`version` nulos nas colunas, mas JSON contém os valores | Consultas por coluna podem divergir do JSON | Não sobrescrever o legado; nova coluna estruturada registra a origem e mantém a divergência explícita |
| NBR6034 | Manifest/Bronze/Gold registram 2005; documentação de baseline registra edição 2004 e vigência a partir de 2005 | Confundir edição com validade | Preservar 2005 como valor registrado e separar `edition`, `publication` e `effective`; confirmação visual/jurídica permanece pendente |
| Datas ausentes | Alguns registros não têm datas verificáveis no snapshot | Inferência silenciosa | `null` + proveniência `unknown` |
| Títulos conflitantes | Valores diferentes entre camadas | Promoção de descrição incorreta | `metadata_conflicts` denuncia o campo; nenhuma camada é escolhida automaticamente |

Não houve reprocessamento para resolver divergências.
