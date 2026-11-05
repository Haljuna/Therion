"""Consulta de tarefas pendentes, somente leitura e com a mesma fonte do panorama.

Sem isso a pergunta caía no modelo, que podia negar uma tarefa que o panorama acabou de citar.
"""
import re

MAX_SPOKEN = 6
# Verbos de escrita ficam com o agente, que tem confirmação e recibos.
_WRITE = re.compile(r'\b(?:cri\w*|adicion\w*|anot\w*|inclu\w*|conclu\w*|termin\w*|marc\w*|complet\w*|'
                    r'apag\w*|remov\w*|exclu\w*|delet\w*|feit[ao]s?|finaliz\w*|edit\w*|alter\w*|mud\w*|renome\w*)\b')
_TASK = re.compile(r'\btarefas?\b')
# A transcrição troca o verbo inicial com frequência ("Come a tarefa pendente"); o pedido
# continua claro quando fala de tarefa pendente ou usa uma pista de consulta.
_READ_CUE = re.compile(r'\b(?:pendentes?|minhas?|quais|qual|tenho|lista|listar|mostr\w*|lei\w*|ler|fal\w*|'
                       r'coment\w*|diga|diz|ver|veja|sobre|existe|ha)\b')


# Pedidos compostos ("agenda e tarefas") ficam com o fluxo de workflows.
_OTHER_SUBJECT = re.compile(r'\b(?:agenda|compromissos?|eventos?|calendario|notas?|e-?mails?|segundo cerebro)\b')


def task_query_request(command):
    """Só cobre o que o fluxo de tarefas da sessão não reconhece e que cairia no modelo."""
    from therion.context.language import control
    from therion.memory.session_tasks import task_request
    text = control(command)
    words = text.split()
    if (not words or len(words) > 10 or not _TASK.search(text) or _WRITE.search(text)
            or _OTHER_SUBJECT.search(text) or task_request(command) is not None):
        return False
    return bool(_READ_CUE.search(text))


_STATE = re.compile(
    r'(?:(conclu\w*|complet\w*|finaliz\w*|termin\w*)|(reabr\w*)|marqu\w*|marc\w*|deix\w*)\s+(?:a\s+)?tarefa(?:\s+(.*?))?'
    r'(?:\s+como\s+(concluida|concluido|feita|feito|pendente))?')


def task_state_request(command):
    """{'state', 'hint'} para concluir/reabrir tarefa SALVA; números e "essa tarefa" ficam com a sessão."""
    from therion.context.language import control
    text = control(command)
    match = _STATE.fullmatch(text)
    if not match:
        return None
    finish, reopen, rest, mark = match.groups()
    if not (finish or reopen or mark):
        return None
    hint = (rest or '').strip()
    if re.fullmatch(r'(?:n(?:umero|[ºo.])\s*)?\d+', hint) or re.fullmatch(r'(?:essa|esta|aquela)', hint):
        return None
    hint = re.sub(r'^(?:pendente|que (?:esta|ta) pendente)$', '', hint).strip()
    state = 'pending' if reopen or mark == 'pendente' else 'completed'
    return {'state': state, 'hint': hint}


def pending_tasks(row):
    saved = [r for r in row.get('saved', []) if r.get('state') != 'completed']
    temporary = [r for r in row.get('temporary', []) if not r.get('completed')]
    return [r['title'] for r in saved + temporary]


def _join(items):
    return items[0] if len(items) == 1 else '; '.join(items[:-1]) + '; e ' + items[-1]


def render(row):
    """Retorna (mensagem na tela, fala)."""
    titles = pending_tasks(row)
    if row.get('state') != 'ready' and not titles:
        text = 'Não consegui consultar as tarefas salvas. ' + (row.get('message') or 'Confira Capacidades.')
        return text, text
    if not titles:
        text = 'Você não tem tarefas pendentes.'
        return text, text
    head = 'Você tem uma tarefa pendente' if len(titles) == 1 else f'Você tem {len(titles)} tarefas pendentes'
    screen = head + ':\n' + '\n'.join(f'{i}. {t}' for i, t in enumerate(titles, 1))
    spoken = head + ': ' + _join([t[:120] for t in titles[:MAX_SPOKEN]]) + '.'
    if len(titles) > MAX_SPOKEN:
        spoken += f' E mais {len(titles) - MAX_SPOKEN} no painel.'
    if row.get('state') != 'ready':
        note = 'As tarefas salvas estão indisponíveis; mostrei só as desta conversa.'
        screen += '\n\n' + note
        spoken += ' ' + note
    return screen, spoken
