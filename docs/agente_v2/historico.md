# Histórico e isolamento

Cada requisição aceita `conversation_id` validado. Uma conversa nova é inicializada apenas com mensagens anteriores à pergunta atual; o turno atual é anexado depois da decisão. IDs diferentes têm estados separados, o contexto é limitado por quantidade de mensagens e caracteres, e o botão **Nova conversa** cria um novo ID e limpa a interface.

Evidências de turnos anteriores permanecem apenas como contexto textual. Toda pergunta normativa executa uma nova recuperação no turno corrente.
