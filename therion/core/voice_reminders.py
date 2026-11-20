"""Lembretes por voz: entende "quando" e "o quê" das frases, sem Qt e com relógio injetado.

A frase é lida numa cópia sem acento e em minúsculas (mesmo tamanho da original, letra a letra),
então o texto do lembrete sai com a capitalização que o usuário falou.
"""
import json
import os
import re
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

from therion.calendar.adapter import CalendarError
from therion.calendar.dialogue import _SPOKEN, _SPOKEN_PATTERN, parse_day, parse_time
from therion.calendar.spoken import spoken_date
from therion.context.language import control

MAX_TEXT = 200
SOON_MINUTES = 10
_WEEKDAYS = ('segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo')
_WD = r'(?:' + '|'.join(_WEEKDAYS) + r')s?(?:-feiras?)?'
_WD_LIST = rf'{_WD}(?:(?:\s*,\s*|\s+e\s+){_WD})*'
_N = rf'(?:\d{{1,2}}|{_SPOKEN_PATTERN})'
_COUNT = rf'(?:\d+|{_SPOKEN_PATTERN})'

_TRIGGER = re.compile(
    r'^\s*(?:(?:therion|por favor)[,\s]+)*'
    r'(?:me (?:lembra|lembre|avisa|avise|chama)|(?:lembra|lembre)-me|(?:cria|crie|criar)(?: um)? lembrete|lembrete\s*:)(?!\w)')
_DAILY = re.compile(r'(?<!\w)(?:todos os dias|todos dias|todo (?:santo )?dia|diariamente)(?!\w)')
_RANGE = re.compile(r'(?<!\w)(?:de\s+)?segunda\s+a\s+sexta(?:-feira)?(?!\w)|(?<!\w)(?:nos\s+)?dias\s+uteis(?!\w)')
_WEEKEND = re.compile(r'(?<!\w)(?:(?:no\s+)?(?:fim|fins)\s+de\s+semana|sabados?\s+e\s+domingos?)(?!\w)')
_EVERY = re.compile(rf'(?<!\w)tod[ao]s?\s+(?:(?:as|os)\s+)?({_WD_LIST})(?!\w)')
_PLURAL = re.compile(rf'(?<!\w)as\s+((?:{"|".join(_WEEKDAYS)})s(?:-feiras)?(?:(?:\s*,\s*|\s+e\s+){_WD})*)(?!\w)')
_RELATIVE = re.compile(
    rf'(?<!\w)(?:em|daqui\s+a)\s+(?:(?P<soon>pouco)|(?P<half>meia\s+hora)'
    rf'|(?P<n>{_COUNT})\s*(?P<unit>horas?|h|minutos?|min)(?:\s+e\s+(?:(?P<more_half>meia)|(?P<more>{_COUNT})(?:\s*(?:minutos?|min))?))?)(?!\w)')
_PHRASE = (rf'{_N}(?:h\d{{2}}|:\d{{2}}|h|\s+horas?)?(?:\s+(?:e\s+)?(?:{_N}|meia)(?:\s+minutos?)?)?'
           r'(?:\s+(?:da|de)\s+(?:manha|tarde|noite|madrugada))?')
_DAY = r'depois\s+de\s+amanha|amanha|hoje|(?:proxim[ao]\s+)?' + rf'(?:{"|".join(_WEEKDAYS)})(?:-feira)?(?:\s+que\s+vem)?|dia\s+\d{{1,2}}'
_CLOCK = re.compile(
    rf'(?<!\w)(?:(?P<day>{_DAY})\s+)?(?:(?:as|ao)\s+|a\s+(?=meia[\s-]?noite|\d{{1,2}}(?:h|:\d|\s+da\s)|(?:uma|duas)\s+(?:horas?|da\s)|{_N}\s*$))(?:(?P<noon>meio[\s-]?dia)|(?P<mid>meia[\s-]?noite)|(?P<t>{_PHRASE}))(?!\w|:)')
_DAY_ONLY = re.compile(rf'(?<!\w)(?P<day>{_DAY})(?!\w|/)')
_PERIOD = re.compile(r'\s(?:da|de)\s+(?:manha|tarde|noite|madrugada)$')


@dataclass(frozen=True)
class Repeat:
    days: tuple[int, ...]  # weekday(): 0 = segunda
    time: str              # "HH:MM"; vazio enquanto falta a hora


