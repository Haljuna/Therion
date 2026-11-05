"""Versão falada da agenda: datas e horários como uma pessoa diria; títulos ficam intactos."""

MONTHS = ('janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho',
          'agosto', 'setembro', 'outubro', 'novembro', 'dezembro')
MAX_SPOKEN_EVENTS = 6


def plural_compromissos(count):
    return f"{count} compromisso{'' if count == 1 else 's'}"


def spoken_date(day):
    return f'{day.day} de {MONTHS[day.month - 1]}'


def spoken_day(day, today):
    """'hoje', 'amanhã' ou 'em 20 de novembro' — pronto para seguir um verbo."""
    delta = (day - today).days
    if delta == 0:
        return 'hoje'
    if delta == 1:
        return 'amanhã'
    return 'em ' + spoken_date(day)


def spoken_time(hour, minute):
    if minute == 0:
        if hour == 0:
            return 'à meia-noite'
        if hour == 12:
            return 'ao meio-dia'
        return 'à 1 hora' if hour == 1 else f'às {hour} horas'
    lead = 'à' if hour in (0, 1) else 'às'
    return f'{lead} {hour} e {minute}'


def _join(items):
    if len(items) == 1:
        return items[0]
    return '; '.join(items[:-1]) + '; e ' + items[-1]


def spoken_agenda(entries, first_day, days, today):
    """entries: [(dia, título, (hora, minuto) ou None para dia inteiro)] já ordenadas."""
    if days == 1:
        when = spoken_day(first_day, today)
    else:
        when = f'entre {spoken_date(first_day)} e {spoken_date(first_day.__class__.fromordinal(first_day.toordinal() + days - 1))}'
    if not entries:
        return f'Você não tem compromissos {when}.'
    items = []
    for day, title, clock in entries[:MAX_SPOKEN_EVENTS]:
        moment = 'o dia todo' if clock is None else spoken_time(*clock)
        if days > 1:
            moment = f'dia {day.day}, {moment}'
        items.append(f'{title}, {moment}')
    subject = when[0].upper() + when[1:]
    text = f'{subject} você tem {plural_compromissos(len(entries))}: {_join(items)}.'
    rest = len(entries) - MAX_SPOKEN_EVENTS
    if rest > 0:
        text += f" E mais {rest} no painel."
    return text
