"""ASR experimental com pesos locais instalados, sem importar o app VoiceStudio."""
import ctypes
import io
from pathlib import Path
import time
import wave


def memory():
    from ctypes import wintypes
    class Status(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong) for name in ('total_physical','available_physical',
                'commit_limit','available_commit','total_virtual','available_virtual','extended')]
    row = Status()
    row.length = ctypes.sizeof(row)
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    if not api.GlobalMemoryStatusEx(ctypes.byref(row)):
        raise OSError('Nao foi possivel verificar a memoria')
    return {'available_ram_gib':round(row.available_physical/1024**3,3),
            'available_commit_gib':round(row.available_commit/1024**3,3)}


def process_memory():
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('size',wintypes.DWORD),('faults',wintypes.DWORD)] + [
            (name,ctypes.c_size_t) for name in ('peak_working_set','working_set','peak_paged',
                'paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]
    row = Counters()
    row.size = ctypes.sizeof(row)
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi')
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(row),row.size):
        raise OSError('Contadores de processo indisponiveis')
    return {'private_mib':round(row.private/1024**2,1),
            'working_set_mib':round(row.working_set/1024**2,1),
            'peak_working_set_mib':round(row.peak_working_set/1024**2,1)}


REPOSITORIES = {
    'parakeet':'models--csukuangfj--sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8',
    'tiny':'models--csukuangfj--sherpa-onnx-whisper-tiny',
    'turbo':'models--deepdml--faster-whisper-large-v3-turbo-ct2',
}


def installed_path(kind, root=Path('F:/VoiceStudio/models')):
    if kind == 'baseline':
        result = Path('F:/Therion/models/faster-whisper-small')
    else:
        snapshots = list((root/REPOSITORIES[kind]/'snapshots').glob('*'))
        snapshots = [item for item in snapshots if item.is_dir()]
        if len(snapshots) != 1:
            raise ValueError('Snapshot local ausente ou ambiguo; nao sera baixado')
        result = snapshots[0]
    if not result.is_dir():
        raise ValueError('Modelo local ausente')
    return result


def decode_wav(raw):
    import numpy as np
    with wave.open(io.BytesIO(raw)) as audio:
        rate, channels, width, frames = audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getnframes()
        if width != 2 or channels not in (1,2) or not 8000 <= rate <= 48000 or not 0 < frames/rate <= 30:
            raise ValueError('Aceito somente WAV PCM16 mono/estereo de ate 30 segundos')
        pcm = audio.readframes(frames)
        if len(pcm) != frames*channels*width:
            raise ValueError('WAV truncado')
        data = np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
        data = data.reshape(-1,channels).mean(axis=1)
        if rate != 16000:
            data = np.interp(np.arange(round(len(data)*16000/rate))*rate/16000,
                             np.arange(len(data)),data).astype(np.float32)
    return data


class Recognizer:
    def __init__(self, kind, threads=2):
        self.kind, self.threads = kind, threads
        required = {'baseline':1.5,'tiny':0.75,'parakeet':2.0,'turbo':6.0}[kind]
        self.memory_before = memory()
        if self.memory_before['available_commit_gib'] < required:
            raise MemoryError('Margem de memoria insuficiente para este ensaio isolado')
        path = installed_path(kind)
        started = time.perf_counter()
        if kind in ('baseline','turbo'):
            from faster_whisper import WhisperModel
            self.model = WhisperModel(str(path), device='cpu', compute_type='int8',
                cpu_threads=threads, num_workers=1, local_files_only=True)
        else:
            import sherpa_onnx
            if kind == 'parakeet':
                self.model = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=str(path/'encoder.int8.onnx'), decoder=str(path/'decoder.int8.onnx'),
                    joiner=str(path/'joiner.int8.onnx'),tokens=str(path/'tokens.txt'),
                    num_threads=threads, provider='cpu', model_type='nemo_transducer',
                    decoding_method='greedy_search')
            else:
                self.model = sherpa_onnx.OfflineRecognizer.from_whisper(
                    encoder=str(path/'tiny-encoder.int8.onnx'),decoder=str(path/'tiny-decoder.int8.onnx'),
                    tokens=str(path/'tiny-tokens.txt'), language='pt', task='transcribe',
                    num_threads=threads, provider='cpu', decoding_method='greedy_search')
        self.load_seconds = round(time.perf_counter()-started,3)

    def transcribe(self, raw):
        data = decode_wav(raw)
        duration = round(len(data)/16000,3)
        started = time.perf_counter()
        quality = None
        if not data.any():
            text, quality = '', True  # silencio digital exato, nao limiar que apague fala baixa.
        elif self.kind in ('baseline','turbo'):
            segments, _ = self.model.transcribe(data,language='pt',beam_size=5,temperature=0,
                vad_filter=True,condition_on_previous_text=False,
                hotwords='Therion, Obsidian, Segundo Cérebro, cancele')
            segments = list(segments)
            text = ' '.join(segment.text.strip() for segment in segments).strip()
            quality = all(segment.avg_logprob >= -1 and segment.no_speech_prob <= .6
                          and segment.compression_ratio <= 2.4 for segment in segments)
        else:
            stream = self.model.create_stream()
            stream.accept_waveform(16000,data)
            self.model.decode_stream(stream)
            text = stream.result.text.strip()
        return {'text':text,'model':self.kind,'language':'pt','audio_seconds':duration,
                'processing_seconds':round(time.perf_counter()-started,4),
                'confidence_gate_passed':quality}
