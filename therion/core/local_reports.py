"""Consultas locais só de leitura: resumo do dia, estado de um projeto e saúde do PC.

Nenhuma passa pelo modelo e nenhuma altera nada. Projetos são lidos apenas dos caminhos
que o usuário cadastrou em config.json → "projects" ({"nome": "caminho absoluto"}).
"""
import csv
import ctypes
import io
import re
import shutil
import subprocess
from pathlib import Path

from therion.context.language import control

_POLITE = r'(?:,? por favor)?'
_DAY = re.compile(
    r'(?:me (?:diga|fale|conta|conte) )?'
    r'(?:o que (?:eu |a gente |nos )?(?:fiz|fizemos|fez) hoje|como foi (?:o )?meu dia)'
    + _POLITE)
_PC = re.compile(
    r'(?:(?:por ?que|porque) )?(?:o |meu )?(?:pc|computador) (?:esta|ta|anda|ficou) (?:muito |tao |bem )?(?:lento|travando|devagar|pesado)'
    r'|como (?:esta|ta) (?:a memoria|a saude) do (?:pc|computador)|(?:saude|estado) do (?:pc|computador)' + _POLITE)
_PROJECT = re.compile(
    r'(?:como (?:esta|ta|anda|vai)|(?:qual (?:e )?)?(?:o )?(?:status|estado|situacao) d[oe]) (?:o |a )?(projeto )?(.+?)' + _POLITE)
_GAME = r'(?:o |a )?mod[oa]s? (?:de )?(?:jogo|game)'  # o Whisper ouve "moda de jogo"
# 24/11: "abre o modo de jogo" foi para o catálogo de apps. Qualquer verbo antes liga ("abre", "pode ligar", "deixa no"),
# menos pergunta, negação ou frase dupla com "e" (essa é da cleanup_then_game ou da IA).
_GAME_ON = re.compile(r'(?:(?!(?:o que|como|qual|quando|onde|por ?que|porque|pra que|para que|sobre)\b)(?:(?!(?:e|nao|nunca|sem) )[a-z]+ ){0,6}'
                      + _GAME + r'(?: (?:pra|para) mim| agora| ai| ja)*|vou jogar(?: agora)?)' + _POLITE)
_GAME_OFF = re.compile(r'(?:desativa|desative|desativar|desliga|desligue|desligar|sai d|saia d|sair d|encerra|encerre|tira d'
                       r'|fecha|feche|fechar|para|pare|parar|termina|termine|terminar|acaba|acabe|cancela|cancele)(?:o | o | )?' + _GAME
                       + r'|parei de jogar|terminei de jogar|modo normal' + _POLITE)
_VAULT = re.compile(r'(?:como (?:esta|ta|anda|vai)|(?:qual (?:e )?)?(?:o )?(?:status|estado|situacao) d[oe]) (?:o |meu )?segundo cerebro' + _POLITE)
_WAKE_OFF = re.compile(r'(?:para|pare|parar) de me (?:ouvir|escutar)' + _POLITE)
_GB = 1024 ** 3


def configured_projects(config=None):
    """Só entradas nome → caminho absoluto; qualquer outra coisa é ignorada."""
    if config is None:
        from therion.config.local import load_config
        config = load_config()
    rows = config.get('projects') if isinstance(config, dict) else None
    if not isinstance(rows, dict):
        return {}
    return {name.strip(): path for name, path in rows.items()
            if isinstance(name, str) and name.strip() and isinstance(path, str) and Path(path).is_absolute()}


def game_mode_request(command):
    """True liga, False desliga, None não é sobre o modo jogo."""
    # "Aham, desliga o modo de jogo": a interjeição da fala não muda o pedido.
    text = re.sub(r'^(?:aham|ah|ok|ta|beleza|mano|entao|agora|isso|e)[, ]+', '', control(command).rstrip('?!. '))
    if _GAME_OFF.fullmatch(text):
        return False
    return True if _GAME_ON.fullmatch(text) else None


def wake_off_request(command):
    """'Therion, para de me ouvir': desliga a palavra de ativação até reiniciar."""
    return bool(_WAKE_OFF.fullmatch(control(command).rstrip('?!. ')))


def report_request(command, projects=None):
    """('day',) | ('pc',) | ('vault',) | ('game', ligar) | ('project', nome, caminho) | ('unknown_project', nomes) | None."""
    text = control(command).rstrip('?!. ')
    game = game_mode_request(command)
    if game is not None:
        return ('game', game)
    if _DAY.fullmatch(text):
        return ('day',)
    if _PC.fullmatch(text):
        return ('pc',)
    if _VAULT.fullmatch(text):
        return ('vault',)
    match = _PROJECT.fullmatch(text)
    if not match:
        return None
    projects = configured_projects() if projects is None else projects
    wanted = match[2].strip()
    for name, path in projects.items():
        if control(name) == wanted:
            return ('project', name, path)
    # Sem a palavra "projeto", "como está o X" pertence a outras rotas (apps, agenda).
    return ('unknown_project', tuple(projects)) if match[1] else None