@dataclass(frozen=True)
class Parsed:
    kind: str  # 'create' | 'need_when' | 'need_what' | 'need_period' | 'invalid'
    text: str | None = None
    due: datetime | None = None
    repeat: Repeat | None = None
    hour: int | None = None
    question: str | None = None
    day: date | None = None  # dia dito sem hora (need_when)
    minute: int = 0          # minutos da hora ambígua (need_period)


def _fold(text):
    out = []
    for char in text:
        folded = ''.join(c for c in unicodedata.normalize('NFD', char.casefold()) if unicodedata.category(c) != 'Mn')
        out.append(folded if len(folded) == 1 else char)
    return ''.join(out)


def _count(raw):
    return int(raw) if raw.isdigit() else _SPOKEN[raw]


def _weekdays(raw):
    return tuple(sorted({_WEEKDAYS.index(name) for name in re.findall('|'.join(_WEEKDAYS), raw)}))


def next_due(repeat, after):
    hour, minute = map(int, repeat.time.split(':'))
    base = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for offset in range(8):
        candidate = base + timedelta(days=offset)
        if candidate > after and candidate.weekday() in repeat.days:
            return candidate
    raise ValueError('Repeat sem dias')


def _day_date(token, hour_minute, now):
    """(data, é_dia_da_semana). Dia já passado hoje vira a próxima ocorrência."""
    token = ' '.join(token.split())
    if token.startswith('dia '):
        number = int(token[4:])
        year, month = now.year, now.month
        for _ in range(13):
            try:
                found = date(year, month, number)
                if datetime.combine(found, datetime.min.time().replace(hour=hour_minute[0], minute=hour_minute[1])) > now.replace(tzinfo=None):
                    return found, False
            except ValueError:
                pass
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        raise CalendarError('Data inválida. Informe outra data.')
    if token == 'depois de amanha':
        return now.date() + timedelta(days=2), False
    weekday = token.endswith('que vem') or token.startswith('proxim') or any(token.startswith(n) for n in _WEEKDAYS)
    if token.endswith(' que vem'):
        token = 'proxima ' + token[:-len(' que vem')]
    return parse_day(token, now), weekday


def _resolve_due(day, hour, minute, ambiguous, now):
    if day:
        hours = [hour, hour + 12] if ambiguous else [hour]
        found, weekday = _day_date(day, (hours[-1], minute), now)
        for extra in ((0, 7) if weekday else (0,)):
            for h in hours:
                due = datetime(found.year, found.month, found.day, h, minute, tzinfo=now.tzinfo) + timedelta(days=extra)
                if due > now:
                    return due
        raise CalendarError('Esse horário já passou. Informe outra data ou horário.')
    hours = [hour, hour + 12] if ambiguous else [hour]
    for offset in (0, 1):
        for h in hours:
            due = now.replace(hour=h, minute=minute, second=0, microsecond=0) + timedelta(days=offset)
            if due > now:
                return due
    raise CalendarError('Horário inválido.')  # inalcançável: amanhã sempre é futuro


