"""Modo foco: frases, estado salvo, histórico do dia e texto do fim. Sem Qt e com relógio injetado.

O estado fica em %LOCALAPPDATA%\\Therion\\foco.json; quem dispara o fim na hora é a janela (interface/desktop.py).
"""
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from therion.context.language import control
from therion.core.voice_reminders import PENDING_SECONDS, TERMINAL_MESSAGE, _COUNT, _clock, _count, _duration, _hm

MIN_FOCUS, MAX_FOCUS = 5, 180
MIN_PAUSE, MAX_PAUSE = 1, 60
DEFAULT_FOCUS, DEFAULT_PAUSE = 50, 10
HISTORY_DAYS = 30
MAX_SHOWN_HELD = 3
MAX_HELD_CHARS = 90
NOT_SAVED = 'Não consegui salvar o foco agora.'

_DUR = (rf'(?:(?P<half>meia\s+hora)|(?P<n>{_COUNT})\s*(?P<unit>horas?|h|minutos?|min)'
        rf'(?:\s+e\s+(?:(?P<more_half>meia)|(?P<more>{_COUNT})(?:\s*(?:minutos?|min))?))?)')
_START = re.compile(
    r'^(?:(?:ativa|ative|ativar|liga|ligue|ligar|inicia|inicie|iniciar|comeca|comece|comecar|entra|entre|entrar|coloca|bota)\s+'
    rf'(?:(?:no|o|um|em)\s+)*)?(?:modo\s+)?foco(?:\s+(?:de|por|em))?(?:\s+{_DUR})?$')
_WANT = re.compile(rf'^(?:vou|quero|preciso|vamos)\s+(?:focar|entrar\s+em\s+foco)(?:\s+(?:por|durante|de|em))?(?:\s+{_DUR})?$')
_EXTEND = re.compile(
    r'^(?:(?:estica|estique|esticar|prolonga|prolongue|prolongar|aumenta|aumente|aumentar)\s+(?:o\s+)?(?:foco\s+)?(?:em\s+|por\s+|mais\s+)?|mais\s+)'
    rf'{_DUR}(?:\s+de\s+foco)?$')
_STOP = re.compile(
    r'^(?:(?:sai|saia|sair)\s+do|(?:para|pare|parar|cancela|cancele|cancelar|encerra|encerre|encerrar|acaba|acabe|termina|termine|desativa|desative|desliga|desligue)\s+(?:com\s+)?(?:o\s+)?'
    r'|chega\s+de|fim\s+do)\s*(?:modo\s+)?foco$')
_LEFT = re.compile(r'^quanto\s+(?:tempo\s+)?(?:falta|resta)(?:\s+(?:do|da|pro|pra|para)\s+(?:o\s+|a\s+)?(?:fim\s+d[oa]\s+)?(?:foco|pausa))?$')
_PAUSE = re.compile(
    r'^(?:(?:faz|faca|fazer|toma|tomar|inicia|comeca|vou\s+(?:fazer|tomar))\s+)?(?:uma\s+)?pausa\s+(?:(?:de|por)\s+)?' + _DUR + '$')
_PAUSE_BARE = re.compile(r'^(?:faz|faca|fazer|toma|tomar|vou\s+fazer|vou\s+tomar)\s+uma\s+pausa$')
_STOP_PAUSE = re.compile(
    r'^(?:(?:sai|saia|sair)\s+da|(?:para|pare|parar|encerra|encerre|encerrar|acaba|acabe|termina|termine|cancela|cancele)\s+(?:a\s+)?|chega\s+de|fim\s+da)\s*pausa$')
_YES = {'sim', 'pode', 'pode sim', 'sim pode', 'claro', 'isso', 'manda', 'pode ser', 'quero', 'sim por favor', 'vamos', 'bora'}
_NO = {'nao', 'nao precisa', 'agora nao', 'deixa', 'deixa assim', 'deixa pra la', 'deixa quieto', 'esquece', 'nada', 'nao obrigado', 'nao quero'}


@dataclass
class FocusState:
    phase: str                 # 'focus' | 'pause' | 'off'
    start: datetime | None
    minutes: int
    held: list[str]


def _empty():
    return FocusState('off', None, 0, [])


def _state_json(state):
    return dict(phase=state.phase, start=state.start.isoformat(timespec='seconds') if state.start else None,
                minutes=state.minutes, held=list(state.held))


