"""Prefixo antecipável: só texto nativo; nunca JSON, tags ou pensamento."""
import re


def first_sentence(text):
    if not isinstance(text,str) or len(text)>2000 or text.lstrip().startswith(('{','[')):
        return None
    # Não transmitir sequer à síntese local blocos de raciocínio/markup.
    if any(marker in text for marker in ('<','>','```')):
        return None
    from .kokoro_worker import chunk_speech
    # Esperar delimitador seguido de espaço evita confundir 3.14 com frase.
    if not re.search(r'[.!?]\s',text):return None
    parts=chunk_speech(text)
    if len(parts)<2:return None
    prefix=parts[0]
    if 20<=len(prefix)<=240 and re.search(r'[.!?]["”’»)\]]*\s*$',prefix):
        return prefix
    return None