def parse_reminder(command, now):
    """Parsed, ou None quando não é pedido de lembrete (inclusive "me lembra que X" sem tempo = memória)."""
    original = command.strip().rstrip('.!?').rstrip()
    folded = _fold(original)
    trigger = _TRIGGER.match(folded)
    if not trigger:
        return None
    work = list(folded)

    def take(pattern, start=None):
        match = pattern.search(''.join(work), trigger.end() if start is None else start)
        if match:
            for i in range(match.start(), match.end()):
                work[i] = ' '
        return match

    take(re.compile(r',?\s+por favor$'))
    # Repetição
    days = None
    if m := take(_RANGE):
        days = (0, 1, 2, 3, 4)
    elif m := take(_WEEKEND):
        days = (5, 6)
    elif m := take(_EVERY):
        days = _weekdays(m[1])
    elif m := take(_PLURAL):
        days = _weekdays(m[1])
    elif take(_DAILY):
        days = (0, 1, 2, 3, 4, 5, 6)
    # Relativo
    minutes = None
    if rel := (None if days else take(_RELATIVE)):
        if rel['soon']:
            minutes = SOON_MINUTES
        elif rel['half']:
            minutes = 30
        else:
            hours = rel['unit'].startswith('h')
            minutes = _count(rel['n']) * (60 if hours else 1)
            if hours and rel['more_half']:
                minutes += 30
            elif hours and rel['more']:
                minutes += _count(rel['more'])
    # Hora (com dia opcional antes)
    clock = take(_CLOCK)
    day = ' '.join(clock['day'].split()) if clock and clock['day'] else None
    if not day and not minutes:
        if only := take(_DAY_ONLY):
            day = only['day']
    rest = ''.join(work[trigger.end():])
    when = bool(days or minutes is not None or clock)
    if not when and re.match(r'\s*que\b', rest):
        return None  # memória: "me lembra que X"
    shown = ''.join(c if work[i] != ' ' or c == ' ' else ' ' for i, c in enumerate(original))[trigger.end():]
    text = re.sub(r'\s+', ' ', shown).strip()
    text = re.sub(r'^[,:;\s]+', '', text)
    text = re.sub(r'^(?:(?:de|para|pra|que)\b\s*)+', '', text, flags=re.I)
    text = re.sub(r'[\s,.;:!?]+$', '', text) or None
    if text and len(text) > MAX_TEXT:
        return Parsed('invalid', question='O lembrete pode ter até 200 caracteres.')
    repeat = Repeat(days, '') if days else None
    if not when or (days and not clock):
        found = None
        if day and not clock:
            try:
                found = _day_date(day, (23, 59), now)[0]
            except CalendarError as err:
                return Parsed('invalid', question=str(err))
        return Parsed('need_when', text, repeat=repeat, day=found)
    hour = minute = None
    ambiguous = False
    if clock:
        try:
            if clock['noon']:
                hour, minute = 12, 0
            elif clock['mid']:
                hour, minute = 0, 0
            else:
                phrase = clock['t']
                hour, minute = parse_time(phrase)
                ambiguous = 1 <= hour <= 11 and not _PERIOD.search(phrase) and not re.search(r'\d(?:h|:)', phrase)
        except CalendarError as err:
            return Parsed('invalid', question=str(err))
    if days:
        if ambiguous:
            return Parsed('need_period', text, repeat=Repeat(days, ''), hour=hour, minute=minute)
        repeat = Repeat(days, f'{hour:02d}:{minute:02d}')
        due = next_due(repeat, now)
    elif minutes is not None:
        due = now + timedelta(minutes=minutes)
    else:
        try:
            due = _resolve_due(day, hour, minute, ambiguous, now)
        except CalendarError as err:
            return Parsed('invalid', question=str(err))
    if not text:
        return Parsed('need_what', None, due, repeat)
    return Parsed('create', text, due, repeat)


# --- depósito -------------------------------------------------------------------------------------------------
MAX_ITEMS = 50
ON_TIME = timedelta(minutes=2)
TOO_OLD = timedelta(days=7)
_NUMBERS = ('zero', 'um', 'dois', 'três', 'quatro', 'cinco', 'seis', 'sete', 'oito', 'nove', 'dez')


@dataclass(frozen=True)
class Reminder:
    id: str
    text: str
    due: datetime
    repeat: Repeat | None
    created: datetime


def _to_json(item):
    repeat = {'days': list(item.repeat.days), 'time': item.repeat.time} if item.repeat else None
    return dict(id=item.id, text=item.text, due=item.due.isoformat(timespec='seconds'), repeat=repeat,
                created=item.created.isoformat(timespec='seconds'))


def _from_json(row):
    repeat = row['repeat']
    return Reminder(str(row['id']), str(row['text']), datetime.fromisoformat(row['due']),
                    Repeat(tuple(repeat['days']), repeat['time']) if repeat else None,
                    datetime.fromisoformat(row['created']))


