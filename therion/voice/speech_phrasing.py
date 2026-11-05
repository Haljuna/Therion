"""Pontuação para a cópia falada; palavras, números e horários permanecem iguais."""
import re


_LITERAL = re.compile(
    r'```[\s\S]*?```|`[^`\n]*`|'
    r'"[A-Za-z]:\\[^"\n]*"|“[A-Za-z]:\\[^”\n]*”|'
    r'(?:[A-Za-z]:\\|\\\\)[^\s]+|(?:https?://|www\.)[^\s]+')


def _phrase(text):
    text = text.replace('…', '...')
    text = re.sub(r'(?m)^[ \t]*(?:[-*•][ \t]+|#{1,6}[ \t]+)', '', text)
    text = re.sub(r'(?<!\w)\*\*(\S(?:[^\n]*?\S)?)\*\*(?!\w)', r'\1', text)
    text = re.sub(r'[ \t]+[—–][ \t]+', ', ', text)
    # Quebras de linha sem pontuação precisam de uma pausa, não de palavras coladas.
    text = re.sub(r'([^\s.!?;:])[ \t]*\r?\n+[ \t]*(?=\S)', r'\1. ', text)
    text = re.sub(r'(?<=[.!?;:])[ \t]*\r?\n+[ \t]*', ' ', text)
    return text


def phrase_for_speech(text):
    """Protege literais técnicos; nunca interpreta nem executa seu conteúdo."""
    parts=[];start=0
    for match in _LITERAL.finditer(text):
        parts.append(_phrase(text[start:match.start()]))
        parts.append(match.group());start=match.end()
    parts.append(_phrase(text[start:]))
    return ''.join(parts)
