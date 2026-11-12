# Orquestração e contratos

`PlannerDecision` aceita apenas intenções conhecidas e indica se a recuperação é necessária. `ToolExecution` associa ferramenta, conversa, turno, consulta, status e resultado bruto. `SynthesisResponse` exige `answer`, lista explícita de `evidence_ids` e limitações.

Intenções conversacionais, ambíguas, fora de escopo e ações não disponíveis não chamam o RAG. Consultas normativas chamam o RAG antes da síntese. O controlador nunca permite que uma mensagem livre do modelo substitua a seleção estruturada de evidências.