class ReminderStore:
    def __init__(self, path=None):
        self._path = Path(path) if path else Path(os.environ['LOCALAPPDATA']) / 'Therion' / 'lembretes.json'
        self._lock = threading.Lock()
        self.broken_notice = None
        self._items = []
        self._loaded = False  # enquanto a leitura não deu certo, nada grava (senão sobrescreve o arquivo)
        self.reload()

    def reload(self):
        with self._lock:
            self._load()

    def _load(self):
        items = self._read()
        if items is not None:
            self._items, self._loaded = items, True
        return self._loaded

    def _read(self):
        """Lista lida; [] se não há arquivo; None se a leitura falhou agora (tenta de novo no próximo reload)."""
        try:
            raw = self._path.read_bytes()
        except FileNotFoundError:
            return []
        except OSError:
            return None
        try:
            data = json.loads(raw.decode('utf-8'))
            if data['version'] != 1:
                raise ValueError('versão')
            return sorted((_from_json(row) for row in data['items']), key=lambda item: item.due)
        except (ValueError, KeyError, TypeError):
            return self._quarantine()

    def _quarantine(self):
        kept = self._path.with_name(f'{self._path.name}.bad-{datetime.now():%Y%m%d-%H%M%S}')
        try:
            os.replace(self._path, kept)
        except OSError:
            return None   # sem mover, nada grava: o arquivo estragado nunca é sobrescrito
        self.broken_notice = f'Não consegui ler seus lembretes antigos; guardei o arquivo como {kept.name}.'
        return []

    def _write(self, items):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(self._path.name + '.tmp')
        try:
            with open(temporary, 'w', encoding='utf-8') as file:
                json.dump({'version': 1, 'items': [_to_json(item) for item in items]}, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self._path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def items(self):
        with self._lock:
            return list(self._items)

    def add(self, text, due, repeat, now):
        with self._lock:
            if not (self._loaded or self._load()):
                raise OSError('Não consegui ler os lembretes agora.')
            if len(self._items) >= MAX_ITEMS:
                raise ValueError(f'Você já tem {MAX_ITEMS} lembretes; cancele algum antes.')
            taken = {item.id for item in self._items}
            while (new_id := 'r-' + secrets.token_hex(2)) in taken:
                pass
            item = Reminder(new_id, text, due, repeat, now)
            items = sorted([*self._items, item], key=lambda x: x.due)
            self._write(items)
            self._items = items
            return item

    def remove(self, ids):
        ids = set(ids)
        with self._lock:
            if not (self._loaded or self._load()):
                raise OSError('Não consegui ler os lembretes agora.')
            gone = [item for item in self._items if item.id in ids]
            if gone:
                items = [item for item in self._items if item.id not in ids]
                self._write(items)
                self._items = items
            return gone

    def take_due(self, now):
        """(na hora, atrasados, quantos passaram de 7 dias). Os que repetem contam uma vez, na ocorrência mais recente."""
        on_time, late, old = [], [], 0
        with self._lock:
            if not (self._loaded or self._load()):
                return [], [], 0
            keep = []
            for item in self._items:
                if item.due > now:
                    keep.append(item)
                    continue
                if item.repeat:
                    latest = item.due
                    while (following := next_due(item.repeat, latest)) <= now:
                        latest = following
                    item = replace(item, due=latest)
                    keep.append(replace(item, due=next_due(item.repeat, now)))
                lateness = now - item.due
                if lateness <= ON_TIME:
                    on_time.append(item)
                elif lateness <= TOO_OLD:
                    late.append(item)
                else:
                    old += 1
            if len(keep) != len(self._items) or on_time or late or old:
                self._items = sorted(keep, key=lambda x: x.due)
                try:
                    self._write(self._items)
                except OSError:
                    pass  # fala mesmo assim; no pior caso repete depois de reiniciar
        late.sort(key=lambda item: item.due)
        return on_time, late, old

    def next_time(self):
        with self._lock:
            return self._items[0].due if self._items else None

    def mtime(self):
        try:
            return self._path.stat().st_mtime
        except OSError:
            return None


_shared = None
_shared_lock = threading.Lock()


def store():
    """Instância única, para o orchestrator e a janela enxergarem o mesmo depósito."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = ReminderStore()
        return _shared


def _number(count):
    return _NUMBERS[count] if count < len(_NUMBERS) else str(count)


def due_message(reminders):
    if len(reminders) == 1:
        return f'Lembrete: {reminders[0].text}.'
    return f'{_number(len(reminders)).capitalize()} lembretes: ' + '; '.join(r.text for r in reminders) + '.'


def late_message(late, old):
    more = f' e mais {old} antigo{"s" if old != 1 else ""}' if old else ''
    if not late:
        if not old:
            return None
        return ('Passou 1 lembrete antigo' if old == 1 else f'Passaram {old} lembretes antigos') + ' enquanto eu estava fechado.'
    if len(late) > 3:
        names = ', '.join(r.text for r in late[:3])
        return f'Passaram {len(late)} lembretes enquanto eu estava fechado: {names} e mais {len(late) - 3}{more}.'
    shown = '; '.join(f'{r.text} ({r.due:%H:%M})' for r in late)
    return f'Enquanto eu estava fechado, passou da hora de: {shown}{more}.'


# --- frases: criar, perguntar, listar, cancelar, adiar -------------------------------------------------------
PENDING_SECONDS = 120
SNOOZE_SECONDS = 300
TERMINAL_MESSAGE = 'Lembretes e foco funcionam com a janela do Therion aberta.'
NOT_SAVED = 'Não consegui salvar o lembrete agora.'
_DAY_NAMES = ('segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo')
_HOURS = ('', 'Uma', 'Duas', 'Três', 'Quatro', 'Cinco', 'Seis', 'Sete', 'Oito', 'Nove', 'Dez', 'Onze')
_ORDINALS = {'primeiro': 1, 'primeira': 1, 'segundo': 2, 'segunda': 2, 'terceiro': 3, 'terceira': 3, 'quarto': 4, 'quinta': 5, 'quinto': 5}
_STOP = {'nao', 'nao precisa', 'agora nao', 'deixa', 'deixa assim', 'deixa pra la', 'deixa quieto', 'esquece', 'nada', 'nao obrigado'}
_YES = {'sim', 'pode', 'pode sim', 'sim pode', 'claro', 'pode cancelar', 'sim cancela', 'cancela', 'cancela tudo', 'isso', 'manda'}
_LISTED = r'(?:os\s+)?(?:meus\s+)?lembretes'
_LIST = re.compile(
    rf'^(?:(?:quais|que)\s+(?:sao\s+)?{_LISTED}(?:\s+(?:eu\s+)?(?:tenho|tem|marcados|ativos))?'
    rf'|(?:os\s+)?meus\s+lembretes|os\s+lembretes'
    r'|(?:eu\s+)?(?:tem|tenho|ha)\s+(?:algum|algo)\s+lembrete(?:\s+(?:marcado|ativo))?'
    rf'|(?:lista|liste|listar|mostra|mostre|mostrar|le|leia|ler|diz|diga)(?:\s+(?:pra|para)\s+mim)?\s+{_LISTED})$')
_CANCEL = re.compile(
    r'^(?:cancela|cancele|cancelar|apaga|apague|apagar|remove|remova|exclui|exclua)\s+(?P<all>(?:todos|todas)\s+)?'
    r'(?:(?:o|os)\s+)?(?:meus?\s+)?(?P<noun>lembretes?)(?!\w)\s*(?P<rest>.*)$')
_AMOUNT = rf'(?:(?:em|daqui\s+a|por)\s+)?(?:pouco|meia\s+hora|{_COUNT}\s*(?:horas?|h|minutos?|min))'
_SNOOZE_VERB = re.compile(
    r'^(?:(?:me\s+)?(?:adia|adie|adiar)(?:\s+(?:isso|o\s+lembrete|ai))?|me\s+(?:lembra|lembre|avisa|avise)\s+(?:de\s+novo|outra\s+vez))'
    rf'(?:\s+(?P<amount>{_AMOUNT}))?$')
_SNOOZE_BARE = re.compile(rf'^(?P<amount>(?:em|daqui\s+a)\s+(?:pouco|meia\s+hora|{_COUNT}\s*(?:horas?|h|minutos?|min)))$')
_PERIOD_WORD = re.compile(r'^(?:(?:da|de)\s+)?(manha|madrugada|tarde|noite)$')
_ORDER = re.compile(r'^(?:(?:o|a|numero)\s+)?(\w+)$')


def _hm(hour, minute):
    return f'{hour}h' + (f'{minute:02d}' if minute else '')


def _clock(hour, minute):
    if (hour, minute) == (0, 0):
        return 'à meia-noite'
    if (hour, minute) == (12, 0):
        return 'ao meio-dia'
    return f'{"à" if hour == 1 else "às"} {_hm(hour, minute)}'


def _weekday_date(day):
    return f'{_DAY_NAMES[day.weekday()]}, {spoken_date(day)}'


def _when(due, now):
    clock = _clock(due.hour, due.minute)
    delta = (due.date() - now.date()).days
    if delta == 0:
        return f'hoje {clock}'
    if delta == 1:
        return f'amanhã, {_DAY_NAMES[due.weekday()]}, {clock}'
    return f'{_weekday_date(due.date())}, {clock}'


def _next_day(due, now):
    delta = (due.date() - now.date()).days
    return 'hoje' if delta == 0 else 'amanhã' if delta == 1 else _weekday_date(due.date())


def _repeat_label(repeat):
    days = tuple(repeat.days)
    if days == (0, 1, 2, 3, 4, 5, 6):
        label = 'todo dia'
    elif days == (0, 1, 2, 3, 4):
        label = 'dias úteis'
    elif days == (5, 6):
        label = 'fim de semana'
    else:
        names = [_DAY_NAMES[d] for d in days]
        label = ('todo ' if days[0] >= 5 else 'toda ') + (names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' e ' + names[-1])
    hour, minute = map(int, repeat.time.split(':'))
    return f'{label} {_clock(hour, minute)}'


def _label(item, now):
    return _repeat_label(item.repeat) if item.repeat else _when(item.due, now)


def _duration(minutes):
    if minutes < 60:
        return f'{minutes} minuto{"" if minutes == 1 else "s"}'
    hours, rest = divmod(minutes, 60)
    return f'{hours} hora{"" if hours == 1 else "s"}' + (f' e {rest} minuto{"" if rest == 1 else "s"}' if rest else '')


def _created_message(item, minutes, now):
    if item.repeat:
        return f'Combinado: {_repeat_label(item.repeat)}, {item.text}. O próximo é {_next_day(item.due, now)}.'
    if minutes is not None:
        when = _clock(item.due.hour, item.due.minute) if item.due.date() == now.date() else _when(item.due, now)
        return f'Combinado: em {_duration(minutes)}, {when}, {item.text}.'
    return f'Combinado: {_when(item.due, now)}, {item.text}.'


def _repeat_phrase(days):
    if tuple(days) == (0, 1, 2, 3, 4, 5, 6):
        return 'todo dia'
    if tuple(days) == (0, 1, 2, 3, 4):
        return 'dias uteis'
    if tuple(days) == (5, 6):
        return 'fim de semana'
    return 'toda ' + ' e '.join(_WEEKDAYS[d] for d in days)


def _day_phrase(day, now):
    delta = (day - now.date()).days
    return 'hoje' if delta == 0 else 'amanha' if delta == 1 else f'dia {day.day}'


def _relative_minutes(command, due, repeat, now):
    if repeat or not _RELATIVE.search(_fold(command)):
        return None
    return round((due - now).total_seconds() / 60)


def _from_parsed(parsed, command, now):
    if parsed.kind == 'invalid':
        return ('say', parsed.question)
    if parsed.kind == 'need_when':
        return ('ask', 'Que horas?' if parsed.repeat else 'Quando eu te lembro?', 'when', (parsed.text, parsed.repeat, parsed.day))
    if parsed.kind == 'need_period':
        return ('ask', f'{_HOURS[parsed.hour]} da manhã ou da tarde?', 'period', (parsed.text, parsed.repeat, parsed.hour, parsed.minute))
    minutes = _relative_minutes(command, parsed.due, parsed.repeat, now)
    if parsed.kind == 'need_what':
        return ('ask', 'Te lembro do quê?', 'what', (parsed.due, parsed.repeat, minutes))
    return ('create', parsed.text, parsed.due, parsed.repeat, minutes)


def _fresh(command, text, now):
    """A frase abre uma conversa de lembrete (criar, listar ou cancelar)? Ação ou None."""
    if _LIST.match(text):
        return ('list',)
    if found := _CANCEL.match(text):
        return ('cancel', found['rest'], bool(found['all']) or (found['noun'] == 'lembretes' and not found['rest']))
    parsed = parse_reminder(command, now)
    if parsed is None:
        return None
    bare = parsed.kind == 'need_when' and not parsed.day and not parsed.repeat
    if bare and (text.startswith('me chama') or (parsed.text is None and re.match(r'(?:cria|crie|criar)\b', text))):
        return None  # "me chama de Fulano" não é lembrete; "crie um lembrete" puro segue o fluxo da agenda (compromisso ou aviso)
    return _from_parsed(parsed, command, now)


def _words(text, size=4):
    return {word for word in re.findall(r'[a-z0-9]+', _fold(text)) if len(word) >= size}


def _item_time(item):
    return item.repeat.time if item.repeat else f'{item.due:%H:%M}'


def _match(items, qualifier, size=4):
    """Lembretes que a frase aponta: mais palavras em comum, ou a mesma hora. Sem nada dito, todos."""
    if not qualifier.strip():
        return list(items)
    folded = _fold(qualifier)
    words = _words(folded, size)
    pool = list(items)
    if clock := re.search(r'(?<!\w)(?:das|as|a|ao|do)\s+(\d{1,2})(?:h|:)?(\d{2})?(?!\w)', folded):
        pool = [item for item in pool if _item_time(item) == f'{int(clock[1]):02d}:{clock[2] or "00"}']
        if not words:
            return pool
    scores = {item.id: len(words & _words(item.text, size)) for item in pool}
    best = max(scores.values(), default=0)
    if best == 0:
        return pool if clock and pool else []
    return [item for item in pool if scores[item.id] == best]


def _amount_phrase(amount):
    amount = re.sub(r'^(?:em|daqui\s+a|por)\s+', '', amount or 'pouco')
    return 'daqui a pouco' if amount == 'pouco' else 'em ' + amount


def _followup(command, text, kind, data, now):
    """Resposta à pergunta pendente, ou None quando a frase não é a resposta."""
    if kind == 'when':
        old_text, repeat, day = data
        prefix = 'me lembra de x ' + (_repeat_phrase(repeat.days) + ' ' if repeat else _day_phrase(day, now) + ' ' if day else '')
        parsed = parse_reminder(prefix + command, now)
        if parsed is not None and parsed.kind == 'need_when' and parsed.text == 'x' and parsed.day and not parsed.repeat:
            return ('ask', 'Que horas?', 'when', (old_text, None, parsed.day))   # só o dia: guarda o dia e pergunta a hora
        if parsed is None or parsed.kind == 'need_when' or (parsed.kind != 'invalid' and parsed.text != 'x'):
            return None
        if parsed.kind == 'invalid':
            return ('say', parsed.question)
        if parsed.kind == 'need_period':
            return ('ask', f'{_HOURS[parsed.hour]} da manhã ou da tarde?', 'period', (old_text, parsed.repeat, parsed.hour, parsed.minute))
        minutes = _relative_minutes(command, parsed.due, parsed.repeat, now)
        if old_text is None:
            return ('ask', 'Te lembro do quê?', 'what', (parsed.due, parsed.repeat, minutes))
        return ('create', old_text, parsed.due, parsed.repeat, minutes)
    if kind == 'what':
        due, repeat, minutes = data
        if _fresh(command, text, now) is not None:
            return None
        if text in _STOP:
            return ('say', 'Tudo bem.')
        cleaned = re.sub(r'^(?:(?:de|para|pra|que)\b\s*)+', '', command.strip().rstrip('.!?').rstrip(), flags=re.I).strip()
        if not cleaned:
            return None
        if len(cleaned) > MAX_TEXT:
            return ('say', 'O lembrete pode ter até 200 caracteres.')
        return ('create', cleaned, due, repeat, minutes)
    if kind == 'period':
        old_text, repeat, hour, minute = data
        if word := _PERIOD_WORD.match(text):
            hour = hour + 12 if word[1] in ('tarde', 'noite') else hour
        else:
            try:
                hour, minute = parse_time(text)
            except CalendarError:
                return None
            if 1 <= hour <= 11 and not re.search(r'\d(?:h|:)', text):
                return None  # continua ambígua
        repeat = Repeat(repeat.days, f'{hour:02d}:{minute:02d}')
        due = next_due(repeat, now)
        if old_text is None:
            return ('ask', 'Te lembro do quê?', 'what', (due, repeat, None))
        return ('create', old_text, due, repeat, None)
    if kind == 'pick':
        order = _ORDER.match(text)
        number = None
        if order:
            word = order[1]
            number = int(word) if word.isdigit() else _ORDINALS.get(word, _SPOKEN.get(word))
        if number is not None and 1 <= number <= len(data):
            return ('remove', [data[number - 1].id])
        found = _match(data, text, 3)
        return ('remove', [found[0].id]) if len(found) == 1 else None
    if kind == 'cancel_all':
        if text in _YES:
            return ('remove', list(data))
        return ('say', 'Tudo bem.') if text in _STOP else None
    return None


def _classify(command, host, now):
    """Para onde vai a frase, sem efeito colateral: (ação, …) ou None."""
    text = control(command).replace(',', '')   # a transcrição põe vírgulas: "Sim, pode."
    pending =getattr(host, '_reminder_pending', None)
    if pending and time.monotonic() < pending[0]:
        if found := _followup(command, text, pending[1], pending[2], now):
            return found
    snooze = getattr(host, '_reminder_snooze', None)
    if snooze and time.monotonic() < snooze[0] and (found := _SNOOZE_VERB.match(text) or _SNOOZE_BARE.match(text)):
        return ('snooze', snooze[1], found['amount'])
    return _fresh(command, text, now)


def reminder_request(command, host, now=None):
    """Sem efeito: a frase é desta rota? (o agente deixa a rota local responder)."""
    return _classify(command, host, now or datetime.now()) is not None


def snooze_window(host, reminder_text):
    """A janela chama quando um lembrete toca: por 5 min, "adia 10 minutos" reagenda o mesmo texto."""
    host._reminder_snooze = (time.monotonic() + SNOOZE_SECONDS, reminder_text)


def _create(host, text, due, repeat, minutes, now):
    try:
        item = store().add(text, due, repeat, now)
    except ValueError as err:
        return str(err)
    except OSError:
        return NOT_SAVED
    host._reminders_changed = True
    return _created_message(item, minutes, now)


def _remove(host, ids, now):
    try:
        gone = store().remove(ids)
    except OSError:
        return NOT_SAVED
    if not gone:
        return 'Não achei esse lembrete.'
    host._reminders_changed = True
    if len(gone) == 1:
        return f'Cancelei: {gone[0].text} ({_label(gone[0], now)}).'
    return f'Cancelei os {len(gone)} lembretes.'


def _cancel(host, qualifier, everything, now):
    items = store().items()
    if not items:
        return 'Nenhum lembrete marcado.'
    found = items if everything else _match(items, qualifier)
    if not found:
        return 'Não achei esse lembrete.'
    if len(found) == 1:
        return _remove(host, [found[0].id], now)
    if everything:
        host._reminder_pending = (time.monotonic() + PENDING_SECONDS, 'cancel_all', tuple(item.id for item in found))
        return f'Cancelo os {len(found)} lembretes?'
    host._reminder_pending = (time.monotonic() + PENDING_SECONDS, 'pick', tuple(found))
    return 'Qual deles? ' + ' '.join(f'{number}) {_label(item, now)}, {item.text}' for number, item in enumerate(found, 1))


def _snooze(host, text, amount, now):
    parsed = parse_reminder('me lembra ' + _amount_phrase(amount), now)
    if parsed is None or parsed.due is None:
        return None
    minutes = round((parsed.due - now).total_seconds() / 60)
    message = _create(host, text, parsed.due, None, minutes, now)
    if message.startswith('Combinado'):
        host._reminder_snooze = None
    return message


def answer(command, host, now=None):
    """Resposta pronta ou None. Perguntas pendentes valem 2 min e só para a próxima frase."""
    now = now or datetime.now()
    action = _classify(command, host, now)
    if getattr(host, '_reminder_pending', None) is not None:
        host._reminder_pending = None
    if action is None:
        return None
    if not getattr(host, 'desktop_timers', False):
        return TERMINAL_MESSAGE
    kind = action[0]
    if kind == 'say':
        return action[1]
    if kind == 'ask':
        host._reminder_pending = (time.monotonic() + PENDING_SECONDS, action[2], action[3])
        return action[1]
    if kind == 'create':
        return _create(host, *action[1:], now)
    if kind == 'remove':
        return _remove(host, action[1], now)
    if kind == 'cancel':
        return _cancel(host, action[1], action[2], now)
    if kind == 'snooze':
        return _snooze(host, action[1], action[2], now)
    items = store().items()
    if not items:
        return 'Nenhum lembrete marcado.'
    return f'Você tem {len(items)} lembrete{"" if len(items) == 1 else "s"}: ' + '; '.join(f'{_label(item, now)}, {item.text}' for item in items) + '.'
