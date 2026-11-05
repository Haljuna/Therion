"""Pré-síntese Kokoro real: retenção, validação e descarte; sem tocar áudio."""
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
    args=parser.parse_args()
    root=args.state_root.resolve()/('streaming-voice-'+uuid.uuid4().hex);root.mkdir(parents=True)
    for variable in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        folder=root/variable;folder.mkdir();os.environ[variable]=str(folder)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from therion.voice.speech_output import SpeechOutput
    from therion.voice.stream_prefix import first_sentence
    app=QApplication([])
    service=SpeechOutput({'provider':'kokoro','streaming_prepare':True,
        'python_path':str(args.python.resolve(strict=True)),
        'model_root':str(args.model_root.resolve(strict=True)),'voice':'alex_santa_c'})
    report={'passed':False,'playback_used':False,'microphone_used':False,'parts':[],
        'errors':[],'profile':'alex_santa_c','online_services_enabled':False}
    phase=['preparing'];started=time.monotonic();commit_at=[None];cancel_at=[None]
    text=('Esta é uma reunião fictícia. A próxima etapa é revisar o relatório às 14:30. '
          'O código de conferência é 42. Nenhuma mensagem deve ser enviada. '
          'Esta parte final testa a geração de voz depois da validação da resposta.')
    prefix=first_sentence(text)
    if prefix is None:raise ValueError('A frase fictícia não produziu prefixo.')
    def fail(message):
        report['errors'].append(message);phase[0]='failed';service.shutdown();app.quit()
    service.failed.connect(fail)
    def sink():
        if service._hold_audio:return fail('Áudio chegou ao destino antes da validação.')
        while service._audio_queue:
            path=service._audio_queue.pop(0)
            with wave.open(str(path)) as audio:
                if audio.getnframes()<=0 or audio.getnchannels()!=1:return fail('WAV inválido.')
                report['parts'].append({'frames':audio.getnframes(),'rate':audio.getframerate(),
                    'seconds_after_commit':round(time.monotonic()-commit_at[0],4)})
    service._play_queued=sink
    def poll():
        if phase[0]=='preparing' and service._pending is None and service._audio_queue:
            report['prepared_seconds']=round(time.monotonic()-started,4)
            report['held_parts']=len(service._audio_queue)
            report['released_before_validation']=len(report['parts'])
            commit_at[0]=time.monotonic();phase[0]='committed'
            if not service.commit_prefix(text):return fail('Prefixo não correspondeu à resposta validada.')
        elif phase[0]=='committed' and not service._busy and service._pending is None:
            if len(report['parts'])<2:return fail('O restante não foi sintetizado.')
            phase[0]='rejecting'
            if not service.prepare_prefix(prefix):return fail('Pré-síntese indisponível.')
        elif phase[0]=='rejecting' and service._pending is None and service._audio_queue:
            old_folder=service.folder;count=len(report['parts'])
            report['mismatch_rejected']=not service.commit_prefix('Não confirmei essa ação.')
            report['rejected_audio_removed']=not old_folder.exists() and count==len(report['parts'])
            phase[0]='cancelling';service.prepare_prefix(prefix);cancel_at[0]=time.monotonic()
            service.stop();report['cancel_feedback_seconds']=round(time.monotonic()-cancel_at[0],4)
            service.release()
        elif phase[0]=='cancelling':
            elapsed=time.monotonic()-cancel_at[0]
            if service.is_quiescent:
                report['quiescent_seconds']=round(elapsed,4)
                report['passed']=(report['released_before_validation']==0 and report['mismatch_rejected']
                    and report['rejected_audio_removed'] and elapsed<=2 and report['cancel_feedback_seconds']<=.5)
                phase[0]='finished';app.quit()
            elif elapsed>2:fail('Processo próprio não encerrou em dois segundos.')
    timer=QTimer();timer.setInterval(10);timer.timeout.connect(poll);timer.start()
    QTimer.singleShot(0,lambda:service.prepare_prefix(prefix))
    QTimer.singleShot(150000,lambda:fail('Avaliação excedeu o tempo limite.'))
    app.exec();service.shutdown()
    report['process_quiescent']=service.is_quiescent
    path=root/'evaluation.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(path),**report},ensure_ascii=False),flush=True)
    return 0 if report['passed'] and report['process_quiescent'] else 1


if __name__=='__main__':sys.exit(main())
