"""Interpretação determinística de agenda, sem acesso externo ou síntese de voz."""
import re
import unicodedata
from datetime import date, datetime, timedelta

from therion.calendar.adapter import CalendarError
from therion.context.language import query_control

TIME = r'\d{1,2}(?:(?::|h)\d{2}|h)?'
WEEKDAY = r'(?:segunda|terça|terca|quarta|quinta|sexta|s[aá]bado|domingo)(?:-feira)?'
DATE = rf'(?:pr[oó]xim[ao]\s+)?{WEEKDAY}|amanh[ãa]|hoje|\d{{1,2}}/\d{{1,2}}(?:/\d{{4}})?|dia\s+\d{{1,2}}'
NUMBER = r'(?:uma?|meia|[+-]?\d+(?:[.,]\d+)?)'
DURATION = re.compile(rf'\b(?:por|durante|dura[çc][ãa]o(?:\s+(?:de|para))?)\s+({NUMBER})\s*(horas?|h|minutos?|min)\b(?:\s+e\s+(?:({NUMBER})\s*(?:minutos?|min)\b|(meia)\b))?', re.I)


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold()) if not unicodedata.combining(c))


_UNITS = ('zero','um','dois','tres','quatro','cinco','seis','sete','oito','nove',
          'dez','onze','doze','treze','quatorze','quinze','dezesseis','dezessete','dezoito','dezenove')
_SPOKEN = {word: value for value, word in enumerate(_UNITS)}
_SPOKEN.update({'uma':1,'duas':2,'catorze':14})
for _ten, _word in ((20,'vinte'),(30,'trinta'),(40,'quarenta'),(50,'cinquenta')):
    _SPOKEN[_word] = _ten
    for _unit in range(1,10):
        _SPOKEN[f'{_word} e {_UNITS[_unit]}'] = _ten + _unit
_SPOKEN_PATTERN = '(?:' + '|'.join(word.replace('tres','tr[eê]s') for word in
                                 sorted(map(re.escape,_SPOKEN),key=len,reverse=True)) + ')'


def normalize_spoken_fields(text):
    """Normaliza números somente em expressões explícitas de data/horário."""
    def number(value):
        return int(value) if value.isdigit() else _SPOKEN[normalized(value)]
    n = rf'(?:\d{{1,2}}|{_SPOKEN_PATTERN})'
    year = rf'(?:\d{{4}}|dois mil(?: e)? {_SPOKEN_PATTERN})'
    def day(match):
        raw_year = normalized(match[3])
        year_value = int(raw_year) if raw_year.isdigit() else 2000 + _SPOKEN[re.sub(r'^dois mil(?: e)? ', '', raw_year)]
        return f'{number(match[1]):02d}/{number(match[2]):02d}/{year_value:04d}'
    text = re.sub(rf'\b(?:dia\s+)?({n})\s+(?:do|de)\s+({n})\s+de\s+({year})(?!\w)',day,text,flags=re.I)
    def time(match):
        if re.fullmatch(TIME,match[1],re.I):
            return match[0]
        try:hour,minute=parse_time(match[1])
        except CalendarError:return match[0]
        return f'as {hour:02d}:{minute:02d}'
    phrase=rf'(?:{n})(?:h\d{{2}}|:\d{{2}}|h|\s+horas?)?(?:\s+(?:e\s+)?(?:{n}|meia)(?:\s+minutos?)?)?(?:\s+(?:da|de)\s+(?:manhã|manha|tarde|noite|madrugada))?'
    return re.sub(rf'\b(?:às|as|à|a)\s+({phrase})(?!\w|:)',time,text,flags=re.I)


