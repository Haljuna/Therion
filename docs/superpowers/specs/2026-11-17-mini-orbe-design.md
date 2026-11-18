# Mini orbe flutuante com a saúde do PC

Data: 17/11/2026 · Branch: `vigia-pc` (sobre o vigia do PC, commits c5356a7 e dc3acb4)

## Por quê

O usuário joga e conversa no Discord com a janela do Therion fora de vista. Ele quer uma presença pequena e
sempre à mão no segundo monitor: a própria orbe do Therion, em miniatura, parada e respirando, que mostra de
relance se o PC está apertado e, com um clique, mostra quem está gastando RAM e VRAM. Ela também vira o sinal
visual do vigia (o item 6 que estava em aberto) e, no projeto seguinte, o lugar onde se vê o Therion acordar
pela palavra de ativação.

## Objetivos

- Uma janela pequena só com a orbe (modelo A escolhido pelo usuário): a mesma orbe de hoje, não uma imitação.
- Arrastável para qualquer lugar; lembra a posição; nasce no canto inferior direito do segundo monitor.
- Sempre por cima das outras janelas, fora da barra de tarefas, sem bordas nem fundo.
- Em repouso, respira devagar. Espelha o estado da orbe grande (ouvindo, pensando, falando…).
- Fica âmbar enquanto o vigia tiver um problema ativo.
- Mouse em cima: uma etiqueta ao lado com RAM %, VRAM % e espaço livre no C (a etiqueta do modelo C).
- Clique: abre um painel colado na orbe com RAM, VRAM (e temperatura), memória virtual, disco C, os 3 programas
  que mais usam RAM e os 3 que mais usam VRAM. Outro clique, Esc ou clique fora fecha.
- Painel aberto atualiza a cada 3 s; fechado, não mede nada além do que o vigia já mede.

## Não objetivos

- Falar com o Therion pela mini orbe: a voz pela palavra de ativação é o projeto seguinte
  (`2026-11-17-palavra-de-ativacao-design.md`). Aqui ela só mostra os estados.
- Agir pelo painel (fechar programas, limpar). A limpeza continua sendo pelo "libera espaço" ou pelo "sim".
- Substituir o modo compacto. Pode vir depois, se o uso mostrar que sobra um dos dois.

## Antiobjetivos (seria um fracasso mesmo funcionando)

- Pesar no jogo: a mini orbe não pode roubar quadros nem CPU de forma perceptível.
- Derrubar o Therion ao fechar. As 5 quedas no driver NVIDIA (`nvwgf2umx.dll`) aconteceram no fechamento;
  uma segunda superfície OpenGL não pode piorar isso.
- Ficar no caminho: ela não pode roubar o foco do jogo ao aparecer, atualizar ou mudar de cor.

## Restrições

- Mesmo processo do Therion (PySide6, Python 3.14, `F:\Therion\app\.venv`). Repositório público: nada pessoal
  nos arquivos versionados.
- Escala de letras do projeto: 11 rótulo, 12 detalhe, 13 base. Superfície "vidro" `rgba(20,19,30,184)`, borda
  `rgba(255,255,255,23)`, raio 14 (ver `interface/design_system.py`).
- Testes sempre pelo `scripts/test-v4.py` (isolamento de APPDATA/LOCALAPPDATA).

## Abordagens consideradas

1. **Reaproveitar a `OrbGL` (`interface/orb_renderer.py`) numa janela própria** — escolhida. É a orbe de verdade,
   com o mesmo movimento (`OrbMotion`) e o mesmo controle de qualidade (`QualityController`).
2. Desenhar uma orbe nova com QPainter: leve, mas sairia diferente da atual, contra o pedido.
3. Copiar quadros da orbe grande para a pequena: depende da janela grande estar desenhando e quebra quando ela
   está minimizada.

## Como funciona

**Janela** (`interface/mini_orb.py`, novo)
- `QWidget` top-level com `Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint` e
  `WA_TranslucentBackground`, `WA_ShowWithoutActivating`; nunca chama `activateWindow`.
- Contém uma `OrbGL` de 72 px (janela ~96 px para caber o brilho), com `set_quality('low')`.
- Se o fundo transparente não funcionar com a `QOpenGLWidget` (fundo preto quadrado), usar máscara redonda
  (`setMask` com uma região elíptica) e fundo igual ao da orbe. Decisão minha.
- Continua visível com a janela principal minimizada ou na bandeja: some só quando o Therion fecha.
- Em tela cheia (`reminders.do_not_disturb()`) ou com o modo jogo forçado, usa o movimento reduzido
  (`advance(..., reduced=True)`) ou para o timer de desenho: quase congela.
