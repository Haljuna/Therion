import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts' / 'estacao'))
import seguranca  # noqa: E402


class TestSeguranca(unittest.TestCase):
    def setUp(self):
        self.pasta = Path(tempfile.mkdtemp())

    def test_config_sem_client_ip_falha(self):
        (self.pasta / 'config.json').write_text('{"bind": "192.0.2.10"}', encoding='utf-8')
        with self.assertRaises(ValueError):
            seguranca.carregar_config(self.pasta)

    def test_config_le_porta_padrao(self):
        (self.pasta / 'config.json').write_text('{"client_ip": "192.0.2.20", "bind": "192.0.2.10"}', encoding='utf-8')
        self.assertEqual(seguranca.carregar_config(self.pasta).port, 3904)

    def test_token_e_criado_uma_vez(self):
        a = seguranca.carregar_token(self.pasta)
        b = seguranca.carregar_token(self.pasta)
        self.assertEqual(a, b)
        self.assertGreaterEqual(len(a), 40)

    def test_pareamento_certo_uma_vez(self):
        p = seguranca.Pareamento(self.pasta, relogio=lambda: 1000.0)
        c = p.gerar()
        self.assertRegex(c, r'^\d{6}$')
        self.assertTrue(p.validar(c))
        self.assertFalse(p.validar(c))

    def test_pareamento_expira_em_300s(self):
        t = [1000.0]
        p = seguranca.Pareamento(self.pasta, relogio=lambda: t[0])
        c = p.gerar()
        t[0] = 1301.0
        self.assertFalse(p.validar(c))

    def test_pareamento_bloqueia_apos_5_erros(self):
        p = seguranca.Pareamento(self.pasta, relogio=lambda: 1000.0)
        c = p.gerar()
        errado = '000000' if c != '000000' else '111111'
        for _ in range(5):
            self.assertFalse(p.validar(errado))
        self.assertFalse(p.validar(c))

    def test_pareamento_sem_arquivo_ou_corrompido(self):
        p = seguranca.Pareamento(self.pasta)
        self.assertFalse(p.validar('123456'))
        (self.pasta / 'pareamento.json').write_text('{lixo', encoding='utf-8')
        self.assertFalse(p.validar('123456'))

    def test_guarda_ip(self):
        g = seguranca.Guarda('192.0.2.20', 'tok')
        self.assertTrue(g.ip_ok('192.0.2.20'))
        self.assertFalse(g.ip_ok('192.0.2.21'))

    def test_guarda_cookie_entre_outros_e_lixo(self):
        g = seguranca.Guarda('192.0.2.20', 'tok')
        self.assertTrue(g.cookie_ok('a=1; estacao=tok'))
        self.assertFalse(g.cookie_ok('estacao=outro'))
        self.assertFalse(g.cookie_ok(None))
        self.assertFalse(g.cookie_ok(';;=\x00"'))

    def test_set_cookie_persistente(self):
        v = seguranca.cabecalho_set_cookie('tok')
        self.assertTrue(v.startswith('estacao=tok;'))
        self.assertIn('Expires=', v)
        self.assertIn('HttpOnly', v)


if __name__ == '__main__':
    unittest.main()
