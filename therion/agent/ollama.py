"""Adapter Ollama local, streaming e cancelamento cooperativo de conexão."""
import asyncio
import json
import re
import threading

from therion.config.local import is_local_ollama_endpoint
from therion.memory.coordinator import INFERENCE_GATE
from .contracts import AgentDecision, AgentError, ToolCall,ProviderUnavailable

DECISION_SCHEMA = {'type': 'object', 'properties': {
    'kind': {'type': 'string', 'enum': ['final', 'clarification', 'tools']},
    'message': {'type': 'string'},
    'calls': {'type': 'array', 'items': {'type': 'object', 'properties': {
        'name': {'type': 'string'}, 'arguments': {'type': 'object'}}, 'required': ['name', 'arguments']}}
}, 'required': ['kind', 'message', 'calls'], 'additionalProperties': False}

_ASYNC_INFERENCE_SLOT=threading.Lock()


def final_text(value):
    # Alguns templates locais colocam o delimitador final no campo content.
    for tag in ('think','analysis','reasoning'):
        closing='</'+tag+'>'
        if closing in value:
            value=value.rsplit(closing,1)[1]
        if '<'+tag+'>' in value:
            raise AgentError('Modelo retornou raciocínio sem resposta final; nada foi aplicado.')
    return value.strip()


