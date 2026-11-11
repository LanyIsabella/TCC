# Matriz determinística

| Cenário | Cobertura |
|---|---|
| uma evidência com metadados normativos | API e terminal |
| duas evidências em páginas distintas | API preserva ordem e páginas |
| ausência de evidência | API/terminal classificam `unsupported` |
| conteúdo omitido | API e terminal exibem limitação |
| resposta parcial | terminal rotula `parcial`, sem alegar suporte completo |
| isolamento de turno e execução | IDs são propagados no registro público |
| campos internos | schema `extra=forbid` e asserções de não vazamento |
| cliente legado | resposta com campos opcionais omitidos mantém JSON anterior |

Os testes utilizam mensagens e tool payloads determinísticos; não afirmam
fidelidade factual universal do modelo.
