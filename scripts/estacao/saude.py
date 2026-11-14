"""Sondas de saúde da Estação Therion: RAM, VRAM, Ollama, voz, transcrição e o próprio Therion."""
import ctypes
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable
from urllib.request import ProxyHandler, build_opener

URL_OLLAMA = 'http://127.0.0.1:11435/api/version'
URL_VOZ = 'http://127.0.0.1:3901/health'
URL_TRANSCR = 'http://127.0.0.1:3902/stt/health'
SEM_JANELA = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_abrir = build_opener(ProxyHandler({})).open


def checar_http(url: str, timeout: float = 1.0) -> bool:
    try:
        with _abrir(url, timeout=timeout) as resposta:
            return 200 <= resposta.status < 300
    except Exception:
        return False


class _Memoria(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong)] + [
        (nome, ctypes.c_ulonglong) for nome in (
            'ullTotalPhys', 'ullAvailPhys', 'ullTotalPageFile', 'ullAvailPageFile',
            'ullTotalVirtual', 'ullAvailVirtual', 'ullAvailExtendedVirtual')]


def ram_percentual() -> int | None:
    estado = _Memoria()
    estado.dwLength = ctypes.sizeof(_Memoria)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
        return None
    return int(estado.dwMemoryLoad)


def formatar_vram(saida: str) -> str | None:
    try:
        usado, total = (float(x) for x in saida.strip().splitlines()[0].split(','))
    except (ValueError, IndexError):
        return None
    return f'{usado / 1024:.1f}'.replace('.', ',') + f'/{round(total / 1024)} GB'


def vram() -> str | None:
    try:
        saida = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=1, creationflags=SEM_JANELA)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return formatar_vram(saida.stdout) if saida.returncode == 0 else None


def contem_therion(linhas_de_comando: list[str], repo: Path) -> bool:
    raiz = str(repo).lower()
    return any(raiz in linha.lower() and '-m therion.interface.desktop' in linha for linha in linhas_de_comando if linha)


def therion_vivo(repo: Path) -> bool:
    comando = "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | ForEach-Object CommandLine"
    saida = subprocess.run(['powershell', '-NoProfile', '-Command', comando],
                           capture_output=True, text=True, timeout=5, creationflags=SEM_JANELA)
    return contem_therion(saida.stdout.splitlines(), repo)


def a_cada(segundos: float, sonda: Callable[[], object], relogio: Callable[[], float] = time.monotonic):
    """Roda a sonda no máximo uma vez por intervalo e repete o último valor no meio."""
    ultimo = {'quando': None, 'valor': None}

    def medir():
        agora = relogio()
        if ultimo['quando'] is None or agora - ultimo['quando'] >= segundos:
            ultimo['valor'] = sonda()
            ultimo['quando'] = agora
        return ultimo['valor']
    return medir


def sondas_padrao(repo: Path) -> dict[str, Callable[[], object]]:
    return {
        'ram': ram_percentual,
        'vram': vram,
        'ollama': lambda: checar_http(URL_OLLAMA),
        'voz': lambda: checar_http(URL_VOZ),
        'transcr': lambda: checar_http(URL_TRANSCR),
        # Cada consulta abre um PowerShell (~0,4 s); a cada 2 s isso pesaria o PC o dia todo.
        'therion': a_cada(15, lambda: therion_vivo(repo)),
    }


class Saude:
    def __init__(self, sondas: dict[str, Callable[[], object]], intervalo: float = 2.0):
        self.sondas = sondas
        self.intervalo = intervalo
        self._trava = threading.Lock()
        self._ultimo = {nome: None for nome in sondas}

    def medir(self) -> dict:
        resultado = {}
        for nome, sonda in self.sondas.items():
            try:
                resultado[nome] = sonda()
            except Exception:
                resultado[nome] = None
        with self._trava:
            self._ultimo = resultado
        return dict(resultado)

    def atual(self) -> dict:
        with self._trava:
            return dict(self._ultimo)

    def iniciar(self) -> None:
        def laco():
            while True:
                self.medir()
                time.sleep(self.intervalo)
        threading.Thread(target=laco, daemon=True, name='estacao-saude').start()
