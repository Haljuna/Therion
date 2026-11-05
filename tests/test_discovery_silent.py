"""Descoberta sem processos auxiliares; atalhos fictícios nunca são executados."""
import ctypes
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from therion.autonomy import shortcuts
from therion.autonomy.apps import discover_applications


@pytest.mark.skipif(os.name != 'nt', reason='Shell Links requer Windows.')
def test_native_shortcut_read_unicode_and_arguments_without_subprocess(tmp_path):
    target = str(Path(os.environ['WINDIR'])/'System32'/'charmap.exe')
    with patch('subprocess.Popen', side_effect=AssertionError('Não deve criar processo')):
        with shortcuts.ShellLinks() as reader:
            for filename, arguments in [('Aplicativo com acentuação.lnk', ''), ('Com argumentos.lnk', '--test')]:
                link, persist = reader._open()
                try:
                    shortcuts._check(shortcuts._method(link, 20, ctypes.c_long, ctypes.c_wchar_p)(link, target))
                    shortcuts._check(shortcuts._method(link, 11, ctypes.c_long, ctypes.c_wchar_p)(link, arguments))
                    shortcuts._check(shortcuts._method(persist, 6, ctypes.c_long, ctypes.c_wchar_p,
                        ctypes.c_int)(persist, str(tmp_path/filename), True))
                finally:
                    shortcuts._method(persist, 2, ctypes.c_ulong)(persist)
                    shortcuts._method(link, 2, ctypes.c_ulong)(link)
            path, arguments = reader.read(tmp_path/'Aplicativo com acentuação.lnk')
            assert Path(path) == Path(target) and arguments == ''
        (tmp_path/'Inválido.lnk').write_bytes(b'not a shortcut')
        with ThreadPoolExecutor(max_workers=1) as worker:
            candidates = worker.submit(shortcuts.discover_shortcuts, [tmp_path]).result(timeout=10)
        assert len(candidates) == 1
        assert candidates[0]['name'] == 'Aplicativo com acentuação'


@pytest.mark.skipif(os.name != 'nt', reason='Consulta de aplicativos requer Windows.')
def test_real_discovery_does_not_spawn_any_process():
    with patch('subprocess.Popen', side_effect=AssertionError('Descoberta abriu processo auxiliar')):
        rows = discover_applications()
    assert isinstance(rows, list)
    assert len({os.path.normcase(row['path']) for row in rows}) == len(rows)
    assert all(Path(row['path']).is_file() for row in rows)


def test_com_failure_keeps_registry_discovery_available():
    if os.name != 'nt':
        pytest.skip('Consulta de aplicativos requer Windows.')
    with patch.object(shortcuts.ShellLinks, '__enter__', side_effect=OSError('COM indisponível')):
        assert shortcuts.discover_shortcuts([]) == []
        assert isinstance(discover_applications(), list)
