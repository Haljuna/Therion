"""Porteiro da Estação Therion: serve a página do tablet, o status do PC e as ações fixas.

Uso: porteiro.py [--pasta DIR] [--parear]
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acoes import Executor, Registro  # noqa: E402
from saude import Saude, sondas_padrao, therion_vivo  # noqa: E402
from seguranca import (PASTA_PADRAO, Config, Guarda, Pareamento, cabecalho_set_cookie,  # noqa: E402
                       carregar_config, carregar_token)

MAX_CORPO = 1024
REPO = Path(__file__).resolve().parents[2]


def estado_json(saude: Saude, executor: Executor, registro: Registro, desde: int) -> dict:
    status = saude.atual()
    return {
        'estado': 'parado' if status.get('therion') is True else 'offline',
        'status': status,
        'mensagens': registro.desde(desde),
        'acao': executor.em_curso(),
    }


def criar_servidor(config: Config, guarda: Guarda, pareamento: Pareamento, saude: Saude, executor: Executor,
                   registro: Registro, paginas: dict[str, bytes]) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def responder(self, status, corpo=b'', tipo=None, extras=None):
            self.send_response(status)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(corpo)))
            if tipo:
                self.send_header('Content-Type', tipo)
            for nome, valor in (extras or {}).items():
                self.send_header(nome, valor)
            self.end_headers()
            self.wfile.write(corpo)

        def liberado(self):
            if not guarda.ip_ok(self.client_address[0]):
                self.responder(403)
                return False
            return True

        def com_cookie(self):
            return guarda.cookie_ok(self.headers.get('Cookie'))

        def do_GET(self):
            if not self.liberado():
                return
            partes = urlsplit(self.path)
            if partes.path == '/':
                pagina = paginas['estacao' if self.com_cookie() else 'parear']
                return self.responder(200, pagina, 'text/html; charset=utf-8')
            if not self.com_cookie():
                return self.responder(403)
            if partes.path == '/estado':
                try:
                    desde = int(parse_qs(partes.query).get('desde', ['0'])[0])
                except ValueError:
                    desde = 0
                corpo = json.dumps(estado_json(saude, executor, registro, desde), ensure_ascii=False).encode()
                return self.responder(200, corpo, 'application/json; charset=utf-8')
            self.responder(404)

        def do_POST(self):
            if not self.liberado():
                return
            tamanho = self.headers.get('Content-Length')
            if tamanho is None or not tamanho.isdigit() or int(tamanho) > MAX_CORPO:
                return self.responder(400)
            corpo = self.rfile.read(int(tamanho)).decode('utf-8', 'replace')
            caminho = urlsplit(self.path).path
            if caminho == '/parear':
                codigo = parse_qs(corpo).get('codigo', [''])[0]
                if pareamento.validar(codigo):
                    return self.responder(204, extras={'Set-Cookie': cabecalho_set_cookie(guarda.token)})
                return self.responder(403)
            if not self.com_cookie():
                return self.responder(403)
            if caminho.startswith('/acao/'):
                resposta = executor.disparar(caminho[len('/acao/'):])
                return self.responder({'aceito': 202, 'ocupado': 409}.get(resposta, 404))
            self.responder(404)

    return ThreadingHTTPServer((config.bind, config.port), Handler)


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description='Porteiro da Estação Therion')
    args.add_argument('--pasta', type=Path, default=PASTA_PADRAO)
    args.add_argument('--parear', action='store_true', help='gera um código de pareamento para o tablet')
    opcoes = args.parse_args(argv)
    if opcoes.parear:
        print(f'Código: {Pareamento(opcoes.pasta).gerar()} (vale por 5 minutos)')
        return 0
    try:
        config = carregar_config(opcoes.pasta)
    except ValueError as erro:
        print(erro)
        return 2
    aqui = Path(__file__).resolve().parent
    paginas = {nome: (aqui / f'{nome}.html').read_bytes() for nome in ('estacao', 'parear')}
    saude = Saude(sondas_padrao(REPO))
    saude.iniciar()
    registro = Registro()
    executor = Executor(REPO, registro, opcoes.pasta, lambda: therion_vivo(REPO))
    servidor = criar_servidor(config, Guarda(config.client_ip, carregar_token(opcoes.pasta)),
                              Pareamento(opcoes.pasta), saude, executor, registro, paginas)
    registro.adicionar('porteiro', 'no ar')
    servidor.serve_forever()
    return 0


if __name__ == '__main__':
    sys.exit(main())
