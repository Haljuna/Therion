"""Desktop/Qt + Ollama + Kokoro reais, com texto fictício e destino WAV sem som.

Uma rodada de aquecimento não pontuada; ordem ABBA, mesmo pedido e sessões
novas. Mede disponibilidade do WAV, não percepção auditiva ou latência STT.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python',required=True,type=Path)
    parser.add_argument('--model-root',required=True,type=Path)
    parser.add_argument('--state-root',required=True,type=Path)
    parser.add_argument('--model',default='qwen3:4b')
    parser.add_argument('--endpoint',default='http://127.0.0.1:11435/api/chat')
    args=parser.parse_args()
    from therion.config.local import is_local_ollama_endpoint,_validate_config
    if not is_local_ollama_endpoint(args.endpoint):parser.error('Endpoint local obrigatório.')
    root=args.state_root.resolve()/('streaming-desktop-'+uuid.uuid4().hex);root.mkdir(parents=True)
    for variable in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        path=root/variable;path.mkdir();os.environ[variable]=str(path)
    vault=root/'vault';vault.mkdir()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from therion.interface.desktop import MainWindow
    from therion.memory.runtime import KnowledgeRuntime
    config=_validate_config({'ai':{'enabled':True,'model':args.model,'endpoint':args.endpoint,
        'timeout_seconds':180,'think':False},'agent':{'enabled':True,'protocol':'native',
        'context_tokens':8192,'output_tokens':4096,'think':False},
        'tts':{'enabled':True,'provider':'kokoro','voice':'alex_santa_c','streaming_prepare':False,
            'python_path':str(args.python.resolve(strict=True)),'model_root':str(args.model_root.resolve(strict=True))},
        'voice':{'model_path':None},'runtime':{'real_actions_enabled':False}})
    app=QApplication([])
    window=MainWindow(app,config,knowledge_runtime=KnowledgeRuntime(vault,root/'memory',lambda:config),
        config_loader=lambda:config,log_dir=str(root/'logs'))
    window.setWindowTitle('Therion — medição fictícia — sem áudio')
    service=window._speech_output;service.keep_warm=True
    report={'model':args.model,'endpoint':args.endpoint,'voice':'alex_santa_c',
        'protocol':'native','context_tokens':8192,'output_tokens':4096,'think':False,
        'microphone_used':False,'playback_used':False,'personal_configuration_loaded':False,
        'rounds':[],'errors':[],'passed':False,'limitations':[
            'Amostra pequena e repetição de prompt com cache; ordem ABBA reduz, mas não elimina, efeitos de ordem.',
            'WAV inspecionado substitui o dispositivo de áudio; não mede percepção, STT ou sessão acústica.',
            'Somente resposta textual sem ferramentas; não comprova desempenho de tarefas compostas.']}
    modes=[('warmup',False),('baseline',False),('prepared',True),('prepared',True),('baseline',False)]
    active=[None];index=[0];stage=['warming'];start=time.monotonic()
    text=('A cidade fictícia Aurora tem uma biblioteca perto da praça. '
          'O encontro de leitura está previsto para as 14:30. '
          'Os participantes podem levar um livro e compartilhar suas ideias. '
          'Esta descrição serve apenas para avaliar a voz do assistente em português.')
    command='Repita somente o texto entre aspas, sem introdução nem conclusão: “'+text+'”'
    def persist():
        (root/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def fail(message):
        if stage[0]=='failed':return
        report['errors'].append(message);stage[0]='failed';persist()
        window._conversation_mode=False;window._orchestrator.cancel_agent();service.release();app.quit()
    service.failed.connect(fail)
    original_prepare=service.prepare_prefix;original_commit=service.commit_prefix
    def prepare(prefix):
        value=original_prepare(prefix)
        if value and active[0] is not None:active[0]['prefix_at']=time.monotonic()-active[0]['start']
        return value
    def commit(value):
        accepted=original_commit(value)
        if active[0] is not None:active[0]['prefix_committed']=accepted
        return accepted
    service.prepare_prefix=prepare;service.commit_prefix=commit
    def sink():
        row=active[0]
        if row is None:return fail('Áudio sem rodada ativa.')
        if service._hold_audio:return fail('Áudio liberado antes da validação.')
        if window._processing or window._last_agent_response_status!='success':return fail('Áudio sem resultado público verificado.')
        while service._audio_queue:
            path=service._audio_queue.pop(0)
            with wave.open(str(path)) as audio:
                if audio.getnframes()<=0 or audio.getframerate()!=24000:return fail('WAV inválido.')
                row['parts'].append({'ready_seconds':round(time.monotonic()-row['start'],4),
                    'audio_seconds':audio.getnframes()/audio.getframerate()})
    service._play_queued=sink
    def next_round():
        if index[0]>=len(modes):
            window._conversation_mode=False;service.release();stage[0]='retiring';return
        mode,enabled=modes[index[0]];index[0]+=1
        window._orchestrator.clear_session()
        service.config['streaming_prepare']=enabled
        row={'mode':mode,'start':time.monotonic(),'parts':[],'prefix_committed':False}
        report['rounds'].append(row);active[0]=row;stage[0]='running'
        window._conversation_mode=True
        window._conversation_capture_generation=0
        window._conversation_capture_started_at=time.monotonic()-20
        window._on_voice_transcribed(0,command)
    def poll():
        if stage[0]=='warming' and service.is_ready:
            report['tts_warmup_seconds']=round(time.monotonic()-start,4);next_round()
        elif stage[0]=='running':
            row=active[0]
            if not window._processing and row.get('model_seconds') is None:
                row['model_seconds']=round(time.monotonic()-row['start'],4)
                row['status']=getattr(window,'_last_agent_response_status',None)
                row['message']=window._speech_text
                provider=getattr(window._orchestrator._agent_runtime,'provider',None)
                row['usage']=getattr(provider,'usage',{})
                persist()
                if row['status']!='success':return fail('Modelo não concluiu a rodada: '+str(row['status']))
            if row['parts'] and not service._busy and service._pending is None and not window._processing:
                row['total_seconds']=round(time.monotonic()-row.pop('start'),4)
                print(json.dumps({'mode':row['mode'],'model_seconds':row['model_seconds'],
                    'first_wav_seconds':row['parts'][0]['ready_seconds'],
                    'prefix_committed':row['prefix_committed']},ensure_ascii=False),flush=True)
                persist();active[0]=None;stage[0]='between';QTimer.singleShot(100,next_round)
            elif time.monotonic()-row['start']>240:fail('Rodada excedeu o tempo limite.')
        elif stage[0]=='retiring' and service.is_quiescent:
            report['passed']=all(row.get('status')=='success' and row['parts'] for row in report['rounds'])
            report['prepared_commits']=sum(row['prefix_committed'] for row in report['rounds'] if row['mode']=='prepared')
            persist();app.quit()
    timer=QTimer();timer.setInterval(10);timer.timeout.connect(poll);timer.start()
    QTimer.singleShot(0,service.warmup)
    QTimer.singleShot(900000,lambda:fail('Avaliação excedeu quinze minutos.'))
    window.show();app.exec()
    window._conversation_mode=False;window._orchestrator.cancel_agent()
    if window._command_worker is not None:window._command_worker.wait(3000)
    window._orchestrator.close();service.shutdown();window._quit_requested=True;window.close()
    report['process_quiescent']=service.is_quiescent;persist()
    print(json.dumps({'report':str(root/'evaluation.json'),'passed':report['passed'],
        'prepared_commits':report.get('prepared_commits'),'rounds':len(report['rounds']),
        'errors':report['errors'],'process_quiescent':report['process_quiescent']},ensure_ascii=False),flush=True)
    return 0 if report['passed'] and report['process_quiescent'] else 1


if __name__=='__main__':sys.exit(main())