def parse_day(raw, now):
    value = normalized(normalize_spoken_fields(raw).strip().rstrip('.!?'))
    value = re.sub(r'^(?:na|no|em|de|para)\s+', '', value)
    value = re.sub(r'^(?:a|o)\s+', '', value)
    if value == 'hoje':
        return now.date()
    if value == 'amanha':
        return now.date() + timedelta(days=1)
    if value in {'semana que vem','proxima semana','semana seguinte'}:
        return now.date() + timedelta(days=7-now.weekday())
    weekdays = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
    weekday = re.fullmatch(r'(proxim[ao]\s+)?(' + '|'.join(weekdays) + r')(?:-feira)?', value)
    if weekday:
        offset = (weekdays.index(weekday.group(2)) - now.weekday()) % 7
        return now.date() + timedelta(days=7 if offset == 0 and weekday.group(1) else offset)
    day_only = re.fullmatch(r'dia\s+(\d{1,2})', value)
    explicit = re.fullmatch(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', value)
    try:
        if day_only:
            return date(now.year, now.month, int(day_only.group(1)))
        if explicit:
            return date(int(explicit.group(3) or now.year), int(explicit.group(2)), int(explicit.group(1)))
    except ValueError as err:
        raise CalendarError('Data inválida. Informe outra data.') from err
    raise CalendarError('Não reconheci a data. Informe hoje, amanhã, um dia da semana ou DD/MM/AAAA.')


def parse_time(raw):
    value=normalized(raw.strip().rstrip('.!?'))
    value=re.sub(r'^(?:as|a)\s+', '', value)
    if re.fullmatch(r'dez\s+(?:seis|sete|oito|nove)(?:\s+horas?)?',value):
        raise CalendarError('Esse horário ficou ambíguo na transcrição. Diga novamente usando, por exemplo, dezoito horas ou 18:00.')
    period=re.search(r'\s+(?:da|de)\s+(manha|tarde|noite|madrugada)$',value)
    if period:value=value[:period.start()]
    digits=value.split()
    if len(digits)==4 and all(word in _UNITS[:10] for word in digits):
        value=''.join(str(_SPOKEN[word]) for word in digits)
        value=value[:2]+':'+value[2:]
    match = re.fullmatch(r'(\d{1,2})(?:(?:h|:)(\d{2})|h)?', value, re.I)
    if match:
        hour,minute=int(match[1]),int(match[2] or 0)
    elif value in _SPOKEN:
        hour,minute=_SPOKEN[value],0
    else:
        n=rf'(?:\d{{1,2}}|{_SPOKEN_PATTERN})'
        match=re.fullmatch(rf'({n})(?:\s+horas?)?(?:\s+(?:e\s+)?({n}|meia)(?:\s+minutos?)?)?',value)
        if not match:
            raise CalendarError('Horário inválido. Diga, por exemplo, dezessete e cinquenta, ou 17:50.')
        def number(word):return int(word) if word.isdigit() else _SPOKEN[word]
        hour=number(match[1]);minute=30 if match[2]=='meia' else number(match[2]) if match[2] else 0
    if period:
        if period[1] in {'tarde','noite'} and 1 <= hour < 12:hour+=12
        elif period[1] in {'manha','madrugada'}:
            if hour==12:hour=0
            elif hour>12:raise CalendarError('O horário informado não corresponde ao período da manhã.')
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise CalendarError('Horário inválido. Informe um horário entre 00:00 e 23:59.')
    return hour,minute


def _number(raw):
    return {'um': 1, 'uma': 1, 'meia': .5}.get(raw.casefold(), None) if normalized(raw) in {'um', 'uma', 'meia'} else float(raw.replace(',', '.'))


def extract_fields(text):
    """Retorna texto residual e campos ainda sujeitos à validação do rascunho."""
    text = normalize_spoken_fields(text)
    fields, issues = {}, {}
    if re.search(rf'\b(?:antes|depois)\s+(?:de|das?)\s+(?:\d{{1,2}}|{_SPOKEN_PATTERN})(?:\s|h|:|[.!?]|$)', text, re.I):
        issues['start_time'] = 'Qual é o horário exato de início? Antes ou depois de um horário não define o início da reunião.'
    def store(key, value):
        if key in fields and fields[key] != value:
            issues[key] = 'Há valores diferentes para o mesmo campo. Informe o valor correto.'
        fields[key] = value
    def duration(match):
        value = _number(match.group(1)) * (60 if match.group(2).casefold().startswith('h') else 1)
        if match.group(3):
            value += _number(match.group(3))
        if match.group(4):
            value += .5 * (60 if match.group(2).casefold().startswith('h') else 1)
        store('duration_minutes', value)
        store('duration_explicit', True)
        return ' '
    rest = DURATION.sub(duration, text)
    invalid_duration = re.compile(r'\b(?:por|durante|dura[çc][ãa]o(?:\s+(?:de|para))?)\s+\S+(?:\s+e\s+\S+)?\s*(?:horas?|minutos?|segundos?)\b', re.I)
    if invalid_duration.search(rest):
        issues['duration_minutes'] = 'Não reconheci essa duração. Informe a duração em horas ou minutos, usando números.'
        rest = invalid_duration.sub(' ', rest)
    def interval(match):
        store('start_time', match.group(1))
        store('end_time', match.group(2))
        return ' '
    rest = re.sub(rf'\b(?:das?|de)\s+({TIME})\s+(?:às|as|at[eé])\s+({TIME})(?!\w|:)', interval, rest, flags=re.I)
    def start(match):
        store('start_time', match.group(1))
        return ' '
    rest = re.sub(rf'\b(?:às|as)\s+({TIME})(?:\s+horas?)?(?!\w|:)', start, rest, flags=re.I)
    if re.search(r'\b(?:às|as)\s+[+-]?\d', rest, re.I):
        issues['start_time'] = 'Horário inválido. Informe o horário correto.'
    def day(match):
        store('date', match.group(0))
        return ' '
    rest = re.sub(rf'(?<!\w)(?:{DATE})(?!\w|/)', day, rest, flags=re.I)
    if re.search(r'\b\d{1,2}/\d{1,2}(?:/\d+)?\b', rest):
        issues['date'] = 'Data inválida. Informe a data correta.'
    if issues:
        fields['_issues'] = issues
    rest = re.sub(r'^[,.:\s]+|[,.:\s]+$', '', rest)
    rest = re.sub(r'\s+(?:na|no|em|de|para)$', '', rest, flags=re.I)
    return ' '.join(rest.split()), fields


def event_datetimes(draft, now):
    if draft.get('_issues'):
        raise CalendarError(next(iter(draft['_issues'].values())))
    day = parse_day(draft.get('date', ''), now)
    hour, minute = parse_time(draft.get('start_time', ''))
    start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=now.tzinfo)
    duration = draft.get('duration_minutes', 60)
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 1 <= duration <= 1440 or int(duration) != duration:
        raise CalendarError('Informe uma duração inteira entre 1 e 1440 minutos.')
    end = start + timedelta(minutes=int(duration))
    if 'end_time' in draft:
        end_hour, end_minute = parse_time(draft['end_time'])
        explicit_end = start.replace(hour=end_hour, minute=end_minute)
        if explicit_end <= start:
            raise CalendarError('O término deve ser posterior ao início. Informe outro término ou outra duração.')
        if draft.get('duration_explicit') and explicit_end != end:
            raise CalendarError('O intervalo e a duração são diferentes. Informe qual deseja manter.')
        end = explicit_end
    if start <= now:
        raise CalendarError('Esse horário já passou ou já começou. Informe outra data ou horário.')
    return start, end


