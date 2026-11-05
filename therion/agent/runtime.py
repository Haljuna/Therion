"""Ciclo iterativo limitado, sem Qt, com barreira antes de cada efeito."""
import asyncio
import json
import threading
import time
import uuid
import inspect

from .contracts import AgentDecision, AgentError, AgentEvent, Cancelled, CancellationToken, ToolResult, TurnBudget, TurnResult,current_evidence,ProviderUnavailable
from .context import ContextBuilder, SYSTEM
from .execution import cooperative_call


class AgentRuntime:
    def __init__(self, provider, registry, *, store=None, emit=None, context=None, confirmations=None):
        self.provider, self.registry, self.store = provider, registry, store
        self.emit = emit or (lambda event: None)
        self.context = context or ContextBuilder()
        self.confirmations=confirmations
        self.waiting_confirmation=False
        self._sources=()
        self._lock = threading.Lock()
        self._token = None
        self._generation = 0
        self._sequence = 0
        self.turn_id=''

    @property
    def sources(self):
        from copy import deepcopy
        return deepcopy(self._sources)

    def cancel(self):
        if self._token is not None:
            self._token.cancel()

    @property
    def active(self):
        return self._token is not None

    @property
    def accepting_output(self):
        return self._token is not None and not self._token.cancelled

    async def run(self, message, *, session_id, token=None, budget=None, history=(), temporary=False,history_sources=()):
        if not self._lock.acquire(blocking=False):
            return TurnResult('failed', 'Já há um pedido ativo nesta sessão.', '')
        start, turn = time.monotonic(), uuid.uuid4().hex
        self.turn_id=turn
        self._generation += 1
        generation = self._generation
        token, budget = token or CancellationToken(), budget or TurnBudget()
        self._token = token
        self._sources=()
        deadline = start + budget.seconds
        results, rows, previous, duplicates, repair = [], [{'role': 'system', 'content': SYSTEM}], None, 0, 1
        call_count=0
        effect_attempts=set()

        def event(kind, **payload):
            if generation != self._generation:
                return
            self._sequence += 1
            self.emit(AgentEvent(self._sequence, session_id, turn, generation, kind, payload))

        def finish(status, text):
            if status in {'completed','awaiting_clarification'}:
                from therion.context.response_style import normalize_model_greeting
                text=normalize_model_greeting(message,text)
            if self.store:
                try:
                    sources=current_evidence(list(history_sources)+[source for _,row in results if row.status=='success' for source in row.evidence])
                    self.store.append(session_id, 'assistant', text, temporary=temporary,sources=sources)
                except (OSError, ValueError):
                    status = 'uncertain' if any(row.side_effect_state!='none' for _,row in results) else 'failed'
                    text = 'Não consegui registrar a resposta. Confira as evidências antes de repetir ações.'
            from .reading import READERS, complete_reads
            event('terminal', status=status, message=text,
                read_count=sum(call.name in READERS and row.status=='success' for call,row in results),
                complete_read_count=len(complete_reads(results)))
            return TurnResult(status, text, turn, tuple(results), time.monotonic() - start)

        try:
            set_profile=getattr(self.context,'set_profile',None)
            if callable(set_profile):
                set_profile((type(self.provider),getattr(self.provider,'endpoint',None),getattr(self.provider,'model',None),
                    getattr(self.provider,'model_revision',None),getattr(self.provider,'protocol',None),getattr(self.provider,'think',None)))
            if not isinstance(message, str) or not message.strip() or len(message) > 16000:
                raise AgentError('Pedido vazio ou acima do limite.')
            token.check()
            if self.store:
                self.store.append(session_id, 'user', message, temporary=temporary)
            for item in history:
                if isinstance(item, dict) and item.get('role') in {'user', 'assistant'} and isinstance(item.get('content'), str):
                    rows.append({'role': item['role'], 'content': item['content']})
            protected_from=len(rows)
            rows.append({'role': 'user', 'content': message})
            for iteration in range(budget.iterations):
                token.check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                schemas = self.registry.schemas()
                effective_budget=budget
                try:
                    # Decisores determinísticos não enviam contexto a modelo: o limite de tokens
                    # não se aplica, mas build continua aplicando revalidação de fontes.
                    from dataclasses import replace as _replace
                    build_budget=_replace(budget,context_tokens=32768) if getattr(self.provider,'model_free',False) else budget
                    context = self.context.build(rows, schemas, build_budget,protected_from=protected_from)
                except ValueError as error:
                    if not str(error).startswith('O contexto excede o orçamento'):raise
                    from dataclasses import replace
                    for reserve in (1024,512,256):
                        if reserve>=budget.output_tokens:continue
                        try:
                            context=self.context.build(rows,schemas,replace(budget,output_tokens=reserve),protected_from=protected_from)
                            break
                        except ValueError as reduced_error:
                            if not str(reduced_error).startswith('O contexto excede o orçamento'):raise
                    else:raise error
                    available=budget.context_tokens-self.context.estimate(context,schemas)-64
                    effective_budget=replace(budget,output_tokens=max(reserve,min(budget.output_tokens,available)))
                    event('context_budget_adjusted',configured_output=budget.output_tokens,max_output_tokens=effective_budget.output_tokens)
                event('thinking', iteration=iteration + 1)
                try:
                    decision = await asyncio.wait_for(self.provider.decide(context, schemas, effective_budget, token, event), remaining)
                    self.context.record_usage(context, schemas, getattr(self.provider,'usage',{}).get('prompt_eval_count'))
                    if not isinstance(decision, AgentDecision):
                        decision = AgentDecision.parse(decision)
                    prepared = [self.registry.prepare(call) for call in decision.calls]
                    event('decision_validated',decision_kind=decision.kind)
                except Cancelled:
                    raise
                except ProviderUnavailable as error:
                    event('provider_failed',reason=str(error))
                    return finish('partial' if results else 'failed',str(error))
                except AgentError as error:
                    event('decision_rejected',reason=str(error))
                    if repair <= 0:
                        raise
                    repair -= 1
                    rows.append({'role': 'user', 'content': 'Retorne uma decisão válida para o pedido original: '+message+'\nA tentativa anterior foi recusada: ' + str(error) + ' Corrija o formato ou use ferramenta permitida.'})
                    continue
                token.check()
                if decision.kind == 'clarification':
                    return finish('awaiting_clarification', decision.message)
                if decision.kind == 'final':
                    import re
                    cited=set(re.findall(r'\b(?:ecc|note|web|message|procedure|report|gmail|receipt|calendar|memory|document|browser|task):[\w-]+(?:[.:][\w-]+)*',decision.message))
                    # O host fornece proveniência do histórico, nunca permissão.
                    # Revalidá-la no store permite citar uma leitura de outro turno
                    # sem aceitar IDs inventados ou restaurar autorizações antigas.
                    historical=[source for source in history_sources if source.get('id') in cited] if self.store is not None else []
                    evidence=current_evidence(historical+[source for _,row in results if row.status=='success' for source in row.evidence])
                    if evidence and self.store and self.store.source_validator(evidence) is not True:
                        return finish('partial','Uma fonte mudou ou perdeu autorização durante o pedido. Consulte novamente antes de concluir.')
                    sources={source['id']:source.get('source',source['id']) for source in evidence if isinstance(source.get('id'),str)}
                    if cited-set(sources):
                        return finish('partial','A resposta citou uma fonte que não foi confirmada. Consulte os resultados das etapas antes de concluir.')
                    from .claims import unsupported_claim
                    if unsupported_claim(decision.message,results):
                        return finish('partial','Não há recibo verificado para confirmar a ação anunciada. Nenhum novo efeito foi executado por essa resposta.')
                    from .reading import missing_reading
                    if missing_reading(message,decision.message,results,cited,
                            historical_ids={source.get('id') for source in historical}):
                        reason='A conclusão exige leitura integral neste turno; busca lexical e resumo anterior não comprovam dados novos, ausência nem releitura.'
                        event('decision_rejected',reason=reason)
                        if repair > 0:
                            repair -= 1
                            rows.append({'role':'user','content':reason+' Pedido original: '+message+
                                '\nCorrija usando as ferramentas: leia novamente a fonte pertinente e complete a paginação. '
                                'Se a seleção estiver indisponível ou alterada, refaça a busca antes de ler. '
                                'Não apresente resultado anterior como leitura deste turno. Se não conseguir, declare a limitação sem anunciar revisão completa.'})
                            continue
                        return finish('partial','Não há leitura integral verificada neste turno para sustentar essa conclusão. A busca ou uma resposta anterior não comprovam a releitura solicitada.')
                    issues=set()
                    for call,result in results:
                        if result.status!='success':issues.add(result.issue_key or 'call:'+call.id)
                        else:issues.difference_update(result.resolves)
                    failed=bool(issues)
                    substantive=[row for call,row in results if row.status=='success' and call.name not in {'tool_catalog','load_tools','ask_user'}]
                    if failed and not substantive:
                        limitations='\n'.join(call.name+': '+(row.message or row.status) for call,row in results if row.status!='success')
                        failed_calls=[call.name for call,row in results if row.status!='success']
                        header=('Não consegui preparar a ação.' if all(name.startswith('prepare_') for name in failed_calls) else
                                'Não consegui verificar os dados solicitados. Falha ou indisponibilidade não significa resultado vazio.')
                        return finish('partial',header+'\n'+limitations)
                    # O runtime não converte prosa em prova de efeito externo.
                    if any(result.side_effect_state in {'pending', 'uncertain'} for _, result in results):
                        return finish('uncertain', 'Há uma operação pendente ou incerta. Não confirmei a conclusão. ' + decision.message)
                    footer='\n\nFontes consultadas:\n'+'\n'.join(identifier+' — '+str(source) for identifier,source in list(sources.items())[:10]) if sources else ''
                    return finish('partial' if failed else 'completed', decision.message+footer)
                fingerprint = tuple(call.fingerprint for call in decision.calls)
                duplicates = duplicates + 1 if fingerprint == previous else 0
                previous = fingerprint
                if duplicates >= 1:
                    return finish('partial', 'O pedido não avançou após duas tentativas equivalentes. Não repeti a operação.')
                rows.append({'role': 'assistant', 'content': '', 'tool_calls': [
                    {'id': call.id, 'type': 'function', 'function': {'name': call.name, 'arguments': json.dumps(call.arguments, ensure_ascii=False)}}
                    for call in decision.calls]})
                for call, (spec, rejection) in zip(decision.calls, prepared):
                    token.check()
                    if call_count>=budget.calls:
                        return finish('partial','Limite de chamadas atingido. Não iniciei novas operações.')
                    call_count+=1
                    if rejection is None and spec.effect not in {'read','prepare'}:
                        if call.fingerprint in effect_attempts:
                            return finish('partial','Esta operação já foi tentada no turno. Não repeti o efeito.')
                        effect_attempts.add(call.fingerprint)
                    event('tool_started', name=call.name, call_id=call.id)
                    result = rejection
                    verified = False
                    if result is None:
                        if self.store:
                            self.store.begin(call, session_id, turn, spec.effect)
                        elif spec.effect not in {'read','prepare'}:
                            raise AgentError('Efeito externo exige recibo durável.')
                        # Revalidar imediatamente antes do handler, após persistência.
                        _, result = self.registry.prepare(call)
                        if result is None:
                            try:
                                token.check()
                                async def invoke():
                                    if inspect.iscoroutinefunction(spec.handler):
                                        value=await spec.handler(call.arguments,attempt_token)
                                        attempt_token.check()
                                        return value
                                    value=await cooperative_call(spec.handler,call.arguments,attempt_token,token=attempt_token)
                                    return await value if inspect.isawaitable(value) else value
                                for attempt in range(2):
                                    attempt_token = CancellationToken(parent=token)
                                    _, result = self.registry.prepare(call)
                                    if result is not None:break
                                    completed=False
                                    try:
                                        token.check()
                                        event('tool_running',name=call.name,call_id=call.id,effect=spec.effect)
                                        value=await asyncio.wait_for(invoke(),min(spec.timeout,max(.01,deadline-time.monotonic())))
                                        completed=True
                                        break
                                    except (ConnectionError, TimeoutError) as error:
                                        if spec.effect!='read' or attempt or time.monotonic()>=deadline:raise
                                        event('tool_retry',name=call.name,call_id=call.id,reason=type(error).__name__)
                                    finally:
                                        if not completed:attempt_token.cancel()
                                if result is not None:
                                    value=result
                                if not isinstance(value, ToolResult):
                                    raise AgentError('Ferramenta retornou contrato inválido.')
                                token.check()
                                result = value
                                if result.status=='success' and spec.verify is not None:
                                    verified=spec.verify(call.arguments,result) is True
                                    if not verified and spec.effect in {'read','prepare'}:
                                        result=ToolResult('blocked',message='Não confirmei a fonte ou a autorização depois da consulta. Não entreguei o conteúdo ao modelo.',
                                            issue_key=result.resolves[0] if result.resolves else result.issue_key)
                                if spec.effect not in {'read','prepare'} and result.status == 'success':
                                    if not verified:
                                        result = ToolResult('uncertain', message='Efeito sem verificação independente.', side_effect_state='uncertain')
                            except Cancelled:
                                result = ToolResult('cancelled' if spec.effect in {'read','prepare'} else 'uncertain', side_effect_state='none' if spec.effect in {'read','prepare'} else 'uncertain')
                            except (ValueError,OSError) as error:
                                safe=spec.effect in {'read','prepare'}
                                result=ToolResult(('blocked' if isinstance(error,ValueError) else 'unavailable') if safe else 'uncertain',
                                    message=str(error)[:500] if safe else 'Efeito não confirmado. Não repeti a operação.',side_effect_state='none' if safe else 'uncertain')
                            except Exception:
                                result = ToolResult('failed' if spec.effect in {'read','prepare'} else 'uncertain', message='Ferramenta não concluiu; resultado preservado sem repetição.', side_effect_state='none' if spec.effect in {'read','prepare'} else 'uncertain')
                        if self.store:
                            self.store.finish(call.id, result.status,verified=verified and result.status=='success')
                    if result.status=='awaiting_confirmation' and self.confirmations is not None and isinstance(result.data,dict) and result.data.get('proposal_id'):
                        resolutions=result.resolves
                        self.waiting_confirmation=True
                        event('awaiting_confirmation',proposal_id=result.data['proposal_id'],message=result.message)
                        try:
                            result=await self.confirmations.wait_for_result(result.data['proposal_id'],token,max(0,deadline-time.monotonic()))
                            if result.status=='success' and resolutions:
                                from dataclasses import replace
                                result=replace(result,resolves=tuple(dict.fromkeys(result.resolves+resolutions)))
                        finally:self.waiting_confirmation=False
                        if self.store:self.store.finish(call.id,result.status,verified=result.side_effect_state=='verified')
                    results.append((call, result))
                    self._sources=tuple(current_evidence([source for _,value in results if value.status=='success' for source in value.evidence]))
                    observation=result.observation()
                    if call.name in {'gmail_search','gmail_message_headers'}:
                        # A vinculação opaca à conta fica integral nos recibos e
                        # em result.evidence, usados para autorização/histórico.
                        # IDs, versões, fontes e dados consultados ficam no prompt.
                        observation['evidence']=[{key:value for key,value in source.items() if key!='account'}
                                                 for source in observation['evidence']]
                        content=json.dumps(observation,ensure_ascii=False,default=str,separators=(',',':'))
                    else:content=json.dumps(observation,ensure_ascii=False,default=str)
                    rows.append({'role': 'tool', 'tool_call_id': call.id, 'content':content})
                    from .reading import read_range, complete_reads
                    reading=read_range(call,result)
                    if reading is not None:
                        reading['complete']=bool(complete_reads(results).intersection(source.get('id') for source in result.evidence))
                    event('tool_finished', name=call.name, call_id=call.id, status=result.status,
                        verified=verified or result.side_effect_state=='verified',reading=reading)
                    if result.status in {'uncertain', 'awaiting_confirmation','awaiting_clarification','cancelled'}:
                        return finish(result.status, result.message or 'Operação aguardando revisão.')
                    token.check()
            return finish('partial', 'Limite de etapas atingido. Consulte os resultados das etapas concluídas.')
        except Cancelled:
            return finish('cancelled', 'Pedido cancelado. Efeitos já ocorridos não foram desfeitos.')
        except asyncio.CancelledError:
            token.cancel()
            if self.confirmations is not None:self.confirmations.clear()
            return finish('cancelled','Pedido interrompido; propostas pendentes foram invalidadas. Confira recibos antes de repetir efeitos.')
        except TimeoutError:
            return finish('partial' if results else 'failed', 'Tempo total do pedido esgotado; não iniciei novas etapas.')
        except (AgentError, ValueError, OSError) as error:
            return finish('partial' if results else 'failed', str(error))
        except Exception:
            return finish('partial' if results else 'failed', 'O processamento falhou. Nenhuma nova etapa foi iniciada; confira os recibos antes de repetir ações.')
        finally:
            try:
                close = getattr(self.provider, 'aclose', None)
                if close:
                    await close()
            finally:
                self._token = None
                self._lock.release()
