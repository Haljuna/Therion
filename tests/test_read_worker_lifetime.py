"""Destruir o painel com uma leitura em andamento não pode derrubar o processo."""
import subprocess
import sys
from pathlib import Path

SCRIPT = '''
import os, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import shiboken6
from PySide6.QtWidgets import QApplication, QWidget
from therion.interface.dashboard import ReadWorker
app = QApplication([])
parent = QWidget()
worker = ReadWorker(lambda token: time.sleep(.6), parent)
done = []
worker.finished.connect(lambda: done.append(1))
worker.start(); time.sleep(.1)
shiboken6.delete(parent); del worker   # o que acontece quando um teste larga a janela
deadline = time.monotonic() + 5
while not done and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.02)
print("terminou" if done else "sem resultado")
'''


def test_destroying_parent_while_reading_keeps_process_alive():
    root = Path(__file__).resolve().parents[1]
    run = subprocess.run([sys.executable, '-c', SCRIPT], cwd=root, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr[-500:]
    assert 'terminou' in run.stdout
