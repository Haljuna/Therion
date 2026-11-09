import unittest
from pathlib import Path

PASTA = Path(__file__).parents[1] / 'scripts' / 'estacao'
PROIBIDO = ['=>', 'let ', 'const ', '`', 'fetch(', 'class ']


class TestPagina(unittest.TestCase):
    def test_es5_apenas(self):
        for nome in ('estacao.html', 'parear.html', 'app/assets/espera.html'):
            texto = (PASTA / nome).read_text(encoding='utf-8')
            for p in PROIBIDO:
                self.assertNotIn(p, texto, f'{nome}: {p!r}')

    def test_ids_e_textos(self):
        t = (PASTA / 'estacao.html').read_text(encoding='utf-8')
        for i in ('anel', 'rotulo', 'log', 'status', 'b1', 'b2', 'b3', 'b4'):
            self.assertIn(f'id="{i}"', t)
        for s in ('THERION OS v1 -- ESTACAO 01', '[3] REINICIAR OLLAMA', '[ TOQUE DE NOVO ]', 'PORTEIRO SEM RESPOSTA'):
            self.assertIn(s, t)

    def test_pareamento(self):
        t = (PASTA / 'parear.html').read_text(encoding='utf-8')
        self.assertIn('/parear', t)
        self.assertIn('maxlength="6"', t)

    def test_gesto_de_manutencao(self):
        t = (PASTA / 'estacao.html').read_text(encoding='utf-8')
        self.assertIn('id="cabecalho"', t)
        self.assertIn('estacao://manutencao', t)
        self.assertIn('5000', t)
        self.assertIn('orientation: portrait', t)


if __name__ == '__main__':
    unittest.main()
