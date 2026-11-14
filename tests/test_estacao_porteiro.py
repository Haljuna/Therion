import contextlib
import http.client
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts' / 'estacao'))
import acoes  # noqa: E402
import porteiro  # noqa: E402
import saude  # noqa: E402
import seguranca  # noqa: E402

PAGINAS = {'estacao': b'<estacao>', 'parear': b'<parear>'}


class _Lento:
    """Substitui subprocess.run: segura a ação até ser liberado."""
    def __init__(self):
        self.liberar = threading.Event()

    def __call__(self, *a, **k):
        self.liberar.wait(5)
        return type('R', (), {'returncode': 0})()


class TestPorteiro(unittest.TestCase):
    def montar(self, client_ip='127.0.0.1'):
        self.pasta = Path(tempfile.mkdtemp())
        repo = Path(tempfile.mkdtemp())
        (repo / 'scripts').mkdir()
        (repo / 'scripts' / 'start-local-ollama.ps1').write_text('', encoding='utf-8')
        self.therion = [True]
        self.saude = saude.Saude({'ollama': lambda: True, 'therion': lambda: self.therion[0]})
        self.saude.medir()
        self.registro = acoes.Registro()
        self.lento = _Lento()
        self.executor = acoes.Executor(repo, self.registro, self.pasta, lambda: False, rodar=self.lento)
        self.pareamento = seguranca.Pareamento(self.pasta)
        config = seguranca.Config(client_ip=client_ip, bind='127.0.0.1', port=0)
        self.servidor = porteiro.criar_servidor(config, seguranca.Guarda(client_ip, 'tok'), self.pareamento,
                                                self.saude, self.executor, self.registro, PAGINAS)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)
        self.addCleanup(self.lento.liberar.set)

    def pedir(self, metodo, caminho, corpo=None, cookie=True, cabecalhos=None):
        c = http.client.HTTPConnection('127.0.0.1', self.servidor.server_address[1], timeout=5)
        h = dict(cabecalhos or {})
        if cookie:
            h['Cookie'] = 'estacao=tok'
        if corpo is not None:
            h.setdefault('Content-Type', 'application/x-www-form-urlencoded')
        c.request(metodo, caminho, body=corpo, headers=h)
        r = c.getresponse()
        return r.status, r.read(), r

    def test_ip_bloqueado_403_em_tudo(self):
        self.montar(client_ip='192.0.2.99')
        for caminho in ('/', '/estado'):
            status, corpo, _ = self.pedir('GET', caminho)
            self.assertEqual((status, corpo), (403, b''))

    def test_sem_cookie_mostra_pareamento(self):
        self.montar()
        status, corpo, _ = self.pedir('GET', '/', cookie=False)
        self.assertEqual((status, corpo), (200, PAGINAS['parear']))
        self.assertEqual(self.pedir('GET', '/')[1], PAGINAS['estacao'])

    def test_parear_certo_da_cookie(self):
        self.montar()
        c = self.pareamento.gerar()
        status, _, r = self.pedir('POST', '/parear', f'codigo={c}', cookie=False)
        self.assertEqual(status, 204)
        self.assertIn('estacao=tok', r.getheader('Set-Cookie'))

    def test_parear_errado_403(self):
        self.montar()
        c = self.pareamento.gerar()
        errado = '000000' if c != '000000' else '111111'
        self.assertEqual(self.pedir('POST', '/parear', f'codigo={errado}', cookie=False)[0], 403)

    def test_estado_exige_cookie(self):
        self.montar()
        self.assertEqual(self.pedir('GET', '/estado', cookie=False)[0], 403)

    def test_estado_parado_e_offline(self):
        self.montar()
        status, corpo, _ = self.pedir('GET', '/estado')
        dados = json.loads(corpo)
        self.assertEqual((status, dados['estado']), (200, 'parado'))
        for valor in (False, None):
            self.therion[0] = valor
            self.saude.medir()
            self.assertEqual(json.loads(self.pedir('GET', '/estado')[1])['estado'], 'offline')

    def test_estado_desde_invalido(self):
        self.montar()
        self.registro.adicionar('porteiro', 'a')
        self.registro.adicionar('porteiro', 'b')
        for q in ('?desde=abc', '?desde=99999', ''):
            mensagens = json.loads(self.pedir('GET', '/estado' + q)[1])['mensagens']
            self.assertEqual([m['texto'] for m in mensagens], ['a', 'b'])

    def test_acao_codigos(self):
        self.montar()
        self.assertEqual(self.pedir('POST', '/acao/2', '')[0], 202)
        self.assertEqual(self.pedir('POST', '/acao/2', '')[0], 409)
        self.assertEqual(json.loads(self.pedir('GET', '/estado')[1])['acao'], '2')
        self.assertEqual(self.pedir('POST', '/acao/9', '')[0], 404)

    def test_post_sem_tamanho_ou_grande_400(self):
        self.montar()
        c = http.client.HTTPConnection('127.0.0.1', self.servidor.server_address[1], timeout=5)
        c.putrequest('POST', '/parear')
        c.putheader('Content-Length', '2000')
        c.endheaders()
        self.assertEqual(c.getresponse().status, 400)
        c = http.client.HTTPConnection('127.0.0.1', self.servidor.server_address[1], timeout=5)
        c.putrequest('POST', '/acao/2')
        c.putheader('Cookie', 'estacao=tok')
        c.endheaders()
        self.assertEqual(c.getresponse().status, 400)

    def test_main_parear_imprime_codigo(self):
        pasta = tempfile.mkdtemp()
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            self.assertEqual(porteiro.main(['--pasta', pasta, '--parear']), 0)
        self.assertRegex(saida.getvalue(), r'Código: \d{6}')

    def test_main_config_invalida_sai_2(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(porteiro.main(['--pasta', tempfile.mkdtemp()]), 2)


if __name__ == '__main__':
    unittest.main()
