# Grounding e publicação

O adaptador cria uma trilha de mensagens com usuário, chamada da tool, retorno da tool e síntese. A validação central calcula evidências disponíveis e confronta os IDs selecionados com o conteúdo retornado. IDs inexistentes, ausência de seleção, falha de recuperação e contradições não são publicados como fatos.

O resultado público inclui `grounding_status`, IDs disponíveis/selecionados/publicados, limitações e `tool_provenance`. Evidências publicadas passam por `public_evidence`, que remove campos internos.
