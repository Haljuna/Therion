"""Adapters de leitura sobre as permissões atuais do host."""
import asyncio
from dataclasses import asdict
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
from .execution import cooperative_call
from therion.memory.knowledge import safe_path

from .contracts import ToolResult, ToolSpec
from .registry import ToolRegistry, TEXT, object_schema
from therion.context.read_scope import ReadScope


def build_read_registry(host, *, scope=None):
    registry = ToolRegistry()
    selected = {}
    # Identificadores são referências a versões, não autorizações. Fontes da
    # sessão podem ser relidas sem uma nova busca: read_note revalida escopo e
    # acesso, e o handler abaixo compara a versão antes de entregar conteúdo.
    for (session,_),sources in reversed(list(getattr(host,'_agent_turn_sources',{}).items())):
        if session!=host.session_id:continue
        for source in reversed(sources):
            if not isinstance(source,dict):continue
            identifier=source.get('id','')
            if (not isinstance(identifier,str) or not identifier.startswith('note:')
                    or not identifier[5:].isdigit() or not isinstance(source.get('version'),str)
                    or len(selected)>=128):continue
            try:
                path=Path(source['source']).relative_to(Path(host.second_brain.vault_root))
                selected.setdefault(identifier,(str(path),source['version']))
            except (KeyError,ValueError,TypeError):continue
    prior_ids=[int(source['id'][5:]) for sources in getattr(host,'_agent_turn_sources',{}).values() for source in sources
        if isinstance(source,dict) and isinstance(source.get('id'),str) and source['id'].startswith('note:') and source['id'][5:].isdigit()]
    host._agent_source_sequence=max([getattr(host,'_agent_source_sequence',0)]+prior_ids)
    def verified(arguments,result):
        return result.status=='success' and host._history_sources_allowed(result.evidence)

    def allowed(arguments):
        try:
            host._sync_knowledge_access()
            host.second_brain._check_access()
            return True
        except (OSError, ValueError, PermissionError):
            return False

    async def search(arguments, token):
        from therion.context.second_brain import SecondBrainReader,SearchTrace
        trace=SearchTrace();options={'scope':scope}
        if 'max_results' in arguments:options['max_results']=arguments['max_results']
        if isinstance(host.second_brain,SecondBrainReader):options.update(normalize_accents=True,constrained=True,trace=trace,
            context_hint=getattr(host,'_agent_original_request',''),cancel_check=token.check)
        rows = await cooperative_call(host.second_brain.search_notes, arguments['query'],token=token,**options)
        token.check()
        evidence, data = [], []
        for row in rows:
            # A mesma busca pode ser refeita com outros termos. Um ID publicado
            # nunca passa a designar outro arquivo ou outra versão.
            identifier = next((key for key,value in selected.items() if value==(row.path,row.version)),None)
            if identifier is None:
                if len(selected)>=256:return ToolResult('blocked',message='Limite de fontes selecionadas atingido neste pedido.')
                host._agent_source_sequence+=1
                identifier = 'note:' + str(host._agent_source_sequence)
            selected[identifier] = (row.path, row.version)
            canonical=safe_path(Path(host.second_brain.vault_root)/row.path,host.second_brain.allowed_roots)
            data.append(dict(id=identifier, snippet=row.snippet, path=row.path,size_bytes=canonical.stat().st_size,coverage='snippet'))
            evidence.append(dict(id=identifier, source=str(canonical), version=row.version))
        message='Resultados são trechos de busca, não leitura integral. Se foi solicitado ler a nota original, use read_source antes de concluir.'
        if trace.unavailable_files:message+=f' {trace.unavailable_files} arquivo(s) fora dos limites de leitura ou indisponível(is); a busca não cobre esses arquivos.'
        return ToolResult('unavailable' if trace.unavailable_files and not data else 'success', data=data, evidence=tuple(evidence),message=message)

    async def read(arguments, token):
        item = selected.get(arguments['source_id'])
        if item is None:
            return ToolResult('blocked', message='Escolha uma fonte retornada pela busca deste pedido.')
        from therion.context.second_brain import SecondBrainReader
        options={'scope':scope}
        if isinstance(host.second_brain,SecondBrainReader):options['constrained']=True
        result = await cooperative_call(host.second_brain.read_note, item[0],token=token,**options)
        token.check()
        if not result.success:
            return ToolResult('blocked', message=result.error or 'Fonte indisponível.')
        version = hashlib.sha256(result.content.encode()).hexdigest()
        issue='source:'+hashlib.sha256(str(result.canonical_path).encode()).hexdigest()
        if item[1] and version != item[1]:
            return ToolResult('blocked', message='Fonte mudou desde a busca. Faça nova busca.',issue_key=issue)
        offset=arguments.get('offset',0);limit=arguments.get('limit',8000)
        if offset>len(result.content):return ToolResult('blocked',message='Intervalo fora do texto da fonte.')
        end=min(offset+limit,len(result.content))
        message=(f'Leitura parcial: caracteres {offset}–{end} de {len(result.content)}. Continue com offset={end} antes de afirmar ausência; há conteúdo ainda não consultado.'
            if end<len(result.content) else 'Fim da fonte selecionada. Este resultado começa em '+str(offset)+'.' if offset else 'Fonte original entregue integralmente neste resultado.')
        return ToolResult('success', data={'text':result.content[offset:end],'total_characters':len(result.content),
            'offset':offset,'partial':offset>0 or end<len(result.content),'next_offset':end if end<len(result.content) else None},
            evidence=(dict(id=arguments['source_id'], source=result.canonical_path, version=version),),resolves=(issue,),message=message)

    async def memory(arguments, token):
        repo = host._knowledge_repository
        if repo is None:
            return ToolResult('unavailable', message='Memória persistente não configurada.')
        data = await cooperative_call(repo.retrieve, arguments['query'], host.knowledge.policy,
            host.knowledge.clock(), host._knowledge_source_resolver,token=token)
        token.check()
        return ToolResult('success', data=list(data), evidence=tuple(dict(id='memory:'+row['id'],source=str(Path(row['path']).resolve()),
            version=hashlib.sha256(Path(row['path']).read_text(encoding='utf-8').encode()).hexdigest()) for row in data))

    async def calendar(arguments, token):
        try:
            day = date.fromisoformat(arguments['day'])
        except ValueError:
            from therion.calendar.dialogue import parse_day
            from therion.calendar.adapter import CalendarError
            try:
                day = parse_day(arguments['day'],host._calendar_now())
            except (CalendarError,AttributeError):
                return ToolResult('awaiting_clarification', message='Não reconheci a data da consulta. Informe hoje, amanhã ou uma data completa.')
        from therion.calendar.google_adapter import GoogleCalendarAdapter
        if isinstance(host.calendar_adapter,GoogleCalendarAdapter):
            from therion.integrations.calendar import account_key,worker_call
            account=account_key(host)
            if account is None:return ToolResult('unavailable',message='Agenda sem conta autorizada; isto não significa dia vazio.')
            rows=await cooperative_call(worker_call,host,'list',{'day':day.isoformat()},token,account,token=token)
            token.check()
            if account_key(host)!=account:return ToolResult('blocked',message='A conta da agenda mudou durante a consulta.')
            return ToolResult('success',data=rows,evidence=(dict(id='calendar:'+day.isoformat(),source='Google Calendar',account=account),))
        rows = await cooperative_call(host.calendar_adapter.list_events_for_day, day,token=token)
        token.check()
        return ToolResult('success', data=[asdict(row) for row in rows], evidence=(dict(id='calendar:'+day.isoformat(), source='Google Calendar'),))

    search_schema=object_schema(query=TEXT)
    search_schema['properties']['max_results']={'type':'integer','minimum':1,'maximum':5,'default':5}
    registry.register(ToolSpec('search_notes', 'Busca lexical de notas autorizadas; use assunto/nome do projeto em termos curtos. Resultados são trechos: para ler a nota original, chame read_source. Se vazio, reformule a busca sem ampliar acesso.', search_schema, search, authorize=allowed,verify=verified))
    def source_schema():
        schema=object_schema(source_id=dict(type='string',enum=list(selected)))
        schema['properties'].update(offset={'type':'integer','minimum':0,'maximum':1000000,'default':0},limit={'type':'integer','minimum':128,'maximum':8000,'default':8000})
        return schema
    registry.register(ToolSpec('read_source', 'Ler nota original pelo ID. Para nota pequena, omita offset/limit: retorna até8000caracteres. Se houver next_offset, continue por ele; não conclua ausência com leitura parcial.', object_schema(source_id=TEXT), read, authorize=allowed,
        available=lambda:bool(selected), parameters_factory=source_schema,verify=verified))
    registry.register(ToolSpec('search_memory', 'Recuperar memórias autorizadas com origem.', object_schema(query=TEXT), memory, authorize=allowed,
                               available=lambda: host._knowledge_repository is not None,verify=verified))
    registry.register(ToolSpec('calendar_day', 'Consultar agenda em uma data explícita (AAAA-MM-DD, DD/MM/AAAA, hoje ou amanhã); datas relativas usam o relógio local do Therion.', object_schema(day=dict(type='string', minLength=1, maxLength=80)), calendar,
                               authorize=lambda args: host.calendar_adapter is not None, available=lambda: host.calendar_adapter is not None,verify=verified))
    return registry
