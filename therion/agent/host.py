"""Integração opt-in do runtime, sem alterar autorizações existentes."""
import asyncio
from collections import deque
from pathlib import Path
import os
import hashlib
import json
import re
import threading

from .builtin import build_read_registry
from .contracts import CancellationToken, ToolResult, ToolSpec, TurnBudget,current_evidence
from .ollama import OllamaAgentProvider
from .registry import TEXT, object_schema,initial_tools
from .runtime import AgentRuntime
from .store import SessionStore


class AgentSupport:
    def _init_agent(self, config=None, state_root=None, provider=None):
        from .settings import validate_settings
        self._agent_config = validate_settings(config)
        self._agent_root = Path(state_root) if state_root else Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'AppData'/'Local')))/'Therion'/'agent'
        self._agent_provider = provider
        self._agent_runtime = None
        self._agent_store = None
        self._agent_proposals = None
        self._agent_workers = {}
        self._agent_reviewer = None
        self._agent_events = deque(maxlen=256)
        self._agent_event_lock = threading.Lock()
        self._agent_temporary = False
        self._agent_turn_sources = {}
        self._agent_waiting_for_answer=False
        self._agent_legacy_pending={}
        self._agent_turn_token=None
        self._gmail_read_offer=None
        self._gmail_list_context=None
        self._gmail_draft_request=None
        self._gmail_current_context=None
        from .mailbox import Mailbox
        self._mailbox=Mailbox(self)

    def _get_agent_store(self):
        if self._agent_store is None:
            store=SessionStore(self._agent_root/'sessions.sqlite3',enabled=self._agent_config.get('history_enabled') is True)
            store.interrupted()
            self._agent_store=store
        self._agent_store.source_validator=self._history_sources_allowed
        return self._agent_store

    def _agent_begin_legacy(self, confirmation):
        binding=self._agent_legacy_pending.get(confirmation)
        if binding and binding['session']==self.session_id:
            self._agent_store.finish(binding['call_id'],'running')

    def _agent_finish_legacy(self, confirmation, result=None):
        binding=self._agent_legacy_pending.pop(confirmation,None)
        if not binding:return
        state='uncertain';verified=False
        if result is not None:
            if binding['session']!=self.session_id:
                state='uncertain'
            elif self._confirmation_id==confirmation:
                # Consultar status/memória durante uma proposta não confirma
                # o efeito pendente, mesmo se essa consulta retornar sucesso.
                self._agent_legacy_pending[confirmation]=binding
                state='awaiting_confirmation'
            elif result.status=='awaiting_confirmation' and self._confirmation_id:
                self._agent_legacy_pending[self._confirmation_id]=binding
                state='awaiting_confirmation'
            elif result.status=='success':state='success';verified=True
            elif result.status=='executed_simulated':state='simulated'
            elif result.status in {'cancelled','forbidden'}:state=result.status
            if binding.get('plan') and result.plan is not None and self._plan_fingerprint(result.plan)!=binding['plan']:
                state='uncertain';verified=False
        self._agent_store.finish(binding['call_id'],state,verified=verified)

    def cancel_agent(self):
        self._gmail_read_offer=None
        self._gmail_list_context=None
        self._gmail_draft_request=None
        self._gmail_current_context=None
        if self._agent_turn_token:self._agent_turn_token.cancel()
        if self._agent_runtime:
            self._agent_runtime.cancel()
        if self._agent_proposals:self._agent_proposals.clear()
        if self._agent_reviewer:self._agent_reviewer.cancel()

    def close_agent(self):
        self._mailbox.clear()
        self._gmail_read_offer=None
        self.cancel_agent()
        if self._agent_reviewer:
            self._agent_reviewer.cancel()
        for worker in self._agent_workers.values():
            worker.close()
        self._agent_workers.clear()
        if self._agent_proposals:
            self._agent_proposals.clear()

    def agent_events(self):
        with self._agent_event_lock:
            rows=list(self._agent_events)
            self._agent_events.clear()
        return rows

    def _emit_agent_event(self,event):
        with self._agent_event_lock:
            if (event.type=='provider_activity' and self._agent_events
                    and self._agent_events[-1].type=='provider_activity'):
                self._agent_events[-1]=event
            else:
                self._agent_events.append(event)

    def _record_legacy_history(self, command, result):
        if self._agent_config.get('enabled') is not True and self._agent_config.get('history_enabled') is not True:return
        from therion.memory.commands import memory_request
        private_control=memory_request(command) is not None or any(getattr(row,'origin','')=='memory_preview' for row in list(self.memory.turns)[-2:])
        sources=self._legacy_history_sources()
        for row in list(self.memory.turns)[-2:]:
            if row.role=='therion' and getattr(row,'origin','')!='memory_preview':self._agent_turn_sources[(self.session_id,row.turn_id)]=sources
        if self._agent_config.get('history_enabled') is not True or self._agent_temporary:
            return
        self._get_agent_store()
        self._agent_store.append(self.session_id,'user','Controle supervisionado de memória' if private_control else command)
        self._agent_store.append(self.session_id,'assistant','Controle de memória processado; prévia mantida fora do histórico.' if private_control else result.message,sources=sources)

    def _history_access_key(self):
        from .proposals import fingerprint
        return fingerprint({'roots':list(self.second_brain.allowed_roots),'memory_policy':str(self.knowledge.policy),
            'calendar':self.calendar_adapter is not None,'settings':{key:self._agent_config.get(key) for key in (
                'gmail_enabled','browser_enabled','desktop_enabled','documents_enabled','web_enabled',
                'browser_domains','document_read_roots','desktop_targets')}})

    def _legacy_history_sources(self):
        sources=[{'id':'legacy:access','source':'política local','version':self._history_access_key()}]
        snapshot=getattr(self,'_personal_snapshot',None)
        if snapshot:
            sources.extend({'id':'legacy:file','source':row.path,'version':row.version,'encoding':'text'} for row in snapshot[0])
        evidence=getattr(self,'_last_tool_evidence',None)
        if isinstance(evidence,dict) and evidence.get('kind')=='note':
            path=Path(self.second_brain.vault_root)/evidence.get('path','')
            try:
                self.second_brain._check_access()
                from therion.memory.knowledge import safe_path
                path=safe_path(path,self.second_brain.allowed_roots)
                text=path.read_text(encoding='utf-8')
                if not text.startswith(evidence.get('content','')):raise ValueError('Fonte alterada')
                sources.append({'id':'legacy:file','source':str(path),'version':hashlib.sha256(text.encode()).hexdigest(),'encoding':'text'})
            except (OSError,ValueError):sources.append({'id':'unresolved:source','source':'fonte indisponível'})
        search=getattr(self,'_search_snapshot',None)
        if search:
            for row in search[0].get('matches',[]):
                sources.append({'id':'legacy:file','source':str(Path(self.second_brain.vault_root)/row['path']),'version':row.get('version',''),'encoding':'text'})
        return sources

    def _history_sources_allowed(self,references,seen=frozenset()):
        from therion.memory.knowledge import safe_path
        if not isinstance(references,(list,tuple)) or len(references)>100 or len(seen)>64:return False
        for reference in references:
            if not isinstance(reference,dict):return False
            source=reference.get('source','')
            identifier=reference.get('id','')
            if not isinstance(source,str) or not isinstance(identifier,str):return False
            if identifier=='legacy:access':
                if reference.get('version')!=self._history_access_key():return False
                continue
            if identifier.startswith('receipt:'):
                if self._agent_store is None or not self._agent_store.operations(identifier.split(':',1)[1]):return False
                continue
            if identifier.startswith('mcp:'):
                from .proposals import fingerprint
                parts=identifier.split(':')
                if self._agent_config.get('mcp_enabled') is not True or len(parts)!=3:return False
                server=next((row for row in self._agent_config.get('mcp_servers',[]) if row.get('id')==parts[1]),None)
                if server is None or reference.get('registration')!=fingerprint(server):return False
                from therion.integrations.mcp import verify_pins
                try:verify_pins(server)
                except (OSError,ValueError):return False
                continue
            if identifier.startswith('ecc:'):
                from therion.skills.ecc import EccSkill
                parts=identifier.split(':')
                if len(parts)!=3:return False
                try:current=EccSkill().read(parts[1],parts[2])
                except (OSError,ValueError):return False
                if source!=current['source'] or reference.get('version')!=current['sha256']:return False
                continue
            if identifier.startswith('procedure:'):
                if self._agent_config.get('learning_enabled') is not True or self._agent_store is None:return False
                from .procedures import ProcedureLibrary
                try:procedure=ProcedureLibrary(self._agent_store).get(identifier.split(':',1)[1])
                except ValueError:return False
                if procedure['state']!='active' or procedure['digest']!=reference.get('version'):return False
                continue
            if identifier.startswith('session:'):
                if identifier in seen:return False
                parts=identifier.split(':')
                if len(parts)!=3 or parts[1]!=self.session_id:return False
                original=next((row for row in self.memory.turns if str(row.turn_id)==parts[2]),None)
                if original is None:return False
                if original.role!='user':
                    sources=self._agent_turn_sources.get((self.session_id,original.turn_id))
                    if sources is None or not self._history_sources_allowed(sources,seen|{identifier}):return False
                continue
            if identifier.startswith('message:'):
                if identifier in seen or self._agent_store is None or not self._agent_store.enabled:return False
                try:
                    with self._agent_store.connection() as db:
                        original=db.execute('SELECT sources FROM messages WHERE id=? AND expires>?',(int(identifier.split(':',1)[1]),self._agent_store.clock())).fetchone()
                    if original is None or not self._history_sources_allowed(json.loads(original['sources']),seen|{identifier}):return False
                except (ValueError,TypeError,OSError):return False
                continue
            if identifier.startswith('gmail:'):
                if self._agent_config.get('gmail_enabled') is not True:return False
                from therion.integrations.gmail import account_identity
                from .proposals import fingerprint
                factory=getattr(self,'_gmail_adapter_factory',None)
                account=fingerprint(['fixture',id(factory)]) if factory is not None else account_identity(self._agent_root/'credentials')
                if account is None or reference.get('account')!=account:return False
            if identifier.startswith('calendar:'):
                if self.calendar_adapter is None:return False
                from therion.calendar.google_adapter import GoogleCalendarAdapter
                if isinstance(self.calendar_adapter,GoogleCalendarAdapter):
                    from therion.integrations.calendar import account_key
                    account=account_key(self)
                    if account is None or reference.get('account')!=account:return False
            if identifier.startswith('web:') and self._agent_config.get('web_enabled') is not True:return False
            if identifier.startswith(('gmail:','calendar:','web:')):continue
            if identifier.startswith('browser:'):
                from urllib.parse import urlsplit
                if self._agent_config.get('browser_enabled') is not True or urlsplit(source).hostname not in self._agent_config.get('browser_domains',[]):return False
                if reference.get('browser_channel','chromium')!=self._agent_config.get('browser_channel','chromium'):return False
                continue
            if identifier.startswith('desktop:'):
                if self._agent_config.get('desktop_enabled') is not True:return False
                continue
            if os.path.isabs(source):
                try:
                    roots=[]
                    try:self.second_brain._check_access();roots=list(self.second_brain.allowed_roots)
                    except PermissionError:pass
                    if self._agent_config.get('documents_enabled') is True:roots+=self._agent_config.get('document_read_roots',[])
                    path=safe_path(source,roots)
                    if path.stat().st_nlink!=1 or path.stat().st_size>20_000_000:return False
                    if identifier.startswith('memory:'):
                        if self._knowledge_repository is None:return False
                        self._knowledge_repository._check(self.knowledge.policy,self.knowledge.clock())
                    data=path.read_text(encoding='utf-8').encode() if identifier.startswith(('note:','memory:')) or reference.get('encoding')=='text' else path.read_bytes()
                    if not reference.get('version') or hashlib.sha256(data).hexdigest()!=reference['version']:return False
                except (ValueError,OSError,PermissionError):return False
                continue
            return False
        return True

    def _dispatch_agent(self, command, cancelled=None):
        from therion.core.orchestrator import OrchestrationResult, _parse_scope_syntax
        from therion.context.read_scope import ReadScope
        from therion.context.language import control
        from therion.memory.commands import memory_request
        from therion.context.knowledge_review import review_request
        config = self._agent_config
        memory_control=memory_request(command)
        if self._agent_turn_token is not None:
            if memory_control and memory_control['operation'] in {'pause','revoke_write','revoke_access'}:
                # Controles humanos restritivos têm efeito mesmo durante um
                # turno: interromper primeiro e aplicar a política legada.
                self.cancel_agent()
                return None
            if control(command) in {'cancela','cancelar','cancele o pedido'}:
                self.cancel_agent()
                return OrchestrationResult(status='cancelled',message='Cancelamento solicitado; aguarde o encerramento do turno ativo.')
            return OrchestrationResult(status='clarification',message='Já há um pedido ativo nesta sessão. Aguarde ou use Parar.')
        if self._agent_reviewer:
            self._agent_reviewer.cancel()
        if config.get('enabled') is not True:
            self._gmail_read_offer=None
            self._gmail_list_context=None
            self._gmail_draft_request=None
            self._gmail_current_context=None
            return None
        from therion.context.conversation_frame import email_capability_request
        if email_capability_request(command):
            self._gmail_read_offer=None
            self._gmail_list_context=None
            self._gmail_current_context=None
            return None  # O resolvedor local informa a capacidade configurada.
        from therion.core.workflows import read_only_workflow
        if not self._confirmation_id and read_only_workflow(command, self._calendar_now()):
            # 04/11: o modelo quebrava "tarefas e e-mail importante"; o motor de compostos responde sem ele.
            return None
        import time
        from .gmail_queries import listed_mail_request,recent_mail_request
        from .gmail_searches import contextual_mail_request,is_mail_query,ambiguous_mail_list
        if ambiguous_mail_list(command) and not self._confirmation_id and not self._gmail_draft_request:
            return OrchestrationResult(status='clarification',message='Você quis dizer listar seus e-mails? Diga “lista meus e-mails” para eu consultar.')
        gmail_followup=None
        gmail_reference_mode=None
        mail_request=recent_mail_request(command,now=self._calendar_now())
        contextual=contextual_mail_request(command)
        ordinal_request=listed_mail_request(command)
        # Referências vagas como “o segundo” continuam ligadas à lista falada;
        # um gesto no painel só a substitui quando o usuário identifica e-mail.
        if contextual or (ordinal_request and re.search(r'\be[- ]?mail\b',control(command))):
            ui=self._mailbox.context()
            if ui:
                now=time.monotonic()
                if ui['current'] and (self._gmail_current_context is None or now>=self._gmail_current_context['deadline'] or ui['at']>=self._gmail_current_context['deadline']-120):
                    self._gmail_current_context=dict(ui['current'],session=self.session_id,deadline=now+120,sources=ui['sources'])
                if ui['messages'] and (self._gmail_list_context is None or now>=self._gmail_list_context['deadline'] or ui['at']>=self._gmail_list_context['deadline']-120):
                    self._gmail_list_context=dict(messages=ui['messages'],session=self.session_id,deadline=now+120,sources=ui['sources'])
        current=self._gmail_current_context
        if current is not None and (current['session']!=self.session_id or time.monotonic()>=current['deadline']):
            self._gmail_current_context=None;current=None
        if contextual and not self._confirmation_id:
            if current is None:
                return OrchestrationResult(status='clarification',message='Qual e-mail você quer consultar? Peça para mostrar um e-mail primeiro.')
            if not self._history_sources_allowed(current['sources']):
                self._gmail_current_context=None
                return OrchestrationResult(status='forbidden',message='A conexão Gmail mudou. Faça uma nova consulta.')
            gmail_reference_mode=contextual if contextual in {'received','body'} else 'summary'
            gmail_followup=dict(current)
            if contextual=='previous':
                snapshot=current.get('snapshot',[])
                index=next((i for i,row in enumerate(snapshot) if row['message_id']==current['message_id']),None)
                if index is None or index+1>=len(snapshot):
                    return OrchestrationResult(status='clarification',message='Não há outro e-mail anterior na seleção consultada. Peça uma nova lista.')
                gmail_followup=dict(snapshot[index+1],query=current['query'],snapshot=snapshot)
        elif mail_request:
            self._gmail_current_context=None
        elif control(command) not in {'sim','pode','leia','leia para mim','pode ler','leia completo','nao','no','nao precisa','agora nao','see','but','point'} and not listed_mail_request(command):
            self._gmail_current_context=None
        ordinal=listed_mail_request(command)
        listing=self._gmail_list_context
        if listing is not None and (listing['session']!=self.session_id or time.monotonic()>=listing['deadline']):
            self._gmail_list_context=None;listing=None
        if ordinal is not None and not self._confirmation_id:
            self._gmail_read_offer=None
            if listing is None:
                return OrchestrationResult(status='clarification',message='Qual lista de e-mails você quer consultar? Peça para listar os mais recentes primeiro.')
            if not self._history_sources_allowed(listing['sources']):
                self._gmail_list_context=None
                return OrchestrationResult(status='forbidden',message='A conexão ou a autorização do Gmail mudou. Faça uma nova consulta.')
            if ordinal[1]>len(listing['messages']):
                return OrchestrationResult(status='clarification',message='A última lista não contém essa posição. Peça uma nova lista de e-mails.')
            gmail_followup=dict(listing['messages'][ordinal[1]-1])
            gmail_reference_mode=ordinal[0]
        elif not mail_request and not contextual and control(command) not in {'sim','pode','leia','leia para mim','pode ler','leia completo','nao','no','nao precisa','agora nao','see','but','point'}:
            self._gmail_list_context=None
        elif mail_request:
            self._gmail_list_context=None
        offer=self._gmail_read_offer
        if offer is not None:
            self._gmail_read_offer=None
            if offer['session']==self.session_id and time.monotonic()<offer['deadline'] and not self._confirmation_id:
                if control(command) in {'sim','pode','leia','leia para mim','pode ler','leia completo'}:
                    if not self._history_sources_allowed(offer['sources']):
                        return OrchestrationResult(status='forbidden',message='A conexão ou a autorização do Gmail mudou. Faça uma nova consulta.')
                    gmail_followup=offer
                elif control(command) in {'nao','no','nao precisa','agora nao'}:
                    return OrchestrationResult(status='success',message='Tudo bem. Não vou ler o e-mail em voz alta.')
                elif control(command) in {'see','but','point','sim?','nao?'}:
                    self._gmail_read_offer=offer
                    return OrchestrationResult(status='clarification',message='Não reconheci sua resposta. Quer que eu leia esse e-mail? Diga sim ou não.')
        self._agent_original_request = command
        if self._agent_provider is None and not self._confirmation_id and not self._gmail_draft_request and is_mail_query(command):
            if config.get('gmail_enabled') is not True:
                return OrchestrationResult(status='forbidden',message='Ative e conecte o Gmail no painel Capacidades antes de consultar mensagens.')
            if not (mail_request or gmail_followup or ordinal or contextual):
                return OrchestrationResult(status='clarification',message='Posso listar e-mails recentes, de hoje ou de ontem, buscar por assunto e informar a data de recebimento. Qual consulta você deseja?')
        if not self.memory.can_start_exchange(command):
            return OrchestrationResult(status='session_limit',message='Limite de mensagem ou sessão atingido. Inicie outra conversa.')
        direct_draft=None
        if self._agent_provider is None and not self._confirmation_id and not any(getattr(self,attr,None) for attr in (
                '_pending_event_draft','_alias_flow_step','_delete_alias_flow_step','_replace_alias_flow_step','_unknown_target_flow_step')):
            from .gmail_drafts import draft_dialogue,DraftProvider
            draft_turn=draft_dialogue(self,command)
            if draft_turn is not None:
                if 'question' in draft_turn:
                    self.memory.add_turn('user',command);self.memory.add_turn('therion',draft_turn['question'])
                    self._agent_waiting_for_answer=self._gmail_draft_request is not None
                    return OrchestrationResult(status='clarification',message=draft_turn['question'])
                direct_draft=draft_turn['draft']
        # Propostas/controles existentes conservam a autoridade de seus fluxos.
        memory_control=memory_request(command)
        if (self._confirmation_id or (memory_control and memory_control['operation'] in {'pause','revoke_write','revoke_access'}) or review_request(command)
                or control(command) in {'cancela', 'cancelar', 'cancele o pedido', 'status do pedido'}
                or (not gmail_followup and not self._agent_waiting_for_answer and control(command) in {'sim','nao','pode'})
                or any(getattr(self, attr, None) for attr in ('_pending_event_draft', '_alias_flow_step',
                    '_delete_alias_flow_step', '_replace_alias_flow_step', '_unknown_target_flow_step'))):
            return None
        if memory_control:
            from .memory_control import run_memory_control
            return run_memory_control(self,command,memory_control,cancelled)
        syntax = _parse_scope_syntax(command)
        if syntax.malformed:
            return OrchestrationResult(status='clarification', message='Escopo inválido: ' + syntax.reason)
        from therion.context.conversation_frame import personal_request, capabilities_request, current_date_request, current_time_request, app_status_request,app_close_request,app_result_request
        status_followup=self._catalog_status_followup(syntax.command)
        if (personal_request(syntax.command,voice=self.voice_conversation) is not None or capabilities_request(syntax.command)
                or current_date_request(syntax.command) or current_time_request(syntax.command) or app_status_request(syntax.command)
                or app_close_request(syntax.command) or app_result_request(syntax.command)
                or status_followup):
            # Relógio, capacidades e perfil mantêm seus resolvedores locais.
            # Ativar o runtime não pode ocultá-los nem conceder leitura nova.
            return None
        legacy_intent=self._voice_opening_review(syntax.command,self.intent_recognizer.parse(syntax.command))
        if self._calendar_followup_request(syntax.command) is not None:
            return None
        self._calendar_query_context = None
        if legacy_intent is not None and legacy_intent.action in {
                'listar aliases','adicionar alias','excluir alias','substituir alias','planejar dia',
                'consultar agenda','calendário hoje'}:
            return None
        if (legacy_intent is not None and legacy_intent.action=='criar evento calendário'
                and self._agent_provider is not None):
            return None
        if (legacy_intent is not None and legacy_intent.action=='calendário hoje'
                and self.intent_recognizer._CALENDAR_TODAY_PATTERN.fullmatch(syntax.command.strip())):
            return None
        scope = None
        if syntax.present:
            resolved=self._resolve_scope_roots(syntax.roots)
            if resolved.invalid:
                return OrchestrationResult(status='invalid_scope',message='Raízes inválidas. Use caminhos relativos ao cofre, sem segmentos de saída.')
            if syntax.roots and not resolved.accepted:
                return OrchestrationResult(status='forbidden',message='As raízes declaradas estão fora do escopo permitido. Nenhuma nota foi consultada.')
            scope=ReadScope(self.session_id,resolved.accepted)
        try:
            self._get_agent_store()
            self._agent_store.purge()
        except (OSError,ValueError):
            return OrchestrationResult(status='ai_unavailable',message='Histórico ou recibos indisponíveis. Preservei os dados e não iniciei operações; confira o banco antes de continuar.')
        self._agent_store.source_validator=self._history_sources_allowed
        if self._agent_proposals is None:
            from .proposals import ActionProposals
            self._agent_proposals = ActionProposals(self._agent_store, lambda:self.session_id,
                dependencies=lambda:self._agent_runtime.sources if self._agent_runtime and self._agent_runtime.active else (),
                verify_dependencies=lambda sources,token:self._history_sources_allowed(sources))
        core_provider = getattr(self.ai_core, '_provider', None)
        from .grounded_questions import question_kind,GroundedQuestionProvider,GroundedQuestionContext
        from .gmail_queries import recent_mail_request,RecentMailProvider,GmailQueryContext
        direct_gmail=((gmail_reference_mode or 'body',1) if gmail_followup else recent_mail_request(syntax.command,now=self._calendar_now())) if self._agent_provider is None and config.get('gmail_enabled') is True else None
        grounded_kind=question_kind(syntax.command) if self._agent_provider is None and direct_draft is None else None
        if grounded_kind=='activity_scope':
            return OrchestrationResult(status='clarification',message='Você quer saber a próxima atividade da faculdade ou o próximo compromisso da agenda?')
        direct_app=self._agent_provider is None and legacy_intent is not None and legacy_intent.action=='abrir aplicativo'
        direct_calendar=self._agent_provider is None and legacy_intent is not None and legacy_intent.action=='criar evento calendário'
        direct_search=self._agent_provider is None and not grounded_kind and legacy_intent is not None and legacy_intent.action=='buscar segundo cérebro'
        from therion.integrations.task_query import task_state_request
        # O modelo negava tarefas existentes sem consultar; aqui a fonte decide e a confirmação continua.
        direct_task=task_state_request(syntax.command) if self._agent_provider is None and direct_draft is None else None
        if direct_task:
            from .direct import ExplicitTaskStateProvider
            provider=ExplicitTaskStateProvider(direct_task['state'],direct_task['hint'])
        elif direct_draft:
            provider=DraftProvider(direct_draft)
        elif direct_gmail:
            summarizer=(getattr(self,'_gmail_summary_provider',None) or
                (OllamaAgentProvider(core_provider.ENDPOINT,core_provider.model,protocol=config.get('protocol','json'),think=False)
                 if core_provider is not None and direct_gmail[0]=='summary' else None))
            provider=RecentMailProvider(direct_gmail,summarizer=summarizer,selected=gmail_followup)
        elif direct_app or direct_calendar:
            from .direct import ExplicitAppProvider
            provider=ExplicitAppProvider(syntax.command)
        elif direct_search:
            from .direct import ExplicitSearchProvider
            provider=ExplicitSearchProvider(legacy_intent.target.rstrip('.!?').strip())
        else:
            provider = self._agent_provider or (OllamaAgentProvider(core_provider.ENDPOINT, core_provider.model,
                protocol=config.get('protocol', 'json'), think=core_provider.think if config.get('think') is None else config['think']) if core_provider is not None else None)
        if grounded_kind and provider is not None:
            if scope is None:
                requested=('10 - Projetos/Therion' if grounded_kind=='project' else '02 - Faculdade',)
                resolved=self._resolve_scope_roots(requested)
                if not resolved.accepted:
                    return OrchestrationResult(status='forbidden',message='A fonte desse pedido não está no escopo permitido. Nenhuma nota foi consultada.')
                scope=ReadScope(self.session_id,resolved.accepted)
            provider=GroundedQuestionProvider(provider,grounded_kind,self._calendar_now())
        if provider is None:
            return OrchestrationResult(status='ai_unavailable', message='Configure a IA local antes de usar o núcleo de ferramentas.')
        registry = build_read_registry(self, scope=scope)
        from therion.integrations.tools import register_personal_tools
        register_personal_tools(registry, self,read_cache=bool(direct_gmail))
        from therion.integrations.visual_tools import register_visual_tools
        register_visual_tools(registry, self)
        from therion.integrations.mcp_tools import register_mcp_tools
        register_mcp_tools(registry,self)
        from therion.skills.cybersecurity import register_cybersecurity_tools
        register_cybersecurity_tools(registry)
        from therion.skills.ecc import register_ecc_tools
        register_ecc_tools(registry)
        from therion.skills.graphify import register_graphify_tools
        register_graphify_tools(registry, self, requested=bool(re.search(r'\bgraphify\b', syntax.command, re.I)))
        from therion.integrations.calendar import register_calendar_tools
        structured_calendar=register_calendar_tools(registry,self)
        from therion.integrations.routines import register_routine_tools
        register_routine_tools(registry,self)
        async def operation_receipts(arguments,token):
            token.check()
            rows=self._agent_store.operations(arguments['call_id'] or None)
            return ToolResult('success',data=rows,evidence=tuple({'id':'receipt:'+row['call_id'],'source':'registro operacional local','created':row['created']} for row in rows))
        registry.register(ToolSpec('operation_receipts','Consultar estado e identificadores mínimos de operações, inclusive interrompidas/incertas. Não repete nem autoriza ações.',
            object_schema(call_id=dict(type='string',maxLength=100)),operation_receipts,authorize=lambda args:True))
        async def search_session(arguments,token):
            from therion.memory.session_recall import search
            token.check()
            allowed=[]
            for row in self.memory.turns:
                if getattr(row,'origin','')=='memory_preview':continue
                sources=self._agent_turn_sources.get((self.session_id,row.turn_id))
                if row.role=='user' or (sources is not None and self._history_sources_allowed(sources)):allowed.append(row)
            matches=search(allowed,arguments['query'],limit=6)
            data=[{'id':'session:'+self.session_id+':'+str(row.turn_id),'role':row.role,'content':row.text} for row in matches]
            if self._agent_store.enabled:
                with self._agent_store.connection() as db:
                    for item in data:
                        original=db.execute('SELECT id FROM messages WHERE session=? AND role=? AND content=? AND expires>? ORDER BY id DESC LIMIT 1',
                            (self.session_id,'user' if item['role']=='user' else 'assistant',item['content'],self._agent_store.clock())).fetchone()
                        if original:item['id']='message:'+str(original['id'])
            return ToolResult('success',data=data,evidence=tuple({'id':row['id'],'source':'sessão atual'} for row in data))
        registry.register(ToolSpec('search_session','Buscar mensagens originais da conversa atual, inclusive trechos anteriores ao contexto abreviado.',
            object_schema(query=TEXT),search_session,authorize=lambda args:True))
        if self._agent_store.enabled:
            async def search_history(arguments,token):
                token.check()
                data=self._agent_store.search(arguments['query'])
                return ToolResult('success',data=data,evidence=tuple({'id':'message:'+str(row['id']),'source':'histórico local','created':row['created']} for row in data))
            registry.register(ToolSpec('search_history','Buscar mensagens originais não expiradas no histórico autorizado.',
                object_schema(query=TEXT),search_history,authorize=lambda args:self._agent_store.enabled and not self._agent_temporary))
        if config.get('learning_enabled') is True:
            from .procedures import ProcedureLibrary
            library=ProcedureLibrary(self._agent_store)
            async def procedure_index(arguments,token):
                token.check();return ToolResult('success',data=[row for row in library.index() if row['state']=='active'])
            async def procedure_read(arguments,token):
                token.check()
                procedure=library.get(arguments['id'])
                if procedure['state']!='active':return ToolResult('blocked',message='Procedimento ainda não está ativo. Faça a revisão e os testes no painel.')
                return ToolResult('success',data=procedure,message='Instruções declarativas, não resultado. Execute os passos por ferramentas autorizadas; catálogo → load_tools → chamada quando necessário. Não use o critério de verificação como resposta da consulta.',evidence=({'id':'procedure:'+procedure['id'],'source':procedure['body']['title'],'version':procedure['digest']},))
            registry.register(ToolSpec('procedure_index','Consultar índice de procedimentos declarativos.',object_schema(),procedure_index,
                authorize=lambda args:self._agent_config.get('learning_enabled') is True))
            registry.register(ToolSpec('procedure_read','Ler procedimento e seu estado; não concede permissão.',object_schema(id=TEXT),procedure_read,
                authorize=lambda args:self._agent_config.get('learning_enabled') is True))
        from therion.context.language import control as conversation_control
        previous_reply=next((row.text for row in reversed(self.memory.turns) if row.role=='therion'),'')
        web_topic_followup=(self._agent_waiting_for_answer
            and conversation_control(syntax.command).startswith('sobre ')
            and 'pesquis' in conversation_control(previous_reply))
        registry.enable_discovery({'prepare_existing_action'} if direct_app or direct_calendar else
                                  {'search_notes'} if direct_search else
                                  {'gmail_profile','gmail_prepare_draft'} if direct_draft else
                                  {'gmail_search','gmail_message_headers','gmail_thread'} if direct_gmail else
                                  {'search_notes','read_source'} if grounded_kind else
                                  {'web_search','web_read_source'} if web_topic_followup else initial_tools(syntax.command))
        pending = []

        async def existing_action(arguments, token):
            token.check()
            # O executor legado conserva seu lock e sua própria governança.
            with self._operation_lock:
                token.check()
                result = self._process_command(command, cancelled=token)
            pending.append(result)
            if (getattr(self,'_agent_ui_confirmations',False) and not direct_app and result.status=='awaiting_confirmation' and result.plan is not None and self._confirmation_id):
                session=self.session_id;confirmation=self._confirmation_id;plan=result.plan;plan_key=self._plan_fingerprint(plan)
                def valid(row,cancel):
                    with self._operation_lock:
                        return not cancel.cancelled and self.session_id==session and self._confirmation_id==confirmation and self._plan_fingerprint(plan)==plan_key
                def execute(row,cancel):
                    final=self.confirm_session_proposal(plan,True,session,confirmation,cancelled=cancel)
                    simulated=final.status=='executed_simulated'
                    if final.status=='success' or simulated:
                        return ToolResult('success',data={'simulated':simulated},message=final.message,side_effect_state='none' if simulated else 'verified')
                    if final.status in {'cancelled','forbidden'}:return ToolResult('cancelled' if final.status=='cancelled' else 'blocked',message=final.message)
                    return ToolResult('uncertain',message=final.message+'\nConfira as etapas antes de repetir a ação.',side_effect_state='uncertain')
                operation='apps.open' if plan.intent.action=='abrir aplicativo' else 'calendar.create'
                proposal=self._agent_proposals.prepare(operation,{'command':arguments['command'],'confirmation_id':confirmation},result.message,execute,
                    lambda row,value,cancel:value.status=='success',valid,token_aware=True,preparation_token=token)
                return ToolResult('awaiting_confirmation',data={'proposal_id':proposal.id},message='Revise a ação existente no painel Capacidades.',side_effect_state='pending')
            uncertain=result.status in {'verification_failed','execution_failed','uncertain'}
            state = ('awaiting_clarification' if result.status == 'clarification' else
                     'awaiting_confirmation' if result.status == 'awaiting_confirmation' else
                     'uncertain' if uncertain else 'success' if result.status == 'success' else
                     'cancelled' if result.status=='cancelled' else 'blocked')
            return ToolResult(state, message=result.message,
                side_effect_state='pending' if state == 'awaiting_confirmation' else 'uncertain' if uncertain else 'verified' if state == 'success' else 'none')

        def explicit_action(arguments):
            # O pedido inteiro preserva negações, condições e raízes declaradas.
            value = arguments['command']
            if value != syntax.command:
                return False
            intent = self.intent_recognizer.parse(value)
            intent = self._voice_opening_review(value,intent)
            return intent is not None and (intent.action=='abrir aplicativo' or (intent.action=='criar evento calendário' and (not structured_calendar or direct_calendar)))

        registry.register(ToolSpec('prepare_existing_action', 'Preparar ação simples existente usando o pedido humano inteiro, sem remover negações/condições. A confirmação continua obrigatória quando exigida.',
            object_schema(command=TEXT), existing_action, effect='external', authorize=explicit_action,
            verify=lambda args, result: result.side_effect_state == 'verified'))
        history=[];history_sources=[]
        for row in self.memory.turns:
            if getattr(row,'origin','')=='memory_preview':continue
            sources=self._agent_turn_sources.get((self.session_id,row.turn_id))
            if row.role=='user' or (sources is not None and self._history_sources_allowed(sources)):
                history.append({'role':'user' if row.role=='user' else 'assistant','content':row.text})
                if sources:history_sources.extend(sources)
        with self._agent_event_lock:self._agent_events.clear()
        history_sources=list({json.dumps(source,sort_keys=True):source for source in history_sources}.values())
        self._agent_runtime = AgentRuntime(provider, registry, store=self._agent_store, emit=self._emit_agent_event,
            context=GmailQueryContext() if direct_gmail or direct_draft else GroundedQuestionContext() if grounded_kind else None,
            confirmations=self._agent_proposals if getattr(self,'_agent_ui_confirmations',False) and not direct_app else None)
        token = CancellationToken(cancelled)
        run_session=self.session_id
        self._agent_turn_token=token
        async def run():
            return await self._agent_runtime.run(syntax.command,session_id=run_session,
                token=token,budget=TurnBudget(seconds=config.get('timeout_seconds',180),context_tokens=config['context_tokens'],
                                             output_tokens=min(config['output_tokens'],768) if grounded_kind else config['output_tokens']),history=history,
                temporary=self._agent_temporary,history_sources=history_sources)
        try:
            if getattr(self,'_agent_ui_confirmations',False):
                # Condition libera/restaura publicamente todos os níveis do
                # RLock enquanto o núcleo trabalha. A UI consegue confirmar ou
                # cancelar sem bloquear no lock do worker principal.
                condition=threading.Condition(self._operation_lock);outcome=[]
                def background():
                    try:value=(True,asyncio.run(run()))
                    except BaseException as error:value=(False,error)
                    with condition:outcome.append(value);condition.notify_all()
                thread=threading.Thread(target=background,name='therion-agent-turn',daemon=True)
                with condition:
                    thread.start()
                    condition.wait_for(lambda:bool(outcome))
                thread.join()
                ok,result=outcome[0]
                if not ok:raise result
            else:result=asyncio.run(run())
        except (ValueError, OSError) as error:
            return OrchestrationResult(status='ai_invalid_response', message=str(error))
        finally:
            if self._agent_turn_token is token:self._agent_turn_token=None
        if self.session_id!=run_session:
            return OrchestrationResult(status='cancelled',message='O turno pertence à conversa encerrada; descartei o resultado da sessão atual.')
        if direct_gmail and result.status=='completed' and provider.read_offer is not None:
            self._gmail_read_offer=dict(provider.read_offer,session=self.session_id,deadline=time.monotonic()+120,
                sources=[source for _,row in result.results for source in row.evidence if source.get('id','').startswith('gmail:')])
        if direct_gmail and result.status=='completed' and provider.list_selection is not None:
            self._gmail_list_context=dict(messages=provider.list_selection,session=self.session_id,deadline=time.monotonic()+120,
                sources=[source for _,row in result.results for source in row.evidence if source.get('id','').startswith('gmail:')])
        if direct_gmail and result.status=='completed' and provider.current_selection is not None:
            self._gmail_current_context=dict(provider.current_selection,session=self.session_id,deadline=time.monotonic()+120,
                sources=[source for _,row in result.results for source in row.evidence if source.get('id','').startswith('gmail:')])
        if pending and result.status == 'awaiting_confirmation':
            call=next((call for call,row in reversed(result.results) if call.name=='prepare_existing_action'),None)
            if call is not None and self._confirmation_id:
                self._agent_legacy_pending[self._confirmation_id]={'call_id':call.id,'session':self.session_id,
                    'plan':self._plan_fingerprint(pending[-1].plan) if pending[-1].plan else None}
            return pending[-1]
        if not pending:self.memory.add_turn('user', syntax.command)
        self.memory.add_turn('therion', result.message)
        self._agent_waiting_for_answer=result.status=='awaiting_clarification'
        sources=history_sources+[source for _,observation in result.results if observation.status=='success' for source in observation.evidence]
        sources.append({'id':'legacy:access','source':'política local','version':self._history_access_key()})
        sources=current_evidence(sources)
        self._agent_turn_sources[(self.session_id,self.memory.turns[-1].turn_id)]=sources
        if config.get('learning_enabled') is True and result.status == 'completed' and result.results:
            from .procedures import ProcedureLibrary
            from .learning import LearningReviewer
            if self._agent_reviewer is None:
                self._agent_reviewer = LearningReviewer(ProcedureLibrary(self._agent_store))
            observations=[{'tool':call.name,'status':row.status,'verified':row.side_effect_state=='verified','recovered_issue':bool(row.resolves)} for call,row in result.results]
            self._agent_reviewer.start(provider,observations)
        status = {'completed':'success','awaiting_clarification':'clarification','failed':'ai_invalid_response'}.get(result.status,result.status)
        from .presentation import speech_text
        return OrchestrationResult(status=status, message=result.message,speech_message=speech_text(result.status,result.message))
