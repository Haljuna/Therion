"""Aviso falado antes de um compromisso, sem consultar nada sozinho.

Só usa a agenda que o próprio usuário pediu no panorama ("bom dia") desta sessão.
Enquanto houver algo em tela cheia (jogo, vídeo, apresentação) ou um pedido em andamento,
o aviso fica guardado e sai depois. Desligado por padrão (ui.event_reminders).
"""
import ctypes
import re
from datetime import timedelta

LEAD = timedelta(minutes=15)
_LATE = timedelta(hours=2)   # depois disso o aviso guardado não ajuda mais


def do_not_disturb():
    """True com app em tela cheia, jogo Direct3D em tela cheia ou modo apresentação do Windows."""
    state = ctypes.c_int()
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
    except (OSError, AttributeError):
        return False
    return state.value in (2, 3, 4)   # QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE


class EventReminders:
    def __init__(self):
        self._pending = {}
        self._told = set()

    def arm(self, items, now):
        """Recebe os compromissos do panorama ({'title', 'time': 'HH:MM'}); os de dia inteiro e os passados ficam de fora."""
        self._pending = {}
        for item in items if isinstance(items, list) else ():
            title, time = (item.get('title'), item.get('time')) if isinstance(item, dict) else (None, None)
            if not isinstance(title, str) or not isinstance(time, str) or not re.fullmatch(r'[0-2]\d:[0-5]\d', time):
                continue
            start = now.replace(hour=int(time[:2]) % 24, minute=int(time[3:]), second=0, microsecond=0)
            key = (start, title[:120])
            if start > now and key not in self._told:
                self._pending[key] = time

    def due(self, now, busy=False):
        messages = []
        for (start, title), time in sorted(self._pending.items()):
            if now < start - LEAD or busy:
                continue
            del self._pending[(start, title)]
            self._told.add((start, title))
            if now < start:
                minutes = max(1, round((start - now).total_seconds() / 60))
                messages.append(f'Em {minutes} {"minuto" if minutes == 1 else "minutos"}: {title}, às {time}.')
            elif now - start <= _LATE:
                messages.append(f'{title} começou às {time}; segurei o aviso enquanto o senhor estava ocupado.')
        return messages
