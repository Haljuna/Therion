# Orbe HUD do Therion — design

Data: 2026-11-13 · Ramo: `orbe-hud` (criado a partir de `orbe-holografica`)

## Intenção

O usuário quer que a presença do Therion pareça viva e com cara de "Jarvis": uma esfera feita de milhares de pontos de luz, com núcleo brilhando, órbitas cruzando e uma moldura de painel em volta que mostra o estado. A escolha saiu de várias rodadas de protótipos; a aprovada é a **Orbe HUD**, com os valores escolhidos por ele:

> roxo e ciano · 3200 pontos · com moldura

Protótipo de referência (comportamento e proporções): https://claude.ai/artifact/3EfYF3YznHhx6HGeZoxiug, na cor "Roxo e ciano". Ele foi inspirado num vídeo de um "Jarvis caseiro"; a referência visual é só o estilo, não copiar a dashboard daquele vídeo.

## Objetivos

- Trocar o visual da orbe holográfica pela Orbe HUD, mantendo o mesmo lugar na interface (`Constellation` → `OrbGL`).
- Cada um dos 13 estados do Therion tem uma aparência reconhecível (tabela abaixo). O usuário pediu "mais estados, se for viável".
- Reagir de verdade à voz: a intensidade que já chega em `set_visual(state, intensity)` move os pontos e o nível da moldura.
- Continuar leve: não pode atrapalhar o modelo local nem a voz.

## Não objetivos

- Os painéis da dashboard do vídeo de referência (clima, consumo, caderno, barra de comandos).
- Mexer em qualquer coisa fora da apresentação (serviços, voz, permissões).
- Juntar com o ramo `master` nesta etapa (é o passo seguinte, ver "Depois").

## Anti-objetivos (falharia mesmo funcionando)

- Parecer "pó": pontos soltos, achatados e apagados. Foi o motivo de recusa de duas orbes de partículas. Os pontos precisam de profundidade (frente maior e mais clara, fundo menor e escuro), núcleo brilhando por trás e as órbitas e a moldura dando estrutura.
- Travar ou engasgar a voz ou o modelo enquanto ele pensa.
- Texto da moldura borrado ou serrilhado.

## Restrições

- PySide6, `QOpenGLWidget` com OpenGL 2.1 compatível (como hoje). GLSL no estilo atual (`attribute`/`varying`).
- A orbe é só apresentação: nada de acesso a serviços, áudio ou rede (regra já escrita no topo dos arquivos).
- Reaproveitar o que já existe e funciona: brilho em camadas (bloom), rastro por FBO, `QualityController` (baixa/média/alta), 30 quadros/s em pensando e executando (`frame_interval_ms`), modo reduzido, reserva 2D sem OpenGL (`StaticConstellation`), `focus_rect` e paralaxe (`SceneMotion`).
- O repositório é público: não commitar o print nem quadros do vídeo de referência.
- Testes com `.venv/Scripts/python.exe -m pytest`.

## Abordagens consideradas

1. **Aproveitar a estrutura da orbe holográfica e trocar só o que se vê** (escolhida). Geometria e shaders novos; todo o resto (bloom, rastro, qualidade, cadência, reserva, integração) fica. Menos risco e menos código.
2. Renderizador novo do zero. Joga fora coisas que funcionam e já foram testadas.
3. Desenhar tudo com `QPainter`, sem OpenGL. Não aguenta 3200 pontos com brilho a 60 quadros/s.

O usuário aprovou a abordagem 1 e o mapa de estados abaixo.

## Desenho

### Composição (proporções do protótipo)

- Centro da orbe a 44% da altura da área de foco. Raio da esfera `R = 0,215 × lado menor` com moldura.
- Moldura com raio `Rf = 1,62 R`. Nome do estado embaixo, em `Rf × 1,3` abaixo do centro.

### Esfera de pontos

- 3200 pontos distribuídos por espiral de Fibonacci na esfera unitária, cada um com uma semente própria.
- Desenhados como pontos redondos e suaves, com mistura aditiva. Tamanho e brilho pela profundidade: frente maior e clara, fundo menor e escuro.
- Movimento no shader de vértice:
  - ondulação lenta da superfície (soma de senos em duas direções);
  - cintilação individual pela semente;
  - giro da esfera (velocidade por estado);
  - efeitos de estado da tabela (ondas, faixas, pulsos).
- Cores: pontos lilás `rgb(200,185,255)`; os mais acesos puxam para ciano claro `rgb(200,255,250)`.

### Núcleo

- Brilho radial roxo `rgb(110,90,230)` atrás da esfera, mais um halo largo e fraco. Fica mais forte em ouvindo, pensando e com a voz.

### Órbitas e eixo

- Três anéis inclinados, raios 1,24 · 1,32 · 1,42 R, cor ciano `rgb(120,215,232)`. A metade de trás é bem mais fraca que a da frente.
- Um ponto brilhante corre em cada anel (velocidades diferentes, uma no sentido oposto).
- Um eixo atravessa a esfera, com um ponto em cada ponta. Gira devagar com ela.