- Arrastar: mover mais de 4 px com o botão apertado move a janela; menos que isso é clique.
- Posição em `%LOCALAPPDATA%\Therion\mini_orb.json` (como a foto do vigia em `pc_watch.json`). Ao abrir, só usa a
  posição salva se ela ainda estiver dentro de alguma tela; senão volta ao canto do segundo monitor (ou do
  principal, se só houver um).
- Botão direito: menu com "Abrir o Therion" (mostra a janela principal) e "Esconder até reiniciar".
- Configuração `ui.mini_orb` (padrão `True`, validada em `config/local.py` como as outras chaves `ui`).

**Estados**
- A janela principal já chama `_update_orbe(state)`; ela passa o mesmo estado para a mini orbe.
- Âmbar: enquanto `PcWatch` tiver problema ativo e a orbe estiver em repouso, a mini orbe usa o estado `error`
  (o âmbar "ATENÇÃO" que já existe em `hud_style.py`). `PcWatch` ganha um `tight()` que diz se há problema ativo
  (o conjunto `_active` sem as chaves de vazamento já avisado há muito tempo fica a critério do construtor).

**Etiqueta (mouse em cima)**
- Janela frameless pequena ao lado da orbe, no lado com espaço na tela, estilo vidro:
  `RAM 62% · VRAM 18% · C 2,5 GB`.
- Mostra na hora o último valor conhecido e pede uma leitura rápida numa thread: `GlobalMemoryStatusEx` e
  `shutil.disk_usage` (instantâneos, já em `core/local_reports._measure`) e
  `nvidia-smi --query-gpu=memory.used,memory.total,temperature.gpu`. Nada de `tasklist` no passar do mouse.

**Painel (clique)**
- Popup colado na orbe, estilo vidro, conteúdo do modelo aprovado: barras de RAM, VRAM (com °C), memória virtual,
  disco C (âmbar abaixo de 5 GB), "Quem mais usa RAM" (3, por nome, do `_measure`) e "Quem mais usa VRAM" (3).
- VRAM por programa: o `nvidia-smi` não dá isso no Windows (modo WDDM). Ler o contador de desempenho
  `\GPU Process Memory(*)\Dedicated Usage` (o mesmo do Gerenciador de Tarefas) via PDH com `ctypes`
  (`PdhOpenQueryW`, `PdhAddEnglishCounterW`, `PdhCollectQueryData`, `PdhGetFormattedCounterArrayW`). As instâncias
  vêm como `pid_<n>_luid_…_phys_0`: somar por PID e cruzar com os nomes do `tasklist`. Sem contador, a seção diz
  "indisponível" e o resto segue.
- Leitura completa numa thread a cada 3 s só com o painel aberto, sem sobrepor leituras (o padrão de
  `_poll_pc_watch` com `is_alive()`).

**Fechamento**
- A mini orbe fecha antes da janela principal desmontar a cena e libera os recursos GL dela com o contexto atual
  (`makeCurrent`/`doneCurrent`), do mesmo jeito que a orbe grande faz hoje. O construtor deve ler o caminho de
  desligamento atual em `desktop.py` (`closeEvent`, `_quit_requested`) e encaixar ali.

## Testes

- Janela: nasce no segundo monitor; posição salva fora da tela é ignorada; arrasto não abre o painel; clique abre e
  fecha; Esc fecha; `ui.mini_orb=false` não cria nada.
- Estados: o estado da orbe grande chega na mini; com `tight()` e repouso fica `error`.
- Etiqueta e painel com medições falsas (sem `nvidia-smi` e sem PDH reais nos testes).
- Parser das instâncias do PDH (`pid_…`) somando por PID.
- Fechar a janela principal com a mini orbe aberta não derruba o processo (teste em subprocesso, como
  `tests/test_read_worker_lifetime.py`).

## Verificação no PC real

- Medir CPU e GPU da mini orbe em repouso e com um jogo em tela cheia (meta: imperceptível; anotar os números).
- Abrir e fechar o Therion 5 vezes com a mini orbe e conferir no Visualizador de Eventos que não há queda nova no
  `nvwgf2umx.dll`.
- O usuário confere arrastar, a etiqueta, o painel e o âmbar com o C abaixo de 5 GB (hoje está em 2,5 GB).

## Decisões minhas (o usuário pode trocar)

Tamanho de 72 px; posição salva fora do `config.json`; menu do botão direito; atualização de 3 s; âmbar só em
repouso; `ui.mini_orb` ligado por padrão.

## Fica para o construtor

Detalhes do PDH em `ctypes`, o tamanho exato da janela para o brilho, o lado da etiqueta e do painel perto das
bordas da tela, e como pausar o timer de desenho da `OrbGL` sem quebrar a `QualityController`.
