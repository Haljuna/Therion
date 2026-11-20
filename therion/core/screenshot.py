"""'Tira a print': salva a tela inteira (todos os monitores) em Imagens\\Screenshots, sem passar pelo modelo."""
from datetime import datetime
from pathlib import Path
import re

from therion.context.language import control


def screenshot_request(command):
    text = re.sub(r'^(?:(?:therion|terion|eterion)[, ]+)?(?:por favor[, ]+)?', '', control(command).rstrip('?!. '))
    # A voz repete o pedido ("tira a print, tira a print"): vale a primeira frase.
    first = re.split(r'[,.;!]', text)[0].strip()
    return bool(re.fullmatch(
        r'(?:tira|tire|tirar|faz|faca|fazer|bate|bater)(?: uma| um| a| o)? (?:print|printscreen|print screen|captura de tela|foto da tela)'
        r'(?: da tela| do monitor| da minha tela)?(?: (?:pra|para) mim)?'
        r'|printa(?: a)? tela', first))


def default_folder():
    """A mesma pasta do Win+PrtScn (aqui, OneDrive\\Imagens\\Capturas de tela)."""
    try:
        import ctypes
        from ctypes import wintypes
        guid = (ctypes.c_byte * 16).from_buffer_copy(
            __import__('uuid').UUID('b7bede81-df94-4682-a7d8-57a52620b86f').bytes_le)   # FOLDERID_Screenshots
        found = wintypes.LPWSTR()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(found)) == 0:
            try:
                return Path(found.value)
            finally:
                ctypes.windll.ole32.CoTaskMemFree(found)
    except (OSError, AttributeError, ValueError):
        pass
    return Path.home() / 'Pictures' / 'Screenshots'


def take_screenshot(folder=None, grab=None, now=datetime.now):
    if grab is None:
        from PIL import ImageGrab
        grab = lambda: ImageGrab.grab(all_screens=True)
    folder = Path(folder or default_folder())
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'Therion {now():%Y-%m-%d %H-%M-%S}.png'
    grab().save(path)
    return path
