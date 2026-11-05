"""Identificadores explícitos de provedores; sem carregamento de bibliotecas."""
import re
from urllib.parse import urlsplit

EDGE_VOICES = ('pt-BR-AntonioNeural', 'pt-BR-FranciscaNeural')
VOICESTUDIO_ENDPOINT = 'http://127.0.0.1:3900/v1/audio/speech'


def is_voicestudio_endpoint(value):
    """Somente a API HTTP no loopback literal, sem proxy, credencial ou redirects."""
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == 'http' and url.hostname in ('127.0.0.1', '::1')
                and url.port is not None and 0 < url.port <= 65535
                and url.netloc in (f'127.0.0.1:{url.port}', f'[::1]:{url.port}')
                and url.path == '/v1/audio/speech' and not url.query and not url.fragment
                and url.username is None and url.password is None)
    except ValueError:
        return False


def is_voicestudio_voice(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value) is not None
