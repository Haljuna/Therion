"""Regressão real da inicialização COM, com backend Windows e sem supressão."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]


def probe(*arguments):
    env=dict(os.environ,QT_QPA_PLATFORM='windows')
    result=subprocess.run([sys.executable,str(ROOT/'scripts'/'diagnose-native-close.py'),
        '--case','original',*arguments],cwd=ROOT,env=env,capture_output=True,text=True,
        encoding='utf-8',errors='replace',timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
    marker=next(line for line in result.stdout.splitlines() if line.startswith('NATIVE_CLOSE_RESULT='))
    return json.loads(marker.partition('=')[2]),result.stderr


@pytest.mark.skipif(sys.platform!='win32',reason='Regressão da ponte nativa Windows.')
def test_original_close_has_zero_com_exceptions_with_accessibility_active():
    report,stderr=probe()
    assert report['exit_code']==0 and report['com_exceptions']==0
    assert report['native_requests']>=1
    assert report['qt_windows_disposed']==1
    assert report['prewarm'][0]['product_state']['state']=='prepared'
    assert '0x8001010d' not in stderr.casefold()


@pytest.mark.skipif(sys.platform!='win32',reason='Controle causal depende de cliente UIA ativo.')
def test_control_path_is_distinguished_from_fixed_native_path():
    report,stderr=probe('--skip-product-preparation')
    assert report['qt_windows_disposed']==1
    if report['com_exceptions']==0:
        pytest.skip('Nenhum cliente UIA desencadeou a condição de controle neste ambiente.')
    assert report['com_exceptions']>=1 and report['native_requests']>=1
    assert '0x8001010d' in stderr.casefold()
    assert report['prewarm'][0]['product_state']['state']=='diagnostic_control'
