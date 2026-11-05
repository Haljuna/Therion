"""QProcess real de voz: partes WAV e cancelamento, sem microfone/reprodução."""
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
    parser.add_argument('--state-root',required=True,type=Path)
    parser.add_argument('--allow-online',action='store_true')
    args=parser.parse_args()
    if not args.allow_online:parser.error('Use --allow-online para sintetizar somente frases fictícias.')
    root=args.state_root.resolve()/('edge-qt-'+uuid.uuid4().hex);root.mkdir(parents=True)
    for variable in ('APPDATA','LOCALAPPDATA','TEMP','TMP'):
        folder=root/variable;folder.mkdir();os.environ[variable]=str(folder)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from therion.voice.speech_output import SpeechOutput
    app=QApplication([])
    service=SpeechOutput({'provider':'edge','online_allowed':True,
        'edge_python_path':str(args.python.resolve(strict=True)),'edge_voice':'pt-BR-AntonioNeural'})
    report={'status':'running','states':[],'parts':[],'errors':[],'playback_used':False,'microphone_used':False}
    service.changed.connect(lambda state:report['states'].append(state))
    def fail(message):
        report['errors'].append(message);report['status']='failed';service.shutdown();app.quit()
    service.failed.connect(fail)
    phase=['synthesis'];cancelled_at=[None]
    poll=QTimer();poll.setInterval(10)
    def check_retirement():
        if phase[0]!='cancelling':return
        elapsed=time.monotonic()-cancelled_at[0]
        if service.is_quiescent:
            report['retired_seconds']=round(elapsed,4)
            report['status']='completed' if elapsed<=2 and report['feedback_seconds']<=.5 and len(report['parts'])>=2 else 'failed'
            poll.stop();service.shutdown();app.quit()
        elif elapsed>2:
            fail('A árvore de voz não encerrou em dois segundos.')
    poll.timeout.connect(check_retirement)
    def cancel():
        phase[0]='cancelling';cancelled_at[0]=time.monotonic()
        service.stop();report['feedback_seconds']=round(time.monotonic()-cancelled_at[0],4)
        poll.start()
    def start_cancel():
        service.speak('Esta é outra frase fictícia para verificar o cancelamento da síntese online.')
        QTimer.singleShot(100,cancel)
    def record_parts():
        while service._audio_queue:
            path=service._audio_queue.pop(0)
            with wave.open(str(path)) as audio:
                if audio.getframerate()!=24000 or audio.getnframes()<=0:return fail('WAV inválido.')
                report['parts'].append({'frames':audio.getnframes(),'rate':audio.getframerate()})
        if not service._busy and phase[0]=='synthesis':
            phase[0]='next';QTimer.singleShot(50,start_cancel)
    # Inspecionar o áudio gerado em vez de acionar QSoundEffect.play.
    service._play_queued=record_parts
    text=('Este é um teste fictício do Therion. A reunião de exemplo é às 14:30 e o código é 42. '
          'Não envie mensagens nem altere configurações. Esta segunda parte verifica a geração de áudio por trechos. '
          'O texto e os números permanecem como foram escritos.')
    QTimer.singleShot(0,lambda:service.speak(text))
    QTimer.singleShot(65000,lambda:fail('Avaliação excedeu o tempo limite.'))
    app.exec()
    service.shutdown()
    report['process_quiescent']=service.is_quiescent
    path=root/'evaluation.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(path),'status':report['status'],'parts':len(report['parts']),
        'feedback_seconds':report.get('feedback_seconds'),'retired_seconds':report.get('retired_seconds')},ensure_ascii=False),flush=True)
    return 0 if report['status']=='completed' and report['process_quiescent'] else 1


if __name__=='__main__':sys.exit(main())
