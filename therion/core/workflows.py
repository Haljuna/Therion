"""Interpretação de pedidos compostos; nenhuma ferramenta é executada aqui.

Parâmetros são extraídos novamente pelo código de trechos literais do pedido.
Uma decomposição do provider não pode fornecer ações, argumentos ou permissões.
"""
import re
import time
from dataclasses import dataclass
from datetime import datetime

from therion.calendar.adapter import CalendarError
from therion.calendar.dialogue import parse_day, parse_time, query_request
from therion.context.note_references import normalize, reference_request
from therion.core.intent import IntentRecognizer
from therion.memory.session_tasks import SessionTasks, task_request


class WorkflowError(ValueError):
    """Pedido composto precisa de esclarecimento antes de qualquer execução."""


class _DecompositionError(WorkflowError):
    """Uma segmentação diferente ainda pode ser validada sem inventar dados."""


@dataclass(frozen=True)
class WorkflowStep:
    action: str
    command: str
    arguments: dict
    depends_on: tuple[int, ...] = ()


@dataclass(frozen=True)
class WorkflowSpec:
    steps: tuple[WorkflowStep, ...]


# O lookahead exige outro pedido, evitando separar "pão e leite", títulos e
# durações. Aspas protegem títulos que contenham verbos e conectivos.
_VERBS = (r'veja|ver|consulte|consultar|liste|lista|listar|mostre|mostra|mostrar|'
          r'exiba|procure|procura|procurar|busque|busca|buscar|pesquise|pesquisar|'
          r'leia|ler|abra|abrir|resuma|resume|resumir|adicione|adiciona|adicionar|'
          r'anote|anota|coloque|coloca|conclua|complete|reabra|marque|marcar|'
          r'agende|agendar|crie|criar|prepare|planeje|organize|envie|mande|'
          r'apague|exclua|remova|altere|edite|execute|baixe|instale|salve|guarde')
_START = (r'(?:(?:por favor|tamb[eé]m|primeiro|depois|em seguida|ent[aã]o)[,\s]+)*'
          r'(?:(?:n[aã]o|nunca)\s+)?(?:(?:pode|voc[eê] pode|quero|preciso)\s+)?'
          r'(?:' + _VERBS + r'|o que (?:eu )?tenho|como est[aá] (?:a |minha )?agenda|'
          r'(?:(?:a|minha|a minha)\s+)?agenda|(?:(?:as|minhas)\s+)?tarefas|'
          # 04/11: "quais são minhas tarefas ... e tem algum e-mail importante?"
          r'quais s[aã]o|(?:eu\s+)?(?:queria|quero|gostaria de) saber|'
          r'(?:se\s+)?(?:tem|h[aá]|existe)\s+algum|(?:se\s+)?algum(?:a|as|ns)?\s+(?:e-?mails?|e\s+meios?))\b')
_SEPARATOR = re.compile(
    r'(?:[;\n]+\s*|[.!?]\s+|,\s*(?:e\s+)?|\s+(?:e(?:\s+depois|\s+ent[aã]o)?|'
    r'depois|em\s+seguida|ent[aã]o)\s+)(?=' + _START + ')', re.I)
_GAP = re.compile(r'[\s,;.!?]*(?:(?:e|depois|em seguida|ent[aã]o|tamb[eé]m)\b[\s,;.!?]*)*', re.I)


def _masked(text):
    return re.sub(r'"[^"\n]*"|“[^”\n]*”|\'[^\'\n]*\'',
                  lambda match: ' ' * len(match[0]), text)


def _clean(command):
    value = command.strip().rstrip('.!?').strip()
    value = re.sub(r'^(?:therion|por favor|primeiro|tamb[eé]m)[,\s]+', '', value, flags=re.I)
    value = re.sub(r'^(?:voc[eê] pode|pode)\s+', '', value, flags=re.I)
    value = re.sub(r'^(?:eu\s+)?(?:queria|quero|gostaria de) saber\s+', '', value, flags=re.I)
    return value


