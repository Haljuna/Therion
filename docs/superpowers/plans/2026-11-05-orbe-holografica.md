# Orbe holográfica Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trocar a orbe de partículas do Therion por uma esfera holográfica de peças 3D em roxo, fiel ao GIF de referência, reagindo aos 13 estados e à voz.

**Architecture:** Forma (`orb_geometry.py`, numpy puro), comportamento (`orb_motion.py`, ampliado) e desenho (`orb_renderer.py` + `orb_shaders.py`, OpenGL 2.1) separados. `Constellation` continua sendo a moldura usada por `dashboard.py` e `launcher.py`, agora com `OrbGL` no lugar de `ParticleGL`. Rastro por FBOs alternados com decaimento; brilho em até 3 escalas.

**Tech Stack:** Python, PySide6 (QOpenGLWidget, QOpenGLShaderProgram, QOpenGLFramebufferObject), numpy, GLSL 1.20, pytest.

**Spec:** `docs/superpowers/specs/2026-11-05-orbe-holografica-design.md`

## Global Constraints

- Contexto OpenGL 2.1 compatibility (`#version 120`); sem geometry shader; linhas viram quadriláteros no vertex shader.
- Sem dependências novas.
- Cores: base `#7C4DFF`, contornos `#C9B8FF`, miolo `#F4F0FF`, clarão `#DDEBFF`, erro `#FF6B7A` misturado a 30%, fundo `#09090F`.
- Raio da esfera = 1; nada além de raio 1,2.
- Lado de trás com 35% do brilho.
- Linhas: 1,2 px numa orbe de 500 px, nunca menos de 1 px.
- "Pequena" = orbe abaixo de 260 px, com transição gradual.
- Clarão de ~0,3 s, no máximo um a cada 4 s, só na passagem thinking/executing → synthesizing/speaking.
- "Reduzir movimento": sem giro, sem rastro, sem clarão; só cor e brilho mudam.
- Em thinking e executing: 30 quadros/s (intervalo 33 ms) e brilho mais leve.
- Não versionar o GIF de referência nem quadros dele. Não fazer push.
- Rodar testes com `.venv/Scripts/python.exe scripts/test-v4.py <arquivos> -q` a partir de `F:\Therion\app`.

## Review Focus

1. A orbe muda de tamanho no meio da animação (o painel anima `set_focus_rect`; a janela entra em tela cheia): os FBOs são recriados sem quadro preto e sem quebrar → teste na Task 3.
2. Estados alternando rápido (thinking → speaking → thinking → speaking em 2 s): um único clarão → teste na Task 2.
3. Ligar "Reduzir movimento" com rastro na tela: o rastro some no quadro seguinte, sem mancha congelada → teste na Task 5.
4. `cleanup()` chamado duas vezes ou com contexto já destruído (o painel chama ao fechar): não lança erro → teste na Task 3.
5. Orbe minúscula ou zerada (0 px, 40 px) e gigante (4000 px): largura de linha e detalhe finitos, dentro dos limites → teste na Task 3.

---

### Task 1: Branch e forma da orbe (`orb_geometry.py`)

**Files:**
- Create: `therion/interface/orb_geometry.py`
- Test: `tests/test_orb_geometry.py`

**Interfaces:**
- Produces:
  - Constantes de camada: `ANTENNA=0, CAGE=1, SHELL=2, CORE=3, GYRO=4, EYE=5, SPARKS=6`.
  - `VERTEX_FLOATS = 12`. Layout de cada vértice (float32): `x,y,z, ox,oy,oz, side, layer, spin, detail, glow, seed`.
    - `ox,oy,oz`: outra ponta do segmento (só linhas; nos demais = posição). `side`: ±1 nas linhas, 0 nos demais.
    - `spin`: fator de giro relativo à casca (casca = 1,0).
    - `detail`: 0 = sempre aparece, 1 = some quando pequena.
    - `glow`: brilho de 0 a 2.
  - `@dataclass(frozen=True) class OrbMesh: surfaces: np.ndarray; lines: np.ndarray; points: np.ndarray`. Cada array tem formato `(n, 12)`, float32. `surfaces` e `lines` são listas de triângulos (cada segmento de linha vira 6 vértices).
  - `shell_plates(seed: int = 419) -> np.ndarray` com formato `(n, 4)`: `lat0, lat1, lon0, lon1` em radianos.
  - `build_orb(seed: int = 419) -> OrbMesh`.
- Eixos fixos no shader (Task 3), não na malha: GYRO é gerado no plano XY local e inclinado 25° em X no shader; EYE é gerado no plano XY (de frente).

- [ ] **Step 1: Criar a branch e descartar a tentativa anterior**

