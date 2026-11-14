# Estação Therion, fase 1: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** um porteiro sempre ligado no PC que serve ao tablet uma página de terminal com o anel (parado/offline), o status do sistema e 4 botões que religam as peças do Therion.

**Architecture:** processo Python só com biblioteca padrão em `scripts/estacao/`, dividido em segurança (IP, cookie, pareamento), saúde (sondas a cada 2 s), ações (lista fixa de scripts .ps1, uma por vez) e o servidor HTTP que liga tudo. A página é um único HTML com JavaScript ES5, que consulta `/estado` a cada 1 s.

**Tech Stack:** Python 3.14 (`http.server`, `ctypes`, `subprocess`, `secrets`), PowerShell 5.1, HTML/SVG/ES5, pytest com testes no estilo `unittest` (padrão do repositório).

**Spec:** `docs/superpowers/specs/2026-11-09-estacao-therion-design.md`. A fase 2 (ponte, estados completos, conversa, confirmação) fica para outro plano.

**Onde executar:** num worktree novo a partir de `master` (branch `estacao-therion`), nunca na pasta `F:\Therion\app`, que está na branch `orbe-holografica` de outra sessão. Primeiro passo do worktree: copiar a spec e este plano (hoje não versionados em `F:\Therion\app`) e commitar os dois.

## Global Constraints