def _git(path, *args):
    try:
        # core.fsmonitor desligado: uma configuração do repositório não pode executar programa nesta leitura.
        done = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', path, *args], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=8, stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _plural(count, one, many):
    return f'{count} {one if count == 1 else many}'


def vault_report(vault):
    """Só o que se lê na hora: quantos itens esperam na Entrada (contar o cofre todo leva ~20 s)."""
    entrada = Path(vault) / '00 - Entrada'
    if not entrada.is_dir():
        return 'Não encontrei a pasta do Segundo Cérebro.'
    try:
        items = [p for p in entrada.iterdir() if p.is_file() and p.name != 'Entrada.md' and not p.name.startswith('.')]
        attachments = entrada / 'Anexos para organizar'
        if attachments.is_dir():
            items += [p for p in attachments.iterdir() if not p.name.startswith('.')]
    except OSError:
        return 'Não consegui ler a Entrada do Segundo Cérebro agora.'
    if not items:
        return 'No Segundo Cérebro, a Entrada está vazia: nada esperando organização.'
    noun = 'item esperando' if len(items) == 1 else 'itens esperando'
    return f'No Segundo Cérebro, a Entrada tem {len(items)} {noun} organização.'


def project_note(name, vault=None):
    """Propriedades painel_* da nota do projeto no cofre (só o cabeçalho); {} se não houver."""
    if vault is None:
        from therion.context.second_brain import SecondBrainReader
        vault = SecondBrainReader.DEFAULT_VAULT_ROOT
    try:
        with (Path(vault) / '10 - Projetos' / name / f'{name}.md').open(encoding='utf-8', errors='replace') as stream:
            head = stream.read(4000)
    except (OSError, ValueError):
        return {}
    match = re.match(r'---\r?\n(.*?)\r?\n---', head, re.S)
    rows = re.findall(r'^(painel_\w+):[ \t]*(.*?)[ \t]*$', match[1], re.M) if match else []
    return {key: value.strip('"\'') for key, value in rows
            if control(value.strip('"\'')) not in {'', 'nao informado', 'nenhum', '-'}}


def project_status(name, path, git=_git, note=None):
    # Fase e próximo passo vêm da nota do projeto; o git diz o que falta guardar.
    note = note or {}
    items = [prefix + note[key][:160].rstrip('.') + '.' for key, prefix in
             (('painel_fase', ''), ('painel_proxima_acao', 'Próximo passo: '), ('painel_bloqueio', 'Bloqueio: '))
             if note.get(key)]
    lead = f'{name}: ' + ' '.join(items) if items else ''
    branch = git(path, 'rev-parse', '--abbrev-ref', 'HEAD')
    if branch is None:
        failed = f'Não consegui ler o projeto {name}: a pasta cadastrada não respondeu como repositório git.'
        return f'{lead} {failed}' if lead else failed
    changed = len([line for line in (git(path, 'status', '--porcelain') or '').splitlines() if line.strip()])
    ahead = git(path, 'rev-list', '--count', '@{u}..HEAD')
    last = git(path, 'log', '-1', '--pretty=%cd — %s', '--date=format:%d/%m %H:%M')
    parts = [f'Ramo {branch}.' if lead else f'{name}: ramo {branch}.',
             'Tudo commitado.' if not changed else _plural(changed, 'arquivo', 'arquivos') + ' sem commit.']
    if ahead is None or not ahead.isdigit():
        parts.append('Este ramo não tem remoto para comparar.')
    else:
        parts.append('Tudo enviado.' if ahead == '0' else _plural(int(ahead), 'commit', 'commits') + ' sem push.')
    if last:
        parts.append(f'Último commit: {last[:160]}.')
    return ' '.join([lead] * bool(lead) + parts)


def _conversations(folder, day):
    """Conta pedidos nas notas de conversa do dia; o texto das conversas não é lido para a resposta."""
    try:
        notes = sorted(Path(folder).glob(day.strftime('%Y-%m-%d') + '_*.md'))
    except OSError:
        return None
    asked = failed = 0
    for note in notes:
        try:
            text = note.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        asked += text.count('\n**Você:**')
        failed += len(re.findall(r'^`rota: .*· status: (?!success\b)', text, re.M))
    return (len(notes), asked, failed) if asked else None