```bash
cd /f/Therion/app
git checkout -- therion/interface/constellation.py therion/interface/presentation.py tests/test_constellation.py
git checkout -b orbe-holografica
```
Expected: `git status --short` mostra só os 2 READMEs de scripts que já estavam modificados e os arquivos da spec e do plano.

- [ ] **Step 2: Escrever os testes que falham**

```python
from therion.interface.orb_geometry import (build_orb, shell_plates, VERTEX_FLOATS,
    ANTENNA, CAGE, SHELL, CORE, GYRO, EYE, SPARKS)

def test_mesh_has_every_layer_inside_the_sphere():
    mesh = build_orb()
    allv = np.vstack((mesh.surfaces, mesh.lines, mesh.points))
    assert allv.dtype == np.float32 and allv.shape[1] == VERTEX_FLOATS
    assert np.isfinite(allv).all()
    assert set(np.unique(allv[:, 7]).astype(int)) == {ANTENNA, CAGE, SHELL, CORE, GYRO, EYE, SPARKS}
    assert np.linalg.norm(allv[:, :3], axis=1).max() <= 1.2
    assert len(mesh.surfaces) % 3 == 0 and len(mesh.lines) % 6 == 0

def test_shell_covers_between_half_and_seventy_percent():
    plates = shell_plates()
    assert 60 <= len(plates) <= 80
    rng = np.random.default_rng(1); v = rng.normal(size=(20000, 3)); v /= np.linalg.norm(v, axis=1)[:, None]
    lat = np.arcsin(v[:, 1]); lon = np.mod(np.arctan2(v[:, 2], v[:, 0]), 2*np.pi)
    hit = np.zeros(len(v), bool)
    for lat0, lat1, lon0, lon1 in plates:
        d = np.mod(lon - lon0, 2*np.pi)
        hit |= (lat >= lat0) & (lat <= lat1) & (d <= np.mod(lon1 - lon0, 2*np.pi))
    assert .5 <= hit.mean() <= .7

def test_detail_flags_follow_the_spec():
    mesh = build_orb()
    def share(arr, layer): sel = arr[arr[:, 7] == layer]; return (sel[:, 9] == 1).mean()
    assert share(mesh.points, SPARKS) == pytest.approx(.7, abs=.05)
    assert share(mesh.lines, CORE) > .8            # miolo some quase todo
    assert share(mesh.lines, CAGE) == pytest.approx(.5, abs=.1)
    for layer in (ANTENNA, GYRO, EYE): assert share(mesh.lines, layer) == 0

def test_spin_factors_and_counts():
    mesh = build_orb()
    spins = {int(l): set(np.round(mesh.lines[mesh.lines[:, 7] == l, 8], 3)) for l in (ANTENNA, CAGE, SHELL, CORE, GYRO)}
    assert spins == {ANTENNA: {1.0}, CAGE: {1.0}, SHELL: {1.0}, CORE: {-0.5}, GYRO: {1.5}}
    assert 1400 <= (mesh.points[:, 7] == SPARKS).sum() <= 1600
    eye = mesh.lines[mesh.lines[:, 7] == EYE]
    assert set(np.round(eye[:, 8], 3)) <= {0.0, 2.0}  # anel parado, cometa a 2x

def test_build_is_deterministic():
    a, b = build_orb(), build_orb()
    assert all(np.array_equal(x, y) for x, y in zip((a.surfaces, a.lines, a.points), (b.surfaces, b.lines, b.points)))
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_geometry.py -q`
Expected: FAIL com `ModuleNotFoundError: therion.interface.orb_geometry`.

- [ ] **Step 4: Implementar `orb_geometry.py`**

