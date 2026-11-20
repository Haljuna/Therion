# Só a orbe no segundo monitor (modo jogo, modo foco, minimizar)

Data: 2026-11-19 · Aprovado pelo usuário na conversa.

## Por quê
O usuário quer o monitor principal livre. Hoje o modo jogo encolhe a janela (420×640) no segundo
monitor, e ela atrapalha. Ele quer só a mini orbe (fundo transparente) no canto do segundo monitor,
e o chat aparecer só quando ele chamar.

## O que muda
- **Modo jogo ligado:** a janela some (não encolhe mais). A mini orbe vai para o canto de baixo à
  direita do segundo monitor. O resto fica igual (libera a placa, guarda avisos).
- **Modo foco ligado:** a mini orbe vai para o mesmo canto. A janela fica onde está.
- **Botão minimizar (−):** a janela some e a mini orbe vai para o mesmo canto.
- **Clique na orbe:** abre o chat pequeno (a janela compacta que já existe) ao lado da orbe.
  Outro clique esconde o chat. Arrastar continua só movendo.
- **Botão direito na orbe:** "Abrir o Therion" (janela completa), "Uso do PC" (o painel que hoje abre
  no clique), "Esconder até reiniciar".
- **Ao sair do modo:** a orbe volta para onde o usuário tinha deixado; a janela reaparece se estava
  aberta antes do modo jogo. Depois de minimizar, a orbe volta quando a janela completa reabre
  ("Abrir o Therion", bandeja); o chat pequeno pela orbe não a tira do canto.
- **Voz:** esconder a janela por esses caminhos não pode encerrar a conversa por voz nem cortar a fala
  (hoje o `hideEvent` encerra; só o minimizar escapa).

## Fora do escopo
- O modo compacto manual (botão no cabeçalho) continua como está.
- Sem segundo monitor: o canto vale para o monitor principal (como `default_position` já faz).

## Abordagens
1. **Escolhida:** reaproveitar a `MiniOrb` e o `set_compact` do painel; só mudar onde a orbe fica e o
   que o clique faz. Pouco código, tudo que já é testado continua valendo.
2. Janela nova de chat flutuante só para a orbe: mais bonita talvez, mas duplica o chat. Descartada.
3. Só esconder a janela e deixar o chat pela voz: não atende o "clicar e abrir o chat". Descartada.

## Decisões do construtor
- Canto exato: margem de 24 px, como `default_position`.
- A posição movida pelo modo não é gravada em `mini_orb.json` (a do usuário continua salva).
- A mini orbe é desligável (`ui.mini_orb`); sem ela, minimizar e modo jogo caem no comportamento antigo.