# Leitura de metadados do Gmail; "importante" é a marca do próprio Gmail, não um julgamento do modelo.
# "e meio(s)"/"em meio(s)" é como a transcrição costuma escrever "e-mail(s)".
_MAIL = r'(?:e-?mails?|em? meios?)'
_MAIL_IMPORTANT = re.compile(r'(?:se )?(?:(?:tem|ha|existe|chegou) )?(?:algum |alguns |algumas? )?' + _MAIL
                             + r' importantes?(?: (?:de )?hoje)?')
_MAIL_ABOUT_EVENTS = re.compile(r'(?:se )?(?:(?:tem|ha|existe) )?(?:algum |alguns )?' + _MAIL
                                + r' (?:que )?(?:fala|falam|menciona|mencionam|trata|tratam|sobre)'
                                r'(?: (?:de|sobre))? (?:desses|destes|dos|esses|estes|os|nesses) compromissos')


def _calendar_draft(command, context):
    # "prepare uma reunião" prepara a mesma proposta; nunca autoriza criação.
    parsed = re.sub(r'^prepare\b', 'marque', command, flags=re.I)
    intent = IntentRecognizer().parse(parsed)
    if intent is None or intent.action != 'criar evento calendário':
        return None
    if re.search(r'\b(?:duas|dois|[2-9]\d*|v[aá]ri[ao]s)\s+(?:reuni[oõ]es|eventos|compromissos)\b', _masked(parsed), re.I):
        raise WorkflowError('Peça a criação de um evento por vez; divida os compromissos em pedidos separados.')
    if re.search(r'\b(?:sem confirmar|sem confirmacao|automaticamente|talvez|acho que)\b', normalize(_masked(command))):
        raise WorkflowError('A criação de evento exige uma proposta clara e confirmação específica.')
    draft = dict(intent.entities or {})
    if draft.get('_issues') or any(not draft.get(key) for key in ('title', 'date', 'start_time')):
        raise WorkflowError('Informe título, data e horário completos para a reunião antes de executar o pedido.')
    try:
        now = (context or {}).get('now')
        parse_day(draft['date'], now if isinstance(now, datetime) else datetime.now().astimezone())
        start = parse_time(draft['start_time'])
        duration = draft.get('duration_minutes', 60)
        if type(duration) not in (int, float) or int(duration) != duration or not 1 <= duration <= 1440:
            raise ValueError('duração')
        if draft.get('end_time'):
            end = parse_time(draft['end_time'])
            interval = (end[0] - start[0]) * 60 + end[1] - start[1]
            if interval <= 0 or draft.get('duration_explicit') and interval != duration:
                raise ValueError('intervalo')
    except (CalendarError, ValueError, TypeError) as error:
        raise WorkflowError('Há uma data, horário ou duração inválida na proposta. Esclareça antes de continuar.') from error
    return {'draft': draft}