Valores da spec, por camada (raio 1):
- ANTENNA: mastro de y = 1,0 a 1,18; risco curvo de raio 0,12 no topo. `glow` 0,8.
- CAGE: barrinhas latitudinais de ~8° de comprimento, empilhadas a cada 3° entre −60° e 60°, em 6 longitudes igualmente espaçadas, no raio 1,0. Alterne `detail` 0/1 entre barras vizinhas. `glow` 0,9.
- SHELL: placas de `shell_plates` (sorteio com `default_rng(seed)`: lat0 em [−1,25; 1,15], dlat em [0,08; 0,30], dlon em [0,10; 0,42]; sorteie até a cobertura ficar entre 50% e 70%) no raio 0,96. Preenchimento em `surfaces` (`glow` sorteado em [0,10; 0,18]) e contorno em `lines` (`glow` 1,0). 30% com divisória ou duas "janelas" (linhas de latitude a 1/3 e 2/3), estas com `detail` 1.
- CORE: ~60 caixas (12 arestas em `lines`, `glow` 0,6; faces em `surfaces`, `glow` 0,05), centro em raio [0,25; 0,8], largura e profundidade [0,04; 0,13], altura [0,07; 0,30], giradas em Y para encarar o centro. Exatamente 85% com `detail` 1 (as primeiras 51 de 60).
- GYRO: anel de raio 0,55 no plano XY, com 3 falhas iguais de 20°. `glow` 1,0.
- EYE: anéis de raio 0,10 (`glow` 1,6) e 0,05 (`glow` 1,2) com `spin` 0; cometa de 270° no raio 0,16 com `spin` 2,0 e `glow` subindo de 0 (cauda) a 1,8 (cabeça). Núcleo: pontos em `points` no raio < 0,05, `glow` 2,0, `layer` EYE.
- SPARKS: 1.500 pontos em raio [0,3; 1,05], `glow` [0,4; 1,2]; `spin` = fator da camada cujo raio é o mais próximo (core −0,5 para r < 0,8; senão 1,0); exatamente 70% com `detail` 1 (os primeiros 1.050).
- Curvas viram segmentos com no máximo 3° por segmento. Linha → 6 vértices (dois triângulos) com `side` = −1, +1, −1, +1, −1, +1 e `ox,oy,oz` = a outra ponta.

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_geometry.py -q`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add therion/interface/orb_geometry.py tests/test_orb_geometry.py docs/superpowers/specs/2026-11-05-orbe-holografica-design.md docs/superpowers/plans/2026-11-05-orbe-holografica.md
git commit -m "feat(orbe): forma da orbe holográfica em camadas"
```

---

### Task 2: Comportamento por estado (`orb_motion.py`)

**Files:**
- Modify: `therion/interface/orb_motion.py`
- Test: `tests/test_orb_motion.py` (acrescentar; os testes atuais continuam passando sem mudança)

**Interfaces:**
- Consumes: nada das outras tasks.
- Produces (novos atributos de `OrbMotion`, todos `float`, atualizados em `advance`):
  - `SPIN_SECONDS: dict[str, float]` (segundos por volta da casca; `0` = parada).
  - `spin` (ângulo acumulado da casca, rad), `spin_rate` (rad/s atual, suavizado com o mesmo decaimento de 0,3 s de `speed`).
  - `trail` 0..1, `flash` 0..1, `rim` 0..1, `eye` 0..1,2, `tint` 0..1, `assembly` 0..1.
  - `flash_ready_in` (segundos até o próximo clarão permitido).

Valores:
- `SPIN_SECONDS = {'idle':40,'preparing':20,'listening':120,'transcribing':12,'thinking':6,'executing':4,'synthesizing':20,'speaking':14,'awaiting_confirmation':90,'clarification':90,'error':0,'uncertain':0,'partial':40}`
- `trail = clamp((spin_rate - 2π/40) / (2π/4 - 2π/40), 0, 1)`.
- `flash`: vai a 1 em `set_visual` quando o estado anterior ∈ {thinking, executing}, o novo ∈ {synthesizing, speaking} e `flash_ready_in <= 0`; decai com τ = 0,1 s (praticamente zero em 0,3 s); arma `flash_ready_in = 4`.
- `rim`: listening → `energy`; awaiting_confirmation/clarification → `.5 + .5*sin(π*t)` (uma piscada a cada 2 s); demais → 0.
- `eye`: speaking → `.7 + .5*energy`; synthesizing → `.6 + .15*sin(2π*t/2.5)`; error/uncertain → .25; partial → .55; demais → .7. Mistura suave com τ = 0,11 s (igual a `blend`).
- `tint`: error/uncertain → 1, demais → 0, mesma mistura.
- `assembly`: preparing → sobe de 0 a 1 em 1,2 s (linear) desde a entrada no estado; qualquer outro estado → 1.
- `reduced=True`: `spin_rate = trail = flash = 0`, `spin` congelado; `rim`, `eye`, `tint` vão direto ao alvo; `assembly = 1`.

- [ ] **Step 1: Escrever os testes que falham**

