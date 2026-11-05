"""Ajustes mínimos de apresentação para saudações geradas pelo modelo."""
import re

from therion.context.language import control


_OPENING = re.compile(r'^\s*(?:bom dia|boa tarde|boa noite|ol[aá]|oi)\s*,\s*senhor[.!?]?\s*', re.I)


def normalize_model_greeting(command: str, message: str) -> str:
    """Evita saudações de período inventadas e recomeços em cada turno."""
    if not isinstance(message, str):
        return message
    opening = _OPENING.match(message)
    if opening is None:
        return message
    text = control(command)
    explicit = re.match(r'^(?:(?:therion|terion|eterion) )?(bom dia|boa tarde|boa noite)\b', text)
    rest = message[opening.end():].lstrip()
    if explicit:
        greeting = explicit[1].capitalize() + ', senhor.'
    elif re.fullmatch(r'(?:oi|ola|e ai)(?: (?:therion|terion|eterion))?|'
                      r'fala(?: (?:therion|terion|eterion|ate ai))?(?: beleza)?', text):
        greeting = 'Olá, senhor.'
    else:
        return rest or message
    return greeting + (' ' + rest if rest else '')
