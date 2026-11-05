"""Regressão com AppData/temporários isolados; nunca usa estado pessoal V4.

Uso: .venv/Scripts/python.exe scripts/test-v4.py [argumentos pytest]
Os artefatos ficam em tmp/v4-tests/regression-<id> para auditoria.
"""
from pathlib import Path
import os
import sys
import uuid


def main():
    root=Path(__file__).resolve().parents[1]
    state=Path(os.environ.get('THERION_TEST_ROOT',str(root/'tmp'/'v4-tests')))/('regression-'+uuid.uuid4().hex)
    state.mkdir(parents=True)
    # O Playwright procura o Chromium na LOCALAPPDATA real; guarde antes de isolar.
    if os.environ.get('LOCALAPPDATA'):
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',os.path.join(os.environ['LOCALAPPDATA'],'ms-playwright'))
    for variable,folder in [('APPDATA','roaming'),('LOCALAPPDATA','local'),('TEMP','temp'),('TMP','temp')]:
        path=state/folder;path.mkdir(exist_ok=True);os.environ[variable]=str(path)
    os.chdir(root);sys.path.insert(0,str(root))
    import pytest
    print('Fixtures isoladas:',state)
    args=sys.argv[1:] or ['tests','-q']
    return pytest.main(['--basetemp',str(state/'pytest'),'-p','no:cacheprovider',*args])


if __name__=='__main__':sys.exit(main())
