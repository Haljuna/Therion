"""Teste manual isolado de microfone -> Parakeet -> repeticao pelo Jarvis."""
import argparse
import io
import json
import os
from pathlib import Path
import threading
import time
from urllib.request import build_opener, ProxyHandler, Request
import wave

import numpy as np
import sounddevice as sd
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

FOLDER=Path(__file__).resolve().parents[2]/'tmp/asr-comparison-20261020/manual-gateway'


def request(path,body=None,kind='application/json',timeout=90,headers=None):
    client=build_opener(ProxyHandler({}))
    with client.open(Request('http://127.0.0.1:3902'+path,data=body,
            headers={'Content-Type':kind,**(headers or {})}),timeout=timeout) as response:
        return response.read()


def encode_audio(data):
    output=io.BytesIO()
    with wave.open(output,'wb') as audio:
        audio.setparams((1,2,16000,0,'NONE','not compressed'))
        audio.writeframes(np.clip(data,-32768,32767).astype('<i2').tobytes())
    return output.getvalue()


def transcribe(raw):
    body=(b'--manual\r\nContent-Disposition: form-data; name="model"\r\n\r\nparakeet\r\n'
        b'--manual\r\nContent-Disposition: form-data; name="file"; filename="microphone.wav"\r\n'
        b'Content-Type: audio/wav\r\n\r\n'+raw+b'\r\n--manual--\r\n')
    return json.loads(request('/v1/audio/transcriptions',body,'multipart/form-data; boundary=manual'))


class Events(QObject):
    message=Signal(str)
    done=Signal()


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Teste isolado — Parakeet + Jarvis')
        self.resize(680,440)
        self.stream=None
        self.frames=[]
        self.busy=False
        self.closed=False
        self.cancel=threading.Event()
        self.events=Events()
        self.events.message.connect(self.show_message)
        self.events.done.connect(self.finish)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Microfone → transcrição → Jarvis repete o que entendeu.\nSem IA e sem executar comandos. Grava somente após seu clique.'))
        self.devices=QComboBox()
        self.devices.addItem('Microfone padrão do Windows',None)
        for index,device in enumerate(sd.query_devices()):
            if device['max_input_channels']>0:self.devices.addItem(device['name'],index)
        layout.addWidget(self.devices)
        self.status=QLabel('Preparando Parakeet…')
        layout.addWidget(self.status)
        self.output=QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.record=QPushButton('Gravar frase (máximo 20 segundos)')
        self.record.setEnabled(False)
        self.record.clicked.connect(self.toggle)
        layout.addWidget(self.record)
        self.stop=QPushButton('Cancelar / parar áudio')
        self.stop.clicked.connect(self.cancel_current)
        layout.addWidget(self.stop)
        self.timer=QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.stop_recording)
        self.poll=QTimer(self)
        self.poll.timeout.connect(self.check_ready)
        self.poll.start(1000)
        FOLDER.mkdir(parents=True,exist_ok=True)
        (FOLDER/'client-ready.json').write_text(json.dumps({'pid':os.getpid(),'microphone_active':False,
            'mode':'stt_then_echo','ai_enabled':False}),encoding='utf-8')

    def check_ready(self):
        try:
            health=json.loads(request('/health',timeout=.5))
            if health.get('status')=='ready':
                self.poll.stop()
                self.status.setText('Pronto. Clique em Gravar frase, fale e clique em Parar e testar.')
                self.record.setEnabled(True)
        except Exception:pass

    def toggle(self):
        if self.stream is not None:return self.stop_recording()
        if self.busy:return
        try:
            self.frames=[]
            self.cancel.clear()
            self.stream=sd.InputStream(samplerate=16000,channels=1,dtype='int16',
                device=self.devices.currentData(),callback=self.capture)
            self.stream.start()
            self.record.setText('Parar e testar')
            self.devices.setEnabled(False)
            self.status.setText('Gravando… Clique em Parar e testar ao terminar.')
            self.timer.start(20000)
        except Exception as error:
            self.release_microphone()
            self.status.setText('Não consegui abrir o microfone: '+str(error))

    def capture(self,data,frames,time_info,status):
        # Bound the buffer even if the GUI timer is delayed.
        if sum(len(frame) for frame in self.frames)<320000:self.frames.append(data.copy())

    def release_microphone(self):
        self.timer.stop()
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream=None

    def stop_recording(self):
        if self.stream is None:return
        self.release_microphone()
        self.record.setText('Gravar frase (máximo 20 segundos)')
        if not self.frames:return self.finish()
        data=np.concatenate(self.frames).reshape(-1)[:320000]
        self.frames=[]
        if len(data)<3200:return self.finish()
        self.busy=True
        self.record.setEnabled(False)
        self.status.setText('Transcrevendo…')
        threading.Thread(target=self.run,args=(encode_audio(data),),daemon=True).start()

    def run(self,raw):
        try:
            started=time.perf_counter()
            result=transcribe(raw)
            stt=time.perf_counter()-started
            if self.cancel.is_set():return
            text=result['text'].strip()
            self.events.message.emit(f'Transcrição ({stt:.2f} s): {text or "[sem fala reconhecida]"}')
            if not text:return
            self.events.message.emit('Gerando a repetição com Jarvis…')
            started=time.perf_counter()
            voice=request('/v1/audio/speech',json.dumps({'model':'tts-1','voice':'120f734a',
                'input':text,'language':'pt','response_format':'wav'}).encode())
            tts=time.perf_counter()-started
            if self.cancel.is_set():return
            with wave.open(io.BytesIO(voice)) as audio:
                if audio.getsampwidth()!=2:raise ValueError('Formato de áudio inesperado')
                rate=audio.getframerate()
                samples=np.frombuffer(audio.readframes(audio.getnframes()),dtype='<i2').reshape(-1,audio.getnchannels())
            self.events.message.emit(f'Voz pronta ({tts:.2f} s). Reproduzindo…')
            sd.play(samples,samplerate=rate)
            while sd.get_stream().active:
                if self.cancel.wait(.05):
                    sd.stop()
                    break
            if not self.cancel.is_set():self.events.message.emit('Teste concluído. Pode gravar outra frase.')
        except Exception as error:
            if not self.cancel.is_set():self.events.message.emit('Falha no teste: '+str(error))
        finally:
            if not self.closed:self.events.done.emit()

    def show_message(self,text):
        self.output.append(text)
        self.status.setText(text)

    def finish(self):
        self.busy=False
        self.record.setEnabled(not self.poll.isActive())
        self.devices.setEnabled(True)

    def cancel_current(self):
        self.cancel.set()
        self.release_microphone()
        self.frames=[]
        sd.stop()
        self.record.setText('Gravar frase (máximo 20 segundos)')
        self.status.setText('Cancelado. Aguardando a chamada em andamento terminar.' if self.busy else 'Cancelado. Pode gravar novamente.')
        if not self.busy:self.finish()

    def closeEvent(self,event):
        self.closed=True
        self.cancel_current()
        event.accept()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--self-check',action='store_true')
    args=parser.parse_args()
    app=QApplication([])
    window=Window()
    if args.self_check:
        assert window.stream is None and not window.record.isEnabled()
        window.close()
        print('Interface criada sem abrir o microfone; contrato de audio pronto.')
        return
    window.show()
    app.exec()
    # Stop only the experimental gateway; leave Jarvis and Ollama services alone.
    try:
        state=json.loads((FOLDER/'gateway-process.json').read_text())
        request('/shutdown',b'{}',timeout=2,headers={'Authorization':'Bearer '+state['shutdown_token']})
    except Exception:pass


if __name__=='__main__':main()