def _state_from_json(row):
    phase = str(row['phase'])
    if phase not in ('focus', 'pause', 'off'):
        raise ValueError('fase')
    start = row['start']
    return FocusState(phase, datetime.fromisoformat(start) if start else None, int(row['minutes']), [str(item) for item in row['held']])


class FocusStore:
    """Estado do foco e minutos focados por dia. Lê o arquivo a cada chamada (é pequeno) e grava de forma atômica."""

    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ['LOCALAPPDATA']) / 'Therion' / 'foco.json'
        self._lock = threading.Lock()

    def _read(self):
        """(estado, dias, último foco). Sem arquivo ou arquivo quebrado → vazio (o quebrado vai para .bad-<data>)."""
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return _empty(), {}, 0
        try:
            data = json.loads(raw.decode('utf-8'))
            if data['version'] != 1:
                raise ValueError('versão')
            return (_state_from_json(data['state']), {str(day): int(minutes) for day, minutes in data['days'].items()},
                    int(data.get('last') or 0))
        except (ValueError, KeyError, TypeError, AttributeError):
            try:
                os.replace(self.path, self.path.with_name(f'{self.path.name}.bad-{datetime.now():%Y%m%d-%H%M%S}'))
            except OSError:
                pass
            return _empty(), {}, 0

    def _write(self, state, days, last):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.tmp')
        try:
            with open(temporary, 'w', encoding='utf-8') as file:
                json.dump({'version': 1, 'state': _state_json(state), 'days': days, 'last': last}, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def state(self):
        with self._lock:
            try:
                return self._read()[0]
            except OSError:
                return _empty()

    def save(self, state):
        with self._lock:
            _, days, last = self._read()
            self._write(state, days, state.minutes if state.phase == 'focus' else last)

    def update(self, change):
        """Lê, aplica change(estado) → novo estado e grava sob a mesma trava (um aviso guardado nunca some
        no meio de outra gravação). change devolve o próprio estado para não mudar nada. Devolve (antes, depois)."""
        with self._lock:
            state, days, last = self._read()
            new = change(state)
            if new is not state:
                self._write(new, days, new.minutes if new.phase == 'focus' else last)
            return state, new

    def add_minutes(self, day, minutes):
        with self._lock:
            state, days, last = self._read()
            key = day.isoformat()
            days[key] = days.get(key, 0) + minutes
            cutoff = (day - timedelta(days=HISTORY_DAYS)).isoformat()
            self._write(state, {k: v for k, v in days.items() if k >= cutoff}, last)

    def today(self, day):
        with self._lock:
            try:
                return self._read()[1].get(day.isoformat(), 0)
            except OSError:
                return 0

    def last_minutes(self):
        """Duração do último foco começado (0 se nunca)."""
        with self._lock:
            try:
                return self._read()[2]
            except OSError:
                return 0


_shared = None
_shared_lock = threading.Lock()


def store():
    """Instância única, para o orchestrator e a janela enxergarem o mesmo estado."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = FocusStore()
        return _shared


def end_at(state):
    return state.start + timedelta(minutes=state.minutes)


def remaining(state, now):
    """Segundos até o fim, nunca negativo."""
    if state.start is None:
        return 0.0
    return max(0.0, (end_at(state) - now).total_seconds())


def _config_minutes(key, default, low, high):
    """focus.<key> do config.json; fora do intervalo ou ausente vale o padrão."""
    try:
        from therion.config.local import load_config
        value = (load_config().get('focus') or {}).get(key)
    except (OSError, AttributeError, ValueError):
        return default
    return value if type(value) is int and low <= value <= high else default


def pause_minutes():
    return _config_minutes('pause', DEFAULT_PAUSE, MIN_PAUSE, MAX_PAUSE)


def next_focus_minutes():
    """Duração do "mais um foco": a do último começado, ou o padrão."""
    return store().last_minutes() or _config_minutes('minutes', DEFAULT_FOCUS, MIN_FOCUS, MAX_FOCUS)


def settle(now):
    """Encerra o foco ou a pausa cujo tempo acabou; o foco conta inteiro no dia do fim (pausa não conta).
    Devolve o estado encerrado, ou None se não havia nada para encerrar (ou outro já encerrou)."""
    before, after = store().update(
        lambda state: _empty() if state.phase in ('focus', 'pause') and remaining(state, now) <= 0 else state)
    if after is before:
        return None
    if before.phase == 'focus':
        store().add_minutes(end_at(before).date(), before.minutes)
    return before


# --- frases -------------------------------------------------------------------------------------------------
def _minutes(match):
    if match['half']:
        return 30
    count = _count(match['n'])
    if not match['unit'].startswith('h'):
        return count
    return count * 60 + (30 if match['more_half'] else _count(match['more']) if match['more'] else 0)


def _text(command):
    return control(command).replace(',', '')


def focus_request(command):
    """Sem estado e sem efeito: ('start', min|None), ('extend', min), ('stop',), ('left',), ('pause', min|None), ('stop_pause',) ou None."""
    text = _text(command)
    if _STOP_PAUSE.match(text):
        return ('stop_pause',)
    if _STOP.match(text):
        return ('stop',)
    if (found := _EXTEND.match(text)) and (minutes := _minutes(found)) > 0:
        return ('extend', minutes)
    if _LEFT.match(text):
        return ('left',)
    if found := _PAUSE.match(text):
        return ('pause', _minutes(found))
    if _PAUSE_BARE.match(text):
        return ('pause', None)
    if found := _START.match(text) or _WANT.match(text):
        return ('start', _minutes(found) if found['n'] or found['half'] else None)
    return None


def _state():
    try:
        return store().state()
    except OSError:
        return _empty()


def _active(state, now):
    return state.phase in ('focus', 'pause') and remaining(state, now) > 0


def _route(command, host, now):
    """(ação, texto da frase) sem efeito colateral, ou None. A oferta pendente é dona do "sim"/"não"."""
    text = _text(command)
    offer_pending = getattr(host, '_focus_offer', None)
    if offer_pending and time.monotonic() < offer_pending[0]:
        if text in _YES:
            return ('accept', offer_pending[1]), text
        if text in _NO:
            return ('decline',), text
    request = focus_request(command)
    if request is None:
        return None
    state = _state()
    if request[0] == 'extend' and not (state.phase == 'focus' and _active(state, now)):
        return None   # "mais 10 minutos" sem foco ligado é conversa comum
    if request[0] == 'left' and not (_active(state, now) or 'foco' in text or 'pausa' in text):
        return None
    return request, text


def wanted(command, host):
    """Sem consumir a oferta: a frase é desta rota? (o agente deixa a rota local responder)."""
    return _route(command, host, datetime.now()) is not None


def offer(host, kind):
    """kind: 'pause' ou 'again'. Vale 2 min e só para a próxima frase; só uma pendência é dona do "sim"."""
    host._focus_offer = (time.monotonic() + PENDING_SECONDS, kind)
    host._pc_cleanup_offer = None
    host._reminder_pending = None


# --- textos -------------------------------------------------------------------------------------------------
def _until(end):
    if (end.hour, end.minute) == (0, 0):
        return 'até a meia-noite'
    if (end.hour, end.minute) == (12, 0):
        return 'até o meio-dia'
    return ('até a ' if end.hour == 1 else 'até as ') + _hm(end.hour, end.minute)


def _plural(count, word):
    return f'{count} {word}' + ('' if count == 1 else 's')


def _left(state, now):
    return max(1, math.ceil(remaining(state, now) / 60))


def _faltam(minutes, capital=False):
    word = 'falta' if minutes == 1 else 'faltam'
    return f'{word.capitalize() if capital else word} {_plural(minutes, "minuto")}'


def _total(minutes):
    if minutes < 60:
        return _plural(minutes, 'minuto')
    hours, rest = divmod(minutes, 60)
    return _plural(hours, 'hora') + (f' e {rest}' if rest else '')


def _short(text):
    text = text.strip().rstrip('.!?;: ')
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        text = text[0].lower() + text[1:]
    if len(text) > MAX_HELD_CHARS:
        text = text[:MAX_HELD_CHARS].rsplit(' ', 1)[0]
    return text


def _mail_text(mail):
    if mail is None:
        return None
    if mail.get('error'):
        return 'Não consegui contar os e-mails agora.'
    count = mail.get('count') or 0
    if count == 0:
        return 'Nenhum e-mail novo.'
    head = 'Chegou 1 e-mail' if count == 1 else f'Chegaram {count} e-mails'
    important = list(mail.get('important') or [])[:3]
    if not important:
        return head + '.'
    items = '; '.join(f'{who}, sobre {subject}' if subject else who for who, subject in important)
    label = 'importante' if count == 1 else _plural(len(important), 'importante')
    return f'{head}, {label}: {items}.'


def _held_text(held):
    held = [_short(item) for item in held if item.strip()]
    if not held:
        return None
    more = len(held) - MAX_SHOWN_HELD
    return 'Enquanto você focava: ' + '; '.join(held[:MAX_SHOWN_HELD]) + (f' e mais {_plural(more, "aviso")}' if more > 0 else '') + '.'


def ended_text(minutes_done, today_total, mail, held, suggest_pause):
    """A fala do fim do foco (§6.3), na ordem fixa; cada parte só entra se tiver conteúdo."""
    parts = [f'Foco de {_duration(minutes_done)} concluído. Hoje são {_total(today_total)} de foco.',
             _mail_text(mail), _held_text(held),
             f'Que tal {_duration(suggest_pause)} de pausa?' if suggest_pause else None]
    return ' '.join(part for part in parts if part)


def pause_ended_text(minutes):
    return f'Pausa acabou. Mais {_duration(minutes)} de foco?'


def closed_text(end, today_total):
    """O foco acabou com o Therion fechado (§6.2); today_total None quando o fim foi em outro dia."""
    text = f'Seu foco terminou {_clock(end.hour, end.minute)} enquanto eu estava fechado.'
    return text + (f' Hoje são {_total(today_total)} de foco.' if today_total else '')


# --- e-mails do fim do foco (numa thread; nunca na janela) ------------------------------------------------
def _mail_ids(box, account, adapter, token, query):
    """Só ids, de 500 em 500, como o miolo de briefing.mail_since."""
    found, pages, page = [], set(), None
    while True:
        token.check()
        box._check(account, token)
        row = adapter.search(query, page, limit=500)
        found += [ref['id'] for ref in row.get('messages', [])]
        page = row.get('next_page')
        if not page:
            return found
        if page in pages:
            raise ValueError('Paginação repetida; contagem incompleta.')
        pages.add(page)


def _count_mail(box, account, after, token):
    from therion.integrations.mail_text import mail_header, sender_name
    with box.io_lock:
        with box._adapter(account, token) as adapter:
            count = len(set(_mail_ids(box, account, adapter, token, f'in:inbox after:{after}')))
            important = []
            row = adapter.search(f'in:inbox is:important after:{after}', None, limit=3)
            for ref in row.get('messages', [])[:3]:
                token.check()
                headers = {str(item.get('name', '')).lower(): mail_header(item.get('value', ''))
                           for item in adapter.metadata(ref['id'])['payload']['headers']}
                important.append((sender_name(headers.get('from', '')), headers.get('subject', '')))
    box._check(account, token)
    return {'count': count, 'important': important}


def focus_mail(host, start, token, timeout=10.):
    """E-mails desde o começo do foco: None sem conta; {'count', 'important'}; {'error': True} em falha ou
    prazo. Não abre corpo de e-mail e não mexe no marco da saudação (BriefingMarker)."""
    from therion.agent.briefing import DeadlineToken
    from therion.agent.contracts import Cancelled
    box = host._mailbox
    account = box.identity()
    if account is None:
        return None
    deadline = DeadlineToken(token, timeout)
    result = {}

    def fetch():
        try:
            result['mail'] = _count_mail(box, account, int(start.timestamp()), deadline)
        except (OSError, ValueError, TimeoutError, KeyError, TypeError, Cancelled):
            result['mail'] = {'error': True}

    # Uma chamada presa no Gmail não confere o prazo: a espera é por fora, e o token cancela o resto.
    worker = threading.Thread(target=fetch, name='therion-focus-mail-io', daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        deadline.cancel()
        return {'error': True}
    return result.get('mail', {'error': True})


# --- respostas ----------------------------------------------------------------------------------------------
def _payload(state, ended=False):
    return {'phase': state.phase, 'minutes': state.minutes,
            'start': state.start.isoformat(timespec='seconds') if state.start else None, 'ended': ended}


def _begin(phase, minutes, now):
    state = FocusState(phase, now, minutes, [])
    store().save(state)
    until = _until(end_at(state))
    if phase == 'focus':
        return f'Foco de {_duration(minutes)}, {until}. Seguro meus avisos até lá; seus lembretes continuam valendo.', _payload(state)
    return f'Pausa de {_duration(minutes)}, {until}.', _payload(state)


def _start(minutes, state, now):
    if state.phase == 'focus' and _active(state, now):
        return f'Você já está em foco; {_faltam(_left(state, now))}.', None
    if minutes is None:
        minutes = _config_minutes('minutes', DEFAULT_FOCUS, MIN_FOCUS, MAX_FOCUS)
    if not MIN_FOCUS <= minutes <= MAX_FOCUS:
        return f'Dá para focar de {MIN_FOCUS} a {MAX_FOCUS} minutos.', None
    return _begin('focus', minutes, now)


def _pause(minutes, state, now):
    if _active(state, now):
        who = 'Você está em foco' if state.phase == 'focus' else 'Você já está em pausa'
        return f'{who}; {_faltam(_left(state, now))}.', None
    if minutes is None:
        minutes = pause_minutes()
    if not MIN_PAUSE <= minutes <= MAX_PAUSE:
        return f'Dá para fazer pausas de {MIN_PAUSE} a {MAX_PAUSE} minutos.', None
    return _begin('pause', minutes, now)


def _extend(minutes, state, now):
    if state.minutes >= MAX_FOCUS:
        return f'O foco já está no máximo de {MAX_FOCUS} minutos.', None
    # Releitura sob a trava: um aviso que a janela guardou neste meio-tempo não se perde.
    _, grown = store().update(lambda current: replace(current, minutes=min(current.minutes + minutes, MAX_FOCUS))
                              if current.phase == 'focus' else current)
    if grown.phase != 'focus':
        return 'Você não está em foco.', None
    until = _until(end_at(grown))
    if state.minutes + minutes > MAX_FOCUS:
        return f'O máximo é {MAX_FOCUS} minutos de foco; estiquei {until}.', _payload(grown)
    return f'Mais {_duration(minutes)} de foco, {until}.', _payload(grown)


def _stop(state, now):
    """O resumo (e-mails, avisos guardados, oferta de pausa) quem fala é a janela, igual ao fim natural."""
    state, after = store().update(lambda current: _empty() if current.phase == 'focus' else current)
    if after is state:
        return 'Você não está em foco.', None
    done = min(state.minutes, max(0, int((now - state.start).total_seconds() // 60)))
    if done:
        store().add_minutes(now.date(), done)
    return 'Foco encerrado.', {'phase': 'off', 'minutes': done, 'start': state.start.isoformat(timespec='seconds'),
                               'ended': True, 'held': list(state.held)}


def _stop_pause(state):
    if state.phase != 'pause':
        return 'Você não está em pausa.', None
    store().save(_empty())
    return 'Pausa encerrada.', {'phase': 'off', 'minutes': 0, 'start': None, 'ended': False}


def _how_long(state, now, text):
    if not _active(state, now):
        return ('Você não está em pausa.' if 'pausa' in text and 'foco' not in text else 'Você não está em foco.'), None
    return f'{_faltam(_left(state, now), True)} de {"foco" if state.phase == "focus" else "pausa"}.', None


def _accept(kind, state, now):
    if kind == 'pause':
        return _begin('pause', pause_minutes(), now)
    return _begin('focus', next_focus_minutes(), now)


def answer(command, host, now=None):
    """(texto, ui_payload) ou None. Ofertas pendentes valem 2 min e só para a próxima frase."""
    now = (now or datetime.now()).replace(microsecond=0)
    routed = _route(command, host, now)
    if getattr(host, '_focus_offer', None) is not None:
        host._focus_offer = None
    if routed is None:
        return None
    if not getattr(host, 'desktop_timers', False):
        return TERMINAL_MESSAGE, None
    (kind, *args), text = routed
    state = _state()
    try:
        if kind == 'start':
            return _start(args[0], state, now)
        if kind == 'extend':
            return _extend(args[0], state, now)
        if kind == 'stop':
            return _stop(state, now)
        if kind == 'left':
            return _how_long(state, now, text)
        if kind == 'pause':
            return _pause(args[0], state, now)
        if kind == 'stop_pause':
            return _stop_pause(state)
        if kind == 'accept':
            return _accept(args[0], state, now)
    except OSError:
        return NOT_SAVED, None
    return 'Tudo bem.', None