### Moldura

- Círculo fino, 72 marquinhas girando devagar (uma maior a cada 30°), quatro marcas fixas nos lados, anel tracejado girando ao contrário.
- Dois arcos grossos à esquerda e à direita, com brilho. A abertura e o giro mudam com o estado.
- Embaixo: 25 pontinhos de nível (acendem do centro para fora conforme a intensidade) e o nome do estado em maiúsculas espaçadas.
- Diferente do protótipo, **sem** a linha de números técnicos ("3200 pontos · nível") embaixo do nome. *(Chamada minha: número técnico não ajuda quem está conversando.)*
- Cor ciano, a mesma das órbitas.

### Estados

Todas as trocas são suaves (sem saltos). O clarão curto pensar→falar que existe hoje continua.

| Estado | Nome na moldura | Como a orbe fica |
|---|---|---|
| idle | EM REPOUSO | Ondulação lenta, cintilação, órbitas calmas, arcos com 38°. |
| preparing | PREPARANDO | A esfera se monta: os pontos vêm de um raio menor até o lugar e acendem (como a montagem atual de 1,2 s); os arcos crescem junto. |
| listening | OUVINDO | Ondas correm pela esfera na direção de quem fala, mais fortes com a voz do usuário; arcos abrem para 68°; núcleo acende; o nível segue a voz. |
| transcribing | TRANSCREVENDO | Uma faixa de luz lenta varre a esfera; o nível pulsa; os arcos giram devagar. |
| thinking | PENSANDO | Giro rápido, faixas de luz varrendo, moldura girando. 30 quadros/s. |
| executing | EXECUTANDO | Como pensando, e os pontos das órbitas correm mais rápido deixando rastro curto. 30 quadros/s. |
| synthesizing | PREPARANDO A FALA | A esfera "respira" devagar; o anel da voz aparece fraco. |
| speaking | FALANDO | A superfície pulsa para fora no ritmo da voz; um anel acompanha cada sílaba; o nível segue a voz do Therion. |
| awaiting_confirmation | AGUARDANDO VOCÊ | Calma, giro quase parado, órbitas lentas, arcos piscando devagar (ciclo de ~1,6 s). |
| clarification | AGUARDANDO RESPOSTA | Igual à anterior. |
| error | ATENÇÃO | Pontos com metade do brilho; moldura e órbitas em âmbar `rgb(255,180,90)`; giro parado; um pulso âmbar lento. |
| uncertain | INCERTO | Âmbar mais suave, com uma leve tremida nos pontos. |
| partial | RESULTADO PARCIAL | Cores normais; os arcos ficam com metade do tamanho. |

Estado desconhecido cai em `idle`.

### Rastro e cor de alerta

- O rastro por FBO fica desligado no normal, porque borraria os pontos. Liga fraco só em pensando e executando, para dar sensação de velocidade. *(Chamada minha.)*
- Em erro e incerto o núcleo continua roxo, só que mais fraco; só a moldura, as órbitas e os pontos mais acesos ficam âmbar. *(Chamada minha.)*
- A intensidade que chega em `set_visual` já é a voz de quem está falando no momento: a do usuário em ouvindo, a do Therion em falando.

### Desempenho e qualidade

- 60 quadros/s no normal e 30 em pensando e executando (como hoje).
- Qualidade: alta e média com 3200 pontos; baixa com 1800 pontos e menos camadas de brilho. Orbe pequena (lado menor que 260 px) usa 1800 pontos. *(Números meus, ajustáveis.)*
- Modo reduzido: sem ondulação nem giro, esfera parada com as cores e o nome do estado.
- Reserva sem OpenGL (`StaticConstellation`): a esfera de pontos projetada em 2D, parada, com a moldura e o nome do estado.

## Testes

- Geometria: quantidade de pontos por qualidade, todos no raio certo, órbitas e eixo montados.
- Movimento: todo estado tem parâmetros; trocar de estado não dá salto; estado desconhecido vira `idle`; a intensidade está limitada entre 0 e 1.
- Moldura: tabela de nomes cobre os 13 estados.
- Os testes de renderizador e `Constellation` que já existem continuam passando (modo offscreen).
- Conferência visual: print lado a lado com o protótipo em repouso, ouvindo, pensando e falando, antes de dar por pronto.

## Depois (fora desta etapa)

- Juntar `orbe-hud` com `master` (o `master` tem 18 commits que este ramo não tem, entre eles a Estação) e rodar a suíte inteira.
- O olho guardado no `git stash` continua guardado; não faz parte desta orbe.

## Deixado para quem construir

- Detalhes dos shaders e os números finos de cada efeito, desde que fiquem perto do protótipo.
- Se a moldura é desenhada no próprio `OrbGL` (com `QPainter` depois do OpenGL) ou num widget por cima. O requisito é texto nítido e sem piscar.
- O que reaproveitar das peças da orbe holográfica (`orb_geometry.py`, `orb_shaders.py`, `orb_motion.py`) e o que apagar. O que não for mais usado deve sair.
