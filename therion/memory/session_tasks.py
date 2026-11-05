"""Lista pessoal volátil, alterada apenas por comandos explícitos do usuário."""
import re
from dataclasses import dataclass, replace

from therion.context.note_references import normalize


TEMPORARY_NOTICE = 'Esta lista é temporária: Limpar ou encerrar o aplicativo apaga as tarefas. Não salvo no Segundo Cérebro.'


def task_request(command):
    # Preservar acentos e pontuação das descrições, normalizando somente o controle.
    raw = re.sub(r'^\s*(?:therion[,\s]+|por favor[,\s]+)', '', command, flags=re.I).strip()
    add = re.fullmatch(r'(?:adicione|adiciona|adicona|adicionar|anote|anota|anotar|crie|cria|criar|coloque|coloca)\s+(?:(?:uma|as|minhas|novas)\s+)?(?:tarefas?|tarfeas?)(?:\s+(?:da|desta|na|nesta)\s+sess[aã]o)?\s*(?::\s*|\s+)(.*)', raw, re.I | re.S)
    if add:
        return {'operation': 'add', 'text': add[1]}
    text = normalize(raw)
    if re.fullmatch(r'(?:coloca|coloque|adicione|adiciona|anote|anota)\s+(isso|essa|esta|aquela)(?:\s+tarefa)?\s+(?:na|a)\s+(?:minha |lista de )?lista(?: de tarefas)?', text):
        return {'operation': 'add_reference'}
    mark = re.fullmatch(r'(?:marque|marca|deixe|deixa)\s+(?:a\s+)?tarefa\s+(\S+)\s+(?:como\s+)?(concluida|concluido|feita|feito|pendente)', text)
    if mark:
        return {'operation': 'reopen' if mark[2] == 'pendente' else 'complete', 'id': mark[1]}
    if re.fullmatch(r'(?:conclua|concluir|complete|completar|reabra|reabrir)\s+(?:essa|esta|aquela)\s+tarefa', text):
        return {'operation': 'task_reference', 'action': 'reopen' if text.startswith(('reabra', 'reabrir')) else 'complete'}
    if re.fullmatch(r'(?:adicione|adiciona|adicionar|anote|anota|anotar|crie|cria|criar|coloque|coloca)\s+(?:uma\s+)?tarefas?\s*:?', text):
        return {'operation': 'add', 'text': ''}
    update = re.fullmatch(r'(conclua|concluir|complete|completar|reabra|reabrir)\s+(?:a\s+)?tarefa(?:\s+(?:numero\s+|n[ºo.]\s*)?(.*))?', text)
    if update:
        return {'operation': 'reopen' if update[1] in {'reabra', 'reabrir'} else 'complete', 'id': (update[2] or '').strip()}
    listed = re.fullmatch(r'(?:liste|lista|listar|mostre|mostra|mostrar|exiba|exibir|quais sao)\s+(?:(?:as|minhas|todas|todas as)\s+)?(?:tarefas|pendencias)(?:\s+(pendentes|concluidas))?(?:\s+(?:da|desta|na|nesta)\s+sessao)?', text)
    if listed:
        return {'operation': 'list', 'filter': listed[1] or ('pendentes' if 'pendencias' in text else 'all')}
    return None


@dataclass(frozen=True)
class SessionTask:
    id: int
    description: str
    completed: bool = False


class SessionTasks:
    MAX_TASKS = 30
    MAX_DESCRIPTION = 240

    def __init__(self):
        self._items = []
        self._next_id = 1

    def clear(self):
        self._items.clear()
        self._next_id = 1

    def add(self, text):
        # Uma vírgula pertence à descrição; qualquer elemento vazio invalida o lote.
        descriptions = [re.sub(r'^[-*]\s+', '', item.strip()) for item in re.split(r';|\r?\n', text.strip())]
        if not descriptions or any(not item for item in descriptions):
            raise ValueError('Informe descrições não vazias. Separe tarefas por ponto e vírgula ou por linhas.')
        if any(len(item) > self.MAX_DESCRIPTION for item in descriptions):
            raise ValueError('Cada descrição pode ter no máximo 240 caracteres. Nenhuma tarefa foi adicionada.')
        if len(self._items) + len(descriptions) > self.MAX_TASKS:
            raise ValueError('O limite é de 30 tarefas por sessão, incluindo concluídas. Nenhuma tarefa foi adicionada.')
        added = [SessionTask(self._next_id + index, value) for index, value in enumerate(descriptions)]
        self._items.extend(added)
        self._next_id += len(added)
        return tuple(added)

    def list(self, filter='all'):
        return tuple(item for item in self._items if filter == 'all' or item.completed == (filter == 'concluidas'))

    def update(self, raw_id, completed):
        if not re.fullmatch(r'[1-9]\d*', str(raw_id)):
            raise ValueError('Informe o número da tarefa que aparece na lista.')
        for index, item in enumerate(self._items):
            if item.id == int(raw_id):
                self._items[index] = replace(item, completed=completed)
                return self._items[index]
        raise ValueError('Não encontrei esse número na lista temporária desta sessão.')

    def context(self):
        pending = self.list('pendentes')
        visible = pending[:10]
        return {'temporary': True, 'read_only': True, 'pending_count': len(pending),
                'partial': len(pending) > 10 or any(len(item.description) > 120 for item in visible),
                'items': [{'id': item.id, 'description': item.description[:120],
                           'partial': len(item.description) > 120} for item in visible]}