class OllamaAgentProvider:
    def __init__(self, endpoint, model, *, protocol='json', think=None, client_factory=None,background=False):
        if not is_local_ollama_endpoint(endpoint) or protocol not in {'json', 'native'}:
            raise AgentError('Provider deve usar Ollama local e protocolo conhecido.')
        self.endpoint, self.model, self.protocol, self.think = endpoint, model, protocol, think
        self.client_factory = client_factory
        self.usage = {}
        self.last_response = ''
        self.diagnostics = []
        self._clients = {}
        self.background=background is True

    def background_copy(self):
        return OllamaAgentProvider(self.endpoint,self.model,protocol=self.protocol,think=self.think,
            client_factory=self.client_factory,background=True)

    async def decide(self, messages, schemas, budget, token, event):
        import httpx
        acquired=False
        slot=False
        if not self.background:
            with INFERENCE_GATE.state:INFERENCE_GATE.waiters+=1
        try:
            while not acquired:
                token.check()
                with INFERENCE_GATE.state:foreground_waiting=INFERENCE_GATE.waiters>0
                if self.background and foreground_waiting:
                    if slot:_ASYNC_INFERENCE_SLOT.release();slot=False
                    await asyncio.sleep(.025);continue
                if not slot:slot=_ASYNC_INFERENCE_SLOT.acquire(blocking=False)
                if slot:acquired=INFERENCE_GATE.lock.acquire(blocking=False)
                if not acquired:await asyncio.sleep(.025)
        except BaseException:
            if slot:_ASYNC_INFERENCE_SLOT.release()
            raise
        finally:
            if not self.background:
                with INFERENCE_GATE.state:INFERENCE_GATE.waiters-=1
        try:
            rows = [dict(row) for row in messages]
            # Qwen3 híbrido admite também a instrução oficial /no_think.
            # Alguns templates comunitários ignoram o campo think do Ollama.
            # Aplica somente à cópia de transporte, sem alterar pedido/preview.
            # Instruct-2507 não possui modo thinking: o prefill pode fazê-lo
            # continuar um raciocínio artificial em vez de responder ao usuário.
            if (self.think is False and re.search(r'qwe+n3',self.model,re.I)
                    and 'instruct' not in self.model.lower()):
                if rows and rows[0].get('role')=='system':
                    rows[0]['content']=rows[0].get('content','')+'\n/no_think'
                else:rows.insert(0,{'role':'system','content':'/no_think'})
                # Prefill oficial Qwen3: fecha o bloco vazio antes da geração.
                # Templates antigos podem abrir <think> mesmo com think=False.
                rows.append({'role':'assistant','content':'<think>\n\n</think>\n\n'})
            payload = dict(model=self.model, stream=True, messages=rows,
                           options=dict(num_ctx=budget.context_tokens, num_predict=budget.output_tokens, temperature=0))
            # Preservar a mesma residência de 5 min solicitada pelo aquecimento;
            # depois disso a IA sai da VRAM e recarrega em ~2 s na próxima pergunta.
            if not self.background:
                payload['keep_alive'] = '5m'
            if self.think is not None:
                payload['think'] = self.think
            if self.protocol == 'native':
                payload['tools'] = schemas
                payload['messages'] = [dict(row) for row in rows]
                for row in payload['messages']:
                    if row.get('tool_calls'):
                        row['tool_calls'] = [dict(call, function=dict(call['function'], arguments=
                            json.loads(call['function']['arguments']) if isinstance(call['function']['arguments'],str) else call['function']['arguments']))
                            for call in row['tool_calls']]
            else:
                import copy
                schema = copy.deepcopy(DECISION_SCHEMA)
                if schemas:
                    schema['properties']['calls']['items'] = {'oneOf': [
                        {'type':'object','properties':{'name':{'type':'string','enum':[spec['function']['name']]},
                            'arguments':spec['function']['parameters']},'required':['name','arguments'],'additionalProperties':False}
                        for spec in schemas]}
                tool_schema = copy.deepcopy(schema)
                tool_schema['properties']['kind']['enum'] = ['tools']
                tool_schema['properties']['calls']['minItems'] = 1
                tool_schema['properties']['calls']['maxItems'] = 4
                final_schema = copy.deepcopy(schema)
                final_schema['properties']['kind']['enum'] = ['final','clarification']
                final_schema['properties']['calls']['maxItems'] = 0
                payload['format'] = {'oneOf':[tool_schema,final_schema]} if schemas else final_schema
                rows = [dict(row) for row in rows]
                rows[0] = dict(rows[0], content=rows[0]['content'] +
                    '\nResponda JSON kind=final|clarification|tools, message e calls=[{name,arguments}]. '
                    'Para chamar ferramentas, kind deve ser tools. final e clarification exigem calls vazio. '
                    'Não responda por memória se o usuário pediu uma consulta. Ferramentas: ' + json.dumps(schemas, ensure_ascii=False))
                # O protocolo JSON recebe observações textuais, sem semântica tool nativa.
                payload['messages'] = [dict(role='user' if row['role'] == 'tool' else row['role'],
                    content=('Observação de ferramenta: ' if row['role'] == 'tool' else '') + row.get('content', '') +
                    ('\nChamadas anteriores: ' + json.dumps(row['tool_calls'], ensure_ascii=False) if row.get('tool_calls') else '')) for row in rows]
            factory = self.client_factory or httpx.AsyncClient
            loop = asyncio.get_running_loop()
            if loop not in self._clients:
                self._clients[loop] = factory(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(budget.seconds))
            client = self._clients[loop]
            if client:
                task = asyncio.create_task(self._read(client, payload, event))
                try:
                    while not task.done():
                        token.check()
                        await asyncio.wait({task}, timeout=.025)
                    token.check()
                    try:return task.result()
                    except httpx.TransportError as error:
                        raise ProviderUnavailable('Não consegui comunicar com o Ollama local; nenhuma decisão foi aplicada.') from error
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
        finally:
            INFERENCE_GATE.lock.release()
            _ASYNC_INFERENCE_SLOT.release()

    async def aclose(self):
        client = self._clients.pop(asyncio.get_running_loop(),None)
        if client:
            await client.aclose()

    async def _read(self, client, payload, event):
        content, calls, size, complete = [], [], 0, False
        prefix_sent=False
        implicit_thinking=bool(payload['messages'] and payload['messages'][-1].get('role')=='assistant'
            and payload['messages'][-1].get('content')=='<think>\n\n</think>\n\n')
        async with client.stream('POST', self.endpoint, json=payload) as response:
            if response.status_code != 200:
                raise ProviderUnavailable(f'Ollama indisponível: HTTP {response.status_code}.')
            async for line in response.aiter_lines():
                if not line:
                    continue
                size += len(line)
                if size > 2_000_000:
                    raise AgentError('Resposta do provider acima do limite.')
                try:
                    row = json.loads(line)
                except (ValueError, TypeError) as error:
                    raise AgentError('Stream Ollama inválido.') from error
                if row.get('error'):
                    raise AgentError('Ollama recusou a geração.')
                message = row.get('message', {})
                content.append(message.get('content', ''))
                calls.extend(message.get('tool_calls') or [])
                if self.protocol=='native' and not calls and not prefix_sent:
                    from therion.voice.stream_prefix import first_sentence
                    raw=''.join(content)
                    boundary=any(tag in raw for tag in ('</think>','</analysis>','</reasoning>'))
                    try:public=final_text(raw) if boundary or not implicit_thinking else ''
                    except AgentError:public=''
                    prefix=first_sentence(public)
                    if prefix:
                        event('response_prefix',text=prefix)
                        prefix_sent=True
                event('provider_activity')
                if row.get('done'):
                    complete = True
                    self.usage = {key: row.get(key) for key in ('prompt_eval_count', 'eval_count', 'total_duration','load_duration','prompt_eval_duration','eval_duration')}
                    if row.get('done_reason') == 'length':
                        raise AgentError('Geração truncada pelo orçamento; nenhuma decisão aplicada.')
        if not complete:
            raise AgentError('Stream terminou sem confirmação de conclusão.')
        if self.protocol == 'json':
            self.last_response = ''.join(content)
            try:
                parsed=json.loads(''.join(content))
                if isinstance(parsed,dict) and isinstance(parsed.get('message'),str):parsed['message']=final_text(parsed['message'])
                return AgentDecision.parse(parsed)
            except (ValueError, TypeError) as error:
                self.diagnostics.append({'error':str(error),'response':self.last_response[:4000]})
                self.diagnostics[:]=self.diagnostics[-3:]
                raise AgentError('Decisão JSON inválida.') from error
        if calls:
            normalized = []
            for call in calls:
                function = call.get('function', {})
                arguments = function.get('arguments')
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError as error:
                        raise AgentError('Argumentos nativos inválidos.') from error
                normalized.append({'name': function.get('name'), 'arguments': arguments})
            return AgentDecision.parse(dict(kind='tools', message='', calls=normalized))
        return AgentDecision.parse(dict(kind='final', message=final_text(''.join(content)), calls=[]))
