"""Kokoro local: síntese avulsa ou servidor persistente via JSON no stdin."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

try:
    from .speech_phrasing import phrase_for_speech
    from .kokoro_profile import prepare_profile, process_profile, SUPPORTED_PROFILES
except ImportError:  # Execução direta pelo QProcess, sem importar o aplicativo.
    from speech_phrasing import phrase_for_speech
    from kokoro_profile import prepare_profile, process_profile, SUPPORTED_PROFILES


# Compatibilidade entre eSpeak e o vocabulário do Kokoro V1, conforme
# https://github.com/hexgrad/misaki/blob/main/misaki/espeak.py (EspeakG2P).
# A conversão fonética preserva palavras e valores; só a pontuação da cópia
# falada é preparada para pausas. O texto exibido não passa por esta etapa.
_PT_BR_V1_PHONEMES = (
    ('a^ɪ', 'I'), ('a^ʊ', 'W'), ('d^z', 'ʣ'), ('d^ʒ', 'ʤ'),
    ('e^ɪ', 'A'), ('o^ʊ', 'O'), ('s^s', 'S'), ('t^s', 'ʦ'),
    ('t^ʃ', 'ʧ'), ('ɔ^ɪ', 'Y'), ('ə^ʊ', 'Q'),
)


_SPEECH_CHUNK_CHARACTERS = 144
_SPEECH_SENTENCE_CHARACTERS = 240
_ABBREVIATIONS = frozenset({
    'sr', 'sra', 'srta', 'dr', 'dra', 'prof', 'profa', 'eng', 'enga',
    'av', 'r', 'pág', 'págs', 'art', 'cap', 'vol', 'n', 'ex', 'obs', 'etc',
})


def chunk_speech(text):
    """Agrupa frases curtas, preservando cada caractere e a ordem do texto.

    O orçamento é flexível para uma frase de até 240 caracteres ou um trecho indivisível.
    Não interpreta nem reescreve palavras, números, caminhos ou instruções.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('Texto inválido para reprodução.')
    protected = [(match.start(), match.end()) for match in re.finditer(
        r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|`[^`\n]*`', text)]

    def inside_protected(position):
        return any(start < position < end for start, end in protected)

    sentence_ends = set()
    blocked = set()
    for match in re.finditer(r'([.!?]+)["”’»)\]]*\s+', text):
        position = match.end()
        if inside_protected(position):
            continue
        if match.group(1) == '.':
            word = re.search(r'(\w+)\.$', text[:match.start() + 1])
            previous = word.group(1) if word else ''
            following = text[position:position + 1]
            if (previous.casefold() in _ABBREVIATIONS or len(previous) == 1
                    or (previous.isdigit() and following.isdigit())):
                blocked.add(position)
                continue
        sentence_ends.add(position)
    word_ends = [match.end() for match in re.finditer(r'\s+', text)
                 if match.end() not in blocked and not inside_protected(match.end())]
    # Não produzir uma parte contendo só espaços nas extremidades.
    word_ends = [position for position in word_ends
                 if text[:position].strip() and text[position:].strip()]
    sentence_ends.intersection_update(word_ends)
    clause_ends = {match.end() for match in re.finditer(r'[,;:]\s+', text)
                  if not inside_protected(match.end())}
    chunks = []
    start = 0
    while len(text) - start > _SPEECH_CHUNK_CHARACTERS:
        limit = start + _SPEECH_CHUNK_CHARACTERS
        endings = [position for position in sentence_ends if start < position <= limit]
        if not endings:
            # Terminar uma frase um pouco maior evita reiniciar sua entonação
            # no meio da oração. O primeiro áudio continua limitado por trecho.
            later = [position for position in sentence_ends
                     if limit < position <= start + _SPEECH_SENTENCE_CHARACTERS]
            if later:
                endings = [min(later)]
            elif (len(text)-start <= _SPEECH_SENTENCE_CHARACTERS
                    and re.search(r'[.!?]["”’»)\]]*\s*$', text)):
                endings = [len(text)]
        if not endings:
            endings = [position for position in clause_ends if start+72 < position <= limit]
        if not endings:
            endings = [position for position in word_ends if start < position <= limit]
        if not endings:
            later = [position for position in word_ends if position > limit]
            if not later:
                break
            end = min(later)
        else:
            end = max(endings)
        chunks.append(text[start:end])
        start = end
    if start < len(text):chunks.append(text[start:])
    return chunks


def create_speech(engine, text):
    """Sintetiza português com G2P compatível, reutilizando o backend local."""
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('Texto inválido para reprodução.')
    backend = getattr(engine, '_therion_ptbr_backend', None)
    if backend is None:
        from phonemizer.backend import EspeakBackend
        backend = EspeakBackend(language='pt-br', preserve_punctuation=True,
                                with_stress=True, tie='^', language_switch='remove-flags')
        engine._therion_ptbr_backend = backend
    result = backend.phonemize([phrase_for_speech(text)])
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], str):
        raise ValueError('Não foi possível preparar os fonemas da voz local.')
    phonemes = result[0].strip()
    for original, compatible in _PT_BR_V1_PHONEMES:
        phonemes = phonemes.replace(original, compatible)
    phonemes = phonemes.replace('^', '').replace('-', '')
    if not phonemes:
        raise ValueError('Não foi possível preparar os fonemas da voz local.')
    audio, rate = engine.create(phonemes, voice=getattr(engine, '_therion_voice_style', 'pm_alex'),
                                speed=1.0, lang='pt-br', is_phonemes=True)
    return process_profile(audio, rate, getattr(engine, '_therion_voice_profile', 'pm_alex')), rate


def create_engine(root, timings=None, *, cache_directory=None, voice_profile='pm_alex',memory_efficient=False):
    if voice_profile not in SUPPORTED_PROFILES:
        raise ValueError('Perfil de voz Kokoro desconhecido.')
    started = time.perf_counter()
    os.environ['ONNX_PROVIDER'] = 'CPUExecutionProvider'
    import numpy as np
    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    if timings is not None:
        timings['imports'] = round(time.perf_counter()-started, 3)
    started = time.perf_counter()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    if memory_efficient:
        options.enable_cpu_mem_arena=False
        options.enable_mem_pattern=False
    source = root / 'kokoro-v1.0.onnx'
    source_stat = source.stat()
    # ORT evita analisar novamente o protobuf ONNX. O cache regenerável fica
    # nos temporários, sem duplicar pesos no disco que contém o modelo.
    identity = hashlib.sha256(str(source.resolve()).encode('utf-8')).hexdigest()[:16]
    cache_directory = (Path(cache_directory) if cache_directory is not None else
                       Path(tempfile.gettempdir()) / 'therion-kokoro-runtime')
    cache = cache_directory / f'kokoro-cpu-v1-{ort.__version__}-{identity}-{source_stat.st_size}-{source_stat.st_mtime_ns}.ort'
    legacy = root / 'runtime-cache' / f'kokoro-cpu-{ort.__version__}-{source_stat.st_size}-{source_stat.st_mtime_ns}.onnx'
    session = None
    cached = False
    cache_format = 'source'
    if cache.is_file():
        try:
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
            session = ort.InferenceSession(str(cache), sess_options=options, providers=['CPUExecutionProvider'])
            cached = True
            cache_format = 'ort'
        except Exception:
            # Cache pode ser interrompido/corrompido. O modelo original continua disponível.
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if session is None:
        temporary = None
        exported = False
        load_source = legacy if legacy.is_file() else source
        try:
            cache_directory.mkdir(parents=True, exist_ok=True)
            # Sem espaço, apenas carregar. Uma otimização não deve encher disco.
            if shutil.disk_usage(cache_directory).free >= source_stat.st_size + 64 * 1024 * 1024:
                temporary = cache_directory / f'preparing-{uuid.uuid4().hex}.ort'
                options.optimized_model_filepath = str(temporary)
                options.add_session_config_entry('session.save_model_format', 'ORT')
        except OSError:
            pass
        try:
            try:
                if load_source == legacy:
                    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
                session = ort.InferenceSession(str(load_source), sess_options=options, providers=['CPUExecutionProvider'])
                exported = temporary is not None
                cached = load_source == legacy
                cache_format = 'onnx' if cached else 'source'
            except Exception:
                if temporary is None and load_source == source:
                    raise
                # Falha ao salvar/ler cache não deve impedir carregar o original.
                options.optimized_model_filepath = ''
                options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                session = ort.InferenceSession(str(source), sess_options=options, providers=['CPUExecutionProvider'])
            if exported and temporary is not None and temporary.is_file():
                try:
                    temporary.replace(cache)
                except OSError:
                    pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
    if timings is not None:
        timings['session'] = round(time.perf_counter()-started, 3)
        timings['cache_hit'] = cached
        timings['cache_format'] = cache_format
    started = time.perf_counter()
    engine = Kokoro.from_session(session, str(root / 'voices-v1.0.bin'))
    if timings is not None:
        timings['tokenizer'] = round(time.perf_counter()-started, 3)

    class TypedSession:
        def get_inputs(self):
            return session.get_inputs()

        def run(self, outputs, inputs):
            types = {'tensor(float)': np.float32, 'tensor(int64)': np.int64, 'tensor(int32)': np.int32}
            return session.run(outputs, {item.name: np.asarray(inputs[item.name], dtype=types[item.type])
                                         for item in self.get_inputs()})

    engine.sess = TypedSession()
    prepare_profile(engine, voice_profile)
    return engine


def synthesize(engine, request):
    import numpy as np
    import soundfile as sf
    text = request['text']
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('Texto inválido para reprodução.')
    started = time.perf_counter()
    audio, rate = create_speech(engine, text)
    if not len(audio) or not np.isfinite(audio).all() or not np.max(np.abs(audio)):
        raise ValueError('Áudio inválido.')
    sf.write(request['output'], audio, rate, subtype='PCM_16')
    return {'event': 'audio', 'id': request.get('id'), 'seconds': round(time.perf_counter()-started, 3),
            'audio_seconds': round(len(audio)/rate, 3)}


def emit(value):
    print(json.dumps(value), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--root')
    parser.add_argument('--voice', choices=SUPPORTED_PROFILES, default='pm_alex')
    parser.add_argument('--memory-efficient',action='store_true')
    args = parser.parse_args()
    if not args.serve:
        request = json.load(sys.stdin)
        synthesize(create_engine(Path(request['model_root']), voice_profile=request.get('voice', args.voice)), request)
        return
    started = time.perf_counter()
    timings = {}
    extra={'memory_efficient':True} if args.memory_efficient else {}
    engine = create_engine(Path(args.root), timings, voice_profile=args.voice,**extra)
    # Primeira inferência prepara kernels; as respostas seguintes reutilizam o modelo.
    warming_started = time.perf_counter()
    create_speech(engine, 'Olá.')
    timings['first_inference'] = round(time.perf_counter()-warming_started, 3)
    emit({'event': 'ready', 'seconds': round(time.perf_counter()-started, 3), 'phases':timings, 'voice':args.voice,'pid':os.getpid()})
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            text = request['text']
            if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                raise ValueError('Texto inválido para reprodução.')
            parts = chunk_speech(text) if request.get('stream') else [text]
            base = Path(request['output'])
            for index, part in enumerate(parts):
                item = dict(request, text=part, output=str(base if index==0 else base.with_name(f'{base.stem}-{index}{base.suffix}')))
                result = synthesize(engine, item)
                result.update(part=index, last=index==len(parts)-1)
                emit(result)
        except Exception:
            emit({'event': 'error', 'id': request.get('id') if isinstance(request, dict) else None})


if __name__ == '__main__':
    main()
