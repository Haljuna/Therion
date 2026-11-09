import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts' / 'estacao'))
import acoes  # noqa: E402


class TestAcoes(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.reg = acoes.Registro()
        (self.repo / 'scripts' / 'estacao').mkdir(parents=True)

    def exec(self, **kw):
        kw.setdefault('therion_vivo', lambda: False)
        return acoes.Executor(self.repo, self.reg, self.repo, **kw)

    def esperar(self, e):
        for _ in range(400):
            if e.em_curso() is None:
                return
            time.sleep(0.05)
        self.fail('ação não terminou')

    def script(self, texto):
        (self.repo / 'scripts' / 'start-local-ollama.ps1').write_text(texto, encoding='utf-8')

    def test_registro_desde(self):
        self.reg.adicionar('porteiro', 'a')
        s = self.reg.adicionar('porteiro', 'b')
        self.assertEqual([m['texto'] for m in self.reg.desde(1)], ['b'])
        self.assertEqual(len(self.reg.desde(s + 10)), 2)
        self.assertEqual(len(self.reg.desde(-3)), 2)

    def test_id_desconhecido(self):
        self.assertEqual(self.exec().disparar('9'), 'desconhecido')

    def test_script_inexistente(self):
        e = self.exec()
        self.assertEqual(e.disparar('2'), 'aceito')
        self.esperar(e)
        self.assertEqual(self.reg.desde(0)[-1]['texto'], 'falhou: script não encontrado')

    def test_ligar_com_therion_vivo_nao_executa(self):
        chamadas = []
        e = self.exec(therion_vivo=lambda: True, rodar=lambda *a, **k: chamadas.append(a))
        e.disparar('1')
        self.esperar(e)
        self.assertEqual(chamadas, [])
        self.assertEqual(self.reg.desde(0)[-1]['texto'], 'já está ligado')

    def test_toques_simultaneos_so_um_aceito(self):
        self.script('Start-Sleep 1')
        e = self.exec()
        r = []
        ts = [threading.Thread(target=lambda: r.append(e.disparar('2'))) for _ in range(5)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(sorted(r), ['aceito'] + ['ocupado'] * 4)
        self.esperar(e)

    def test_tempo_esgotado(self):
        self.script('Start-Sleep 10')
        e = self.exec(timeout=1.0)
        e.disparar('2')
        self.esperar(e)
        self.assertEqual(self.reg.desde(0)[-1]['texto'], 'falhou: tempo esgotado')

    def test_erro_mostra_ultima_linha(self):
        self.script("throw 'Executável do Ollama não encontrado.'")
        e = self.exec()
        e.disparar('2')
        self.esperar(e)
        t = self.reg.desde(0)[-1]['texto']
        self.assertTrue(t.startswith('falhou: '), t)
        self.assertLessEqual(len(t), len('falhou: ') + 80)

    def test_filho_em_segundo_plano_nao_prende_a_acao(self):
        self.script("Start-Process -FilePath ping -ArgumentList '-n','30','127.0.0.1' -WindowStyle Hidden")
        e = self.exec(timeout=20.0)
        inicio = time.time()
        e.disparar('2')
        self.esperar(e)
        self.assertLess(time.time() - inicio, 10)
        self.assertTrue(self.reg.desde(0)[-1]['texto'].startswith('ollama de pé em'))


if __name__ == '__main__':
    unittest.main()
