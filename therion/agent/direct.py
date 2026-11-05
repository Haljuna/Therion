"""Pedido explícito de aplicativo: ferramenta governada, sem interpretação LLM."""
import json

from .contracts import AgentDecision, AgentError, ToolCall


class ExplicitAppProvider:
    """Escolhe a ponte existente; não executa, autoriza ou confirma operações.

    O host só seleciona este decisor após o reconhecedor de intenções aceitar
    o pedido humano. Schema, política, confirmação e verificação continuam no
    registro/runtime. A resposta final reproduz a observação do executor.
    """
    model_free = True

    def __init__(self, command):
        self.command = command
        self.called = False
        self.usage = {}

    async def decide(self, messages, tools, budget, token, emit):
        token.check()
        if not self.called:
            self.called = True
            return AgentDecision('tools', calls=(ToolCall('prepare_existing_action', {'command': self.command}),))
        for row in reversed(messages):
            if row.get('role') == 'tool':
                observation = json.loads(row['content'])
                message = observation.get('message')
                if isinstance(message, str) and message.strip():
                    return AgentDecision('final', message)
                break
        raise AgentError('Não recebi resultado operacional da abertura. Não repeti a ação.')


class ExplicitTaskStateProvider:
    """Concluir/reabrir tarefa salva sem o modelo decidir se ela existe.

    Lista a fonte real; só prepara quando há exatamente uma candidata. A prévia e a
    confirmação continuam com prepare_task_state e o runtime, como em qualquer escrita.
    """
    model_free = True  # não envia contexto a modelo; o orçamento de tokens não se aplica

    def __init__(self, state, hint):
        self.state = state
        self.hint = hint
        self.step = 0
        self.usage = {}

    @staticmethod
    def _key(text):
        from therion.context.language import control
        return control(text)

    async def decide(self, messages, tools, budget, token, emit):
        token.check()
        if self.step == 0:
            # As ferramentas de tarefas não começam anunciadas; o runtime exige carregá-las.
            self.step = 1
            return AgentDecision('tools', calls=(ToolCall('load_tools', {'names': ['list_inbox', 'prepare_task_state']}),))
        observation = next((json.loads(row['content']) for row in reversed(messages) if row.get('role') == 'tool'), None)
        if observation is None:
            raise AgentError('Não recebi a lista de tarefas. Não alterei nada.')
        if self.step == 1:
            if observation.get('status') != 'success':
                return AgentDecision('final', observation.get('message') or 'As ferramentas de tarefas não estão disponíveis. Não alterei nada.')
            self.step = 1.5
            source = 'pending' if self.state == 'completed' else 'completed'
            return AgentDecision('tools', calls=(ToolCall('list_inbox', {'state': source, 'limit': 10}),))
        if self.step == 2:
            return AgentDecision('final', observation.get('message') or 'Preparei a alteração da tarefa para confirmação.')
        if observation.get('status') != 'success':
            return AgentDecision('final', observation.get('message') or 'Não consegui consultar as tarefas salvas. Não alterei nada.')
        rows = (observation.get('data') or {}).get('tasks') or []
        if self.hint:
            wanted = self._key(self.hint)
            rows = [row for row in rows if wanted in self._key(row['title'])]
        label = 'pendente' if self.state == 'completed' else 'concluída'
        if not rows:
            extra = f' com "{self.hint}"' if self.hint else ''
            return AgentDecision('final', f'Não encontrei tarefa {label}{extra} nas tarefas salvas. Não alterei nada.')
        if len(rows) > 1:
            names = '; '.join(row['title'] for row in rows[:6])
            return AgentDecision('final', f'Há {len(rows)} tarefas {label}s: {names}. Qual delas? Diga o nome.')
        self.step = 2
        return AgentDecision('tools', calls=(ToolCall('prepare_task_state', {'id': rows[0]['id'], 'state': self.state}),))


class ExplicitSearchProvider:
    """Busca explícita publica trechos verificados sem rodadas de inferência."""
    model_free = True

    def __init__(self, query):
        self.query = query
        self.called = False
        self.usage = {}

    async def decide(self, messages, tools, budget, token, emit):
        token.check()
        if not self.called:
            self.called = True
            return AgentDecision('tools', calls=(ToolCall('search_notes', {'query': self.query}),))
        for row in reversed(messages):
            if row.get('role') != 'tool':
                continue
            observation = json.loads(row['content'])
            if observation.get('status') != 'success':
                return AgentDecision('final', observation.get('message') or 'Não consegui concluir a busca autorizada.')
            matches = observation.get('data') or []
            if not matches:
                return AgentDecision('final', 'A busca retornou zero correspondências no escopo permitido. Isso não comprova ausência de informação nas notas.')
            lines = [f"{index}. {item['path']} [{item['id']}]"
                     for index, item in enumerate(matches, 1)]
            return AgentDecision('final', 'Resultados da busca no Segundo Cérebro:\n\n' + '\n'.join(lines)
                                 + '\n\nQual nota você quer consultar? A busca selecionou caminhos e trechos; ainda falta ler a nota escolhida.')
        raise AgentError('Não recebi o resultado da busca. Não repeti a operação.')
