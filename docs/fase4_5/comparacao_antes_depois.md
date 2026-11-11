# Comparação antes/depois

| Cenário | Antes | Depois |
|---|---|---|
| Regra no fim de página longa | prefixo podia descartar a regra | unidade com o match é preservada |
| Regra em página posterior | páginas iniciais ocupavam o orçamento | página com match é priorizada |
| Condição em parágrafo seguinte | não havia seleção semântica | unidade vizinha contígua é mantida quando cabe |
| Páginas descontínuas | contexto podia parecer um bloco único | evidências permanecem individualizadas por página |
| Excesso de contexto | descarte silencioso | `omitted_content` informa caracteres e páginas |
| Texto sem espaços | limite era apenas de caracteres | há fallback adicional para o orçamento estimado de tokens |

Nos fixtures da fase, os trechos preservados continuam sendo substrings do
texto de origem e conservam números, versão e página.
