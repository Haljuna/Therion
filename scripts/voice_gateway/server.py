"""API de teste: ASR CPU + relay para Jarvis residente, sem app VoiceStudio."""
import argparse
from email.parser import BytesParser
from email import policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

from asr import Recognizer, decode_wav, process_memory

MAX_BODY = 2_200_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def parse_audio(content_type, raw, model):
    message = BytesParser(policy=policy.default).parsebytes(
        ('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
    if message.get_content_type() != 'multipart/form-data' or not message.is_multipart():
        raise ValueError('Requer multipart/form-data com arquivo WAV')
    fields, audio = {}, None
    for part in message.iter_parts():
        name = part.get_param('name',header='content-disposition')
        data = part.get_payload(decode=True)
        if name == 'file':
            if audio is not None:raise ValueError('Apenas um arquivo e permitido')
            audio = data
        elif name in ('model','language','response_format'):
            if name in fields:raise ValueError('Campo duplicado')
            fields[name] = data.decode('utf-8')
        else:raise ValueError('Campo nao suportado')
    if not audio or fields.get('model') not in ('whisper-1',model):
        raise ValueError('Arquivo ou modelo invalido')
    if fields.get('language','pt') != 'pt' or fields.get('response_format','json') != 'json':
        raise ValueError('Comparacao aceita portugues e resposta JSON')
    decode_wav(audio)  # Validar cabecalho/duracao antes de reservar o modelo.
    return audio


class State:
    def __init__(self, model):
        self.model, self.recognizer = model, None
        self.lock = threading.Lock()
        self.status = 'loading'
        self.failure = None
        self.load_seconds = None

    def load(self):
        try:
            with self.lock:
                self.recognizer = Recognizer(self.model, threads=2)
                self.load_seconds = self.recognizer.load_seconds
                self.status = 'ready'
        except Exception as error:
            self.failure, self.status = type(error).__name__, 'error'

    def snapshot(self):
        return {'status':self.status,'model':self.model,'device':'cpu','threads':2,
                'load_seconds':self.load_seconds,'failure_type':self.failure,
                'process_memory':process_memory()}


class Gateway(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self,address,state,token,voice_port=3901):
        self.state, self.token = state, token
        self.voice_base = f'http://127.0.0.1:{voice_port}'
        self.client = build_opener(ProxyHandler({}),NoRedirect())
        super().__init__(address,Handler)

    def relay(self,path,raw=None):
        request = Request(self.voice_base+path,data=raw,
                          headers={'Content-Type':'application/json'} if raw is not None else {})
        with self.client.open(request,timeout=90 if raw is not None else 3) as response:
            kind = response.headers.get_content_type()
            result = response.read(12_000_001 if raw is not None else 65537)
        if len(result) > (12_000_000 if raw is not None else 65536):
            raise ValueError('Resposta da voz acima do limite')
        if raw is not None and (kind != 'audio/wav' or result[:4] != b'RIFF' or result[8:12] != b'WAVE'):
            raise ValueError('Resposta da voz nao e WAV')
        return kind,result


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self,*_):pass

    def reply(self,status,body,kind='application/json'):
        raw = json.dumps(body).encode('utf-8') if isinstance(body,dict) else body
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('Connection','close')
        self.end_headers()
        self.close_connection = True
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass

    def allowed(self):
        if self.headers.get('Origin') or self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            self.reply(403,{'error':'client_not_allowed'})
            return False
        return True

    def do_GET(self):
        if not self.allowed():return
        if self.path in ('/health','/stt/health'):
            result = self.server.state.snapshot()
            if self.path == '/health':
                try:
                    _,raw = self.server.relay('/health')
                    result['voice_status'] = json.loads(raw).get('status')
                except Exception:result['voice_status']='unavailable'
                if result['status']=='ready' and result['voice_status']!='ready':result['status']='degraded'
            return self.reply(200 if result['status']=='ready' else 503,result)
        if self.path == '/profiles/120f734a':
            try:
                kind,raw = self.server.relay(self.path)
                if json.loads(raw).get('id') != '120f734a':raise ValueError('Perfil divergente')
                return self.reply(200,raw,kind)
            except Exception:return self.reply(503,{'error':'profile_unavailable'})
        self.reply(404,{'error':'not_found'})

    def do_POST(self):
        if not self.allowed():return
        if self.path=='/shutdown':
            if not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.server.token):
                return self.reply(403,{'error':'authentication_required'})
            if not self.server.state.lock.acquire(blocking=False):return self.reply(409,{'error':'busy'})
            try:
                self.reply(200,{'status':'stopping'})
                threading.Thread(target=self.server.shutdown,daemon=True).start()
            finally:self.server.state.lock.release()
            return
        if self.path not in ('/v1/audio/transcriptions','/v1/audio/speech'):
            return self.reply(404,{'error':'not_found'})
        if self.headers.get('Transfer-Encoding'):return self.reply(415,{'error':'chunked_not_supported'})
        try:size=int(self.headers.get('Content-Length','0'))
        except ValueError:return self.reply(400,{'error':'invalid_length'})
        if not 0 < size <= MAX_BODY:return self.reply(413,{'error':'body_too_large'})
        raw = self.rfile.read(size)
        if len(raw)!=size:return self.reply(400,{'error':'truncated_body'})
        if self.path=='/v1/audio/speech':
            if self.headers.get('Content-Type','').split(';')[0] != 'application/json' or size>16384:
                return self.reply(415,{'error':'json_required'})
            try:
                payload=json.loads(raw)
                if payload.get('voice')!='120f734a':return self.reply(404,{'error':'profile_unavailable'})
                kind,result=self.server.relay(self.path,raw)
                return self.reply(200,result,kind)
            except HTTPError as error:
                code=error.code;error.close()
                return self.reply(code,{'error':'voice_request_failed'})
            except Exception:return self.reply(503,{'error':'voice_unavailable'})
        try:audio=parse_audio(self.headers.get('Content-Type',''),raw,self.server.state.model)
        except Exception:return self.reply(422,{'error':'invalid_audio_request'})
        state=self.server.state
        if state.status!='ready':return self.reply(503,{'error':'model_not_ready'})
        if not state.lock.acquire(blocking=False):return self.reply(409,{'error':'busy'})
        try:
            result=state.recognizer.transcribe(audio)
            return self.reply(200,result)
        except Exception as error:
            return self.reply(500,{'error':'transcription_failed','failure_type':type(error).__name__})
        finally:state.lock.release()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',choices=('baseline','tiny','parakeet','turbo'),required=True)
    parser.add_argument('--port',type=int,default=3902)
    parser.add_argument('--runtime',required=True,type=Path)
    args=parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
    args.runtime.mkdir(parents=True,exist_ok=True)
    state=State(args.model)
    token=secrets.token_urlsafe(32)
    server=Gateway(('127.0.0.1',args.port),state,token)
    process_file=args.runtime/'gateway-process.json'
    process_file.write_text(json.dumps({'pid':os.getpid(),'port':args.port,'shutdown_token':token}),encoding='utf-8')
    threading.Thread(target=state.load,daemon=True).start()
    try:server.serve_forever(poll_interval=.25)
    finally:
        server.server_close()
        process_file.unlink(missing_ok=True)


if __name__=='__main__':main()