- Só biblioteca padrão do Python no porteiro; ele não importa o pacote `therion`.
- Porta do porteiro: 3904. Ollama do Therion: `http://127.0.0.1:11435/api/version`. Voz: `http://127.0.0.1:3901/health`. Transcrição: `http://127.0.0.1:3902/stt/health`. Timeout de 1 s por sonda; saúde medida a cada 2 s.
- Pasta de dados: `%LOCALAPPDATA%\Therion\estacao\` (`config.json`, `token`, `pareamento.json`, `acoes.log`). Nada disso vai para o repositório, que é público. Nenhum IP real em código, testes ou README.
- Token: `secrets.token_urlsafe(32)`. Código de pareamento: 6 dígitos, válido por 300 s, no máximo 5 tentativas erradas.
- Uma ação por vez; timeout de 120 s. Scripts rodam com `powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File <script>`; nada vindo do tablet entra na linha de comando.
- Página: só ES5 (sem `=>`, `let `, `const `, crase, `fetch(`, `class `), `XMLHttpRequest`, consulta a cada 1000 ms, anel em SVG redesenhado a cada 100 ms com 120 pontos.
- Paleta: fundo `#0d0a18`, texto `#b9a8ff`, apagado `#6e5bd6`, claro `#e7e0ff`, linhas `#9b87ff`/`#4b3bb0`, erro `#e2738f`.
- Testes ficam em `tests/`, carregam os módulos com `sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts' / 'estacao'))` e rodam com `.venv/Scripts/python.exe -m pytest tests/test_estacao_*.py -v` a partir da raiz do repositório.

## Review Focus

1. **Script que deixa processo filho rodando** (`Launch-Therion.ps1`, `start-local-ollama.ps1` usam `Start-Process`): a ação não pode ficar "ocupada" para sempre esperando o pipe fechar. A saída vai para `acoes.log`, nunca para pipes (teste na Task 3).
2. **Cabeçalho `Cookie` com outros cookies ou malformado:** `a=1; estacao=<token>` passa; lixo não derruba o servidor (teste na Task 1).
3. **Dois toques chegando juntos:** só um é aceito, e o outro recebe `ocupado` (teste na Task 3).
4. **POST sem `Content-Length`, ou com corpo maior que 1024 bytes:** responde `400` sem travar a thread (teste na Task 4).
5. **`desde` inválido ou maior que o último `seq`** (porteiro reiniciou e o tablet guardou um número antigo): trata como 0 e devolve as mensagens existentes (teste na Task 3, e na Task 4 pela rota).

---

### Task 1: Segurança (configuração, token, guarda, pareamento)

**Files:**
- Create: `scripts/estacao/seguranca.py`
- Test: `tests/test_estacao_seguranca.py`

**Interfaces:**
- Produces:
  - `PASTA_PADRAO: Path` = `Path(os.environ['LOCALAPPDATA']) / 'Therion' / 'estacao'`
  - `@dataclass class Config: client_ip: str; bind: str; port: int = 3904`
  - `carregar_config(pasta: Path) -> Config`: lê `config.json`; `ValueError` com mensagem em português se faltar `client_ip` ou `bind`, ou se o arquivo não existir.
  - `carregar_token(pasta: Path) -> str`: lê `token`; se não existir, cria a pasta, gera e grava.
  - `class Pareamento(pasta: Path, relogio: Callable[[], float] = time.time)` com `gerar() -> str` e `validar(codigo: str) -> bool`. O estado fica em `pareamento.json` (`{"codigo", "expira", "tentativas"}`), porque `--parear` roda num processo diferente do servidor.
  - `class Guarda(client_ip: str, token: str)` com `ip_ok(ip: str) -> bool` e `cookie_ok(cabecalho: str | None) -> bool`.
  - `cabecalho_set_cookie(token: str) -> str` → `estacao=<token>; Path=/; HttpOnly; Expires=Fri, 31 Dec 2099 23:59:59 GMT`.

- [ ] **Step 1: Write the failing tests**

```python
class TestSeguranca(unittest.TestCase):
    def setUp(self): self.pasta = Path(tempfile.mkdtemp())
    def test_config_sem_client_ip_falha(self):
        (self.pasta/'config.json').write_text('{"bind": "192.0.2.10"}', encoding='utf-8')
        with self.assertRaises(ValueError): seguranca.carregar_config(self.pasta)
    def test_config_le_porta_padrao(self):
        (self.pasta/'config.json').write_text('{"client_ip": "192.0.2.20", "bind": "192.0.2.10"}', encoding='utf-8')
        self.assertEqual(seguranca.carregar_config(self.pasta).port, 3904)
    def test_token_e_criado_uma_vez(self):
        a = seguranca.carregar_token(self.pasta); b = seguranca.carregar_token(self.pasta)
        self.assertEqual(a, b); self.assertGreaterEqual(len(a), 40)
    def test_pareamento_certo_uma_vez(self):
        p = seguranca.Pareamento(self.pasta, relogio=lambda: 1000.0)
        c = p.gerar(); self.assertRegex(c, r'^\d{6}$')
        self.assertTrue(p.validar(c)); self.assertFalse(p.validar(c))
    def test_pareamento_expira_em_300s(self):
        t = [1000.0]; p = seguranca.Pareamento(self.pasta, relogio=lambda: t[0])
        c = p.gerar(); t[0] = 1301.0
        self.assertFalse(p.validar(c))
    def test_pareamento_bloqueia_apos_5_erros(self):
        p = seguranca.Pareamento(self.pasta, relogio=lambda: 1000.0)
        c = p.gerar(); errado = '000000' if c != '000000' else '111111'
        for _ in range(5): self.assertFalse(p.validar(errado))
        self.assertFalse(p.validar(c))
    def test_pareamento_sem_arquivo_ou_corrompido(self):
        p = seguranca.Pareamento(self.pasta)
        self.assertFalse(p.validar('123456'))
        (self.pasta/'pareamento.json').write_text('{lixo', encoding='utf-8')
        self.assertFalse(p.validar('123456'))
    def test_guarda_ip(self):
        g = seguranca.Guarda('192.0.2.20', 'tok')
        self.assertTrue(g.ip_ok('192.0.2.20')); self.assertFalse(g.ip_ok('192.0.2.21'))
    def test_guarda_cookie_entre_outros_e_lixo(self):
        g = seguranca.Guarda('192.0.2.20', 'tok')
        self.assertTrue(g.cookie_ok('a=1; estacao=tok'))
        self.assertFalse(g.cookie_ok('estacao=outro'))
        self.assertFalse(g.cookie_ok(None)); self.assertFalse(g.cookie_ok(';;=\x00"'))
    def test_set_cookie_persistente(self):
        v = seguranca.cabecalho_set_cookie('tok')
        self.assertTrue(v.startswith('estacao=tok;')); self.assertIn('Expires=', v); self.assertIn('HttpOnly', v)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_seguranca.py -v`
Expected: FAIL (`ModuleNotFoundError: seguranca`)

- [ ] **Step 3: Implement `scripts/estacao/seguranca.py`**

Comparação de token e de código com `hmac.compare_digest`. Cookie lido com `http.cookies.SimpleCookie` dentro de `try/except http.cookies.CookieError`. Código com `f'{secrets.randbelow(10**6):06d}'`. Validação: arquivo ausente, JSON inválido, expirado ou `tentativas >= 5` → `False`; erro incrementa `tentativas`; acerto apaga o arquivo.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_seguranca.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/estacao/seguranca.py tests/test_estacao_seguranca.py
git commit -m "feat(estacao): guarda por IP e cookie, token e pareamento por código"
```

---

### Task 2: Saúde (sondas e medição periódica)

**Files:**
- Create: `scripts/estacao/saude.py`
- Test: `tests/test_estacao_saude.py`

**Interfaces:**
- Produces:
  - `checar_http(url: str, timeout: float = 1.0) -> bool`: `True` só com resposta 2xx; usa `urllib.request.build_opener(ProxyHandler({}))`, sem proxy, como o gateway de voz.
  - `ram_percentual() -> int | None`: `dwMemoryLoad` de `GlobalMemoryStatusEx` via `ctypes`.
  - `formatar_vram(saida: str) -> str | None`: `"5222, 8188"` (MiB, saída do `nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits`) → `"5,1/8 GB"` (usado com 1 casa e vírgula, total arredondado). Saída vazia ou inválida → `None`.
  - `vram() -> str | None`: roda o `nvidia-smi` (timeout de 1 s, `CREATE_NO_WINDOW`); se não existir ou falhar → `None`.
  - `contem_therion(linhas_de_comando: list[str], repo: Path) -> bool`: `True` se alguma linha contém `str(repo)` (sem diferenciar maiúsculas) e `-m therion.interface.desktop`. É o mesmo filtro do `Start-Therion.ps1`, linha 46.
  - `therion_vivo(repo: Path) -> bool`: lista as linhas de comando dos `pythonw.exe` com `powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | ForEach-Object CommandLine"` e aplica `contem_therion`.
  - `sondas_padrao(repo: Path) -> dict[str, Callable[[], object]]` com as chaves `ram`, `vram`, `ollama`, `voz`, `transcr`, `therion`, usando as URLs das Global Constraints.
  - `class Saude(sondas: dict[str, Callable[[], object]], intervalo: float = 2.0)` com `medir() -> dict` (sonda que lança exceção vira `None`), `atual() -> dict` (última medição; antes da primeira, todas as chaves com `None`) e `iniciar() -> None` (thread daemon que chama `medir` em loop).

- [ ] **Step 1: Write the failing tests**

```python
class TestSaude(unittest.TestCase):
    def test_formatar_vram(self):
        self.assertEqual(saude.formatar_vram('5222, 8188\n'), '5,1/8 GB')
        self.assertIsNone(saude.formatar_vram('')); self.assertIsNone(saude.formatar_vram('N/A'))
    def test_contem_therion(self):
        repo = Path(r'F:\Therion\app')
        sim = r'"F:\Therion\app\.venv\Scripts\pythonw.exe" -m therion.interface.desktop'
        self.assertTrue(saude.contem_therion([sim.lower()], repo))
        self.assertFalse(saude.contem_therion([r'"F:\Therion\app\.venv\Scripts\pythonw.exe" scripts\estacao\porteiro.py'], repo))
        self.assertFalse(saude.contem_therion([], repo))
    def test_sonda_que_falha_vira_none(self):
        def quebra(): raise OSError('x')
        s = saude.Saude({'ollama': lambda: True, 'voz': quebra})
        self.assertEqual(s.medir(), {'ollama': True, 'voz': None})
    def test_atual_antes_da_primeira_medicao(self):
        s = saude.Saude({'ollama': lambda: True})
        self.assertEqual(s.atual(), {'ollama': None})
    def test_checar_http_porta_fechada(self):
        self.assertFalse(saude.checar_http('http://127.0.0.1:9/', timeout=0.2))
    def test_sondas_padrao_tem_todas_as_chaves(self):
        self.assertEqual(set(saude.sondas_padrao(Path('.'))), {'ram','vram','ollama','voz','transcr','therion'})
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_saude.py -v`
Expected: FAIL (`ModuleNotFoundError: saude`)

- [ ] **Step 3: Implement `scripts/estacao/saude.py`**

`medir` grava o resultado sob `threading.Lock`; `atual` devolve uma cópia.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_saude.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/estacao/saude.py tests/test_estacao_saude.py
git commit -m "feat(estacao): sondas de saúde do Therion, Ollama, voz, RAM e VRAM"
```

---

### Task 3: Ações e registro de mensagens

**Files:**
- Create: `scripts/estacao/acoes.py`
- Create: `scripts/estacao/Restart-Ollama.ps1`
- Test: `tests/test_estacao_acoes.py`

**Interfaces:**
- Consumes: `saude.therion_vivo(repo)` (Task 2), injetado como função.
- Produces:
  - `class Registro(limite: int = 50)` com `adicionar(autor: str, texto: str) -> int` (devolve o `seq`, começando em 1) e `desde(seq: int) -> list[dict]`. Cada item: `{"seq", "hora": "HH:MM", "autor", "texto"}`. Se `seq` for negativo ou maior que o último `seq`, devolve tudo o que existe.
  - `@dataclass(frozen=True) class Acao: id: str; script: str; feito: str` (`script` é relativo à raiz do repositório; `feito` é o verbo da mensagem de sucesso).
  - `ACOES: dict[str, Acao]`:
    - `'1'`: `scripts/Launch-Therion.ps1`, "therion ligado"
    - `'2'`: `scripts/start-local-ollama.ps1`, "ollama de pé"
    - `'3'`: `scripts/estacao/Restart-Ollama.ps1`, "ollama reiniciado"
    - `'4'`: `scripts/VoiceStartup.ps1`, "voz religada"
  - `class Executor(repo: Path, registro: Registro, pasta_log: Path, therion_vivo: Callable[[], bool], timeout: float = 120.0, rodar: Callable = subprocess.run)` com `disparar(id: str) -> str` (`"aceito"`, `"ocupado"`, `"desconhecido"`) e `em_curso() -> str | None`.
- Mensagens no registro (autor `"porteiro"`):
  - sucesso: `"<feito> em <N> s"`;
  - ação 1 com o Therion vivo: `"já está ligado"`, sem executar o script;
  - script inexistente: `"falhou: script não encontrado"`;
  - timeout: `"falhou: tempo esgotado"`;
  - código de saída diferente de 0: `"falhou: <última linha não vazia do log desta execução, até 80 caracteres>"` (ou `"falhou: código <n>"` se o log estiver vazio).
- O comando é o das Global Constraints. stdout e stderr vão para `pasta_log / 'acoes.log'`, aberto em modo `'w'` a cada execução, **nunca** `capture_output` (Review Focus 1). Usa `creationflags=subprocess.CREATE_NO_WINDOW`.
- `Restart-Ollama.ps1`: acha `Get-NetTCPConnection -LocalPort 11435 -State Listen`; se o `OwningProcess` for `ollama`, faz `Stop-Process` e espera a porta liberar (até 15 s); depois chama `& (Join-Path $PSScriptRoot '..\start-local-ollama.ps1')`. Se a porta pertencer a outro processo, sai com `throw 'A porta 11435 não é do Ollama; nada foi encerrado.'`.

- [ ] **Step 1: Write the failing tests**

```python
class TestAcoes(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()); self.reg = acoes.Registro()
        (self.repo/'scripts').mkdir(); (self.repo/'scripts'/'estacao').mkdir()
    def exec(self, **kw):
        kw.setdefault('therion_vivo', lambda: False)
        return acoes.Executor(self.repo, self.reg, self.repo, **kw)
    def esperar(self, e):
        for _ in range(200):
            if e.em_curso() is None: return
            time.sleep(0.05)
        self.fail('ação não terminou')
    def test_registro_desde(self):
        self.reg.adicionar('porteiro','a'); s = self.reg.adicionar('porteiro','b')
        self.assertEqual([m['texto'] for m in self.reg.desde(1)], ['b'])
        self.assertEqual(len(self.reg.desde(s + 10)), 2); self.assertEqual(len(self.reg.desde(-3)), 2)
    def test_id_desconhecido(self):
        self.assertEqual(self.exec().disparar('9'), 'desconhecido')
    def test_script_inexistente(self):
        e = self.exec(); self.assertEqual(e.disparar('2'), 'aceito'); self.esperar(e)
        self.assertEqual(self.reg.desde(0)[-1]['texto'], 'falhou: script não encontrado')
    def test_ligar_com_therion_vivo_nao_executa(self):
        chamadas = []
        e = self.exec(therion_vivo=lambda: True, rodar=lambda *a, **k: chamadas.append(a))
        e.disparar('1'); self.esperar(e)
        self.assertEqual(chamadas, []); self.assertEqual(self.reg.desde(0)[-1]['texto'], 'já está ligado')
    def test_toques_simultaneos_so_um_aceito(self):
        (self.repo/'scripts'/'start-local-ollama.ps1').write_text('Start-Sleep 1', encoding='utf-8')
        e = self.exec(); r = []
        ts = [threading.Thread(target=lambda: r.append(e.disparar('2'))) for _ in range(5)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(sorted(r), ['aceito'] + ['ocupado']*4); self.esperar(e)
    def test_tempo_esgotado(self):
        (self.repo/'scripts'/'start-local-ollama.ps1').write_text('Start-Sleep 10', encoding='utf-8')
        e = self.exec(timeout=1.0); e.disparar('2'); self.esperar(e)
        self.assertEqual(self.reg.desde(0)[-1]['texto'], 'falhou: tempo esgotado')
    def test_erro_mostra_ultima_linha(self):
        (self.repo/'scripts'/'start-local-ollama.ps1').write_text("throw 'Executável do Ollama não encontrado.'", encoding='utf-8')
        e = self.exec(); e.disparar('2'); self.esperar(e)
        t = self.reg.desde(0)[-1]['texto']
        self.assertTrue(t.startswith('falhou: ')); self.assertLessEqual(len(t), len('falhou: ') + 80)
    def test_filho_em_segundo_plano_nao_prende_a_acao(self):
        (self.repo/'scripts'/'start-local-ollama.ps1').write_text(
            "Start-Process -FilePath ping -ArgumentList '-n','30','127.0.0.1' -WindowStyle Hidden", encoding='utf-8')
        e = self.exec(timeout=20.0); inicio = time.time(); e.disparar('2'); self.esperar(e)
        self.assertLess(time.time() - inicio, 10); self.assertTrue(self.reg.desde(0)[-1]['texto'].startswith('ollama de pé em'))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_acoes.py -v`
Expected: FAIL (`ModuleNotFoundError: acoes`)

- [ ] **Step 3: Implement `scripts/estacao/acoes.py` e `scripts/estacao/Restart-Ollama.ps1`**

`disparar` reserva a vaga sob `threading.Lock` (checa e marca `em_curso` na mesma seção crítica) e roda a ação numa thread daemon. A thread libera `em_curso` num `finally`. O timeout usa o `timeout=` do `subprocess.run` (`TimeoutExpired`).

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_acoes.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/estacao/acoes.py scripts/estacao/Restart-Ollama.ps1 tests/test_estacao_acoes.py
git commit -m "feat(estacao): ações fixas, uma por vez, com registro de mensagens"
```

---

### Task 4: Servidor HTTP do porteiro

**Files:**
- Create: `scripts/estacao/porteiro.py`
- Test: `tests/test_estacao_porteiro.py`

**Interfaces:**
- Consumes: `Config`, `Guarda`, `Pareamento`, `cabecalho_set_cookie`, `carregar_config`, `carregar_token`, `PASTA_PADRAO` (Task 1); `Saude`, `sondas_padrao` (Task 2); `Registro`, `Executor` (Task 3).
- Produces:
  - `criar_servidor(config: Config, guarda: Guarda, pareamento: Pareamento, saude: Saude, executor: Executor, registro: Registro, paginas: dict[str, bytes]) -> ThreadingHTTPServer`, com `paginas` tendo as chaves `'estacao'` e `'parear'`. O servidor escuta em `(config.bind, config.port)`.
  - `estado_json(saude: Saude, executor: Executor, registro: Registro, desde: int) -> dict` → `{"estado": "parado" | "offline", "status": saude.atual(), "mensagens": registro.desde(desde), "confirmacao": None, "acao": executor.em_curso()}`. `estado` é `"parado"` só quando `status["therion"] is True`.
  - `main(argv: list[str] | None = None) -> int`: `--pasta` (padrão `PASTA_PADRAO`); com `--parear`, gera o código, imprime `Código: 123456 (vale por 5 minutos)` e sai com 0; sem ele, carrega config e token, inicia a saúde e chama `serve_forever`. Config inválida → imprime a mensagem do `ValueError` e sai com 2.
- Regras do handler (nesta ordem):
  1. IP fora da guarda → `403` sem corpo, em qualquer rota.
  2. `GET /`: cookie válido → página `estacao`; senão → página `parear`. `Content-Type: text/html; charset=utf-8`.
  3. `POST /parear`: corpo `codigo=...` → `204` com `Set-Cookie`, ou `403`.
  4. Qualquer outra rota sem cookie válido → `403`.
  5. `GET /estado?desde=N`: `N` não numérico ou ausente vira 0 → `200` JSON (`application/json; charset=utf-8`, `ensure_ascii=False`).
  6. `POST /acao/<id>` → `202` (aceito), `409` (ocupado), `404` (desconhecido).
  7. Qualquer outra → `404`.
- POST sem `Content-Length`, ou com mais de 1024 bytes → `400`, sem ler o corpo. Todas as respostas levam `Cache-Control: no-store`. `log_message` silenciado.
- Para as páginas, o `main` lê `estacao.html` e `parear.html` da pasta do próprio `porteiro.py`. Antes da Task 5, os testes passam bytes falsos.

- [ ] **Step 1: Write the failing tests**

Fixture: `config = Config(client_ip='127.0.0.1', bind='127.0.0.1', port=0)`, `Saude` com sondas falsas (`therion` controlável), `Executor` com um `rodar` falso, servidor numa thread e requisições com `http.client.HTTPConnection`. O IP bloqueado é testado criando outro servidor com `client_ip='192.0.2.99'`.

```python
def test_ip_bloqueado_403_em_tudo(self): ...       # GET / e GET /estado → 403, corpo vazio
def test_sem_cookie_mostra_pareamento(self): ...   # GET / → corpo == paginas['parear']
def test_parear_certo_da_cookie(self): ...         # p.gerar(); POST /parear codigo=<c> → 204 e 'estacao=' no Set-Cookie
def test_parear_errado_403(self): ...
def test_estado_exige_cookie(self): ...            # GET /estado sem cookie → 403
def test_estado_parado_e_offline(self): ...        # therion True → "parado"; False/None → "offline"; confirmacao is None
def test_estado_desde_invalido(self): ...          # ?desde=abc e ?desde=99999 → mensagens == registro.desde(0)
def test_acao_codigos(self): ...                   # /acao/2 → 202; de novo durante a execução → 409; /acao/9 → 404
def test_post_sem_tamanho_ou_grande_400(self): ... # Content-Length 2000 → 400; sem Content-Length → 400
def test_main_parear_imprime_codigo(self): ...     # main(['--pasta', tmp, '--parear']) == 0 e stdout com r'Código: \d{6}'
def test_main_config_invalida_sai_2(self): ...     # pasta vazia → 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_porteiro.py -v`
Expected: FAIL (`ModuleNotFoundError: porteiro`)

- [ ] **Step 3: Implement `scripts/estacao/porteiro.py`**

O handler é uma classe criada dentro de `criar_servidor` (closure sobre as dependências). Os parâmetros são lidos com `urllib.parse.urlsplit` e `parse_qs`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_porteiro.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/estacao/porteiro.py tests/test_estacao_porteiro.py
git commit -m "feat(estacao): servidor do porteiro com rotas de estado, ação e pareamento"
```

---

### Task 5: Página do tablet e página de pareamento

**Files:**
- Create: `scripts/estacao/estacao.html`
- Create: `scripts/estacao/parear.html`
- Test: `tests/test_estacao_pagina.py`

**Interfaces:**
- Consumes: as rotas e o JSON de `/estado` da Task 4.
- Ids fixos em `estacao.html`: `anel` (svg, `viewBox="-80 -80 160 160"`), `rotulo`, `log`, `status`, `b1`, `b2`, `b3`, `b4`.
- Textos fixos:
  - cabeçalho `THERION OS v1 -- ESTACAO 01`;
  - botões `[1] LIGAR THERION`, `[2] SUBIR OLLAMA`, `[3] REINICIAR OLLAMA`, `[4] RELIGAR VOZ`;
  - `[ TOQUE DE NOVO ]`, `[ ... ]`, `PORTEIRO SEM RESPOSTA`;
  - rótulos do anel `[ PARADO ]` e `[ OFFLINE ]`.
- Comportamento:
  - Consulta `GET /estado?desde=<último seq>` a cada 1000 ms e mantém as últimas 6 mensagens no `log`, como `> porteiro: <texto>`.
  - Resposta 403 → `location.reload()`, que leva à página de pareamento.
  - Erro de rede ou timeout (`xhr.timeout = 2500`) → troca o `log` por `PORTEIRO SEM RESPOSTA`, põe o anel em `offline` e tenta de novo a cada 3000 ms.
  - Linha de status: `RAM 61%  VRAM 5,1/8 GB  OLLAMA ok  VOZ ok  TRANSCR ok  THERION ok`.
    - `true` → `ok`;
    - `false` → `caiu` em `#e2738f` (no THERION, `false` vira `--`);
    - `null` → `--`;
    - RAM e VRAM `null` → `--`.
  - Botões 1 e 2: um toque envia `POST /acao/<id>`. Botões 3 e 4: o primeiro toque troca o rótulo por `[ TOQUE DE NOVO ]` por 3000 ms, e só o segundo toque dentro desse prazo envia.
  - Enquanto `acao` do `/estado` for igual ao id, o botão mostra `[ ... ]`.
  - Anel (`setInterval` de 100 ms, 120 pontos, polyline):
    - `parado`: raio `48 + sin(t*0.8)*2` mais uma ondulação de 1,2 px com 6 lóbulos, traço `#9b87ff`, eco interno a 0,7 em `#4b3bb0`;
    - `offline`: arco vermelho `#e2738f` de 0,35 a 2π−0,35 rad, raio 48, com um desvio raro de 6 px; ponto central vermelho.
    - Sempre há um círculo externo de raio 70 em `#4b3bb0` e um ponto central de raio 4 (`#e7e0ff` quando parado).
  - Layout nas duas posições (spec 3.3), tela inteira, sem barra. Fundo `#0d0a18`, fonte `monospace`, botões em grade 2×2 com pelo menos 44 px de altura.
    - **Deitado (1024×600):** grade `200px | resto`.
    - **Em pé (600×1024):** `@media (orientation: portrait)` empilha cabeçalho, anel (o svg com 300 px de lado, contra 180 deitado), conversa, status e botões no rodapé.
    - Sem JS para a troca: o mesmo DOM, só CSS.
  - Gesto de manutenção (spec 8.3): segurar 5000 ms no cabeçalho (`id="cabecalho"`) faz `location.href = 'estacao://manutencao'`. Funciona com `touchstart`/`touchend` e `mousedown`/`mouseup`; soltar antes cancela.
- `parear.html`: mesmo visual, o texto `DIGITE O CODIGO MOSTRADO NO PC`, um `<input type="tel" maxlength="6">` e o botão `[ PAREAR ]`. Faz `POST /parear` com `codigo=<valor>`; `204` → `location.reload()`; senão mostra `CODIGO INVALIDO OU EXPIRADO`.

- [ ] **Step 1: Write the failing tests**

```python
PROIBIDO = ['=>', 'let ', 'const ', '`', 'fetch(', 'class ']
class TestPagina(unittest.TestCase):
    def test_es5_apenas(self):
        for nome in ('estacao.html', 'parear.html'):
            texto = (PASTA/nome).read_text(encoding='utf-8')
            for p in PROIBIDO: self.assertNotIn(p, texto, f'{nome}: {p!r}')
    def test_ids_e_textos(self):
        t = (PASTA/'estacao.html').read_text(encoding='utf-8')
        for i in ('anel','rotulo','log','status','b1','b2','b3','b4'): self.assertIn(f'id="{i}"', t)
        for s in ('THERION OS v1 -- ESTACAO 01','[3] REINICIAR OLLAMA','[ TOQUE DE NOVO ]','PORTEIRO SEM RESPOSTA'): self.assertIn(s, t)
    def test_pareamento(self):
        t = (PASTA/'parear.html').read_text(encoding='utf-8')
        self.assertIn('/parear', t); self.assertIn('maxlength="6"', t)
    def test_gesto_de_manutencao(self):
        t = (PASTA/'estacao.html').read_text(encoding='utf-8')
        self.assertIn('id="cabecalho"', t); self.assertIn('estacao://manutencao', t); self.assertIn('5000', t)
        self.assertIn('orientation: portrait', t)
```

(`PASTA = Path(__file__).parents[1] / 'scripts' / 'estacao'`; `'class '` não pode aparecer nem no HTML. Use `className` no JS e evite a palavra no texto e no CSS.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_pagina.py -v`
Expected: FAIL (`FileNotFoundError`)

- [ ] **Step 3: Write `estacao.html` e `parear.html`**

O mockup aprovado na conversa (anel de onda, estados parado/offline) é a referência visual. A lógica de anel e de status segue as regras acima.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_pagina.py -v`
Expected: 4 passed

- [ ] **Step 5: Conferência visual no PC**

Rodar o porteiro com um `config.json` de teste (`client_ip` e `bind` = `127.0.0.1`), parear e abrir `http://127.0.0.1:3904/` no navegador do app, em 1024×600 e em 600×1024 (`resize_window`). Esperado: anel animando, status preenchido em até ~4 s, toque duplo no botão 3 mostrando `[ TOQUE DE NOVO ]`, e nada cortado ou sobreposto nas duas posições. Para este teste, use o botão 2 (inofensivo), não o 3.

- [ ] **Step 6: Commit**

```bash
git add scripts/estacao/estacao.html scripts/estacao/parear.html tests/test_estacao_pagina.py
git commit -m "feat(estacao): página de terminal com anel de onda e página de pareamento"
```

---

### Task 6: Instalação, README e conferência no tablet

**Files:**
- Create: `scripts/estacao/Install-Estacao.ps1`
- Create: `scripts/estacao/README.md`

**Interfaces:**
- Consumes: `porteiro.py main()` (Task 4).
- `Install-Estacao.ps1` (o usuário roda; nada é criado automaticamente):
  - Registra a tarefa agendada `Therion Estacao` no logon do usuário atual, com a ação `F:\Therion\app\.venv\Scripts\pythonw.exe scripts\estacao\porteiro.py` (pasta de trabalho = raiz do repositório, achada a partir de `$PSScriptRoot`).
  - Configurações: `-RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)`.
  - Com `-Remover`, apaga a tarefa. Se `config.json` não existir, para com a mensagem de criar o arquivo primeiro (conforme o README).
- `README.md`, nesta ordem:
  1. o que é (2 linhas);
  2. reservar o IP do tablet no roteador;
  3. criar `%LOCALAPPDATA%\Therion\estacao\config.json` com o exemplo `{"client_ip": "192.168.0.X", "bind": "192.168.0.Y", "port": 3904}`;
  4. regra de firewall, que **o usuário roda**: `New-NetFirewallRule -DisplayName 'Therion Estacao' -Direction Inbound -Protocol TCP -LocalPort 3904 -RemoteAddress <IP do tablet> -Profile Private -Action Allow`;
  5. `Install-Estacao.ps1`;
  6. `porteiro.py --parear` e digitar o código no tablet;
  7. no tablet: tempo limite da tela em "Nunca" e a página aberta no navegador;
  8. a lista de conferência manual da spec (seção 6).

- [ ] **Step 1: Write `Install-Estacao.ps1` e `README.md`**

- [ ] **Step 2: Run the whole suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_*.py -v`
Expected: 39 passed

Run: `.venv/Scripts/python.exe -m pytest tests -q`
Expected: só as falhas que já existiam antes (comparar com a mesma execução no `master` antes da Task 1; nenhuma falha nova).

- [ ] **Step 3: Commit**

```bash
git add scripts/estacao/Install-Estacao.ps1 scripts/estacao/README.md
git commit -m "docs(estacao): instalação da tarefa agendada e passo a passo do tablet"
```

- [ ] **Step 4: Conferência no tablet real (com o usuário)**

Seguir a lista do README: página abre e pareia; anel anima sem engasgar; derrubar o Ollama muda o status para `OLLAMA caiu`; o botão 3 com toque duplo o religa; parar o porteiro mostra `PORTEIRO SEM RESPOSTA`. Anotar qualquer travada do navegador antigo antes de dar a fase 1 por pronta.

---

## Modo estação (spec, seção 8)

Constantes do tablet:
- Tela nativa 1024×600 deitado. Tem acelerômetro e a rotação automática está ligada, então em pé a tela fica com 600×1024.
- ADB sempre com `ADB_LIBUSB=1` e o `adb.exe` do scrcpy (ver `F:\Tablet-TR101\notas.md`). Depois de reiniciar o tablet, rode `adb kill-server` antes do próximo comando.

### Task 7: Animação de inicialização

**Files:**
- Create: `scripts/estacao/tablet/bootanimacao.py`
- Test: `tests/test_estacao_bootanimacao.py`

**Interfaces:**
- Produces: `gerar(destino: Path) -> Path`, que grava e devolve `destino / 'bootanimation.zip'`; `main()` grava em `%LOCALAPPDATA%\Therion\estacao\` e imprime o caminho.
- Conteúdo, conforme a spec 8.5:
  - **sem texto**, porque a animação não gira e o tablet pode estar em pé;
  - `desc.txt` = `1024 600 12\np 1 0 part0\np 0 0 part1\n`;
  - `part0/` com 30 PNG (~2,5 s a 12 qps): o anel cresce do raio 0 até 150 px; nos 4 últimos quadros, o traço fica `#e7e0ff` (clarão);
  - `part1/` com 24 PNG: o anel no estado `falando`, em loop.
- Formato dos quadros: nomes `00000.png`, `00001.png`…; todos 1024×600 RGB, fundo `#0d0a18`, anel `#9b87ff` com eco a 0,7 em `#4b3bb0`, linha de 3 px, centro em (512, 300).
- Raio máximo de 150 px, para caber nos 600 px de altura com folga.
- Todas as entradas com `ZIP_STORED`.

- [ ] **Step 1: Write the failing tests**

```python
class TestBootanimacao(unittest.TestCase):
    def setUp(self): self.zip = bootanimacao.gerar(Path(tempfile.mkdtemp()))
    def test_desc_txt(self):
        with zipfile.ZipFile(self.zip) as z: self.assertEqual(z.read('desc.txt').decode(), '1024 600 12\np 1 0 part0\np 0 0 part1\n')
    def test_sem_compressao(self):
        with zipfile.ZipFile(self.zip) as z: self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist()))
    def test_quantidade_de_quadros(self):
        with zipfile.ZipFile(self.zip) as z:
            n = z.namelist()
            self.assertEqual(len([x for x in n if x.startswith('part0/') and x.endswith('.png')]), 30)
            self.assertEqual(len([x for x in n if x.startswith('part1/') and x.endswith('.png')]), 24)
    def test_tamanho_fundo_e_anel_dentro_da_altura(self):
        with zipfile.ZipFile(self.zip) as z:
            img = Image.open(io.BytesIO(z.read('part1/00000.png'))).convert('RGB')
            self.assertEqual(img.size, (1024, 600)); self.assertEqual(img.getpixel((2, 2)), (0x0d, 0x0a, 0x18))
            fundo = (0x0d, 0x0a, 0x18)
            linhas = [y for y in range(600) if any(img.getpixel((x, y)) != fundo for x in range(312, 712, 4))]
            self.assertGreater(min(linhas), 60); self.assertLess(max(linhas), 540)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_bootanimacao.py -v`
Expected: FAIL (`ModuleNotFoundError: bootanimacao`)

- [ ] **Step 3: Implement `scripts/estacao/tablet/bootanimacao.py`**

Anel do `part1`: `r(q) = 150 + sin(8q + 4t)·A·sin(3q + t)`, com `A = 22·(0,5 + |sin(1,7t)|)`, `t = quadro·0,35` e 240 pontos (mesma fórmula do mockup, escalada).

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_bootanimacao.py -v`
Expected: 4 passed

- [ ] **Step 5: Conferência visual**

Gerar o zip, extrair `part0/00010.png`, `part0/00029.png` e `part1/00012.png` para o scratchpad e olhar. Esperado: anel redondo, centralizado e roxo, e o clarão no último quadro do `part0`. Nada desse teste vai para o repositório.

- [ ] **Step 6: Commit**

```bash
git add scripts/estacao/tablet/bootanimacao.py tests/test_estacao_bootanimacao.py
git commit -m "feat(estacao): animação de inicialização do tablet no tema do Therion"
```

---

### Task 8: App "Estação" (APK)

**Files:**
- Create: `scripts/estacao/app/AndroidManifest.xml`
- Create: `scripts/estacao/app/src/com/therion/estacao/EstacaoActivity.java`
- Create: `scripts/estacao/app/assets/espera.html`
- Create: `scripts/estacao/app/build.ps1`
- Modify: `tests/test_estacao_pagina.py` (o teste de ES5 passa a cobrir também `app/assets/espera.html`)

**Interfaces:**
- Consumes: a página da Task 5 (gesto `estacao://manutencao` e layout nas duas posições).
- Produces: `build.ps1 -Sdk F:\Android-SDK` → `%LOCALAPPDATA%\Therion\estacao\estacao.apk`, consumido pela Task 9.
- Manifesto:
  - pacote `com.therion.estacao`, `versionCode 1`, `uses-sdk minSdkVersion=15 targetSdkVersion=15`, permissão `INTERNET`, `android:label="Estação"`, sem ícone próprio;
  - `EstacaoActivity` com `android:theme="@android:style/Theme.NoTitleBar.Fullscreen"`, `screenOrientation="sensor"`, `launchMode="singleTask"`, `configChanges="orientation|keyboardHidden|screenSize"`;
  - dois `intent-filter`: (`MAIN`, `HOME` + `DEFAULT`) e (`MAIN`, `LAUNCHER`).
- `EstacaoActivity` (spec 8.2):
  - `onCreate`: `FLAG_KEEP_SCREEN_ON`; um `WebView` como conteúdo; JavaScript e cookies ligados; `WebViewClient` próprio.
  - Se o intent trouxer o extra `url`, grava em `SharedPreferences("estacao")` com a chave `url`. Carrega a URL gravada; sem URL, carrega `file:///android_asset/espera.html?semurl=1`.
  - `onReceivedError` → carrega `espera.html?url=<url codificada>`.
  - `shouldOverrideUrlLoading`: `estacao://manutencao` → `alternarBarra()` e devolve `true`.
  - `onBackPressed` vazio; `onPause` → `CookieSyncManager.getInstance().sync()`.
  - Girar o tablet não recria a Activity (`configChanges`): o WebView só refaz o layout.
  - `alternarBarra()`: lê `getApplicationEnabledSetting("com.android.systemui")`.
    - Desligada (`COMPONENT_ENABLED_STATE_DISABLED*`) → `su -c "pm enable com.android.systemui"` e abre `Settings.ACTION_SETTINGS`.
    - Ligada → `su -c "pm disable com.android.systemui"`.
    - Usa `Runtime.exec` numa thread e mostra um `Toast` (`BARRA LIGADA`, `BARRA DESLIGADA` ou `FALHOU: SEM ROOT`).
  - Sem `addJavascriptInterface`.
- `espera.html` (ES5): fundo `#0d0a18` e anel `offline` em SVG estático, centralizado nas duas posições. Com `semurl=1` mostra `SEM ENDERECO DO PORTEIRO`; senão mostra `AGUARDANDO PORTEIRO...` e faz `location.replace(url)` a cada 5000 ms.
- `build.ps1`:
  - Se faltar algo em `-Sdk`, para e lista o que instalar: `cmdline-tools/latest`, `build-tools;35.0.0`, `platforms;android-15`.
  - Passos, nesta ordem:
    1. `aapt2 link` (manifesto + assets, `-I platforms/android-15/android.jar --min-sdk-version 15 --target-sdk-version 15`);
    2. `javac --release 8 -classpath android.jar`;
    3. `d8 --min-api 15`, acrescentando o `classes.dex` ao apk;
    4. `zipalign -p 4`;
    5. `apksigner sign --min-sdk-version 15`, com a chave `%LOCALAPPDATA%\Therion\estacao\estacao.keystore` (criada com `keytool` na primeira vez).
  - Usa o JDK 21 achado por busca em `%LOCALAPPDATA%\Programs\Eclipse Adoptium\jdk-21*`, sem caminho de usuário fixo no script.

- [ ] **Step 1: Instalar as ferramentas do Android (com o usuário)**

Baixar o "command-line tools" para Windows na página oficial (`developer.android.com/studio`, seção "Command line tools only") e extrair em `F:\Android-SDK\cmdline-tools\latest`. Depois rodar: `sdkmanager --sdk_root=F:\Android-SDK "build-tools;35.0.0" "platforms;android-15"`.
**A licença do SDK quem aceita é o usuário**: ele roda `sdkmanager --licenses` e responde `y`. Não aceitar em nome dele.
Esperado: `F:\Android-SDK\build-tools\35.0.0\aapt2.exe` e `F:\Android-SDK\platforms\android-15\android.jar` existem.

- [ ] **Step 2: Estender o teste de ES5 para `app/assets/espera.html` e ver falhar**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_pagina.py -v`
Expected: FAIL (`FileNotFoundError` em `espera.html`)

- [ ] **Step 3: Write manifesto, `EstacaoActivity.java`, `espera.html` e `build.ps1`**

- [ ] **Step 4: Montar o APK e conferir o pacote**

Run: `powershell -NoProfile -File scripts/estacao/app/build.ps1 -Sdk F:\Android-SDK`. Depois, `F:\Android-SDK\build-tools\35.0.0\aapt2.exe dump badging` e `apksigner verify --print-certs` no `estacao.apk`.
Expected:
- `package: name='com.therion.estacao'`;
- `sdkVersion:'15'`;
- `launchable-activity` presente;
- `Verified using v1 scheme (JAR signing): true`.

- [ ] **Step 5: Run the page tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_pagina.py -v`
Expected: 4 passed

- [ ] **Step 6: Teste no tablet, sem trocar o launcher ainda**

1. Instalar e abrir: `adb install -r estacao.apk`, depois `adb shell am start -n com.therion.estacao/.EstacaoActivity --es url http://<IP do PC>:3904/`.
2. Capturar a tela com `adb shell screencap -p /data/local/tmp/t.png` e `adb pull` para o scratchpad, uma vez com o tablet deitado e outra em pé.

Esperado:
- a estação em tela cheia nas duas posições, girando sem recarregar;
- parar o porteiro mostra `AGUARDANDO PORTEIRO...`, e religar volta sozinho em até ~5 s.

- [ ] **Step 7: Commit**

```bash
git add scripts/estacao/app tests/test_estacao_pagina.py
git commit -m "feat(estacao): app Android que abre a estação em tela cheia"
```

---

### Task 9: Configuração do tablet (modo estação ligado)

**Files:**
- Create: `scripts/estacao/tablet/Modo-Estacao.ps1`
- Modify: `scripts/estacao/README.md` (seção "Modo estação")

**Interfaces:**
- Consumes: `estacao.apk` (Task 8) e `bootanimation.zip` (Task 7), em `%LOCALAPPDATA%\Therion\estacao\`.
- Uso: `Modo-Estacao.ps1 -UrlPorteiro http://<IP>:3904/ [-Desfazer]`.
- Preparação:
  - acha o `adb.exe` do scrcpy por busca em `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Genymobile.scrcpy_*`;
  - define `ADB_LIBUSB=1`;
  - para com mensagem clara se `adb get-state` não for `device`.
- Pré-checagem: `adb shell su -c id` precisa conter `uid=0`; senão para com `FALHOU: su não responde`.
- Aplicar, na ordem da spec 8.4:
  1. instala o APK;
  2. grava a URL;
  3. `pm disable com.android.launcher`;
  4. checa `lockscreen.password_type` na tabela `secure`: ausente ou 65536 significa deslizar ou nenhum. Com PIN, senha ou padrão, para. Senão, roda `sqlite3 ... "insert or replace into secure(name,value) values('lockscreen.disabled','1');"`;
  5. `adb push bootanimation.zip /data/local/bootanimation.zip` e `chmod 644`;
  6. `pm disable com.android.systemui`;
  7. `adb reboot`.
- `-Desfazer`: `pm enable com.android.systemui`, `pm enable com.android.launcher`, `lockscreen.disabled=0`, `rm /data/local/bootanimation.zip`, `pm uninstall com.therion.estacao` e `adb reboot`.
- Cada passo imprime `[ok] <passo>` ou `[falhou] <passo>: <saída>` e para no primeiro erro.

- [ ] **Step 1: Write `Modo-Estacao.ps1` e a seção do README**

- [ ] **Step 2: Aplicar no tablet (com o usuário olhando)**

Run: `powershell -NoProfile -File scripts/estacao/tablet/Modo-Estacao.ps1 -UrlPorteiro http://<IP do PC>:3904/`
Expected: 7 linhas `[ok]`. O tablet reinicia mostrando a animação do Therion e cai direto na estação, sem bloqueio nem barra.

- [ ] **Step 3: Conferir as duas posições e a saída sem cabo**

No tablet:
1. Girar de deitado para em pé e de volta: a estação acompanha, sem recarregar.
2. Segurar 5 s no cabeçalho: a barra aparece e as configurações abrem.
3. Tocar em home: volta à estação.
4. Segurar 5 s de novo: a barra some.

Esperado: tudo funciona nas duas posições.

- [ ] **Step 4: Conferir o `-Desfazer` e reaplicar**

Rodar com `-Desfazer`: o tablet volta com launcher, barra, bloqueio por deslizar e animação de fábrica. Rodar de novo sem `-Desfazer`: o modo estação volta.

- [ ] **Step 5: Suíte final**

Run: `.venv/Scripts/python.exe -m pytest tests/test_estacao_*.py -v`
Expected: 43 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/estacao/tablet/Modo-Estacao.ps1 scripts/estacao/README.md
git commit -m "feat(estacao): script que liga e desfaz o modo estação no tablet"
```
