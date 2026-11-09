"""Segurança do porteiro da Estação Therion: IP do tablet, cookie e pareamento por código."""
from dataclasses import dataclass
import hmac
from http.cookies import CookieError, SimpleCookie
import json
import os
from pathlib import Path
import secrets
import time
from typing import Callable

PASTA_PADRAO = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Therion' / 'estacao'
VALIDADE_CODIGO = 300
MAX_TENTATIVAS = 5


@dataclass
class Config:
    client_ip: str
    bind: str
    port: int = 3904


def carregar_config(pasta: Path) -> Config:
    arquivo = Path(pasta) / 'config.json'
    if not arquivo.exists():
        raise ValueError(f'Crie {arquivo} com client_ip (IP do tablet) e bind (IP deste PC).')
    try:
        dados = json.loads(arquivo.read_text(encoding='utf-8'))
    except json.JSONDecodeError as erro:
        raise ValueError(f'{arquivo} não é um JSON válido: {erro}') from erro
    for chave in ('client_ip', 'bind'):
        if not isinstance(dados.get(chave), str) or not dados[chave]:
            raise ValueError(f'Falta "{chave}" em {arquivo}.')
    return Config(dados['client_ip'], dados['bind'], int(dados.get('port', 3904)))


def carregar_token(pasta: Path) -> str:
    arquivo = Path(pasta) / 'token'
    if arquivo.exists():
        return arquivo.read_text(encoding='utf-8').strip()
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    arquivo.write_text(token, encoding='utf-8')
    return token


class Pareamento:
    """Estado em arquivo porque `--parear` roda num processo diferente do servidor."""

    def __init__(self, pasta: Path, relogio: Callable[[], float] = time.time):
        self.arquivo = Path(pasta) / 'pareamento.json'
        self.relogio = relogio

    def gerar(self) -> str:
        codigo = f'{secrets.randbelow(10 ** 6):06d}'
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self._gravar({'codigo': codigo, 'expira': self.relogio() + VALIDADE_CODIGO, 'tentativas': 0})
        return codigo

    def validar(self, codigo: str) -> bool:
        try:
            estado = json.loads(self.arquivo.read_text(encoding='utf-8'))
            certo, expira, tentativas = str(estado['codigo']), float(estado['expira']), int(estado['tentativas'])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if self.relogio() > expira or tentativas >= MAX_TENTATIVAS:
            return False
        if hmac.compare_digest(certo.encode(), str(codigo).encode()):
            self.arquivo.unlink(missing_ok=True)
            return True
        estado['tentativas'] = tentativas + 1
        self._gravar(estado)
        return False

    def _gravar(self, estado: dict) -> None:
        self.arquivo.write_text(json.dumps(estado), encoding='utf-8')


class Guarda:
    def __init__(self, client_ip: str, token: str):
        self.client_ip = client_ip
        self.token = token

    def ip_ok(self, ip: str) -> bool:
        return ip == self.client_ip

    def cookie_ok(self, cabecalho: str | None) -> bool:
        if not cabecalho:
            return False
        try:
            cookie = SimpleCookie()
            cookie.load(cabecalho)
        except CookieError:
            return False
        valor = cookie.get('estacao')
        return valor is not None and hmac.compare_digest(valor.value.encode(), self.token.encode())


def cabecalho_set_cookie(token: str) -> str:
    return f'estacao={token}; Path=/; HttpOnly; Expires=Fri, 31 Dec 2099 23:59:59 GMT'
