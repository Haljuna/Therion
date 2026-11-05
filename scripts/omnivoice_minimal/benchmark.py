"""Mede prontidão e duas sínteses de controle, sem repetir POST após falha."""
import argparse
import array
import io
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, ProxyHandler, Request
import wave


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=3901)
    parser.add_argument('--runtime', required=True, type=Path)
    args = parser.parse_args()
    client = build_opener(ProxyHandler({}))
    base = f'http://127.0.0.1:{args.port}'
    report = {'port': args.port, 'synthetic_text': 'Olá, Marcus. Estou pronto para ajudar.', 'cases': []}
    started = time.monotonic()
    while time.monotonic()-started < 240:
        try:
            with client.open(base+'/startup/progress', timeout=10) as response:
                state = json.load(response)
            print(json.dumps({'status':state['status'], 'phase':state.get('phase'),
                              'uptime_seconds':state.get('uptime_seconds')}), flush=True)
            if state['status'] in ('ready','error'):
                report['startup'] = state
                break
        except (URLError, TimeoutError):
            pass
        time.sleep(5)
    else:
        report['startup'] = {'status': 'timeout'}
    if report['startup']['status'] == 'ready':
        for repeat in range(2):
            request = Request(base+'/v1/audio/speech', data=json.dumps({
                'model':'tts-1', 'voice':'120f734a', 'input':report['synthetic_text'],
                'language':'pt', 'response_format':'wav'}).encode(),
                headers={'Content-Type':'application/json'})
            started = time.perf_counter()
            try:
                with client.open(request, timeout=120) as response:
                    assert response.headers.get_content_type() == 'audio/wav'
                    raw = response.read(10_000_001)
                if len(raw) > 10_000_000:
                    raise ValueError('Áudio acima do limite')
                with wave.open(io.BytesIO(raw)) as audio:
                    duration = audio.getnframes()/audio.getframerate()
                    rate, channels, width = audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
                    pcm = array.array('h', audio.readframes(audio.getnframes()))
                    assert 0.2 < duration < 30 and rate == 24000 and channels == 1 and width == 2
                    rms = (sum(value*value for value in pcm)/len(pcm))**0.5/32768
                    assert rms > 0.0001
                output = args.runtime/f'jarvis-control-{repeat}.wav'
                output.write_bytes(raw)
                with client.open(base+'/health', timeout=10) as response:
                    metrics = json.load(response).get('last_generation', {})
                report['cases'].append({'repeat':repeat, 'request_seconds':round(time.perf_counter()-started, 4),
                    'duration':round(duration,3), 'sample_rate':rate, 'rms':round(rms,5), 'bytes':len(raw), **metrics})
            except (HTTPError, URLError, TimeoutError, ValueError, AssertionError) as error:
                if isinstance(error, HTTPError):
                    failure = {'http_status':error.code}
                    error.close()
                else:
                    failure = {'failure_type':type(error).__name__}
                report['cases'].append({'repeat':repeat, **failure})
                break
            finally:
                (args.runtime/'benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (args.runtime/'benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)


if __name__ == '__main__':
    main()