def day_report(now, *, tasks=(), calendar=None, projects=None, conversations=None, git=_git):
    lines = []
    if conversations is None:
        from therion.logging.conversation_log import default_folder
        conversations = _conversations(default_folder(), now)
    if conversations:
        notes, asked, failed = conversations
        line = f'Você me fez {_plural(asked, "pedido", "pedidos")} em {_plural(notes, "conversa", "conversas")}'
        lines.append(line + (f'; {failed} não {"foi concluído" if failed == 1 else "foram concluídos"}.' if failed else '.'))
    done = [task.description for task in tasks if task.completed]
    if done:
        lines.append('Tarefas concluídas nesta conversa: ' + '; '.join(text[:80] for text in done[:5]) + '.')
    try:
        events = calendar.list_events_for_day(now.date()) if calendar is not None else []
        past = [event.summary[:80] for event in events
                if not event.all_day and event.start.replace(tzinfo=None) <= now.replace(tzinfo=None)]
    except Exception:  # agenda indisponível não impede o resto do resumo
        past = []
    if past:
        lines.append('Compromissos que já começaram hoje: ' + '; '.join(past[:5]) + '.')
    for name, path in (configured_projects() if projects is None else projects).items():
        subjects = [row for row in (git(path, 'log', '--since=midnight', '--pretty=%s') or '').splitlines() if row.strip()]
        if subjects:
            lines.append(f'{name}: {_plural(len(subjects), "commit", "commits")} hoje; o mais recente foi "{subjects[0][:100]}".')
    if not lines:
        return 'Não encontrei registro de atividade hoje: nem conversas gravadas, nem tarefas concluídas, nem compromissos, nem commits.'
    return 'Hoje, até agora. ' + ' '.join(lines)


class _Memory(ctypes.Structure):
    _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong)] + [
        (name, ctypes.c_ulonglong) for name in ('ullTotalPhys', 'ullAvailPhys', 'ullTotalPageFile', 'ullAvailPageFile',
                                                'ullTotalVirtual', 'ullAvailVirtual', 'ullAvailExtendedVirtual')]


def _measure():
    stat = _Memory()
    stat.dwLength = ctypes.sizeof(stat)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        raise OSError('GlobalMemoryStatusEx falhou.')
    disks = {}
    for letter in ('C', 'F'):
        try:
            disks[letter] = shutil.disk_usage(letter + ':\\').free
        except OSError:
            pass
    usage, processes = {}, {}
    try:
        listing = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True, text=True, errors='replace', timeout=10,
                                 stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
        for row in csv.reader(io.StringIO(listing)):
            digits = re.sub(r'\D', '', row[4]) if len(row) >= 5 else ''
            if digits:
                usage[row[0]] = usage.get(row[0], 0) + int(digits) * 1024
                if row[1].isdigit():
                    processes[int(row[1])] = (row[0], int(digits) * 1024)   # por PID: o vigia acompanha vazamento
    except (OSError, subprocess.TimeoutExpired):
        pass
    return dict(ram_total=stat.ullTotalPhys, ram_free=stat.ullAvailPhys, commit_total=stat.ullTotalPageFile,
                commit_free=stat.ullAvailPageFile, disks=disks, top=sorted(usage.items(), key=lambda row: -row[1])[:3],
                processes=processes)


def _gb(value):
    return f'{value / _GB:.1f}'.replace('.', ',') + ' GB'


def pc_report(measure):
    problems = []
    if measure['commit_free'] < measure['commit_total'] * .10:
        problems.append(f'a memória virtual está quase esgotada ({_gb(measure["commit_free"])} livres de {_gb(measure["commit_total"])}); '
                        'é esse limite que derruba o modelo do Therion')
    if measure['ram_free'] < measure['ram_total'] * .15:
        problems.append(f'a memória RAM está quase cheia ({_gb(measure["ram_free"])} livres de {_gb(measure["ram_total"])})')
    free_c = measure['disks'].get('C')
    if free_c is not None and free_c < 5 * _GB:
        problems.append(f'o disco C está quase cheio ({_gb(free_c)} livres)')
    if problems:
        message = 'O PC está apertado: ' + '; '.join(problems) + '.'
    else:
        message = (f'Não achei aperto agora: {_gb(measure["ram_free"])} de RAM livres de {_gb(measure["ram_total"])}, '
                   f'{_gb(measure["commit_free"])} de memória virtual livres'
                   + (f' e {_gb(free_c)} livres no disco C.' if free_c is not None else '.'))
    if measure['top']:
        message += ' O que mais usa memória: ' + ', '.join(
            f'{name.removesuffix(".exe")} ({_gb(size)})' for name, size in measure['top']) + '.'
    return message


def answer(command, host):
    """Resposta pronta ou None; `host` é o orquestrador (relógio, tarefas da sessão e agenda)."""
    request = report_request(command)
    if request is None or request[0] == 'game':   # o modo jogo é respondido pelo orquestrador
        return None
    if request[0] == 'day':
        return day_report(host._calendar_now(), tasks=host._session_tasks.list(), calendar=host.calendar_adapter)
    if request[0] == 'pc':
        try:
            return pc_report(_measure())
        except (OSError, AttributeError):
            return 'Não consegui medir a memória e os discos agora.'
    if request[0] == 'vault':
        from therion.context.second_brain import SecondBrainReader
        return vault_report(SecondBrainReader.DEFAULT_VAULT_ROOT)
    if request[0] == 'project':
        return project_status(request[1], request[2], note=project_note(request[1]))
    names = ', '.join(request[1])
    return ('Não conheço esse projeto. Cadastrados: ' + names + '.' if names else
            'Nenhum projeto está cadastrado. Adicione "projects": {"nome": "caminho"} na configuração do Therion.')