```python
from therion.interface.orb_motion import SPIN_SECONDS

def test_spin_follows_spec_seconds_per_turn():
    for state, seconds in (('idle', 40), ('thinking', 6), ('executing', 4), ('listening', 120)):
        m = OrbMotion(); m.set_visual(state); run(m, 3)
        assert m.spin_rate == pytest.approx(2*math.pi/seconds, rel=.01)
    m = OrbMotion(); m.set_visual('error'); run(m, 3); assert m.spin_rate == pytest.approx(0, abs=1e-3)

def test_trail_grows_with_speed():
    vals = []
    for state in ('idle', 'thinking', 'executing'):
        m = OrbMotion(); m.set_visual(state); run(m, 3); vals.append(m.trail)
    assert vals[0] == pytest.approx(0, abs=.01) and vals[0] < vals[1] < vals[2] and vals[2] == pytest.approx(1, abs=.01)

def test_flash_only_on_think_to_speak_and_at_most_every_four_seconds():
    m = OrbMotion(); m.set_visual('idle'); run(m, 5)
    m.set_visual('speaking'); assert m.flash == 0
    m.set_visual('thinking'); run(m, 1); m.set_visual('speaking'); assert m.flash == 1
    run(m, .3); assert m.flash < .06
    for _ in range(4):  # alternância rápida (Review Focus 2)
        m.set_visual('thinking'); run(m, .25); m.set_visual('speaking'); assert m.flash < .06; run(m, .25)
    run(m, 2); m.set_visual('executing'); run(m, .1); m.set_visual('synthesizing'); assert m.flash == 1

def test_rim_tracks_voice_while_listening_and_blinks_while_waiting():
    m = OrbMotion(); m.set_visual('listening', .8); run(m, .5); assert m.rim == pytest.approx(m.energy)
    m.set_visual('awaiting_confirmation'); seen = []
    for _ in range(120): m.advance(1/60); seen.append(m.rim)
    assert min(seen) < .1 and max(seen) > .9
    m.set_visual('idle'); run(m, .1); assert m.rim == 0

def test_eye_and_tint_targets():
    for state, eye, tint in (('idle', .7, 0), ('error', .25, 1), ('partial', .55, 0)):
        m = OrbMotion(); m.set_visual(state); run(m, 1)
        assert m.eye == pytest.approx(eye, abs=.01) and m.tint == pytest.approx(tint, abs=.01)
    m = OrbMotion(); m.set_visual('speaking', 1); run(m, 1); assert m.eye == pytest.approx(1.2, abs=.02)

def test_assembly_plays_during_preparing():
    m = OrbMotion(); m.set_visual('preparing'); run(m, .6); assert .4 < m.assembly < .6
    run(m, 1); assert m.assembly == 1
    m.set_visual('idle'); assert m.assembly == 1

def test_reduced_motion_has_no_spin_trail_or_flash():
    m = OrbMotion(); m.set_visual('thinking'); run(m, 1); m.set_visual('speaking')
    spin = m.spin; run(m, 1, reduced=True)
    assert m.spin == spin and m.spin_rate == m.trail == m.flash == 0 and m.assembly == 1
    m.set_visual('error'); run(m, .1, reduced=True); assert m.tint == 1 and m.eye == .25

def test_new_channels_are_frame_rate_independent():
    out = []
    for rate in (30, 60, 120):
        m = OrbMotion(); m.set_visual('thinking'); run(m, 1, rate); m.set_visual('speaking', .6); run(m, 1, rate)
        out.append((m.spin, m.spin_rate, m.trail, m.flash, m.eye))
    for s in out[1:]: assert s == pytest.approx(out[0], abs=1e-6)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_motion.py -q`
Expected: FAIL em `ImportError: cannot import name 'SPIN_SECONDS'`; os 13 testes antigos continuam passando.

- [ ] **Step 3: Implementar os novos canais em `OrbMotion`**