def _step(command, context):
    cleaned = _clean(command)
    control = normalize(cleaned)
    if _MAIL_IMPORTANT.fullmatch(control):
        return WorkflowStep('mail_important', command, {})
    if _MAIL_ABOUT_EVENTS.fullmatch(control):
        return WorkflowStep('mail_about_events', command, {})
    if re.match(r'^(?:nao|nunca|se|caso)\b', control):
        raise WorkflowError('Esclareça as condições ou negações do pedido antes de executar as etapas.')
    request = task_request(cleaned)
    if request is None:
        add = re.fullmatch(r'(?:adicione|adiciona|coloque|coloca)\s+(.+?)\s+(?:na|a|à)\s+(?:minha\s+)?lista(?:\s+de\s+tarefas)?', cleaned, re.I | re.S)
        if add:
            request = {'operation': 'add', 'text': add[1]}
        elif re.fullmatch(r'(?:(?:as|minhas)\s+)?tarefas(?:\s+pendentes)?', control):
            request = {'operation': 'list', 'filter': 'pendentes' if 'pendentes' in control else 'all'}
        else:
            from therion.integrations.task_query import task_query_request
            if task_query_request(cleaned):
                # Mesma fonte do panorama: tarefas salvas e da sessão.
                return WorkflowStep('saved_tasks', command, {})
    if request is not None:
        operation = request['operation']
        if operation == 'add':
            try:
                SessionTasks().add(request['text'])
            except ValueError as error:
                raise WorkflowError(str(error)) from error
        elif operation in {'complete', 'reopen'}:
            if not re.fullmatch(r'[1-9]\d*', request['id']):
                raise WorkflowError('Informe o número exato da tarefa no pedido composto.')
        elif operation != 'list':
            raise WorkflowError('Informe a tarefa explicitamente; essa referência não identifica uma tarefa do pedido.')
        return WorkflowStep('task_' + operation, command, {'request': request})

    reference = reference_request(cleaned)
    if reference:
        operation, index, _ = reference
        if type(index) is not int or index < 1:
            raise WorkflowError('Informe o número da nota que deseja usar neste pedido.')
        return WorkflowStep('note_summary' if operation == 'summary' else 'note_read', command, {'index': index})

    query_command = re.sub(r'^(?:veja|consulte|liste|mostre)\s+(?:a\s+|minha\s+|a\s+minha\s+)?agenda\s+', 'agenda ', cleaned, flags=re.I)
    request = query_request(query_command)
    if request:
        try:
            if not request.get('next'):
                now = (context or {}).get('now')
                parse_day(request['date'], now if isinstance(now, datetime) else datetime.now().astimezone())
        except (CalendarError, ValueError, TypeError) as error:
            raise WorkflowError('Informe uma data válida para a consulta antes de executar o pedido.') from error
        return WorkflowStep('calendar_query', command, {'request': request, 'plan_day': False})
    if re.fullmatch(r'(?:planeje|organize|prepare)\s+(?:o\s+|meu\s+|o\s+meu\s+)?dia', control):
        return WorkflowStep('calendar_query', command, {'request': {'date': 'hoje', 'days': 1}, 'plan_day': True})

    search = re.fullmatch(r'(?:procure|procura|procurar|busque|busca|buscar|pesquise|pesquisar)\s+(?:(?:no\s+)?(?:segundo\s+c[eé]rebro|2º?\s*c[eé]rebro)[,\s]+|(?:minhas\s+|as\s+)?notas?\s+(?:sobre\s+|de\s+)?)(.+)', cleaned, re.I | re.S)
    if search and search[1].strip():
        query = search[1].strip().strip('"“”')
        return WorkflowStep('note_search', command, {'query': query})
    draft = _calendar_draft(cleaned, context)
    if draft:
        return WorkflowStep('calendar_create', command, draft)
    return None


def _validate(commands, context):
    if not 2 <= len(commands) <= 5:
        raise WorkflowError('Divida o pedido em duas a cinco etapas.')
    steps = []
    last_search = None
    last_calendar = None
    for command in commands:
        step = _step(command, context)
        if step is None:
            raise _DecompositionError('Não identifiquei todas as etapas com segurança. Reformule cada ação explicitamente.')
        if step.action == 'note_search':
            last_search = len(steps)
        if step.action == 'calendar_query':
            last_calendar = len(steps)
        if step.action == 'mail_about_events':
            if last_calendar is None:
                raise WorkflowError('Consulte a agenda neste pedido antes de procurar e-mails sobre os compromissos.')
            step = WorkflowStep(step.action, step.command, step.arguments, (last_calendar,))
        if step.action in {'note_read', 'note_summary'}:
            if last_search is None:
                raise WorkflowError('Faça uma busca neste pedido antes de selecionar uma nota pelo número.')
            step = WorkflowStep(step.action, step.command, step.arguments, (last_search,))
        steps.append(step)
    creations = [index for index, step in enumerate(steps) if step.action == 'calendar_create']
    if len(creations) > 1 or creations and creations != [len(steps) - 1]:
        raise WorkflowError('Use somente uma criação de evento, como última etapa. Divida as outras criações em pedidos separados.')
    return WorkflowSpec(tuple(steps))


