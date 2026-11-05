"""Iniciador PowerShell com estados e HTTP fictícios, sem carregar modelos."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import threading
import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/VoiceStartup.ps1'
POWERSHELL=shutil.which('powershell.exe')
pytestmark=pytest.mark.skipif(not POWERSHELL,reason='Requer PowerShell do Windows')


def run(body):
    prefix="[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $ErrorActionPreference='Stop'; . '"+str(SCRIPT).replace("'","''")+"'; "
    return subprocess.run([POWERSHELL,'-NoProfile','-NonInteractive','-Command',prefix+body],
        capture_output=True,text=True,encoding='utf-8',timeout=20)


@pytest.mark.parametrize('state,free,expected',[
    (None,3.,'start'),({'model':'parakeet','status':'ready'},.2,'ready'),
    ({'model':'parakeet','status':'loading'},.2,'wait'),
    ({'model':'parakeet','status':'error','failure_type':'MemoryError'},3.,'restart')])
def test_startup_action_preserves_ready_service_and_gates_recovery(state,free,expected):
    row=json.dumps(state)
    result=run(f"$state='{row}' | ConvertFrom-Json; Get-ParakeetStartupAction $state {free}")
    assert result.returncode==0 and result.stdout.strip()==expected,result.stderr


@pytest.mark.parametrize('state,free,message',[
    (None,1.2,'2.00 GiB'),
    ({'model':'parakeet','status':'error','failure_type':'MemoryError'},1.3,'1.30 GiB'),
    ({'model':'tiny','status':'ready'},4.,'outro servico'),
    ({'model':'parakeet','status':'error','failure_type':'ImportError'},4.,'ImportError')])
def test_terminal_failure_is_immediate_and_actionable(state,free,message):
    row=json.dumps(state)
    result=run(f"$state='{row}' | ConvertFrom-Json; Get-ParakeetStartupAction $state {free}")
    assert result.returncode!=0 and message in result.stderr


@pytest.mark.parametrize('status',['loading','error'])
def test_http_503_keeps_health_body(status):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(503);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps(dict(status=status,model='parakeet',failure_type='MemoryError')).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:result=run(f"Read-LocalState 'http://127.0.0.1:{server.server_port}/stt/health' | ConvertTo-Json -Compress")
    finally:server.shutdown();server.server_close();thread.join(3)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['status']==status


def test_shutdown_refuses_unmatched_process_without_request(tmp_path):
    (tmp_path/'gateway-process.json').write_text(json.dumps(dict(port=3902,pid=123,shutdown_token='fake-token')),encoding='utf-8')
    path=str(tmp_path).replace("'","''")
    result=run("function Get-NetTCPConnection { [pscustomobject]@{LocalAddress='127.0.0.1';OwningProcess=999} }; Stop-FailedTherionGateway '"+path+"'")
    assert result.returncode!=0 and 'Nenhum processo foi encerrado' in result.stderr


def stt_config(model_path, **voice):
    tts=dict(provider='voicestudio',voicestudio_voice='120f734a',voicestudio_endpoint=voice.pop('speech'))
    return dict(voice=dict(model_path=model_path,**voice),tts=tts,ai=dict(endpoint='http://127.0.0.1:11435/api/chat'))


@pytest.mark.parametrize('voice,expected',[
    (dict(provider='parakeet_http',endpoint='http://127.0.0.1:3902/v1/audio/transcriptions',
          speech='http://127.0.0.1:3902/v1/audio/speech'),'parakeet'),
    (dict(provider='whisper',speech='http://127.0.0.1:3901/v1/audio/speech'),'whisper')])
def test_stt_profile_accepts_only_approved_combinations(tmp_path,voice,expected):
    row=json.dumps(stt_config(str(tmp_path),**voice)).replace("'","''")
    result=run(f"Get-TherionSttProfile ('{row}' | ConvertFrom-Json)")
    assert result.returncode==0 and result.stdout.strip()==expected,result.stderr


@pytest.mark.parametrize('voice',[
    dict(provider='whisper',speech='http://127.0.0.1:3902/v1/audio/speech'),
    dict(provider='parakeet_http',endpoint='http://127.0.0.1:3902/v1/audio/transcriptions',
         speech='http://127.0.0.1:3901/v1/audio/speech')])
def test_stt_profile_rejects_mixed_routes(tmp_path,voice):
    row=json.dumps(stt_config(str(tmp_path),**voice)).replace("'","''")
    result=run(f"Get-TherionSttProfile ('{row}' | ConvertFrom-Json)")
    assert result.returncode!=0 and 'Nenhuma opcao foi alterada' in result.stderr


def test_stt_profile_rejects_missing_whisper_model(tmp_path):
    row=json.dumps(stt_config(str(tmp_path/'ausente'),provider='whisper',speech='http://127.0.0.1:3901/v1/audio/speech'))
    result=run(f"Get-TherionSttProfile ('{row.replace(chr(39),chr(39)*2)}' | ConvertFrom-Json)")
    assert result.returncode!=0


def test_launcher_and_helpers_parse_without_loading_services():
    launcher=SCRIPT.with_name('Start-Therion.ps1')
    for path in (launcher,SCRIPT):
        literal=str(path).replace("'","''")
        result=run("$errors=$null;$tokens=$null;[Management.Automation.Language.Parser]::ParseFile('"+literal+"',[ref]$tokens,[ref]$errors) | Out-Null; if($errors){throw ($errors | Out-String)}")
        assert result.returncode==0,result.stderr


def test_shutdown_refuses_service_that_has_become_ready(tmp_path):
    (tmp_path/'gateway-process.json').write_text(json.dumps(dict(port=3902,pid=123,shutdown_token='fake-token')),encoding='utf-8')
    path=str(tmp_path).replace("'","''")
    result=run("function Get-NetTCPConnection { [pscustomobject]@{LocalAddress='127.0.0.1';OwningProcess=123} }; function Read-LocalState { [pscustomobject]@{model='parakeet';status='ready'} }; Stop-FailedTherionGateway '"+path+"'")
    assert result.returncode!=0 and 'nao esta mais na falha' in result.stderr


def test_jarvis_wait_covers_cold_boot_on_hd():
    # Boot de 2026-11-04: Jarvis pronto em 537 s (import do torch no HD frio); limite de 300 s abortava o Therion.
    import re
    text=(SCRIPT.parent/'Start-Therion.ps1').read_text(encoding='utf-8-sig')
    limit=int(re.search(r"TotalSeconds -gt (\d+)\) \{ throw 'Jarvis nao ficou pronto",text).group(1))
    assert limit>=900