Integre `spin` analiticamente, como `phase` (mesma fórmula de decaimento de 0,3 s), para manter a independência de cadência. `t` dos senos é um relógio interno somado em `advance` (não usa `time`). `flash` e `flash_ready_in` decaem por `exp(-dt/.1)` e `dt`. Não mexa em `SPEEDS`, `EXPRESSIONS`, `phase` nem `presence` (outros arquivos e testes usam).

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_motion.py -q`
Expected: todos passam (antigos e novos).

- [ ] **Step 5: Commit**

```bash
git add therion/interface/orb_motion.py tests/test_orb_motion.py
git commit -m "feat(orbe): giro, rastro, clarão e canais de estado"
```

---

### Task 3: Desenho básico e troca na moldura (etapa 1: forma parada)

**Files:**
- Create: `therion/interface/orb_shaders.py` (strings GLSL)
- Create: `therion/interface/orb_renderer.py`
- Create: `scripts/orb_snapshot.py` (ferramenta de print)
- Modify: `therion/interface/constellation.py` (remove `VERTEX`, `FRAGMENT`, `particle_data`, `visible_particle_count`, `ParticleGL`; `Constellation` passa a criar `OrbGL`; `QUAD_VERTEX`/`BLOOM_FRAGMENT` vão para `orb_shaders.py`)
- Modify: `therion/interface/presentation.py:69` (troca `COUNTS` por `BLOOM_LEVELS = {'low': 1, 'medium': 2, 'high': 3}`)
- Test: `tests/test_orb_renderer.py`; Modify: `tests/test_constellation.py:92-112` (remove os dois testes de partículas)

**Interfaces:**
- Consumes: `build_orb()`, `OrbMesh`, `VERTEX_FLOATS` (Task 1); `OrbMotion` e os canais da Task 2.
- Produces:
  - Funções puras em `orb_renderer.py`:
    - `line_width_px(orb_px: float) -> float` = `max(1.0, 1.2 * orb_px / 500)`, finita para qualquer entrada ≥ 0.
    - `detail_level(orb_px: float) -> float` = smoothstep de 200 a 320 px (0 abaixo de 200, 1 acima de 320).
    - `frame_interval_ms(state: str) -> int` = 33 em thinking/executing, senão `FRAME_INTERVAL_MS`.
    - `bloom_levels(quality: str, state: str) -> int` = `BLOOM_LEVELS[quality]`, limitado a 2 em thinking/executing.
  - `class OrbGL(QOpenGLWidget)` com a mesma interface pública de `ParticleGL`: sinais `failed(str)` e `metrics(dict)` (chaves `fps`, `frame_ms`, `quality`, `detail`); atributos `quality`, `state`, `focus_rect`, `animation` (`OrbMotion`), `scene_motion`, `reduced`, `ready`, `disabled`, `timer`, `target_scene_attention`; métodos `set_visual(state, intensity)`, `set_quality(quality)`, `set_active(active)`, `cleanup()`.
  - Uniforms do shader da cena: `spin` (casca), `clock`, `detail`, `lineWidth`, `viewport`, `fit`, `center`, `aspect`, `eye`, `tint`, `rim`, `flash`, `assembly`, `energy`. Nesta task só `spin`, `detail`, `lineWidth` e geometria têm efeito; os demais existem com valor neutro.
  - `scripts/orb_snapshot.py --state STATE --size PX --seconds S --out PNG [--sheet N]` abre `OrbGL`, aplica o estado, espera S segundos e salva PNG (ou uma folha com N quadros espaçados).

Shader da cena (decisões que o engenheiro não deduz sozinho):
- Rotação por vértice: a casca gira `spin * spin_factor` em Y. GYRO: gira no próprio plano XY e depois inclina 25° em X. EYE: gira em Z (de frente). SPARKS: em Y, como a casca.
- Projeção: a mesma do shader antigo (`depth = 1/(3.1 - z*.48)`, escala `2.05*fit`, `center`), para manter o tamanho na tela.
- Lado de trás: depois da rotação, `z < 0` multiplica o brilho por 0,35 (transição suave entre z −0,1 e 0,1).
- Linhas: no vertex shader, projete as duas pontas, pegue a normal 2D do segmento na tela e desloque o vértice `side * lineWidth/2` px.
- Detalhe: alfa multiplicado por `mix(1, detail, detail_attr)`.
- Cor: `mix(#7C4DFF, #C9B8FF, glow_norm)` e, acima de glow 1,2, até `#F4F0FF`. Mistura aditiva (`ONE, ONE`), sem depth test.
- Ordem de desenho: superfícies, linhas, pontos.

- [ ] **Step 1: Escrever os testes que falham**

```python
from therion.interface.orb_renderer import line_width_px, detail_level, frame_interval_ms, bloom_levels
from therion.interface.graphics import FRAME_INTERVAL_MS

@pytest.mark.parametrize('px', [0, 40, 259, 500, 4000])   # Review Focus 5
def test_helpers_stay_finite_and_bounded(px):
    w, d = line_width_px(px), detail_level(px)
    assert math.isfinite(w) and w >= 1 and math.isfinite(d) and 0 <= d <= 1

def test_helper_values_from_spec():
    assert line_width_px(500) == pytest.approx(1.2) and line_width_px(100) == 1
    assert detail_level(200) == 0 and detail_level(320) == 1 and 0 < detail_level(260) < 1
    assert frame_interval_ms('thinking') == frame_interval_ms('executing') == 33
    assert frame_interval_ms('idle') == FRAME_INTERVAL_MS
    assert bloom_levels('high', 'idle') == 3 and bloom_levels('high', 'thinking') == 2 and bloom_levels('low', 'thinking') == 1

gl = pytest.mark.skipif(os.environ.get('QT_QPA_PLATFORM') in {'offscreen', 'minimal'}, reason='sem OpenGL')

@gl
def test_orb_draws_something_and_survives_resize(app):   # Review Focus 1
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(400, 400); w.show(); w.set_active(True); settle(lambda: w.ready or w.disabled)
    assert w.ready
    for size in (200, 900, 120, 400):
        w.resize(size, size); pump(.15); assert w.ready and not w.disabled
    img = w.grabFramebuffer(); c = img.width() // 2, img.height() // 2
    brightest = max(img.pixelColor(x, y).lightness() for x in range(c[0]-10, c[0]+11) for y in range(c[1]-30, c[1]+11))
    assert brightest > 120   # o olho está aceso perto do centro

@gl
def test_cleanup_is_idempotent(app):   # Review Focus 4
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(300, 300); w.show(); settle(lambda: w.ready)
    w.cleanup(); w.cleanup(); w.close(); w.cleanup()
```

(`settle`, `pump` e `app` no mesmo estilo de `tests/test_constellation.py`; `pump(s)` processa eventos por `s` segundos.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_renderer.py -q`
Expected: FAIL com `ModuleNotFoundError: therion.interface.orb_renderer`.

- [ ] **Step 3: Implementar `orb_shaders.py`, `orb_renderer.py` (só a passada da cena, direto na tela) e `scripts/orb_snapshot.py`**

`OrbGL` envia os três grupos de `OrbMesh` em três VBOs no `initializeGL`, com o layout de 12 floats (stride 48). FBOs, rastro e brilho em escalas ficam para as Tasks 4 e 5; nesta task, mantenha o `BLOOM_FRAGMENT` atual só para halo e chão. Copie de `ParticleGL` o tratamento de falha (`failed.emit` com as mesmas mensagens), métricas, `scene_attention` e `cleanup`.

- [ ] **Step 4: Trocar `ParticleGL` por `OrbGL` em `constellation.py` e `COUNTS` por `BLOOM_LEVELS`**

`StaticConstellation` continua com o desenho antigo até a Task 6. Remova de `tests/test_constellation.py` os testes `test_particle_layers_remain_distributed_at_every_quality` e `test_responsive_density_preserves_coverage_without_saturating_small_sphere`.

- [ ] **Step 5: Rodar e ver passar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_renderer.py tests/test_orb_geometry.py tests/test_orb_motion.py tests/test_constellation.py tests/test_fullscreen.py -q`
Expected: tudo passa.

- [ ] **Step 6: Print para o usuário (etapa 1)**

Run: `.venv/Scripts/python.exe -I scripts/orb_snapshot.py --state idle --size 720 --seconds 1 --out <scratchpad>/etapa1.png`
Monte o lado a lado com o quadro 0 do GIF (o GIF é aberto pelo navegador, nunca salvo no repositório) e mande ao usuário. **Pare até ele aprovar a forma.**

- [ ] **Step 7: Commit**

```bash
git add therion/interface/orb_shaders.py therion/interface/orb_renderer.py scripts/orb_snapshot.py therion/interface/constellation.py therion/interface/presentation.py tests/test_orb_renderer.py tests/test_constellation.py
git commit -m "feat(orbe): desenho das peças e troca da orbe de partículas"
```

---

### Task 4: Luz e profundidade (etapa 2)

**Files:**
- Modify: `therion/interface/orb_renderer.py`, `therion/interface/orb_shaders.py`
- Test: `tests/test_orb_renderer.py`

**Interfaces:**
- Consumes: `OrbGL`, `bloom_levels` (Task 3).
- Produces: `OrbGL.bloom_chain_sizes() -> list[QSize]` (tamanhos dos FBOs de brilho atuais, para teste).

Passadas: cena num FBO em tamanho cheio → brilho com `bloom_levels(quality, state)` níveis (1/2, 1/4, 1/8), cada um com desfoque separável de 9 amostras → composição aditiva (peso por nível: 0,9, 0,7, 0,5) + halo e chão do `BLOOM_FRAGMENT` atual, recoloridos para o violeta `#7C4DFF`. O raio do brilho mais largo deve dar ~6% do diâmetro da orbe. FBOs recriados só quando o tamanho muda.

- [ ] **Step 1: Escrever o teste que falha**

```python
@gl
def test_bloom_chain_follows_quality_and_state(app):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(600, 600); w.show(); w.set_quality('high'); w.set_active(True); settle(lambda: w.ready); pump(.2)
    sizes = w.bloom_chain_sizes(); assert len(sizes) == 3 and sizes[0].width() == round(600*w.devicePixelRatioF()/2)
    w.set_visual('thinking', 0); pump(.2); assert len(w.bloom_chain_sizes()) == 2
    w.set_quality('low'); pump(.2); assert len(w.bloom_chain_sizes()) == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_renderer.py::test_bloom_chain_follows_quality_and_state -q`
Expected: FAIL com `AttributeError: 'OrbGL' object has no attribute 'bloom_chain_sizes'`.

- [ ] **Step 3: Implementar a cadeia de brilho e a composição**

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_renderer.py -q`
Expected: tudo passa.

- [ ] **Step 5: Print para o usuário (etapa 2)**

Mesmo comando da Task 3 com `--out <scratchpad>/etapa2.png`, lado a lado com o quadro 0. Pergunte especificamente se parou de parecer "pó". **Pare até ele aprovar.**

- [ ] **Step 6: Commit**

```bash
git add therion/interface/orb_renderer.py therion/interface/orb_shaders.py tests/test_orb_renderer.py
git commit -m "feat(orbe): brilho em escalas e profundidade"
```

---

### Task 5: Movimento e rastro (etapa 3)

**Files:**
- Modify: `therion/interface/orb_renderer.py`, `therion/interface/orb_shaders.py`
- Test: `tests/test_orb_renderer.py`

**Interfaces:**
- Consumes: `OrbMotion.spin`, `.trail` (Task 2).
- Produces: `trail_keep(trail: float, dt: float) -> float` (pura) = fração do quadro anterior mantida: `exp(-dt / (0.02 + 0.16*trail))`. Com `trail` 0 o rastro some em ~2 quadros; com `trail` 1 dura ~0,5 s. `OrbGL.trail_cleared` (bool, vira True no quadro em que o rastro foi zerado).

Passada nova entre a cena e o brilho: dois FBOs de tamanho cheio alternados; `saída = cena + anterior * trail_keep`. O brilho é aplicado sobre a saída do rastro. Faíscas esticam: no vertex shader, pontos viram traços tangenciais de comprimento `trail * 0.06` (em unidades da esfera) na direção do giro. Ao trocar o tamanho, ao ligar `reduced` ou com `trail_keep` < 0,01, limpe os dois FBOs.

- [ ] **Step 1: Escrever os testes que falham**

```python
from therion.interface.orb_renderer import trail_keep

def test_trail_keep_values():
    assert trail_keep(0, 1/60) < .45 and trail_keep(1, 1/60) > .9
    assert trail_keep(1, 0) == 1 and 0 <= trail_keep(.5, 10) < 1e-6

@gl
def test_reduced_motion_clears_trail_next_frame(app):   # Review Focus 3
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(400, 400); w.show(); w.set_active(True); settle(lambda: w.ready)
    w.set_visual('executing', 0); pump(1.)
    w.reduced = True; w.update(); pump(.1)
    assert w.trail_cleared and w.animation.trail == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_renderer.py -q`
Expected: FAIL com `ImportError: cannot import name 'trail_keep'`.

- [ ] **Step 3: Implementar o rastro, o giro por camada e as faíscas esticadas**

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_renderer.py tests/test_orb_motion.py -q`
Expected: tudo passa.

- [ ] **Step 5: Folha de quadros para o usuário (etapa 3)**

Run: `.venv/Scripts/python.exe -I scripts/orb_snapshot.py --state thinking --size 600 --seconds 3 --sheet 12 --out <scratchpad>/etapa3.png`
Compare com os quadros 30–39 do GIF. **Pare até ele aprovar.**

- [ ] **Step 6: Commit**

```bash
git add therion/interface/orb_renderer.py therion/interface/orb_shaders.py tests/test_orb_renderer.py
git commit -m "feat(orbe): giro por camada e rastro de movimento"
```

---

### Task 6: Estados no desenho e reserva 2D (etapa 4)

**Files:**
- Modify: `therion/interface/orb_renderer.py`, `therion/interface/orb_shaders.py`, `therion/interface/constellation.py` (`StaticConstellation`)
- Test: `tests/test_orb_renderer.py`, `tests/test_constellation.py`

**Interfaces:**
- Consumes: `eye`, `tint`, `rim`, `flash`, `assembly`, `energy` (Task 2); `build_orb` (Task 1).
- Produces: `StaticConstellation` desenhando a projeção 2D de `build_orb().lines` (sem giro) com QPainter.

No shader:
- `eye` multiplica o brilho da camada EYE.
- `tint` mistura 30% de `#FF6B7A` em tudo e reduz o brilho das peças a 60%.
- `rim` acende as barrinhas da CAGE: brilho × `(1 + 1.5*rim)`.
- `flash`: soma `#DDEBFF * flash * 2.0 * exp(-r²/0.02)` em torno do olho (r = distância ao centro na esfera) e esfria a paleta (mistura até 40% para `#DDEBFF`).
- `assembly`: posição = `mix(posição*0.05, posição, smoothstep(seed*0.6, seed*0.6+0.4, assembly))`, de modo que as peças saem do centro em ordem.

- [ ] **Step 1: Escrever os testes que falham**

```python
@gl
@pytest.mark.parametrize('state', ['idle', 'error'])
def test_state_changes_the_picture(app, state):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(300, 300); w.show(); w.set_active(True); settle(lambda: w.ready)
    w.set_visual(state, 0); pump(.6)
    c = w.grabFramebuffer().pixelColor(150, 150)
    if state == 'error': assert c.red() > c.blue() * .6   # toque avermelhado no olho
    else: assert c.blue() > c.red()

def test_static_fallback_uses_new_shape(app):
    from therion.interface.constellation import StaticConstellation
    s = StaticConstellation(); s.resize(300, 300)
    img = s.grab().toImage()
    assert img.pixelColor(150, 150) != QColor('#09090F')
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_renderer.py tests/test_constellation.py -q`
Expected: FAIL nos dois testes novos.

- [ ] **Step 3: Implementar os uniforms de estado no shader e a nova `StaticConstellation`**

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_renderer.py tests/test_constellation.py tests/test_orb_motion.py -q`
Expected: tudo passa.

- [ ] **Step 5: Folhas por estado para o usuário (etapa 4)**

Gere uma folha de 6 quadros para cada um destes: idle, preparing, listening (com intensidade 0,7), thinking → speaking (deve aparecer o clarão), awaiting_confirmation e error. Mande junto com a tabela de estados da spec. **Pare até ele aprovar.**

- [ ] **Step 6: Commit**

```bash
git add therion/interface/orb_renderer.py therion/interface/orb_shaders.py therion/interface/constellation.py tests/test_orb_renderer.py tests/test_constellation.py
git commit -m "feat(orbe): estados, clarão e reserva 2D"
```

---

### Task 7: Tamanhos, desempenho e fechamento (etapa 5)

**Files:**
- Modify: `therion/interface/orb_renderer.py` (cadência por estado e detalhe por tamanho)
- Test: `tests/test_orb_renderer.py`
- Modify: `docs/CODEBASE_MAP.md` (seção da interface: orbe agora em `orb_geometry`/`orb_motion`/`orb_renderer`)

**Interfaces:**
- Consumes: `frame_interval_ms`, `detail_level`, `line_width_px` (Task 3).

- [ ] **Step 1: Escrever os testes que falham**

```python
@gl
def test_cadence_and_detail_follow_state_and_size(app):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(600, 600); w.show(); w.set_active(True); settle(lambda: w.ready)
    w.set_visual('thinking', 0); pump(.1); assert w.timer.interval() == 33
    w.set_visual('idle', 0); pump(.1); assert w.timer.interval() == FRAME_INTERVAL_MS
    w.focus_rect = QRectF(0, 0, 150, 150); pump(.2); assert w.current_detail() == 0
    w.focus_rect = QRectF(0, 0, 500, 500); pump(.2); assert w.current_detail() == 1
```

(`OrbGL.current_detail() -> float` = `detail_level` do lado menor do `focus_rect` em px lógicos.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_renderer.py::test_cadence_and_detail_follow_state_and_size -q`
Expected: FAIL.

- [ ] **Step 3: Implementar a troca de intervalo do timer em `set_visual` e `current_detail()`**

- [ ] **Step 4: Rodar a suíte da interface e a completa**

Run: `.venv/Scripts/python.exe scripts/test-v4.py tests/test_orb_geometry.py tests/test_orb_motion.py tests/test_orb_renderer.py tests/test_constellation.py tests/test_fullscreen.py tests/test_obsidian_interface.py tests/test_obsidian_polish.py tests/test_interface_followup.py -q`
Expected: tudo passa.
Run: `.venv/Scripts/python.exe scripts/test-v4.py tests -q` (~11 min, em segundo plano)
Expected: só as falhas da baseline (19 em 2026-11-05: test_desktop_integration, test_session_recall, test_autonomous_integration, test_current_time_local, test_gmail_small_context, test_cli oscilando, test_startup_reuse oscilando, test_agent_desktop UIA).

- [ ] **Step 5: Medir o desempenho**

- Orbe sozinha: `orb_snapshot.py --state idle --size 720 --seconds 5` imprime `metrics`. Esperado: fps ≥ 59 em high.
- Com o modelo: peça ao usuário para abrir o Therion na branch e fazer a mesma pergunta 3 vezes na master e 3 na branch. Compare o tempo registrado em `%LOCALAPPDATA%\Therion\conversas\*.md`. Esperado: diferença média ≤ 3%.

- [ ] **Step 6: Prints finais para o usuário**

Tela inicial grande, painel aberto (orbe pequena) e launcher, cada um lado a lado com o GIF quando fizer sentido. **Pare até ele dizer "é isso".**

- [ ] **Step 7: Commit**

```bash
git add therion/interface/orb_renderer.py tests/test_orb_renderer.py docs/CODEBASE_MAP.md
git commit -m "feat(orbe): cadência por estado, detalhe por tamanho e mapa atualizado"
```

Juntar na master e fazer push só quando o usuário pedir.
