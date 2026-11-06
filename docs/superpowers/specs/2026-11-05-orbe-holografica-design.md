# Orbe holográfica do Therion: desenho

Data: 2026-11-05. Estado: aguardando revisão do usuário.

## Objetivo

Trocar a orbe de partículas do Therion por uma esfera holográfica com cara de máquina, fiel à
referência escolhida pelo usuário, em roxo, reagindo aos estados do Therion e à voz.

Referência: GIF "Jarvis orb" (Pinterest, pin 638737159689266555; arquivo
`i.pinimg.com/originals/28/96/64/2896641fca4a98dc1e2d7dddaf0815ba.gif`, 540×480, 41 quadros, 2,9 s em loop).
Não versionar o GIF nem quadros dele no repositório (é público e o material não é nosso).

### Por que a tentativa anterior falhou (palavras do usuário)

Parecia feita de pó, achatada, apagada e com as peças erradas. Desenhar só com pontos não chega
nesse visual: falta luz sólida (placas preenchidas, linhas grossas), profundidade, rastro e brilho.

### O que o GIF mostra

1. A esfera inteira gira no eixo vertical; as camadas internas aparecem pelos buracos da casca.
2. Acelera e deixa rastro: a borda vira faixas curvas borradas (quadros 30–39).
3. Clarão branco-azulado perto do centro e a esfera esfria por um instante (quadros 38–40).
4. O olho do centro fica parado e sempre aceso.
5. Uma antena no topo gira junto.

## Decisões do usuário

| Tema | Decisão |
|---|---|
| Comportamento | Mapear o GIF nos estados do Therion |
| Paleta | Roxo com miolo quase branco e clarão branco-azulado |
| Orbe pequena | Simplifica sozinha (some o detalhe fino) |
| Desempenho | A resposta do modelo tem prioridade sobre o visual |
| Ouvindo | O giro quase para e as marcas do aro acendem com o volume da voz |
| Caminho técnico | A: geometria 3D real na mesma janela OpenGL |

## Comportamento por estado

Os estados vêm de `therion/interface/orb_motion.py` (`SPEEDS`).

| Estado | Orbe |
|---|---|
| idle | Gira devagar (casca: 1 volta a cada ~40 s), camadas em ritmos diferentes, olho calmo |
| preparing | As peças se montam: surgem do centro e vão para o lugar |
| listening | Giro quase para (~120 s por volta); marcas do aro acendem com o volume da voz |
| transcribing | Volta a girar, acelerando |
| thinking | Acelera (~6 s por volta) com rastro nas bordas |
| executing | Mais rápido (~4 s por volta); riscos de movimento mais fortes |
| thinking/executing → synthesizing/speaking | Clarão branco-azulado saindo do olho (~0,3 s); a esfera esfria um instante |
| synthesizing | Desacelera; o olho respira |
| speaking | Giro médio; o olho pulsa com a voz do Therion |
| awaiting_confirmation, clarification | Quase parada; o aro pisca devagar |
| error, uncertain | Para; peças escurecem; olho fraco com toque avermelhado |
| partial | Como idle, com o olho um pouco mais fraco |

Regras:
- O clarão nunca repete em sequência: no máximo um a cada 4 s. O código atual evita flashes de
  propósito; este é a única exceção, curta.
- "Reduzir movimento" ligado: sem giro, sem rastro, sem clarão. Só cor e brilho mudam com o estado.

## Anatomia (raio da esfera = 1)

| Camada | Como é | Giro | Orbe pequena (< 260 px) |
|---|---|---|---|
| 1. Antena | Mastro no topo (raio 1,0 → 1,18) e risco curvo de raio 0,12 | Com a casca | Fica |
| 2. Gaiola | Faixas de barrinhas curtas empilhadas a cada ~3° de latitude, em 6 longitudes; na borda viram escadinha | Com a casca | Metade some |
| 3. Casca | ~70 placas no raio 0,96 cobrindo ~60%; preenchimento 10–18% de opacidade, contorno forte; 30% com divisórias ou janelas | Base (1×) | Fica, sem janelas |
| 4. Miolo | ~60 torres e caixas entre raio 0,25 e 0,8; contorno médio, preenchimento leve | 0,5×, sentido contrário | Some quase todo |
| 5. Giroscópio | Anel de raio 0,55 inclinado 25°, faixa fina com 3 falhas | 1,5× no próprio eixo | Fica |
| 6. Olho | Núcleo branco (raio 0,05), anel forte (raio 0,10), cometa de 270° (raio 0,16) com cauda apagando | Cometa 2× | Fica |
| 7. Faíscas | ~1.500 pontos entre raio 0,3 e 1,05, piscando; esticam com a velocidade | Com a camada mais próxima | 30% |
| 8. Luz | Brilho forte (~6% do diâmetro), halo e reflexo no chão | n/a | Mais suave |

