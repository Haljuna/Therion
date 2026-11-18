"""Lembretes por voz: entende "quando" e "o quê" das frases, sem Qt e com relógio injetado.

A frase é lida numa cópia sem acento e em minúsculas (mesmo tamanho da original, letra a letra),
então o texto do lembrete sai com a capitalização que o usuário falou.
"""
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from therion.calendar.adapter import CalendarError
from therion.calendar.dialogue import _SPOKEN, _SPOKEN_PATTERN, parse_day, parse_time

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
    rf'(?<!\w)(?:(?P<day>{_DAY})\s+)?(?:as|ao|a)\s+(?:(?P<noon>meio[\s-]?dia)|(?P<mid>meia[\s-]?noite)|(?P<t>{_PHRASE}))(?!\w|:)')
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
        found, weekday = _day_date(day, (hour, minute), now)
        due = datetime(found.year, found.month, found.day, hour, minute, tzinfo=now.tzinfo)
        if due <= now and weekday:
            due += timedelta(days=7)
        if due <= now:
            raise CalendarError('Esse horário já passou. Informe outra data ou horário.')
        return due
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
        return Parsed('need_when', text, repeat=repeat)
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
            return Parsed('need_period', text, repeat=Repeat(days, ''), hour=hour)
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
