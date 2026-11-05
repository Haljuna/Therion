"""Teste real isolado, sem microfone, reproducao, IA ou alteracao de configuracao."""
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler, Request
import wave


def main():
    root = Path(__file__).resolve().parents[2]
    folder = root/'tmp/asr-comparison-20261020'
    runtime = folder/'gateway'
    runtime.mkdir(exist_ok=True)
    config = Path(os.environ['APPDATA'])/'Therion/config.json'
    before = hashlib.sha256(config.read_bytes()).hexdigest()
    # Never attach to or stop an existing process on the experimental port.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',3902))
    client = build_opener(ProxyHandler({}))
    def request(path, body=None, kind='application/json'):
        with client.open(Request('http://127.0.0.1:3902'+path,data=body,
                headers={'Content-Type':kind}),timeout=95) as response:
            return response.read()
    report = {'model':'parakeet','configuration_before':before}
    with (runtime/'stdout.log').open('wb') as stdout, (runtime/'stderr.log').open('wb') as stderr:
        process = subprocess.Popen([sys.executable,str(Path(__file__).with_name('server.py')),
            '--model','parakeet','--runtime',str(runtime)],cwd=root,stdout=stdout,stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic()+90
            while True:
                if process.poll() is not None:raise RuntimeError('Gateway encerrou antes de ficar pronto')
                try:
                    health = json.loads(request('/stt/health'))
                    if health['status']=='ready':break
                except (URLError,HTTPError):pass
                if time.monotonic()>deadline:raise TimeoutError('Gateway nao ficou pronto')
                time.sleep(.25)
            report['health'] = json.loads(request('/health'))
            report['profile'] = json.loads(request('/profiles/120f734a'))['id']
            audio = (folder/'plano.wav').read_bytes()
            body = (b'--control\r\nContent-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n'
                b'--control\r\nContent-Disposition: form-data; name="file"; filename="synthetic.wav"\r\n'
                b'Content-Type: audio/wav\r\n\r\n'+audio+b'\r\n--control--\r\n')
            started = time.perf_counter()
            report['transcription'] = json.loads(request('/v1/audio/transcriptions',body,
                'multipart/form-data; boundary=control'))
            report['stt_http_seconds'] = round(time.perf_counter()-started,3)
            payload = {'model':'tts-1','voice':'120f734a','input':'Teste de voz concluído.',
                       'response_format':'wav','language':'pt'}
            started = time.perf_counter()
            raw = request('/v1/audio/speech',json.dumps(payload).encode())
            report['tts_http_seconds'] = round(time.perf_counter()-started,3)
            with wave.open(io.BytesIO(raw)) as output:
                report['voice_audio_seconds'] = round(output.getnframes()/output.getframerate(),3)
                assert output.getnframes()>0 and output.getsampwidth()==2
            (folder/'jarvis-gateway.wav').write_bytes(raw)
            assert 'engenharia econômica' in report['transcription']['text'].casefold()
            report['status']='passed'
        except Exception as error:
            report.update(status='failed',failure_type=type(error).__name__)
            raise
        finally:
            statefile = runtime/'gateway-process.json'
            if process.poll() is None and statefile.exists():
                state = json.loads(statefile.read_text())
                if state['pid']==process.pid:
                    control = Request('http://127.0.0.1:3902/shutdown',data=b'{}',
                        headers={'Authorization':'Bearer '+state['shutdown_token']})
                    with client.open(control,timeout=5) as response:response.read()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()  # Only our own newly created experimental process.
                process.wait(timeout=10)
            report['experiment_stopped'] = process.poll() is not None
            report['configuration_unchanged'] = hashlib.sha256(config.read_bytes()).hexdigest()==before
            report['matches_initial_configuration_hash'] = before == (folder/'config-before.sha256').read_text(encoding='utf-8-sig').strip().lower()
            (folder/'gateway-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':main()
