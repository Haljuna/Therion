# Ideia futura — avaliação e ajuste de modelo local

**Estado:** ideia para pesquisa futura; não aprovada para implementação.
**Registro:** 2026-09-28.

O projeto [Soup](https://github.com/MakazhanAlpamys/Soup) foi levantado como possível ferramenta para ajustar modelos locais e exportá-los em GGUF para uso com Ollama. O projeto relata um experimento de ajuste de um modelo de 8 bilhões de parâmetros numa GPU com 4 GB de memória de vídeo, em condições específicas. Isso não demonstra que o computador do Therion terá o mesmo desempenho nem que um modelo ajustado responderá mais rápido ou será genericamente mais inteligente.

**Possível valor para o Therion:** se uma falha estreita e recorrente do modelo persistir após correções mais simples, reunir exemplos reais, definir respostas esperadas e comparar o modelo atual com uma versão ajustada. O método de avaliação pode ser aproveitado independentemente do Soup; o treinamento seria uma hipótese posterior.

**Condições para reabrir:** problema mensurável e repetido; conjunto de exemplos de qualidade; comparação antes/depois; verificação de hardware, memória, espaço em disco, tempo de treinamento, licenças e privacidade dos dados. Não usar dados do Segundo Cérebro para treinamento sem decisão específica.

**Fora do escopo atual:** instalar Soup, baixar modelos, treinar, trocar o modelo do Therion, alterar Ollama ou iniciar testes de hardware. Prioridade atual permanece estabilizar os fluxos existentes.
