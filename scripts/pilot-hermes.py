"""Piloto presencial do runtime, com cofre e configurações fictícios.

Uso: .venv/Scripts/python.exe scripts/pilot-hermes.py
--smoke testa busca/leitura com o modelo real; --ui-check exercita abrir/sair.
Não carrega configuração, credenciais, histórico ou perfil de voz pessoais.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import uuid

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def prepare(model, *, voice_python=None, voice_root=None, stt_model=None, streaming_voice=False):
    voice=any(value is not None for value in (voice_python,voice_root,stt_model))
    if voice:
        if not all(value is not None for value in (voice_python,voice_root,stt_model)):
            raise ValueError('Informe Python, pasta Kokoro e modelo STT locais juntos.')
        voice_python,voice_root,stt_model=map(lambda path:Path(path).resolve(strict=True),(voice_python,voice_root,stt_model))
        if (not voice_python.is_file() or
                not all((voice_root/name).is_file() for name in ('kokoro-v1.0.onnx','voices-v1.0.bin')) or
                not all((stt_model/name).is_file() for name in ('config.json','model.bin','tokenizer.json','vocabulary.txt'))):
            raise ValueError('Arquivos locais de voz ausentes; nenhuma dependência será baixada.')
    elif streaming_voice:
        raise ValueError('Pré-síntese exige os caminhos locais de voz.')
    base = Path(os.environ.get('THERION_TEST_ROOT', str(PROJECT / 'tmp')))
    root = base / 'hermes-pilots' / uuid.uuid4().hex
    root.mkdir(parents=True)
    for variable in ('APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        folder = root / variable
        folder.mkdir()
        os.environ[variable] = str(folder)
    vault = root / 'vault'
    notes = vault / '10 - Projetos' / 'Therion'
    notes.mkdir(parents=True)
    (notes / 'Aurora.md').write_text(
        '# Aurora — dados fictícios\n\nO código de conferência é PONTE-42.\n'
        'A próxima etapa é revisar o relatório, sem enviar e-mails.\n', encoding='utf-8')
    (notes / 'Roteiro.md').write_text(
        '# Roteiro do piloto\n\n1. Buscar e ler Aurora.\n'
        '2. Perguntar qual é o código e a próxima etapa.\n'
        '3. Consultar uma informação inexistente e conferir a limitação.\n'
        '4. Iniciar uma resposta e usar Parar.\n'
        '5. Abrir Capacidades para conferir estados e recibos.\n', encoding='utf-8')
    documents = root / 'documents'
    documents.mkdir()
    config = {
        'ai': {'enabled': True, 'model': model, 'endpoint': 'http://127.0.0.1:11435/api/chat',
               'timeout_seconds': 180, 'think': False},
        'agent': {'enabled': True, 'protocol': 'native', 'timeout_seconds': 180,
                  'context_tokens': 8192, 'output_tokens': 4096, 'think': False,
                  'documents_enabled': True, 'document_read_roots': [str(documents)],
                  'document_write_roots': [str(documents)]},
        'tts': {'enabled': False}, 'calendar': {'enabled': False},
        'runtime': {'real_actions_enabled': False},
        'knowledge_access': {'read_all': True, 'supervised_memory': False,
            'authorization': 'piloto-ficticio-' + root.name,
            'expires_at': (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(), 'revision': 1},
    }
    if voice:
        config['tts']={'enabled':True,'provider':'kokoro','voice':'alex_santa_c',
            'python_path':str(voice_python),'model_root':str(voice_root),
            'online_allowed':False,'warm_on_start':False,'streaming_prepare':streaming_voice is True}
        config['voice']={'model_path':str(stt_model)}
        os.environ['HF_HUB_OFFLINE']='1'
        os.environ['TRANSFORMERS_OFFLINE']='1'
    from therion.config.local import save_config, load_config
    path = root / 'config.json'
    save_config(config, path)
    return root, vault, path, load_config(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='qwen3:4b')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--smoke-followup', action='store_true', help='Testa também ausência de senha no turno seguinte.')
    mode.add_argument('--ui-check', action='store_true')
    parser.add_argument('--voice-python',type=Path)
    parser.add_argument('--voice-root',type=Path)
    parser.add_argument('--stt-model',type=Path)
    parser.add_argument('--streaming-voice',action='store_true',help='Experimento de pré-síntese local, somente nesta fixture.')
    parser.add_argument('--measure-session',action='store_true',help='Mede estados e memória da fixture, sem registrar falas.')
    args = parser.parse_args()
    if (args.smoke or args.smoke_followup) and any((args.voice_python,args.voice_root,args.stt_model,args.streaming_voice)):
        parser.error('Voz é avaliada pela interface; use os caminhos com o piloto interativo ou --ui-check.')
    try:
        root, vault, path, config = prepare(args.model,voice_python=args.voice_python,voice_root=args.voice_root,
            stt_model=args.stt_model,streaming_voice=args.streaming_voice)
    except (ValueError,OSError) as error:parser.error(str(error))
    if args.measure_session and not config['tts']['enabled']:parser.error('Medição da sessão exige piloto de voz local.')
    from therion.config.local import load_config, save_config
    from therion.memory.runtime import KnowledgeRuntime
    loader = lambda: load_config(path)
    writer = lambda value: save_config(value, path)
    knowledge = KnowledgeRuntime(vault, root / 'memory', loader, config_writer=writer)
    info = {'root': str(root), 'vault': str(vault), 'config': str(path),
            'model': args.model, 'personal_configuration_loaded': False,
            'online_services_enabled': False, 'microphone_or_playback_started_at_startup': False,
            'local_voice_enabled':config['tts']['enabled'],
            'streaming_voice_enabled':config['tts'].get('streaming_prepare') is True,
            'session_metrics_enabled':args.measure_session}
    (root / 'pilot.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Piloto isolado:', root, flush=True)
    if args.smoke or args.smoke_followup:
        from therion.core.orchestrator import Orchestrator
        from therion.core.ai_core import AICore
        from therion.core.ai_provider_ollama import OllamaProvider
        from dataclasses import asdict
        import time
        core = AICore(provider=OllamaProvider(model=args.model, timeout=180,
                      endpoint=config['ai']['endpoint'], think=False), available_intents=[])
        host = Orchestrator(simulate=True, vault_root=str(vault), knowledge_runtime=knowledge,
            ai_core=core, agent_config=config['agent'], agent_state_root=root / 'agent', log_dir=str(root / 'logs'))
        started = time.monotonic()
        try:
            result = host.process_command('Busque nas notas Aurora e leia a fonte original. '
                'Qual é o código de conferência e a próxima etapa? Cite a fonte consultada.')
            events = [asdict(event) for event in host.agent_events()]
            receipts = host._get_agent_store().operations()
            report = {'status': result.status, 'message': result.message, 'receipts': receipts,
                      'seconds': round(time.monotonic() - started, 3), 'events': events}
            # Conferir o conteúdo da resposta e evidência de leitura, além do estado.
            report['passed'] = (result.status in ('success', 'completed')
                and 'PONTE-42' in result.message and 'relatório' in result.message.casefold()
                and any(row['tool'] == 'read_source' and row['state'] == 'success'
                        and row['verified'] for row in receipts))
            if args.smoke_followup and report['passed']:
                followup_started = time.monotonic()
                second = host.process_command('Qual é a senha de acesso do projeto Aurora?')
                report['followup'] = {'status': second.status, 'message': second.message,
                    'seconds': round(time.monotonic() - followup_started, 3),
                    'receipts': host._get_agent_store().operations(),
                    'events': [asdict(event) for event in host.agent_events()]}
                from scripts.pilot_checks import password_followup_checks
                report['followup'].update(password_followup_checks(second.status,second.message,
                    receipts,report['followup']['receipts'],report['followup']['events']))
                report['passed'] = report['passed'] and report['followup']['passed']
            (root / 'smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
            print(json.dumps({key: report[key] for key in ('passed', 'status', 'message', 'seconds')}, ensure_ascii=False), flush=True)
            if 'followup' in report:
                print(json.dumps({key: value for key, value in report['followup'].items() if key not in ('receipts','events')}, ensure_ascii=False), flush=True)
            return 0 if report['passed'] else 1
        finally:
            host.close()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from therion.interface.desktop import MainWindow
    app = QApplication([sys.argv[0]])
    window = MainWindow(app, config, knowledge_runtime=knowledge,
        config_loader=loader, config_writer=writer, log_dir=str(root / 'logs'))
    metrics=None
    if args.measure_session:
        from scripts.voice_session_metrics import VoiceSessionMetrics
        from scripts.agent_resources import ResourceSampler
        metrics=VoiceSessionMetrics(window,root)
        metrics.system_sampler=ResourceSampler(root/'voice-session-system.jsonl').start()
    voice_enabled=config['tts']['enabled']
    window.setWindowTitle('Therion — PILOTO HERMES 4 — voz local fictícia' if voice_enabled else
        'Therion — PILOTO HERMES 3 — leitura verificável')
    notice=('Voz local Alex/Santa C disponível. Ouvir reproduz a resposta; Conversar inicia o microfone após sua escolha. '
        'Use somente dados fictícios. Contas e integrações externas desligadas. ' if voice_enabled else
        'Voz, contas e integrações externas desligadas. ')
    window._append('Therion', 'Piloto com dados fictícios. Núcleo de ferramentas e documentos de teste ativos. '
        +notice+'Comece com: '
        '“Busque nas notas Aurora, leia a fonte original e diga o código e a próxima etapa.” '
        'Para sair completamente, use Sair no menu da bandeja.')
    window.show()
    info.update(process_id=os.getpid(),window_title=window.windowTitle(),window_visible_at_startup=window.isVisible())
    (root / 'pilot.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.ui_check:
        QTimer.singleShot(1500, window._quit_application)
    result = app.exec()
    if metrics is not None:metrics.close()
    info['ui_exit_code'] = result
    (root / 'pilot.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    sys.exit(main())
