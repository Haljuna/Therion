"""Servidor experimental OmniVoice, somente loopback, sem importar o app VoiceStudio."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import wave

MAX_BODY = 16384
MAX_TEXT = 500


class Engine:
    def __init__(self, profile, source_root, checkpoint, runtime, steps=16, sequential_load=True):
        self.profile, self.source_root = profile, Path(source_root)
        self.checkpoint, self.runtime, self.steps = Path(checkpoint), Path(runtime), steps
        self.sequential_load = sequential_load
        self.gate, self.state_lock = threading.Lock(), threading.Lock()
        self.state = {'status': 'loading', 'phase': 'starting', 'timings': {}, 'steps': steps,
                      'load_mode': 'sequential' if sequential_load else 'mmap'}
        self.started = time.perf_counter()
        self.model = self.prompt = None

    def status(self):
        with self.state_lock:
            return {**self.state, 'timings': dict(self.state['timings']),
                    'uptime_seconds': round(time.perf_counter() - self.started, 3)}

    def phase(self, name):
        with self.state_lock:
            self.state['phase'] = name
        print(json.dumps({'phase': name, 'seconds': round(time.perf_counter()-self.started, 3)}), flush=True)

    def timed(self, name, operation):
        self.phase(name)
        started = time.perf_counter()
        result = operation()
        with self.state_lock:
            self.state['timings'][name] = round(time.perf_counter()-started, 3)
        return result

    def prepare_reference(self, reference):
        from omnivoice.models.omnivoice import VoiceClonePrompt
        identity = hashlib.sha256(json.dumps(self.profile, sort_keys=True).encode() +
            (self.source_root/'omnivoice/models/omnivoice.py').read_bytes() +
            str(self.checkpoint.resolve()).encode()).hexdigest()[:32]
        cached = self.runtime/('reference-'+identity+'.pt')
        if cached.is_file():
            prompt = VoiceClonePrompt.load(str(cached))  # weights_only=True no pickle arbitrário.
            with self.state_lock:
                self.state['reference_cache_hit'] = True
            return prompt
        prompt = self.model.create_voice_clone_prompt(ref_audio=str(reference),
            ref_text=self.profile['ref_text'], preprocess_prompt=True)
        temporary = cached.with_suffix('.tmp')
        prompt.save(str(temporary))
        temporary.replace(cached)
        with self.state_lock:
            self.state['reference_cache_hit'] = False
        return prompt

    def load(self):
        try:
            with self.gate:
                # Não há recuperação pela rede, troca de modelo ou CPU implícita.
                os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                                  HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1',
                                  TORCH_HOME=str(self.runtime/'torch-cache'))
                sys.path.insert(0, str(self.source_root))
                reference = Path(self.profile['reference_path'])
                if hashlib.sha256(reference.read_bytes()).hexdigest() != self.profile['reference_sha256']:
                    raise ValueError('A referência mudou após a exportação')
                if not (self.checkpoint/'audio_tokenizer').is_dir():
                    raise ValueError('Tokenizador local ausente')
                if not (self.profile.get('ref_text') or '').strip():
                    raise ValueError('Transcrição da referência ausente')

                def import_torch():
                    import torch
                    return torch
                self.torch = self.timed('import_torch', import_torch)
                if not self.torch.cuda.is_available():
                    raise RuntimeError('CUDA indisponível; CPU não foi selecionada automaticamente')
                self.torch.set_num_threads(4)
                free, _ = self.torch.cuda.mem_get_info()
                if free < 5 * 1024**3:
                    raise RuntimeError('Menos de 5 GiB de VRAM livres para o teste isolado')

                def import_model():
                    from omnivoice import OmniVoice
                    return OmniVoice
                cls = self.timed('import_omnivoice', import_model)
                self.model = self.timed('load_weights', lambda: cls.from_pretrained(
                    str(self.checkpoint), device_map='cuda', dtype=self.torch.float16,
                    load_asr=False, local_files_only=True, disable_mmap=self.sequential_load))
                self.model.eval()
                self.prompt = self.timed('prepare_reference', lambda: self.prepare_reference(reference))
                self.torch.cuda.synchronize()
                # A codificação da referência usa buffers grandes que não são o
                # modelo nem o prompt. Devolver blocos livres ao driver permite
                # medir a voz residente sem reter esse pico como cache CUDA.
                self.timed('release_reference_cache', self.torch.cuda.empty_cache)
                with self.state_lock:
                    self.state.update(status='ready', phase='ready',
                        ready_seconds=round(time.perf_counter()-self.started, 3),
                        cuda_allocated_mib=round(self.torch.cuda.memory_allocated()/1024**2, 1),
                        cuda_reserved_mib=round(self.torch.cuda.memory_reserved()/1024**2, 1))
        except Exception as error:
            with self.state_lock:
                self.state.update(status='error', failure_type=type(error).__name__)
            print(json.dumps({'event': 'load_error', 'phase': self.status()['phase'],
                              'failure_type': type(error).__name__}), flush=True)
        finally:
            (self.runtime/'startup-result.json').write_text(json.dumps(self.status(), indent=2), encoding='utf-8')

    def synthesize(self, text):
        started = time.perf_counter()
        try:
            payload, metrics = self._synthesize(text)
        finally:
            # A síntese já terminou e o WAV está na CPU. Libera somente blocos
            # CUDA desocupados; pesos, referência e parâmetros ficam intactos.
            before = self.torch.cuda.memory_reserved()
            cleanup_started = time.perf_counter()
            self.torch.cuda.empty_cache()
            cleanup_seconds = time.perf_counter()-cleanup_started
            allocated = round(self.torch.cuda.memory_allocated()/1024**2, 1)
            reserved = round(self.torch.cuda.memory_reserved()/1024**2, 1)
            with self.state_lock:
                self.state.update(cuda_allocated_mib=allocated, cuda_reserved_mib=reserved)
        metrics.update(total_seconds=round(time.perf_counter()-started, 4),
            cache_cleanup_seconds=round(cleanup_seconds, 4),
            cuda_reserved_before_cleanup_mib=round(before/1024**2, 1),
            cuda_reserved_mib=reserved, cuda_allocated_mib=allocated,
            cuda_released_mib=round(before/1024**2-reserved, 1))
        with self.state_lock:
            self.state['last_generation'] = metrics
        print(json.dumps({'event': 'generated', **metrics}), flush=True)
        return payload, metrics

    def _synthesize(self, text):
        started = time.perf_counter()
        seed = self.profile.get('seed')
        if seed is not None:
            self.torch.manual_seed(seed)
        self.torch.cuda.reset_peak_memory_stats()
        with self.torch.inference_mode():
            audio = self.model.generate(text=text, language='pt', voice_clone_prompt=self.prompt,
                instruct=self.profile.get('instruct') or None, num_step=self.steps,
                guidance_scale=2.0, speed=1.0, denoise=True, preprocess_prompt=True,
                postprocess_output=True)[0]
        self.torch.cuda.synchronize()
        generation_seconds = time.perf_counter()-started
        audio = audio.detach().float().cpu().reshape(-1)
        if not audio.numel() or not self.torch.isfinite(audio).all():
            raise ValueError('Áudio vazio ou inválido')
        pcm = (audio.clamp(-1, 1)*32767).round().to(self.torch.int16).numpy().astype('<i2').tobytes()
        target = io.BytesIO()
        with wave.open(target, 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(self.model.sampling_rate)
            output.writeframes(pcm)
        metrics = {'generation_seconds': round(generation_seconds, 4),
                   'total_seconds': round(time.perf_counter()-started, 4),
                   'audio_seconds': round(audio.numel()/self.model.sampling_rate, 3),
                   'cuda_peak_allocated_mib': round(self.torch.cuda.max_memory_allocated()/1024**2, 1),
                   'cuda_reserved_mib': round(self.torch.cuda.memory_reserved()/1024**2, 1)}
        return target.getvalue(), metrics


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, engine, token):
        self.engine, self.token = engine, token
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_):
        pass  # Não registrar texto, referência nem corpos de requisições.

    def reply(self, status, body, content_type='application/json', headers=None):
        raw = json.dumps(body).encode() if isinstance(body, dict) else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        for name, value in (headers or {}).items():
            self.send_header(name, str(value))
        self.end_headers()
        self.close_connection = True
        self.wfile.write(raw)

    def allowed(self):
        # Clientes desktop não enviam Origin. Nenhum site/browser recebe acesso.
        expected_host = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Origin') or self.headers.get('Host') != expected_host:
            self.reply(403, {'error': 'client_not_allowed'})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        engine = self.server.engine
        if self.path in ('/health', '/startup/progress'):
            state = engine.status()
            self.reply(200 if self.path != '/health' or state['status'] == 'ready' else 503, state)
        elif self.path == '/profiles/'+engine.profile['id']:
            self.reply(200, {'id': engine.profile['id'], 'name': engine.profile['name']})
        else:
            self.reply(404, {'error': 'not_found'})

    def do_POST(self):
        if not self.allowed():
            return
        if self.path == '/shutdown':
            if not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+self.server.token):
                return self.reply(403, {'error': 'authentication_required'})
            if not self.server.engine.gate.acquire(blocking=False):
                return self.reply(409, {'error': 'busy'})
            try:
                self.reply(200, {'status': 'stopping'})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            finally:
                self.server.engine.gate.release()
            return
        if self.path != '/v1/audio/speech':
            return self.reply(404, {'error': 'not_found'})
        if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, {'error': 'json_required'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.reply(400, {'error': 'invalid_length'})
        if not 0 < size <= MAX_BODY:
            return self.reply(413, {'error': 'body_too_large'})
        try:
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            return self.reply(400, {'error': 'invalid_json'})
        engine = self.server.engine
        text = data.get('input')
        if data.get('voice') != engine.profile['id']:
            return self.reply(404, {'error': 'profile_unavailable'})
        if (data.get('model') != 'tts-1' or data.get('response_format') != 'wav'
                or data.get('language', 'pt') != 'pt'
                or not isinstance(text, str) or not 1 <= len(text.strip()) <= MAX_TEXT):
            return self.reply(422, {'error': 'unsupported_request'})
        if set(data)-{'model', 'voice', 'input', 'response_format', 'language'}:
            return self.reply(422, {'error': 'unsupported_parameters'})
        if engine.status()['status'] != 'ready':
            return self.reply(503, {'error': 'model_not_ready'})
        if not engine.gate.acquire(blocking=False):
            return self.reply(409, {'error': 'busy'})
        try:
            audio, metrics = engine.synthesize(text.strip())
        except Exception as error:
            # Sem repetir a síntese, trocar modelo/voz ou retornar texto em WAV.
            print(json.dumps({'event': 'generation_error', 'failure_type': type(error).__name__}), flush=True)
            return self.reply(500, {'error': 'generation_failed', 'failure_type': type(error).__name__})
        finally:
            engine.gate.release()
        self.reply(200, audio, 'audio/wav', {'X-Generation-Seconds': metrics['generation_seconds']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--checkpoint', required=True, type=Path)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--port', type=int, default=3901)
    parser.add_argument('--steps', type=int, choices=(8,16), default=16)
    parser.add_argument('--load-mode', choices=('sequential', 'mmap'), default='sequential')
    args = parser.parse_args()
    args.runtime.mkdir(parents=True, exist_ok=True)
    profile = json.loads(args.profile.read_text(encoding='utf-8'))
    token = secrets.token_urlsafe(32)
    engine = Engine(profile, args.source_root, args.checkpoint, args.runtime, args.steps,
                    sequential_load=args.load_mode == 'sequential')
    server = Server(('127.0.0.1', args.port), engine, token)
    state_path = args.runtime/'process.json'
    state_path.write_text(json.dumps({'pid': os.getpid(), 'port': server.server_port, 'shutdown_token': token}), encoding='utf-8')
    threading.Thread(target=engine.load, name='omnivoice-loader', daemon=True).start()
    print(json.dumps({'event': 'listening', 'port': server.server_port}), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        state_path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
