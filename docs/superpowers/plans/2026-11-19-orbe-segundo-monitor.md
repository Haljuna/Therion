# Só a orbe no segundo monitor — plano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** modo jogo, modo foco e o botão minimizar deixam só a mini orbe no canto do segundo monitor; clicar nela abre o chat pequeno ao lado.

**Architecture:** a `MiniOrb` ganha `park(on)` (vai para o canto e volta) e um `on_click` (clique chama a janela em vez do painel do PC). A `MainWindow` guarda os motivos de estacionar (`game`, `focus`, `minimize`), esconde a janela sem derrubar a voz e abre o chat compacto ao lado da orbe.

**Tech Stack:** Python, PySide6, pytest (+ QTest).

**Spec:** `docs/superpowers/specs/2026-11-19-orbe-segundo-monitor-design.md`

## Global Constraints
- Canto: `default_position(screens, primary, size)` (baixo à direita do segundo monitor, margem 24; sem segundo monitor, o principal).
- A posição de estacionar nunca vai para `mini_orb.json`; a do usuário continua salva (também no `shut()`).
- Sem mini orbe (`ui.mini_orb` falso): minimizar e modo jogo fazem o que fazem hoje (o teste `test_spoken_game_mode_turns_compact_on_and_back_off` continua passando).
- Esconder a janela por esses caminhos não encerra a conversa por voz nem a fala.
- Textos do menu: "Abrir o Therion", "Uso do PC", "Esconder até reiniciar".

## Review Focus
- Modo jogo e foco ligados juntos, um desliga: a orbe continua no canto até o último motivo sair.
- Usuário arrasta a orbe enquanto estacionada: o novo lugar vale, e ao sair do modo ela não pula de volta.
- Fechar o Therion com a orbe estacionada: grava o lugar do usuário, não o canto.
- Clique na orbe com a janela minimizada (não escondida): abre o chat, não esconde.
- Modo jogo ligado com a janela já escondida: ao desligar, a janela não aparece sozinha.

---

### Task 1: `MiniOrb` estaciona no canto e repassa o clique

**Files:**
- Modify: `therion/interface/mini_orb.py` (`MiniOrb.__init__`, `mouseReleaseEvent`, `contextMenuEvent`, `shut`, novo `park`)
- Test: `tests/test_mini_orb.py`

**Interfaces:**
- Produces: `MiniOrb(..., on_click=None)`; `MiniOrb.park(on: bool) -> None`; `MiniOrb.parked -> bool` (propriedade).

- [ ] **Step 1: testes que falham** (usar `make(tmp_path, ...)` e telas reais via `_screens()`; o canto esperado é `default_position(_screens(), QGuiApplication.primaryScreen().availableGeometry(), window.size())`)
  - `test_park_moves_to_the_corner_and_back`: `move(300,300)`; `park(True)` → `pos()==canto` e `parked`; `park(False)` → `pos()==QPoint(300,300)` e não `parked`.
  - `test_park_twice_keeps_the_first_spot`: `park(True)` duas vezes, `park(False)` → volta a `(300,300)`.
  - `test_dragging_while_parked_keeps_the_new_spot`: estaciona, arrasta 30 px (como o teste de arrasto existente), `park(False)` → fica onde soltou.
  - `test_shut_while_parked_saves_the_users_spot`: `move(300,300)`, `park(True)`, `shut()` → `restore(...)` do arquivo dá `QPoint(300,300)`.
  - `test_click_calls_on_click_instead_of_the_panel`: `on_click=lambda: hits.append(1)`; clique → `hits==[1]` e painel fechado.
  - `test_menu_has_pc_usage`: monkeypatch `QMenu.exec` para capturar `[a.text() for a in menu.actions()] == ['Abrir o Therion', 'Uso do PC', 'Esconder até reiniciar']`.
- [ ] **Step 2:** `pytest tests/test_mini_orb.py -q` → os novos falham.
- [ ] **Step 3: implementar.** `park(True)` guarda `self._home = self.pos()` só se ainda não estacionada e move para o canto; `park(False)` volta para `_home` (com `clamp`) e zera. Arrastar estacionada zera `_home` (o lugar novo é do usuário). `shut()` grava `_home or self.pos()`. Clique sem arrasto: `on_click()` se houver, senão o painel de hoje. Menu: "Uso do PC" chama `_open_panel`.
- [ ] **Step 4:** `pytest tests/test_mini_orb.py tests/test_mini_orb_lifetime.py -q` → tudo passa.
- [ ] **Step 5:** commit `feat(mini-orb): estaciona no canto e repassa o clique`.

### Task 2: janela usa a orbe no modo jogo, no foco e no minimizar

