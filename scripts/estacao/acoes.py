"""Ações fixas da Estação Therion (uma por vez) e o registro de mensagens mostrado no tablet."""
from dataclasses import dataclass
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable

SEM_JANELA = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class Registro:
    def __init__(self, limite: int = 50):
        self.limite = limite
        self._itens: list[dict] = []
        self._seq = 0
        self._trava = threading.Lock()

    def adicionar(self, autor: str, texto: str) -> int:
        with self._trava:
            self._seq += 1
            self._itens.append({'seq': self._seq, 'hora': time.strftime('%H:%M'), 'autor': autor, 'texto': texto})
            del self._itens[:-self.limite]
            return self._seq

    def desde(self, seq: int) -> list[dict]:
        with self._trava:
            if seq < 0 or seq > self._seq:
                seq = 0
            return [dict(m) for m in self._itens if m['seq'] > seq]


@dataclass(frozen=True)
class Acao:
    id: str
    script: str
    feito: str


ACOES = {
    '1': Acao('1', 'scripts/Launch-Therion.ps1', 'therion ligado'),
    '2': Acao('2', 'scripts/start-local-ollama.ps1', 'ollama de pé'),
    '3': Acao('3', 'scripts/estacao/Restart-Ollama.ps1', 'ollama reiniciado'),
    '4': Acao('4', 'scripts/VoiceStartup.ps1', 'voz religada'),
}


def _ler(arquivo: Path) -> list[str]:
    try:
        dados = arquivo.read_bytes()
    except OSError:
        return []
    for codificacao in ('utf-8', 'cp850'):
        try:
            texto = dados.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    return [linha.strip() for linha in texto.splitlines() if linha.strip()]


class Executor:
    def __init__(self, repo: Path, registro: Registro, pasta_log: Path, therion_vivo: Callable[[], bool],
                 timeout: float = 120.0, rodar: Callable = subprocess.run):
        self.repo = Path(repo)
        self.registro = registro
        self.pasta_log = Path(pasta_log)
        self.therion_vivo = therion_vivo
        self.timeout = timeout
        self.rodar = rodar
        self._trava = threading.Lock()
        self._em_curso: str | None = None

    def em_curso(self) -> str | None:
        with self._trava:
            return self._em_curso

    def disparar(self, id: str) -> str:
        acao = ACOES.get(id)
        if acao is None:
            return 'desconhecido'
        with self._trava:
            if self._em_curso is not None:
                return 'ocupado'
            self._em_curso = id
        threading.Thread(target=self._executar, args=(acao,), daemon=True, name=f'estacao-acao-{id}').start()
        return 'aceito'

    def _executar(self, acao: Acao) -> None:
        try:
            try:
                texto = self._resultado(acao)
            except Exception:
                texto = 'falhou: erro inesperado'
            self.registro.adicionar('porteiro', texto)
        finally:
            with self._trava:
                self._em_curso = None

    def _resultado(self, acao: Acao) -> str:
        if acao.id == '1' and self.therion_vivo():
            return 'já está ligado'
        script = self.repo / acao.script
        if not script.is_file():
            return 'falhou: script não encontrado'
        self.pasta_log.mkdir(parents=True, exist_ok=True)
        saida, erros = self.pasta_log / 'acoes.log', self.pasta_log / 'acoes.err'
        comando = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', str(script)]
        inicio = time.monotonic()
        # Arquivos, nunca pipes: scripts que usam Start-Process deixam filhos herdando o pipe e prenderiam a ação.
        with open(saida, 'wb') as out, open(erros, 'wb') as err:
            try:
                fim = self.rodar(comando, stdout=out, stderr=err, stdin=subprocess.DEVNULL, cwd=str(self.repo),
                                 timeout=self.timeout, creationflags=SEM_JANELA)
            except subprocess.TimeoutExpired:
                return 'falhou: tempo esgotado'
        if fim.returncode != 0:
            linhas = _ler(erros) or _ler(saida)[-1:]
            return 'falhou: ' + (linhas[0][:80] if linhas else f'código {fim.returncode}')
        return f'{acao.feito} em {round(time.monotonic() - inicio)} s'
