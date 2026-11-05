"""Saída de voz em processo próprio, com provider explícito e cancelamento."""
import json
import shutil
import tempfile
import os
import math
import threading
import time
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtCore import QProcess as NativeQProcess


class SpeechOutput(QObject):
    changed = Signal(str)
    failed = Signal(str)
    warmed = Signal()
    completed = Signal()
    measured = Signal(dict)
    level_changed = Signal(float)
    _envelope_ready = Signal(int, str, object)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.process = None
        self._retiring_processes=[]
        self._process_trees={}
        self._retiring_trees=[]
        self.folder = None
        self.generation = 0
        self.is_ready = False
        self.state = 'idle'
        self._pending = None
        self._busy = False
        self._buffer = b''
        self._playing = False
        self._audio_queue = []
        self._next_part = 0
        self._active_audio = None
        self._audio_seconds = {}
        self._playback_seconds = 120.0
        self._held_prefix = None
        self._hold_audio = False
        self._tail_text = None
        self.sound = QSoundEffect(self)
        self.sound.playingChanged.connect(self._playing_changed)
        self.sound.statusChanged.connect(self._sound_status)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._timeout)
        self.playback_timer = QTimer(self)
        self.playback_timer.setSingleShot(True)
        self.playback_timer.timeout.connect(self._playback_timeout)
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self.release)
        self.keep_warm = False
        self.level = 0.0
        self._meter_enabled = False
        self._envelope = ()
        self._envelope_started = None
        self._envelope_ready.connect(self._accept_envelope)
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(25)
        self._level_timer.timeout.connect(self._tick_level)

    def set_meter_enabled(self, enabled):
        self._meter_enabled = bool(enabled)
        if not enabled:
            self._reset_level()

    def _reset_level(self):
        self._level_timer.stop()
        self._envelope = ()
        self._envelope_started = None
        self.level = 0.0
        self.level_changed.emit(0.0)

    def _analyze_envelope(self, path):
        if not self._meter_enabled:
            return
        generation = self.generation
        def analyze():
            from .envelope import wav_envelope
            try:
                values = wav_envelope(path)
            except Exception:
                values = ()
            try:
                self._envelope_ready.emit(generation, str(path), values)
            except RuntimeError:
                pass  # QObject já encerrado; o trabalho não possui o áudio.
        threading.Thread(target=analyze, daemon=True, name='therion-audio-envelope').start()

    def _accept_envelope(self, generation, path, values):
        if (self._meter_enabled and generation == self.generation
                and self._active_audio is not None and str(self._active_audio) == path):
            self._envelope = values

    def _tick_level(self):
        if not self.sound.isPlaying() or self._envelope_started is None:
            self.level = 0.0
        else:
            index = int((time.monotonic()-self._envelope_started)/.025)
            self.level = self._envelope[index] if index < len(self._envelope) else 0.0
        self.level_changed.emit(self.level)

    @property
    def is_quiescent(self):
        self._retiring_processes=[process for process in self._retiring_processes if process.state()!=QProcess.NotRunning]
        for tree in list(self._retiring_trees):
            if tree.is_quiescent:tree.close();self._retiring_trees.remove(tree)
        return self.process is None and not self._retiring_processes and not self._retiring_trees and not self._playing

    def _own_process(self,process):
        if os.name!='nt' or not isinstance(process,NativeQProcess) or process is not self.process:return
        try:
            from .process_tree import OwnedProcessTree
            if process not in self._process_trees:self._process_trees[process]=OwnedProcessTree(int(process.processId()))
            else:self._process_trees[process].capture()
        except (OSError,ValueError):
            process.closeWriteChannel();process.kill()
            self.failed.emit('Não consegui acompanhar o processo de voz com segurança. A síntese foi interrompida.')

    def _state(self, value):
        self.state = value
        self.changed.emit(value)

    def _playing_changed(self):
        if self.sound.isPlaying():
            self._playing = True
            if self._meter_enabled:
                self._envelope_started = time.monotonic()
                self._level_timer.start()
            if self._active_audio is not None:
                self.playback_timer.start(int((self._playback_seconds + 10) * 1000))
        elif self._playing:
            self._reset_level()
            self.playback_timer.stop()
            self._playing = False
            self.sound.setSource(QUrl())
            if self._active_audio is not None:
                try:
                    self._active_audio.unlink(missing_ok=True)
                except OSError:
                    pass
                self._active_audio = None
            if self._audio_queue:
                self._play_queued()
            elif self._busy:
                self._state('synthesizing')
            else:
                self._clear_audio()
                self._state('idle')
                self._schedule_release()
                self.completed.emit()

    def _sound_status(self):
        if self.sound.status() == QSoundEffect.Error:
            self.stop()
            self.failed.emit('Não foi possível reproduzir a voz. Verifique a saída de áudio.')

    def warmup(self):
        self.idle_timer.stop()
        online=self.config.get('provider','kokoro')=='edge'
        studio=self.config.get('provider')=='voicestudio'
        if online and self.config.get('online_allowed') is not True:
            self.release()
            self.failed.emit('A voz online está desabilitada. Autorize o processamento de texto online antes de usar Edge TTS.')
            return False
        if self.process is not None:
            if self.is_ready:
                self.warmed.emit()
            return True
        root = Path(self.config.get('model_root', ''))
        python_field='voicestudio_python_path' if studio else ('edge_python_path' if online else 'python_path')
        python = Path(self.config.get(python_field, ''))
        from .providers import EDGE_VOICES, is_voicestudio_endpoint, is_voicestudio_voice
        if studio:
            valid=(python.is_file() and is_voicestudio_endpoint(self.config.get('voicestudio_endpoint'))
                   and is_voicestudio_voice(self.config.get('voicestudio_voice')))
        elif online:
            valid=python.is_file() and self.config.get('edge_voice','pt-BR-AntonioNeural') in EDGE_VOICES
        else:
            valid=(self.config.get('provider','kokoro')=='kokoro' and python.is_file()
                and all((root/name).is_file() for name in ('kokoro-v1.0.onnx','voices-v1.0.bin')))
        if not valid:
            self.failed.emit('VoiceStudio local não está configurado.' if studio else
                            ('Edge TTS não está configurado.' if online else 'Kokoro não está configurado ou seus arquivos estão ausentes.'))
            return False
        process = QProcess(self)
        self.process = process
        self._buffer = b''
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.readyReadStandardError.connect(lambda: process.readAllStandardError())
        process.started.connect(lambda:self._own_process(process))
        process.finished.connect(lambda code, status: self._exited(process, code))
        process.errorOccurred.connect(lambda error: self._process_error(process))
        process.setProgram(str(python))
        if studio:
            arguments=[str(Path(__file__).with_name('voicestudio_worker.py')), '--serve',
                       '--endpoint', self.config['voicestudio_endpoint'], '--voice', self.config['voicestudio_voice']]
        elif online:
            arguments=[str(Path(__file__).with_name('edge_worker.py')), '--serve','--allow-online',
                       '--voice',self.config.get('edge_voice','pt-BR-AntonioNeural')]
        else:
            arguments=[str(Path(__file__).with_name('kokoro_worker.py')), '--serve', '--root', str(root),
                       '--voice', self.config.get('voice', 'pm_alex')]
            if self.config.get('memory_efficient') is True:arguments.append('--memory-efficient')
        process.setArguments(arguments)
        self._state('warming')
        self.timer.start(120000)
        process.start()
        return True

    def prepare_prefix(self, text):
        """Pré-síntese local (Kokoro ou VoiceStudio no loopback); nenhum áudio toca antes de commit_prefix."""
        if (self.config.get('provider','kokoro') not in ('kokoro','voicestudio')
                or self.config.get('streaming_prepare') is not True):return False
        if not isinstance(text,str) or not 20<=len(text)<=240:return False
        self.speak(text, _hold=True)
        return self._held_prefix is not None

    def commit_prefix(self, text):
        prefix=self._held_prefix
        if not prefix or not isinstance(text,str) or len(text)>2000 or not text.startswith(prefix):
            if prefix:self.stop()
            return False
        self._held_prefix=None
        self._hold_audio=False
        tail=text[len(prefix):]
        self._tail_text=tail if tail.strip() else None
        if self._pending is None:self._dispatch_tail()
        if self._audio_queue and self._active_audio is None:self._play_queued()
        return True

    def _dispatch_tail(self):
        if self._tail_text is None:return
        text,self._tail_text=self._tail_text,None
        self._next_part=0
        self._pending={'text':text,'output':str(self.folder/'tail.wav'),'id':self.generation,'stream':True}
        self._dispatch()

    def speak(self, text, *, _hold=False):
        self.stop()
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            self.failed.emit('Para ouvir, use uma resposta com até 2.000 caracteres.')
            return
        self._hold_audio=_hold
        self._held_prefix=text if _hold else None
        self.folder = Path(tempfile.mkdtemp(prefix='therion-tts-'))
        self._next_part = 0
        self._pending = {'text': text, 'output': str(self.folder/'speech.wav'), 'id': self.generation, 'stream':True}
        if self.is_ready:
            self._dispatch()
        else:
            if not self.warmup():
                self._clear_audio()
                self._pending = None

    def _dispatch(self):
        if self.process is None or self._pending is None:
            return
        if self.config.get('provider')=='edge' and self.config.get('online_allowed') is not True:
            self.release()
            self.failed.emit('A autorização de voz online foi removida. A síntese foi interrompida.')
            return
        self._busy = True
        self._state('synthesizing')
        self.timer.start(120000)
        self.process.write((json.dumps(self._pending, ensure_ascii=True)+'\n').encode())

    def _read(self, process):
        if process is not self.process:
            process.readAllStandardOutput()
            return
        self._buffer += bytes(process.readAllStandardOutput())
        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            try:
                message = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            self._message(message)

    def _message(self, message):
        if message.get('event')=='startup_error':
            self.release()
            self.failed.emit('Não foi possível preparar VoiceStudio. Confira o endereço local e o perfil salvo.'
                            if self.config.get('provider')=='voicestudio' else
                            'Não foi possível preparar Edge TTS. Confira a autorização e as dependências opcionais de voz.')
            return
        if message.get('event') == 'ready':
            self._own_process(self.process)
            self.is_ready = True
            self.timer.stop()
            self.measured.emit({'stage':'load','seconds':message.get('seconds'),'phases':message.get('phases')})
            if self._pending is not None:
                self._dispatch()
            else:
                self._state('idle')
                self._schedule_release()
            self.warmed.emit()
            return
        if not self._pending or message.get('id') != self.generation:
            return
        if message.get('event')=='error' and self.config.get('provider')=='voicestudio':
            self.stop()
            self.failed.emit('O perfil salvo não está disponível no VoiceStudio. Confira o perfil selecionado.'
                            if message.get('code')=='profile_unavailable' else
                            'Não foi possível gerar a voz no VoiceStudio. Mantenha o aplicativo aberto e confira o modelo. O texto continua disponível.')
            return
        index = message.get('part', 0)
        if index != self._next_part:
            return
        base = Path(self._pending['output'])
        output = base if index==0 else base.with_name(f'{base.stem}-{index}{base.suffix}')
        if message.get('event') != 'audio' or not output.is_file():
            self.stop()
            self.failed.emit('Não foi possível gerar a voz. O texto continua disponível.')
            return
        measurement={'stage':'synthesis','seconds':message.get('seconds'), 'audio_seconds':message.get('audio_seconds')}
        for key in ('profile_seconds', 'http_seconds', 'wav_seconds', 'request_seconds'):
            if key in message:measurement[key]=message[key]
        self.measured.emit(measurement)
        self._next_part += 1
        if message.get('last', True):
            self.timer.stop()
            self._busy = False
            self._pending = None
        self._audio_queue.append(output)
        duration = message.get('audio_seconds')
        self._audio_seconds[output] = (float(duration) if type(duration) in (int, float)
            and math.isfinite(duration) and 0 < duration <= 120 else 120.0)
        if self._pending is None and not self._hold_audio:self._dispatch_tail()
        if not self._hold_audio and not self.sound.isPlaying() and self._active_audio is None:
            self._play_queued()

    def _play_queued(self):
        if not self._audio_queue or self._hold_audio:
            return
        self._active_audio = self._audio_queue.pop(0)
        self._reset_level()
        self._analyze_envelope(self._active_audio)
        self._playback_seconds = self._audio_seconds.pop(self._active_audio, 120.0)
        self._state('playing')
        # play() pode ser assíncrono: limitar também o início, independente
        # do timeout da síntese, que já pode ter sido encerrada.
        self.playback_timer.start(10000)
        self.sound.setSource(QUrl.fromLocalFile(str(self._active_audio)))
        self.sound.play()

    def _playback_timeout(self):
        if self._active_audio is None:
            return
        self.stop()
        self.failed.emit('A reprodução da voz não iniciou ou não terminou no tempo esperado. '
                         'Encerrei a fala; o texto continua disponível. Confira a saída de áudio e tente ouvir novamente.')

    def _process_error(self, process):
        if process is self.process and process.error() == QProcess.FailedToStart:
            self.release()
            self.failed.emit('Não foi possível iniciar a síntese de voz.')

    def _exited(self, process, code):
        tree=self._process_trees.pop(process,None)
        if tree is not None:tree.terminate();self._retiring_trees.append(tree)
        if process in self._retiring_processes:self._retiring_processes.remove(process)
        process.deleteLater()
        if process is not self.process:
            return
        self.process = None
        self.is_ready = False
        waiting = (self._pending is not None or self.state == 'warming'
                   or self._active_audio is not None or bool(self._audio_queue) or self._playing)
        self._pending = None
        self._busy = False
        self.timer.stop()
        self._clear_audio()
        self._state('idle')
        if waiting:
            self.failed.emit('O serviço de voz foi encerrado. Tente novamente.')

    def _timeout(self):
        self.release()
        self.failed.emit('A geração de voz excedeu dois minutos. Você pode tentar novamente.')

    def _clear_audio(self):
        self._reset_level()
        self.playback_timer.stop()
        self._held_prefix=None
        self._hold_audio=False
        self._tail_text=None
        self._playing = False
        self._audio_queue.clear()
        self._audio_seconds.clear()
        self._active_audio = None
        self.sound.stop()
        self.sound.setSource(QUrl())
        folder, self.folder = self.folder, None
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)

    def _schedule_release(self):
        if not self.keep_warm:
            self.idle_timer.start(600000)

    def stop(self):
        self.generation += 1
        self._held_prefix=None
        self._hold_audio=False
        self._tail_text=None
        self.timer.stop()
        self._pending = None
        if self._busy:
            self._kill_process()
        self._busy = False
        self._clear_audio()
        # Aquecimento não contém texto e pode terminar para reutilizar o modelo.
        if self.process is not None and not self.is_ready:
            self.timer.start(120000)
        self._state('idle')
        self._schedule_release()

    def _kill_process(self):
        process, self.process = self.process, None
        self.is_ready = False
        if process is not None:
            if process.state()!=QProcess.NotRunning:self._retiring_processes.append(process)
            tree=self._process_trees.pop(process,None)
            if tree is not None:tree.terminate();self._retiring_trees.append(tree)
            folder = self.folder
            process.finished.connect(lambda *args: shutil.rmtree(folder, ignore_errors=True) if folder else None)
            process.kill()
        return process

    def release(self):
        self.keep_warm = False
        process = self._kill_process()
        self.stop()
        self.idle_timer.stop()
        return process

    def shutdown(self):
        folder = self.folder
        process = self.release()
        if process is not None:
            process.waitForFinished(200)
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)
