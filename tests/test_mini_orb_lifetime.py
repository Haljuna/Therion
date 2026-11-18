"""Fechar com a mini orbe aberta (OpenGL real) não pode derrubar o processo."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = '''
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow
from therion.interface.constellation import Constellation
from therion.interface.mini_orb import MiniOrb

app = QApplication([])
win = QMainWindow()
win.setCentralWidget(Constellation())
win.resize(500, 400)
win.show()
quick = lambda: {"ram": 40.0}
full = lambda: {"ram": 40.0, "ram_used": 1, "ram_total": 2}
mini = MiniOrb(path=sys.argv[1], readers=(quick, full))
mini.show()

def finish():
    mini.shut()
    win.close()
    app.quit()

QTimer.singleShot(1000, finish)
sys.exit(app.exec())
'''


@pytest.mark.skipif(os.environ.get('QT_QPA_PLATFORM') in {'offscreen', 'minimal'}, reason='sem OpenGL')
@pytest.mark.parametrize('rodada', [1, 2, 3])
def test_closing_with_mini_orb_open_exits_cleanly(rodada):
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as tmp:
        run = subprocess.run([sys.executable, '-c', SCRIPT, str(Path(tmp) / 'pos.json')],
                             cwd=root, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, f'codigo {run.returncode}: {run.stderr[-500:]}'
