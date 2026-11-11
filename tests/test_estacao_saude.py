import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts' / 'estacao'))
import saude  # noqa: E402


class TestSaude(unittest.TestCase):
    def test_formatar_vram(self):
        self.assertEqual(saude.formatar_vram('5222, 8188\n'), '5,1/8 GB')
        self.assertIsNone(saude.formatar_vram(''))
        self.assertIsNone(saude.formatar_vram('N/A'))

    def test_contem_therion(self):
        repo = Path(r'F:\Therion\app')
        sim = r'"F:\Therion\app\.venv\Scripts\pythonw.exe" -m therion.interface.desktop'
        self.assertTrue(saude.contem_therion([sim.lower()], repo))
        self.assertFalse(saude.contem_therion([r'"F:\Therion\app\.venv\Scripts\pythonw.exe" scripts\estacao\porteiro.py'], repo))
        self.assertFalse(saude.contem_therion([], repo))

    def test_sonda_que_falha_vira_none(self):
        def quebra():
            raise OSError('x')
        s = saude.Saude({'ollama': lambda: True, 'voz': quebra})
        self.assertEqual(s.medir(), {'ollama': True, 'voz': None})

    def test_atual_antes_da_primeira_medicao(self):
        s = saude.Saude({'ollama': lambda: True})
        self.assertEqual(s.atual(), {'ollama': None})

    def test_checar_http_porta_fechada(self):
        self.assertFalse(saude.checar_http('http://127.0.0.1:9/', timeout=0.2))

    def test_a_cada_repete_o_valor_dentro_do_intervalo(self):
        chamadas, agora = [], [100.0]
        sonda = saude.a_cada(15, lambda: chamadas.append(1) or len(chamadas), relogio=lambda: agora[0])
        self.assertEqual((sonda(), sonda()), (1, 1))
        agora[0] += 15
        self.assertEqual(sonda(), 2)

    def test_sondas_padrao_tem_todas_as_chaves(self):
        self.assertEqual(set(saude.sondas_padrao(Path('.'))), {'ram', 'vram', 'ollama', 'voz', 'transcr', 'therion'})


if __name__ == '__main__':
    unittest.main()
