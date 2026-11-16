"""Isola o estado do usuário antes de qualquer import do Therion.

Sem isto, `pytest` direto lia a configuração e as contas reais e escrevia no log de
auditoria real. `scripts/test-v4.py` já isola e avisa por THERION_TESTS_ISOLATED.
"""
import os
import uuid
from pathlib import Path

if not os.environ.get('THERION_TESTS_ISOLATED'):
    _state = Path(__file__).resolve().parents[1]/'tmp'/'v4-tests'/('pytest-'+uuid.uuid4().hex)
    # O Playwright procura o Chromium na LOCALAPPDATA real; guarde antes de isolar.
    if os.environ.get('LOCALAPPDATA'):
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', os.path.join(os.environ['LOCALAPPDATA'], 'ms-playwright'))
    for _variable, _folder in (('APPDATA', 'roaming'), ('LOCALAPPDATA', 'local'), ('TEMP', 'temp'), ('TMP', 'temp')):
        (_state/_folder).mkdir(parents=True, exist_ok=True)
        os.environ[_variable] = str(_state/_folder)
    os.environ['THERION_TESTS_ISOLATED'] = '1'

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


def _move_test_windows():
    """THERION_TEST_SCREEN=2 abre as janelas dos testes no 2º monitor, para não cobrir o que está em uso."""
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtWidgets import QWidget
    number = os.environ.get('THERION_TEST_SCREEN', '')
    app = QApplication.instance()
    if not number.isdigit() or not isinstance(app, QApplication) or getattr(app, '_therion_screen_filter', None):
        return
    screens = app.screens()
    if not 1 <= int(number) <= len(screens):
        return
    area = screens[int(number) - 1].availableGeometry()

    class Mover(QObject):
        def eventFilter(self, target, event):
            # Só janelas e diálogos; menus e dicas ficam onde o Qt os posiciona.
            if (event.type() == QEvent.Show and isinstance(target, QWidget) and target.isWindow()
                    and target.windowType() in (Qt.Window, Qt.Dialog)
                    and not area.contains(target.frameGeometry().center())):
                target.move(area.x() + 40, area.y() + 40)
            return False

    app._therion_screen_filter = Mover(app)
    app.installEventFilter(app._therion_screen_filter)


def pytest_runtest_setup(item):
    _move_test_windows()


def pytest_runtest_call(item):
    _move_test_windows()


def pytest_configure(config):
    # A gaveta desliza ao abrir; nos testes ela abre já no lugar, para as medidas valerem na hora.
    from therion.interface.workspace import ScenePanel
    ScenePanel.SLIDE_MS = 0
