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