def _ground_commands(message, proposal):
    if not isinstance(proposal, dict) or set(proposal) != {'commands'}:
        raise WorkflowError('Não consegui interpretar todas as etapas com segurança.')
    commands = proposal['commands']
    if not isinstance(commands, list) or not 2 <= len(commands) <= 5:
        raise WorkflowError('Divida o pedido em duas a cinco etapas explícitas.')
    cursor = 0
    for command in commands:
        if not isinstance(command, str) or not command.strip() or len(command) > 2000:
            raise WorkflowError('A interpretação contém uma etapa inválida.')
        start = message.find(command, cursor)
        if start < 0 or not _GAP.fullmatch(message[cursor:start]):
            raise WorkflowError('A interpretação não preservou o pedido completo; reformule as etapas.')
        cursor = start + len(command)
    if not _GAP.fullmatch(message[cursor:]):
        raise WorkflowError('A interpretação omitiu parte do pedido; reformule as etapas.')
    return commands


_READ_ONLY = {'saved_tasks', 'task_list', 'calendar_query', 'note_search', 'note_read', 'note_summary',
              'mail_important', 'mail_about_events'}


def read_only_workflow(command, now=None):
    """Composto só de leitura: o orquestrador responde sem o modelo, antes do agente."""
    try:
        spec = interpret_workflow(command, context={'now': now})
    except WorkflowError:
        return False
    return spec is not None and all(step.action in _READ_ONLY for step in spec.steps)


def interpret_workflow(command, provider=None, context=None):
    """None somente para comando simples; composto inseguro falha sem executar.

    ``context['now']`` pode fornecer um relógio para validação determinística de
    datas. Contexto conversacional não é necessário nem concede referências.
    """
    if not isinstance(command, str):
        return None
    message = command.strip()
    # Vocativos são controle da interface, não uma primeira etapa separada
    # por vírgula. Os trechos restantes continuam literais no pedido original.
    message = re.sub(r'^(?:therion|por favor)[,\s]+', '', message, flags=re.I)
    masked = _masked(message)
    if (re.match(r'^(?:marque|marcar|agende|agendar|crie|criar|prepare)\b', _clean(masked), re.I)
            and re.search(r'\b(?:duas|dois|[2-9]\d*|v[aá]ri[ao]s)\s+(?:reuni[oõ]es|eventos|compromissos)\b', masked, re.I)):
        raise WorkflowError('Peça a criação de um evento por vez; divida os compromissos em pedidos separados.')
    batch = task_request(message)
    if batch and batch.get('operation') == 'add' and re.match(r'^[^:;\n]+\btarefas\s*:', _clean(message), re.I):
        # Sintaxe explícita de lote existente: ; e quebras são dados. Um
        # conectivo como "e depois liste tarefas" ainda pode encerrar o lote.
        masked = re.sub(r'[;\n]', ' ', masked)
    separators = list(_SEPARATOR.finditer(masked))
    # A vírgula entre o introdutor de busca e seu assunto não inicia uma etapa.
    search_header = IntentRecognizer._SEARCH_CONTEXT_PATTERN.match(message)
    if search_header:
        separators = [separator for separator in separators if separator.start() >= search_header.start(1)]
    if not separators:
        return None
    parts, cursor = [], 0
    for match in separators:
        parts.append(message[cursor:match.start()].strip())
        cursor = match.end()
    parts.append(message[cursor:].strip())
    # Conversa comum com um verbo incidental não é um pedido executável.
    if not re.match(_START, _masked(parts[0]), re.I):
        return None
    if len(parts) > 5:
        raise WorkflowError('O limite é de cinco etapas; divida o pedido.')
    try:
        return _validate(parts, context)
    except WorkflowError as initial_error:
        # Decomposição opcional só para um composto provável. A resposta é
        # novamente fundamentada e interpretada pelo código, nunca executada.
        if not isinstance(initial_error, _DecompositionError):
            raise
        method = getattr(provider, 'interpret_workflow_commands', None)
        if method is None:
            raise
        started = time.monotonic()
        try:
            proposal = method(message, context={}, timeout_seconds=20)
            if time.monotonic() - started > 20:
                raise WorkflowError('A interpretação demorou demais. Reformule as etapas explicitamente.')
            if proposal is None:
                raise initial_error
            commands = _ground_commands(message, proposal)
            return _validate(commands, context)
        except WorkflowError:
            raise
        except Exception as error:
            raise WorkflowError('Não consegui interpretar o pedido composto. Reformule cada etapa explicitamente.') from error
