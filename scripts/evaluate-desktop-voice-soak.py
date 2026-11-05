"""Sessão Qt sintética com o perfil diário, STT/Ollama/Kokoro reais e sem som.

Não usa contas, configuração pessoal, microfone ou dispositivo de reprodução.
O destino de áudio é substituído por inspeção WAV; não é aceite acústico.
Use --seconds 90 para verificar o ensaio antes de --seconds 3600.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import queue
import sys
import time
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def source_hashes():
    paths = sorted((ROOT / 'therion').rglob('*.py'))
    paths += sorted((ROOT / 'therion/voice/voices').glob('*.npy'))
    paths += [Path(__file__), ROOT / 'scripts/voice_session_metrics.py', ROOT / 'scripts/pilot-hermes.py']
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--voice-python', required=True, type=Path)
    parser.add_argument('--voice-root', required=True, type=Path)
    parser.add_argument('--stt-model', required=True, type=Path)
    parser.add_argument('--seconds', type=int, required=True, choices=range(1, 7201))
    parser.add_argument('--memory-efficient', action='store_true', help='Comparação isolada; não altera o perfil pessoal.')
    args = parser.parse_args()
    # Reusar a fixture e os parâmetros aprovados, sem ler AppData pessoal.
    import importlib.util
    spec = importlib.util.spec_from_file_location('voice_soak_pilot', ROOT / 'scripts/pilot-hermes.py')
    pilot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pilot)
    root, vault, path, config = pilot.prepare('qwen3:4b', voice_python=args.voice_python,
        voice_root=args.voice_root, stt_model=args.stt_model)
    config['tts']['memory_efficient'] = args.memory_efficient
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QAccessible
    from PySide6.QtWidgets import QApplication
    from scripts.agent_resources import ResourceSampler, sample
    from scripts.voice_session_metrics import VoiceSessionMetrics
    from therion.interface.desktop import MainWindow
    from therion.memory.runtime import KnowledgeRuntime
    from therion.voice.transcription import VoiceTranscriptionService

    app = QApplication([])
    window = MainWindow(app, config, knowledge_runtime=KnowledgeRuntime(vault, root / 'memory', lambda: config),
        config_loader=lambda: config, log_dir=str(root / 'logs'))
    window.setWindowTitle('Therion — estabilidade sintética — sem áudio ou microfone')
    service = window._speech_output
    service.keep_warm = True
    metrics = VoiceSessionMetrics(window, root)
    metrics.system_sampler = ResourceSampler(root / 'voice-session-system.jsonl').start()
    report = {'pid': os.getpid(), 'root': str(root), 'requested_seconds': args.seconds,
        'model': 'qwen3:4b', 'voice': 'alex_santa_c', 'memory_efficient': args.memory_efficient,
        'streaming_prepare': False, 'synthetic': True, 'microphone': False, 'playback': False,
        'personal_configuration_loaded': False, 'source_start': source_hashes(),
        'rounds': [], 'errors': [], 'passed': False, 'acceptance': 'requires_review',
        'limits': ['Não exercita dispositivo físico, eco, captura nem percepção auditiva.',
            'Endpoint Ollama existente; nenhuma configuração do servidor é alterada.',
            'Memória estável depende da análise das séries, não apenas de tempo decorrido.']}
    state = {'phase': 'loading', 'started': time.monotonic(), 'round': None,
             'warm_started': None, 'next': 0, 'quit': False, 'transcriber': None}
    transcripts = queue.Queue()
    request = ('Busque nas notas Aurora, leia a fonte original e diga o código de conferência '
               'e a próxima etapa. Não envie mensagens.')
    def persist():
        (root / 'soak.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    def quit_normally():
        state['quit'] = True
        state['phase'] = 'closing'
        transcriber = state['transcriber']
        if transcriber is not None:
            transcriber.shutdown()
        state['quit_at'] = time.monotonic()
        persist()
        window._quit_application()
    def fail(reason):
        if state['quit']:
            return
        report['errors'].append(reason)
        print(json.dumps({'error': reason}, ensure_ascii=False), flush=True)
        quit_normally()
    service.failed.connect(fail)
    window._voice_service.load_failed.connect(fail)
    def sink():
        row = state['round']
        if row is None or state['phase'] not in ('input_audio', 'output_audio'):
            return fail('WAV sem etapa correspondente.')
        while service._audio_queue:
            audio_path = service._audio_queue.pop(0)
            with wave.open(str(audio_path), 'rb') as audio:
                if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 24000:
                    return fail('WAV fora do contrato PCM16 mono 24 kHz.')
                pcm = audio.readframes(audio.getnframes())
            if not pcm:
                return fail('WAV vazio.')
            if state['phase'] == 'input_audio':
                state['input_pcm'].append(pcm)
            else:
                row['output_frames'] += len(pcm) // 2
            audio_path.unlink(missing_ok=True)
    service._play_queued = sink
    def begin_round():
        row = {'number': len(report['rounds']) + 1, 'start_elapsed': time.monotonic() - state['warm_started'],
               'output_frames': 0, 'passed': False}
        report['rounds'].append(row)
        state.update(phase='input_audio', round=row, input_pcm=[], round_started=time.monotonic())
        state['previous_receipts']={item['call_id'] for item in window._orchestrator._get_agent_store().operations()}
        service.speak(request)
    def poll():
        try:
            tick()
        except Exception as error:
            fail(type(error).__name__ + ': ' + str(error))
    def tick():
        now = time.monotonic()
        if state['quit']:
            if now - state['quit_at'] > 20:
                report['errors'].append('Encerramento cooperativo excedeu vinte segundos.')
                app.exit(1)
            return
        if (root / 'STOP').exists():
            return fail('Interrompido pelo arquivo STOP da fixture.')
        if now - state['started'] > args.seconds + 420:
            return fail('Ensaio excedeu o limite global.')
        if state['phase'] == 'loading':
            if window._voice_service.state == 'ready' and service.is_ready:
                transcriber = VoiceTranscriptionService(window._voice_service.model)
                transcriber.transcribed.connect(lambda generation, text: transcripts.put(('ok', text)))
                transcriber.transcription_failed.connect(lambda generation, error: transcripts.put(('error', error)))
                state.update(transcriber=transcriber, warm_started=now)
                report['warmup_seconds'] = now - state['started']
                report['warm_started_unix'] = time.time()
                begin_round()
            elif now - state['started'] > 180:
                fail('STT/TTS não ficaram prontos em três minutos.')
            return
        if state['phase'] == 'between':
            if now - state['warm_started'] >= args.seconds:
                report['active_seconds'] = now - state['warm_started']
                return quit_normally()
            if now >= state['next']:
                begin_round()
            return
        row = state['round']
        if now - state['round_started'] > 240:
            return fail('Ciclo sintético excedeu quatro minutos.')
        if state['phase'] == 'input_audio' and service._pending is None and not service._busy:
            import numpy as np
            pcm = np.frombuffer(b''.join(state.pop('input_pcm')), dtype='<i2').astype(np.float32) / 32768
            if not len(pcm):
                return fail('Síntese não produziu entrada para STT.')
            pcm = np.interp(np.arange(round(len(pcm) * 16000 / 24000)) * 24000 / 16000,
                            np.arange(len(pcm)), pcm).astype(np.float32)
            state['phase'] = 'transcribing'
            if not state['transcriber'].transcribe_async(pcm, row['number']):
                fail('STT recusou ciclo sequencial.')
        elif state['phase'] == 'transcribing' and not transcripts.empty():
            status, text = transcripts.get_nowait()
            if status != 'ok' or not text.strip():
                return fail('STT rejeitou o áudio sintético: ' + str(text))
            row['transcript'] = text
            row['transcription_elapsed'] = now - state['round_started']
            state['phase'] = 'processing'
            window._input.setPlainText(text)
            window._send_command()
            if not window._processing:
                fail('Interface não iniciou o pedido transcrito.')
        elif state['phase'] == 'processing' and not window._processing:
            row['status'] = getattr(window, '_last_agent_response_status', None)
            row['message'] = window._speech_text
            receipts=window._orchestrator._get_agent_store().operations()
            row['new_receipts']=[{key:item[key] for key in ('call_id','tool','state','verified')}
                for item in receipts if item['call_id'] not in state['previous_receipts']]
            if (row['status'] != 'success' or 'PONTE-42' not in row['message']
                    or 'relatório' not in row['message'].casefold()):
                return fail('Resposta não satisfez o pedido fictício; inspecione a rodada.')
            if len(row['message']) > 2000:
                return fail('Resposta excedeu o limite de voz; não foi truncada.')
            state['phase'] = 'output_audio'
            window._listen_response()
        elif state['phase'] == 'output_audio' and not service._busy and service._pending is None:
            if not row['output_frames']:
                return fail('Resposta sem WAV.')
            row['seconds'] = now - state['round_started']
            row['passed'] = True
            print(json.dumps({'round': row['number'], 'seconds': round(row['seconds'], 3),
                'active_seconds': round(now - state['warm_started'], 3)}, ensure_ascii=False), flush=True)
            persist()
            state.update(phase='between', round=None, next=now + 5)
        if int(now - state['started']) % 10 == 0 and now - state.get('last_resources', 0) > 9:
            state['last_resources'] = now
            # A carga é cancelada se faltar margem; não altera modelos ou perfil para passar.
            resources = sample()
            if resources.get('commit_available_bytes', 2**64) < 800 * 1024**2:
                report['resource_stop'] = resources
                fail('Margem de commit abaixo de 800 MiB; interrompido sem mudar o perfil.')

    print('Fixture de estabilidade:', root, flush=True)
    persist()
    with ExitStack() as guards:
        # Barreiras de teste: uma regressão no harness nunca liga dispositivos.
        guards.enter_context(patch('therion.voice.speech_output.QSoundEffect.play', side_effect=AssertionError('Reprodução proibida no ensaio')))
        guards.enter_context(patch('therion.voice.capture.AudioCaptureService.start', side_effect=AssertionError('Microfone proibido no ensaio')))
        timer = QTimer()
        timer.setInterval(50)
        timer.timeout.connect(poll)
        timer.start()
        window.show()
        service.warmup()
        window._voice_service.load()
        code = app.exec()
        timer.stop()
        transcriber = state['transcriber']
        if transcriber is not None:
            transcriber.shutdown()
            if transcriber._thread is not None:
                transcriber._thread.join(timeout=10)
        service.shutdown()
        report.update(exit_code=code, native_platform=app.platformName(), accessibility_active=QAccessible.isActive(),
            source_unchanged=source_hashes() == report['source_start'], tts_quiescent=service.is_quiescent,
            stt_quiescent=transcriber is None or transcriber.is_quiescent,
            voice_loader_quiescent=window._voice_service.is_quiescent)
        report['metrics'] = metrics.close()
        report['passed'] = (code == 0 and not report['errors'] and report['source_unchanged']
            and report['tts_quiescent'] and report['stt_quiescent'] and report['voice_loader_quiescent']
            and report.get('active_seconds', 0) >= args.seconds and bool(report['rounds'])
            and all(row['passed'] for row in report['rounds']))
        persist()
    print(json.dumps({'report': str(root / 'soak.json'), 'passed': report['passed'],
        'rounds': len(report['rounds']), 'errors': report['errors']}, ensure_ascii=False), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