**Files:**
- Modify: `therion/interface/desktop.py` (criação da `MiniOrb` ~l.362, `_minimize_window`, `_set_game_mode`, `_apply_focus`, `_show_window`, novos `_park_orb`, `_tuck_to_orb`, `_toggle_chat_from_orb`)
- Test: `tests/test_pc_watch.py` (o `FakeMini` ganha `park(on)` → `calls.append(('park', on))`, `parked`, `move`, `size`)

**Interfaces:**
- Consumes: `MiniOrb.park`, `MiniOrb(on_click=...)`, `mini_orb.beside(anchor, size, screen)`.
- Produces: `MainWindow._park_orb(reason: str, on: bool)`; `MainWindow._tuck_to_orb()`; `MainWindow._toggle_chat_from_orb()`.

- [ ] **Step 1: testes que falham** (com `make_mini_window`, `window.show()`):
  - `test_game_mode_hides_the_window_and_parks_the_orb`: `_set_game_mode(True)` → `not window.isVisible()`, `('park', True)` no fim; `_set_game_mode(False)` → visível e `('park', False)`.
  - `test_game_mode_does_not_reopen_a_window_that_was_hidden`: `window.hide()`, liga e desliga → continua escondida.
  - `test_focus_and_game_keep_the_orb_parked_until_both_end`: liga jogo, `_apply_focus({'phase':'focus','start':agora,'minutes':25})`, desliga jogo → último park continua `True`; `_apply_focus({})` → `('park', False)`.
  - `test_minimize_hides_into_the_orb_and_full_open_brings_it_back`: `_minimize_window()` → escondida e `('park', True)`; `_show_window()` → visível e `('park', False)`.
  - `test_hiding_into_the_orb_keeps_the_voice_conversation`: monkeypatch `window._end_conversation` contando chamadas; `_minimize_window()` → 0 chamadas.
  - `test_orb_click_toggles_the_chat`: com jogo ligado, `_toggle_chat_from_orb()` → visível; de novo → escondida, orbe segue estacionada.
  - `test_without_mini_orb_minimize_still_minimizes`: `mini=False`, `_minimize_window()` → `isMinimized()`.
- [ ] **Step 2:** `pytest tests/test_pc_watch.py -q` → os novos falham.
- [ ] **Step 3: implementar.**
  - `_park_orb(reason, on)`: mantém `self._orb_park = set()`; adiciona/remove e chama `mini.park(bool(self._orb_park))`.
  - `_tuck_to_orb()`: sem mini orbe → `showMinimized()`. Com ela → `hide()` dentro de `_changing_window_mode=True` + `QTimer.singleShot(0, self._finish_window_mode_change)` (como `_show_window`), para o `hideEvent` não encerrar a voz.
  - `_minimize_window`: `_park_orb('minimize', True)` e `_tuck_to_orb()`.
  - `_set_game_mode`: com mini orbe, no lugar do bloco do compacto: ligado → `self._game_hid = self.isVisible() and not self.isMinimized()`, `_park_orb('game', True)`, `_tuck_to_orb()`; desligado → `_park_orb('game', False)` e `_show_window()` se `_game_hid`. Sem mini orbe, o bloco do compacto de hoje fica.
  - `_apply_focus`: no fim, `_park_orb('focus', self._focus_view is not None)`.
  - `_toggle_chat_from_orb()` (passado como `on_click`): janela visível e não minimizada → `_tuck_to_orb()`. Senão: dashboard ativo → `set_compact(True)` e `self._orb_compacted = True`; mostra (sem tirar o motivo `minimize`); move para `beside(mini.frameGeometry(), self.frameGeometry().size(), tela da orbe)`.
  - `_show_window` (menu "Abrir o Therion", bandeja): `_park_orb('minimize', False)`; se `_orb_compacted`, `set_compact(False)` e zera. O toggle não chama `_show_window` direto para não desfazer isso: separar o "mostrar" em `_raise_window()` usado pelos dois.
- [ ] **Step 4:** `pytest tests/test_pc_watch.py tests/test_constellation.py tests/test_desktop_focus.py tests/test_focus_wiring.py -q` → passa (as 3 falhas antigas do `test_cli` não entram aqui).
- [ ] **Step 5:** commit `feat(desktop): modo jogo, foco e minimizar deixam só a orbe no segundo monitor`.

### Task 3: conferir no app real

- [ ] Abrir o Therion (`scripts\Start-Therion.ps1`), pedir "modo de jogo": a janela some, a orbe vai para o canto do monitor da direita.
- [ ] Clicar na orbe: o chat pequeno abre ao lado; clicar de novo: some.
- [ ] Botão direito: "Uso do PC" abre o painel.
- [ ] "Sair do modo de jogo": a janela volta. Minimizar (−): só a orbe; "Abrir o Therion": volta tudo.
- [ ] Ligar foco: a orbe vai para o canto com o tempo; a janela fica.
- [ ] Fechar o Therion no fim do teste, ou dizer ao usuário que ficou aberto.
