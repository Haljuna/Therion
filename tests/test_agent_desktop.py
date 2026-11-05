"""UIA real limitada a uma janela Qt fictícia em processo próprio."""
from pathlib import Path
import json
import os
import queue
import subprocess
import sys
import threading

import pytest

from therion.agent.contracts import CancellationToken
from therion.integrations.desktop import DesktopSession
from therion.integrations.rpc import OwnedWorker


@pytest.mark.parametrize('name',['WindowsTerminal.exe','OpenConsole.exe','conhost.exe','wt.exe'])
def test_terminal_windows_are_never_targets(name):
    # Bloqueio pelo nome, antes de qualquer UIA: não depende do processo existir.
    session=DesktopSession({'targets':{'t':{'path':'C:\\Fixture\\'+name,'pid':1}}})
    with pytest.raises(ValueError,match='terminais'):session.window({'target_id':'t'})


def test_uia_fixture_identity_fill_and_click(tmp_path):
    import hashlib
    from therion.integrations.desktop import process_identity
    fixture=tmp_path/'window.py'
    fixture.write_text('''import sys,json
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLineEdit,QPushButton,QLabel
from PySide6.QtCore import QTimer
from therion.interface.native_accessibility import prepare_native_accessibility
app=QApplication([]);window=QWidget();window.setWindowTitle('Therion UIA fixture')
layout=QVBoxLayout(window);label=QLabel('Aurora');edit=QLineEdit();edit.setAccessibleName('Nome')
button=QPushButton('Confirmar');button.clicked.connect(lambda:label.setText('Confirmado'))
for widget in (label,edit,button):layout.addWidget(widget)
prepare_native_accessibility(window);window.show()
QTimer.singleShot(300,lambda:print(json.dumps({'handle':int(window.winId())}),flush=True))
QTimer.singleShot(60000,app.quit);sys.exit(app.exec())
''',encoding='utf-8')
    env=dict(os.environ,PYTHONPATH=str(Path.cwd()),PYTHONIOENCODING='utf-8')
    process=subprocess.Popen([sys.executable,str(fixture)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        text=True,encoding='utf-8',env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    worker=None
    try:
        messages=queue.Queue()
        threading.Thread(target=lambda:messages.put(process.stdout.readline()),daemon=True).start()
        ready=json.loads(messages.get(timeout=15));path,created=process_identity(process.pid)
        target={'pid':process.pid,'handle':ready['handle'],'path':path,'created':created,
                'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'actions':['read','fill','click']}
        worker=OwnedWorker('desktop',{'targets':{'fixture':target}});token=CancellationToken()
        before=worker.call('read',{'target_id':'fixture'},token)
        edit=next(item for item in before['controls'] if item['type']=='Edit')
        filled=worker.call('fill',{'target_id':'fixture','control_id':edit['id'],'version':before['version'],'text':'Teste'},token)
        assert any(item.get('value')=='Teste' for item in filled['controls'])
        button=next(item for item in filled['controls'] if item['type']=='Button' and item['text']=='Confirmar')
        clicked=worker.call('click',{'target_id':'fixture','control_id':button['id'],'version':filled['version'],'expect':{'kind':'text_present','value':'Confirmado'}},token)
        assert any(item['text']=='Confirmado' for item in clicked['controls']), clicked
        assert clicked['action_observed'] is True
    finally:
        if worker:worker.close()
        if process.poll() is None:process.terminate()
        process.wait(timeout=5);process.stdout.close()
