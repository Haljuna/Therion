"""Remove somente cauda textual conhecida antes de um pedido de leitura."""
import re
from therion.context.language import control


def strip_spoken_echo_prefix(text, spoken):
    match = re.match(r'^\s*([^.!?\n]{2,80})[.!?]\s+(.+)$', text, re.S)
    if not match or not spoken:
        return text
    prefix, request = match.groups()
    words = re.findall(r'\w+', control(prefix))
    if any(word in {'nao','nunca','nem','sem','sim','talvez'} for word in words):
        return text
    if words and words[0] == 'e':
        words = words[1:]
    if not 1 <= len(words) <= 4 or (len(words) == 1 and len(words[0]) < 6):
        return text
    tail = re.findall(r'\w+', control(spoken))
    if tail[-len(words):] != words:
        return text
    if not re.match(r'^(?:(?:consegue|pode) (?:me )?(?:mandar|mostrar|ler|resumir)|'
                    r'(?:me )?(?:manda|mande|mostre|exiba|leia|resuma|procura|procure|busque|busca))\b',
                    control(request)):
        return text
    return request.strip()