Profundidade: o lado de trás brilha 35% e fica mais borrado. Linhas com ~1,2 px numa orbe de 500 px,
nunca menos de 1 px. A troca para "pequena" é gradual, sem corte.

### Cores

| Uso | Cor |
|---|---|
| Peças (base) | `#7C4DFF` |
| Contornos acesos | `#C9B8FF` |
| Miolo e partes quentes | `#F4F0FF` |
| Clarão | `#DDEBFF` |
| Erro (mistura de 30%) | `#FF6B7A` |
| Fundo | `#09090F` (o atual) |

Os números são ponto de partida; cada etapa ajusta comparando com os quadros do GIF.

## Arquitetura

Hoje `therion/interface/constellation.py` mistura forma, desenho e janela. Separar em:

1. `therion/interface/orb_geometry.py` (novo): monta as 8 camadas em arrays numpy. Cada vértice
   leva posição, camada, eixo e velocidade de giro, brilho e nível de detalhe (sempre / some quando
   pequena). Três grupos: superfícies (triângulos das placas e caixas), linhas (cada segmento vira um
   quadrilátero voltado para a câmera, porque o contexto é OpenGL 2.1 e não há geometry shader) e
   pontos (faíscas). Sem OpenGL; testável.
2. `therion/interface/orb_motion.py` (ampliado): do estado e do volume da voz saem velocidade por
   camada, comprimento do rastro, pulso do olho, medidor do aro, tom de erro e gatilho do clarão
   (com a trava de 4 s). Mantém a integração analítica atual (sem saltos ao trocar de estado).
3. `therion/interface/orb_renderer.py` (novo): substitui `ParticleGL`. Passadas por quadro:
   1. cena num FBO: superfícies (mistura aditiva, opacidade baixa), linhas, faíscas e olho, com
      atenuação pelo lado de trás;
   2. rastro: o quadro anterior entra com decaimento (dois FBOs alternados); o decaimento sai da
      velocidade atual, então girar mais rápido deixa rastro mais longo;
   3. brilho em várias escalas (1/2, 1/4, 1/8 da tela, com desfoque);
   4. composição com halo e reflexo no chão (aproveitando o que o `BLOOM_FRAGMENT` atual já faz).
4. `therion/interface/constellation.py` (enxuto): continua sendo o `Constellation` usado por
   `dashboard.py` e `launcher.py`, com a mesma interface (`set_visual`, `set_focus_rect`,
   `set_attention`, `set_active`, `set_quality`, `reduced`). A reserva sem OpenGL
   (`StaticConstellation`) passa a desenhar a forma nova em 2D com QPainter.

### Desempenho

- Em thinking e executing (modelo usando a placa) a orbe cai para 30 quadros/s e usa brilho mais leve.
- Os níveis baixo/médio/alto do `QualityController` passam a controlar passadas de brilho e detalhe,
  não quantidade de partículas. A mudança anterior para 24k/56k/96k partículas é desfeita.
- Geometria fixa na placa (VBO), girada no shader; só uniforms mudam por quadro.

### Falhas

- OpenGL não inicia ou falha ao desenhar: mesmo caminho de hoje (aviso e reserva 2D).
- Placa lenta: a qualidade cai sozinha, como hoje.

## Testes

- Forma: as 8 camadas presentes; tudo dentro do raio 1,2; o nível de detalhe marca as peças certas;
  a casca cobre entre 50% e 70%.
- Comportamento: cada estado gera os valores da tabela; o clarão só dispara na passagem
  pensar → falar e respeita os 4 s; "Reduzir movimento" zera giro, rastro e clarão.
- Fumaça: abrir o `Constellation` com OpenGL, desenhar alguns quadros sem erro e conferir o fps
  emitido em `metrics`.
- Atualizar `tests/test_constellation.py`, que hoje testa a distribuição de partículas.

## Etapas de entrega

Cada etapa termina com print ou folha de quadros lado a lado com o GIF, e o usuário aprova antes da próxima.

1. Forma parada: 8 camadas, sem brilho forte nem movimento. Comparar com o quadro 0.
2. Luz e profundidade: brilho em escalas e lado de trás mais fraco. Deve parar de parecer pó.
3. Movimento e rastro: giro por camada e rastro proporcional. Comparar com os quadros 30–39.
4. Estados: a tabela inteira, com clarão, medidor do aro e tom de erro.
5. Tamanhos e desempenho: orbe pequena, launcher e medição real: 60 quadros/s parado e queda de
   no máximo ~3% na velocidade de resposta do modelo enquanto pensa (exige o Therion aberto).

## Fora do escopo

- Trocar a cena ao redor da orbe (fundo, painéis, terreno do `scene_flow.py`).
- Novas dependências.
- Enviar ao GitHub sem pedido do usuário.

## Organização do trabalho

Branch própria (`orbe-holografica`) a partir da master. A tentativa anterior não commitada
(`constellation.py`, `presentation.py`, `tests/test_constellation.py`) é descartada.