def query_request(text):
    clean = query_control(text)
    clean = re.sub(r'^(?:therion|terion)[,\s]+', '', clean)
    clean = re.sub(r'[,\s]+por favor$', '', clean)
    clean = re.sub(
        r'^(?:(?:voce )?pode(?:ria)? )?'
        r'(?:olha|olhe|olhar|confere|confira|consulte|consulta|consultar|veja|ve|ver|verifique|mostra|mostre)\s+'
        r'(?:a\s+)?(?:minha\s+)?agenda(?:\s+(?:pra|para)\s+mim)?'
        r'(?:,?\s+(?:ver|ve|veja|confere|confira|verifique)\s+se\s+(?:eu\s+)?tenho\s+'
        r'(?:(?:alguma?|alguns|algumas)\s+)?(?:coisa|compromissos?|eventos?))?'
        r',?\s+(.+)$', 'agenda '+r'\1', clean)
    clean = re.sub(r'^(?:confere|confira|veja|verifique)\s+(?:se\s+)?(?:eu\s+)?tenho\s+(?:(?:algum|alguns)\s+)?(?:compromissos?|eventos?)\s+', 'agenda ', clean)
    clean = re.sub(r'^(?:tem|ha|existe[m]?)\s+(?:(?:algum|alguns)\s+)?(?:compromissos?|eventos?|reunioes)\s+', 'agenda ', clean)
    clean = re.sub(r'^(?:como (?:esta|ta|ficou) (?:a |minha |a minha )?agenda|(?:eu )?tenho (?:algum |alguns )?(?:compromissos?|eventos?))\s+', 'agenda ', clean)
    clean = re.sub(r'^(?:me (?:mostre|mostra|diga)|(?:pode |voce pode )?(?:consultar|ver|mostrar))\s+(?:a |minha |a minha )?agenda\s+', 'agenda ', clean)
    if re.fullmatch(r'(?:qual (?:e )?(?:o )?(?:meu )?|(?:o )?meu )?proximo compromisso', clean):
        return {'date': 'hoje', 'days': 7, 'next': True}
    match = re.fullmatch(r'(?:(?:(?:minha|a) )?agenda(?: de| para| da| do)?|(?:meus )?(?:compromissos|eventos)(?: de| para| da| do)?|(?:o )?que (?:eu )?tenho)\s+(.+)', clean)
    if not match:
        return None
    requested = re.sub(r'\s+(?:no calendario|na agenda)$', '', match.group(1))
    requested = re.sub(r'^(?:na |a )?agenda (?:para|pra|de|da|do) ', '', requested)
    # "esta semana": de hoje até domingo; o orquestrador calcula os dias restantes.
    if re.fullmatch(r'(?:(?:para|pra|de|da) )?(?:esta|essa|nesta|nessa|desta|dessa) semana', requested):
        return {'date': 'hoje', 'days': 7, 'week': True}
    if re.fullmatch(r'(?:(?:na|a) )?(?:semana que vem|proxima semana|semana seguinte)',requested):
        return {'date':'semana que vem','days':7}
    if re.fullmatch(r'(?:nos |dos |os )?proximos (?:(?:7|sete) )?dias', requested):
        return {'date': 'hoje', 'days': 7}
    return {'date': requested, 'days': 1}


def event_start(event, tz):
    if isinstance(event.start, datetime):
        return event.start.replace(tzinfo=tz) if event.start.tzinfo is None else event.start.astimezone(tz)
    return datetime.combine(event.start, datetime.min.time(), tzinfo=tz)


def partition_events(events, now):
    parts = {'past': [], 'ongoing': [], 'future': [], 'all_day': []}
    for event in sorted(events, key=lambda e: (event_start(e, now.tzinfo), e.summary, e.event_id)):
        if event.all_day:
            parts['all_day'].append(event)
            continue
        start = event_start(event, now.tzinfo)
        end = event.end.replace(tzinfo=now.tzinfo) if event.end.tzinfo is None else event.end.astimezone(now.tzinfo)
        key = 'past' if end <= now else 'ongoing' if start <= now else 'future'
        parts[key].append(event)
    return parts
