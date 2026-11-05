"""Capacidades pessoais: leitura ou proposta revisável, nunca efeito pelo modelo."""
import asyncio
from pathlib import Path
from .gmail import GmailAdapter,RemoteGmailAdapter,address,draft_preview,draft_matches,validate_draft_replacement,account_identity,reply_metadata
from .tasks import TaskInbox
from therion.agent.contracts import ToolSpec, ToolResult,CancellationToken
from therion.agent.registry import TEXT, object_schema
from therion.agent.proposals import fingerprint
from therion.agent.execution import cooperative_call


def register_personal_tools(registry, host,*,read_cache=False):
    config = host._agent_config
    proposals = host._agent_proposals
    def account_key():
        factory=getattr(host,'_gmail_adapter_factory',None)
        if factory is not None:return fingerprint(['fixture',id(factory)])
        root=getattr(host,'_agent_root',None)
        return account_identity(root/'credentials') if root is not None else None
    account=account_key() if config.get('gmail_enabled') is True else None
    def enabled(name):
        if name=='tasks_enabled':return host._agent_config.get('tasks_enabled') is True or host._agent_config.get('gmail_enabled') is True
        return host._agent_config.get(name) is True and account is not None and account_key()==account
    def gmail(mode='read',*,token=None):
        factory = getattr(host,'_gmail_adapter_factory',None)
        if factory:
            adapter=factory(mode)
            return host._mailbox.read_adapter(adapter) if read_cache and mode=='read' else adapter
        from .rpc import OwnedWorker
        key='gmail:'+mode
        configuration={'credentials_root':str(host._agent_root/'credentials'),'mode':mode,'account':account}
        if key in host._agent_workers and host._agent_workers[key].config!=configuration:
            host._agent_workers[key].close();host._agent_workers.pop(key)
        if key not in host._agent_workers:
            host._agent_workers[key]=OwnedWorker('gmail',configuration,max_response_chars=30_000_000)
        adapter=RemoteGmailAdapter(host._agent_workers[key],token or CancellationToken())
        return host._mailbox.read_adapter(adapter) if read_cache and mode=='read' else adapter
    def propose(token,operation, arguments, preview, execute, verify, revalidate):
        if operation.startswith('gmail.'):arguments=dict(arguments,_account=account)
        def verify_scope(row,value,cancel):
            capability='gmail_enabled' if operation.startswith('gmail.') else 'tasks_enabled'
            if not enabled(capability):return False
            confirmed=verify(row,value,cancel)
            return confirmed is True and enabled(capability)
        row = proposals.prepare(operation,arguments,preview,execute,verify_scope,revalidate,token_aware=True,preparation_token=token)
        return ToolResult('awaiting_confirmation',data={'proposal_id':row.id},
            message='Preparei a prévia: '+preview.splitlines()[0][:300]+'\nRevise o conteúdo completo no painel Capacidades antes de executar.',side_effect_state='pending')

    if config.get('gmail_enabled') is True or config.get('tasks_enabled') is True:
        selected_threads=set();selected_attachments={};selected_messages=set();thread_versions={};selected_labels={};search_pages={}
        if read_cache:
            references=host._mailbox.references()
            selected_messages.update(row['message_id'] for row in references)
            selected_threads.update(row['thread'] for row in references)
        system_labels={'INBOX':'Caixa de entrada','UNREAD':'Não lida','STARRED':'Com estrela','IMPORTANT':'Importante'}
        async def profile(args,token):
            data=await cooperative_call(lambda:gmail(token=token).profile(),token=token)
            token.check()
            return ToolResult('success',data={'email':address(data['email'])},
                evidence=({'id':'gmail:profile','source':'Gmail — conta conectada','version':fingerprint(data)},))
        async def labels(args,token):
            data=await cooperative_call(lambda:gmail(token=token).labels(),token=token)
            token.check();selected_labels.clear()
            selected_labels.update({row['id']:row['name'] for row in data['labels']})
            return ToolResult('success',data=data,evidence=({'id':'gmail:labels','source':'Gmail — rótulos','version':fingerprint(data)},))
        async def search(args,token):
            page=args.get('page') or ''
            if page and page not in search_pages.get(args['query'],set()):
                return ToolResult('blocked',message='Token de página não retornado por esta consulta. Na primeira busca, omita page; depois use somente next_page devolvido para a mesma query.',issue_key='gmail:pagination')
            data=await cooperative_call(lambda:gmail(token=token).search(args['query'],args['page']) if args.get('page') else gmail(token=token).search(args['query']),token=token)
            token.check()
            if data.get('next_page'):search_pages.setdefault(args['query'],set()).add(data['next_page'])
            selected_threads.update(row['threadId'] for row in data['messages'] if row.get('threadId'))
            selected_messages.update(row['id'] for row in data['messages'] if row.get('id'))
            return ToolResult('success',data=data,evidence=({'id':'gmail:search','source':'Gmail'},),resolves=('gmail:pagination',))
        async def message_headers(args,token):
            identifiers=args['message_ids']
            if not identifiers or len(set(identifiers))!=len(identifiers) or any(identifier not in selected_messages for identifier in identifiers):
                return ToolResult('blocked',message='Selecione até três mensagens distintas retornadas pela busca atual.')
            messages=[];sources=[]
            for identifier in identifiers:
                data=await cooperative_call(lambda:gmail(token=token).metadata(identifier),token=token)
                token.check()
                if data.get('id')!=identifier:
                    return ToolResult('blocked',message='Não confirmei a identidade da mensagem consultada.')
                # Consulta de assunto/remetente/data não carrega corpo nem anexos.
                headers={}
                for row in data.get('payload',{}).get('headers',[]):
                    name=row.get('name','').casefold()
                    if name in {'subject','from','to','date'}:headers[name]=str(row.get('value',''))[:1000]
                result={'id':identifier,'headers':headers,'internal_date':data.get('internalDate')}
                messages.append(result)
                sources.append({'id':'gmail:'+identifier,'source':'https://mail.google.com/mail/u/0/#all/'+identifier,'version':fingerprint(result)})
            return ToolResult('success',data={'messages':messages,'body_read':False},evidence=tuple(sources))
        async def thread(args,token):
            if args['thread_id'] not in selected_threads:
                return ToolResult('blocked',message='Selecione uma thread retornada pela busca atual.')
            message_id=args.get('message_id')
            if message_id and message_id not in selected_messages:
                return ToolResult('blocked',message='Selecione uma mensagem retornada pela busca atual.')
            data=await cooperative_call(lambda:gmail(token=token).thread(args['thread_id']),token=token)
            token.check()
            if message_id:
                chosen=[message for message in data['messages'] if message.get('id')==message_id]
                if len(chosen)!=1:return ToolResult('blocked',message='Não confirmei a mensagem selecionada nessa thread.')
                data=dict(data,messages=chosen)
            thread_versions[data['id']]=data['version']
            from .excerpts import excerpt
            # O HTML original é só do painel; não entra no contexto do modelo.
            sections=[dict({k:v for k,v in message.items() if k!='html'},section=message['id'],text=message.get('text','')+'\n') for message in data['messages']]
            page=excerpt(sections,args.get('offset',0),args.get('limit',6000))
            # Mensagem vazia ainda pode conter anexos selecionáveis.
            if not sections or not page['total_characters']:
                page['sections']=sections[:10]
                page['partial']=len(sections)>10
            data=dict(data,messages=page.pop('sections'),**page)
            for message in data['messages']:
                selected_messages.add(message['id'])
                for attachment in message.get('attachments',[]):selected_attachments[(message['id'],attachment['id'])]=attachment
            return ToolResult('success',data=data,evidence=({'id':'gmail:'+(message_id or data['id']),
                'source':'https://mail.google.com/mail/u/0/#all/'+message_id if message_id else data['url'],'version':data['version']},))
        async def draft(args,token):
            args=dict(args,draft_id=args.get('draft_id',''))
            address(args['to']);token.check()
            original=await cooperative_call(lambda:gmail('compose',token=token).draft(args['draft_id']),token=token) if args.get('draft_id') else None
            if original:validate_draft_replacement(original.get('message',{}).get('raw',''))
            digest=fingerprint(original) if original else None
            source_id=args.get('source_thread_id') or ''
            source_version=thread_versions.get(source_id)
            if source_id and source_version is None:return ToolResult('blocked',message='Leia a thread de origem antes de preparar uma resposta.')
            if source_id:
                fresh=await cooperative_call(lambda:gmail(token=token).thread(source_id),token=token)
                if fresh['version']!=source_version:return ToolResult('blocked',message='A thread mudou desde a leitura. Consulte a versão atual antes de preparar a resposta.')
                try:args=dict(args,_reply=reply_metadata(fresh,args['subject']))
                except ValueError as error:return ToolResult('blocked',message=str(error))
            dependencies=dict(thread_versions)
            args=dict(args,_source_versions=dependencies)
            def revalidate(row,cancel):
                return (enabled('gmail_enabled') and (digest is None or fingerprint(gmail('compose',token=cancel).draft(row['draft_id']))==digest)
                    and all(gmail(token=cancel).thread(identifier)['version']==version for identifier,version in dependencies.items()))
            def verify_saved(row,value,cancel):
                if not value.get('id'):return False
                actual=gmail('compose',token=cancel).draft(value['id']).get('message',{})
                return draft_matches(actual.get('raw',''),row) and (not row.get('_reply') or actual.get('threadId')==row['_reply']['thread_id'])
            origin='Resposta na thread '+source_id if source_id else 'Composição independente, sem vínculo de resposta a uma thread'
            return propose(token,'gmail.save_draft',args,
                f"Salvar rascunho para {args['to']}\n{origin}\nAssunto: {args['subject']}\n\n{args['body']}",
                lambda row,cancel:gmail('compose',token=cancel).save_draft(row),
                verify_saved,revalidate)
        async def send(args,token):
            original=await cooperative_call(lambda:gmail('compose',token=token).draft(args['draft_id']),token=token)
            token.check()
            raw=original.get('message',{}).get('raw','')
            preview='Enviar rascunho Gmail:\n'+draft_preview(raw)
            digest=fingerprint(original)
            frozen=dict(args,content_identity=fingerprint(draft_preview(raw)))
            return propose(token,'gmail.send_draft',frozen,preview,
                lambda row,cancel:gmail('compose',token=cancel).send_draft(row['draft_id']),
                lambda row,value,cancel:bool(value.get('id') and 'SENT' in gmail(token=cancel).metadata(value['id']).get('labelIds',[])),
                lambda row,cancel:enabled('gmail_enabled') and fingerprint(gmail('compose',token=cancel).draft(row['draft_id']))==digest)
        async def modify(args,token):
            token.check()
            if args['message_id'] not in selected_messages:return ToolResult('blocked',message='Selecione a mensagem na busca antes de preparar alterações.')
            chosen=set(args['add']+args['remove'])
            if not chosen:return ToolResult('success',message='Nenhuma alteração de rótulo foi solicitada; não preparei uma operação.')
            if set(args['add'])&set(args['remove']):return ToolResult('blocked',message='O mesmo rótulo não pode ser adicionado e removido na mesma operação.')
            if any(label not in system_labels and label not in selected_labels for label in chosen):
                return ToolResult('blocked',message='Consulte os rótulos e selecione seus IDs antes de preparar a organização.')
            import re
            if any(label not in system_labels and not re.fullmatch(r'Label_\d+',label) for label in chosen):
                return ToolResult('blocked',message='Exclusão, spam e configurações da conta não são suportados nesta operação.')
            selected_names={identifier:selected_labels[identifier] for identifier in chosen if identifier not in system_labels}
            original=await cooperative_call(lambda:gmail(token=token).metadata(args['message_id']),token=token)
            digest=fingerprint(original)
            def verify_labels(row,value,cancel):
                actual=gmail(token=cancel).metadata(row['message_id']).get('labelIds',[])
                return all(label in actual for label in row['add']) and all(label not in actual for label in row['remove'])
            def revalidate_labels(row,cancel):
                if not enabled('gmail_enabled') or fingerprint(gmail(token=cancel).metadata(row['message_id']))!=digest:return False
                if not selected_names:return True
                current={item['id']:item['name'] for item in gmail(token=cancel).labels()['labels']}
                return all(current.get(identifier)==name for identifier,name in selected_names.items())
            names=lambda identifiers:[system_labels.get(identifier,selected_labels.get(identifier,identifier)) for identifier in identifiers]
            return propose(token,'gmail.modify',args,'Alterar rótulos da mensagem '+args['message_id']+'\nCabeçalhos: '+str(original.get('payload',{}).get('headers',[]))+'\nAdicionar: '+str(names(args['add']))+'\nRemover: '+str(names(args['remove'])),
                lambda row,cancel:gmail('modify',token=cancel).modify(row['message_id'],row['add'],row['remove']),
                verify_labels,
                revalidate_labels)
        async def attachment(args,token):
            selected=selected_attachments.get((args['message_id'],args['attachment_id']))
            if selected is None or selected['size']>20_000_000:return ToolResult('blocked',message='Anexo não selecionado ou acima do limite.')
            from tempfile import TemporaryDirectory
            from .documents import READ_TYPES
            from .rpc import OwnedWorker
            name=Path(selected['name']).name
            if Path(name).suffix.lower() not in READ_TYPES:return ToolResult('blocked',message='Formato de anexo não suportado.')
            def read_attachment():
                data=gmail(token=token).attachment(args['message_id'],args['attachment_id']);token.check()
                with TemporaryDirectory(dir=host._agent_root,prefix='attachment-') as folder:
                    path=Path(folder)/name;path.write_bytes(data)
                    worker=OwnedWorker('documents',{'read_roots':[folder]})
                    try:return worker.call('read',{'path':str(path),'offset':args.get('offset',0),'limit':args.get('limit',6000)},token)
                    finally:worker.close()
            result=await cooperative_call(read_attachment,token=token)
            token.check();result['path']=name
            return ToolResult('success',data=result,evidence=({'id':'gmail:'+args['message_id']+':'+args['attachment_id'],'source':name,'version':result['version']},))
        async def owned_drafts(args,token):
            token.check();rows=[]
            for receipt in host._agent_store.operations():
                if receipt['tool']!='gmail.save_draft' or receipt['state']!='success':continue
                refs=receipt['result_refs']
                if not any(reference.get('_account')==account for reference in refs):continue
                identifier=next((reference['id'] for reference in refs if reference.get('id')),None)
                if identifier:rows.append({'id':identifier,'created':receipt['created'],'call_id':receipt['call_id']})
            return ToolResult('success',data=rows)
        async def inspect_result(args,token):
            rows=host._agent_store.operations(args['call_id'])
            if not rows or rows[0]['tool'] not in {'gmail.save_draft','gmail.send_draft','gmail.modify'}:
                return ToolResult('blocked',message='Recibo Gmail não encontrado.')
            receipt=rows[0]
            bound_account=next((reference['_account'] for reference in receipt['result_refs'] if isinstance(reference.get('_account'),str)),None)
            if bound_account is None or bound_account!=account:return ToolResult('blocked',message='O recibo não pertence à conta autorizada atual. Confira o resultado na conta original; não repeti a operação.')
            identifier=next((reference['id'] for reference in receipt['result_refs'] if isinstance(reference.get('id'),str)),None)
            if identifier is None and receipt['tool']=='gmail.modify':
                identifier=next((reference['message_id'] for reference in receipt['result_refs'] if isinstance(reference.get('message_id'),str)),None)
            if identifier is None:return ToolResult('unavailable',message='A operação não retornou identificador verificável. Confira o Gmail antes de preparar outra ação; não repetirei o efeito.')
            if receipt['tool']=='gmail.save_draft':
                original=await cooperative_call(lambda:gmail('compose',token=token).draft(identifier),token=token)
                data={'id':identifier,'preview':draft_preview(original.get('message',{}).get('raw','')),'receipt_state':receipt['state']}
            else:
                data=await cooperative_call(lambda:gmail(token=token).metadata(identifier),token=token)
                if receipt['tool']=='gmail.send_draft' and 'SENT' in data.get('labelIds',[]):
                    host._agent_store.finish(receipt['call_id'],'success',verified=True)
                    data['reconciled']=True
                if receipt['tool']=='gmail.modify':
                    target=next((reference for reference in receipt['result_refs'] if 'add' in reference and 'remove' in reference),None)
                    labels=data.get('labelIds',[])
                    if target and all(label in labels for label in target['add']) and all(label not in labels for label in target['remove']):
                        host._agent_store.finish(receipt['call_id'],'success',verified=True);data['reconciled']=True
                    else:return ToolResult('uncertain',message='Os rótulos atuais não confirmam a prévia. Não repeti a alteração.',side_effect_state='uncertain')
            token.check()
            return ToolResult('success',data=data,evidence=({'id':'gmail:'+identifier,'source':'https://mail.google.com/mail/u/0/#all/'+identifier,'version':fingerprint(data)},))
        specs=[('gmail_search','Buscar mensagens; falha não equivale a caixa vazia.',object_schema(query=TEXT),search),
            ('gmail_profile','Consultar o endereço da conta Gmail conectada para um pedido explícito de enviar a si mesmo.',object_schema(),profile),
            ('gmail_message_headers','Consultar assunto, remetente e data de até três mensagens retornadas pela busca, numa só chamada. Não lê o corpo; use para listar e-mails recentes.',object_schema(message_ids=dict(type='array',maxItems=3,items=TEXT)),message_headers),
            ('gmail_labels','Consultar nomes e IDs dos rótulos antes de organizar mensagens.',object_schema(),labels),
            ('gmail_inspect_result','Consultar identificador retornado por operação Gmail incerta; envio confirmado no serviço reconcilia o recibo sem repetir.',object_schema(call_id=TEXT),inspect_result),
            ('gmail_thread','Ler thread selecionada em trechos fixos de até 6000 caracteres. Na primeira leitura omita offset; depois use next_offset. Não há argumento limit.',object_schema(thread_id=TEXT),thread),
            ('gmail_read_attachment','Ler anexo selecionado na thread atual, sem executar conteúdo.',object_schema(message_id=TEXT,attachment_id=TEXT),attachment),
            ('gmail_owned_drafts','Listar IDs de rascunhos criados pelo Therion para consulta/continuação.',object_schema(),owned_drafts),
            ('gmail_prepare_draft','Preparar prévia de rascunho. draft_id vazio cria novo.',object_schema(to=TEXT,subject=TEXT,body=dict(type='string',maxLength=16000),draft_id=dict(type='string',maxLength=100)),draft),
            ('gmail_prepare_send','Preparar envio de rascunho para confirmação visual.',object_schema(draft_id=TEXT),send),
            ('gmail_prepare_labels','Preparar rótulos, arquivamento ou marcação de leitura.',object_schema(message_id=TEXT,
                add=dict(type='array',maxItems=10,items=TEXT),remove=dict(type='array',maxItems=10,items=TEXT)),modify)]
        for name,desc,schema,handler in specs:
            if config.get('gmail_enabled') is not True:continue
            if name=='gmail_search':schema['properties']['page']=dict(type='string',maxLength=2000,default='',description='Omitir na primeira busca. Somente next_page retornado para a mesma query; não usar número de página.')
            if name=='gmail_thread':schema['properties'].update(offset=dict(type='integer',minimum=0,maximum=20000000,default=0),message_id=dict(type='string',minLength=1,maxLength=1000,description='Opcional: mensagem já selecionada na busca; limita leitura a essa mensagem da thread.'))
            if name=='gmail_read_attachment':schema['properties'].update(offset=dict(type='integer',minimum=0,maximum=20000000,default=0))
            if name=='gmail_prepare_draft':
                schema['required'].remove('draft_id')
                schema['properties']['draft_id']['default']=''
            if name=='gmail_prepare_draft':schema['properties']['source_thread_id']=dict(type='string',maxLength=200,description='Thread de origem já lida, obrigatória ao responder e-mail; omitir para composição independente.')
            def bind_account(handler):
                async def call(arguments,token):
                    result=await handler(arguments,token)
                    if not enabled('gmail_enabled'):return ToolResult('blocked',message='A conta ou a autorização mudou durante a consulta. Faça um novo pedido.')
                    from dataclasses import replace
                    return replace(result,evidence=tuple(dict(source,account=account) for source in result.evidence))
                return call
            registry.register(ToolSpec(name,desc,schema,bind_account(handler),effect='prepare' if 'prepare_' in name else 'read',authorize=lambda args:enabled('gmail_enabled'),available=lambda:enabled('gmail_enabled')))
        inbox=TaskInbox(host._agent_store)
        async def list_tasks(args,token):
            token.check()
            limit=args.get('limit',5);offset=args.get('offset',0)
            rows=inbox.list(state=args.get('state'),limit=limit+1,offset=offset)
            return ToolResult('success',data={'tasks':rows[:limit],'next_offset':offset+limit if len(rows)>limit else None,'partial':offset>0 or len(rows)>limit})
        async def add_task(args,token):
            token.check()
            allowed={'user:current'}|{'gmail:'+identifier for identifier in selected_threads|selected_messages}
            runtime=getattr(host,'_agent_runtime',None)
            if runtime and runtime.active:allowed.update(row['id'] for row in runtime.sources)
            if args['source_id'] not in allowed:return ToolResult('blocked',data={'allowed_source_ids':sorted(allowed)[:50]},message='Origem não foi selecionada. Use um ID completo desta lista, incluindo prefixo, ou user:current para um pedido seu.',issue_key='tasks:source-selection')
            if not args['title'].strip() or len(args['title'].strip())>500:return ToolResult('awaiting_clarification',message='Qual é o título da tarefa, com até 500 caracteres?')
            try:inbox.validate_due(args['due'] or None)
            except ValueError:return ToolResult('awaiting_clarification',message='Qual é a data, o horário e o fuso do prazo? Informe uma data explícita ou deixe sem prazo.')
            import uuid
            source={'id':args['source_id']}
            if args['source_id'].startswith('gmail:'):source['account']=account
            if runtime and runtime.active:
                reference=next((row for row in runtime.sources if row['id']==args['source_id']),None)
                if reference:source.update({key:reference[key] for key in ('source','version','account') if key in reference})
            expected=TaskInbox.content_version({'title':args['title'],'state':'pending','source':source,'due':args['due'] or None})
            from datetime import datetime,timezone
            due=datetime.fromisoformat(args['due']).astimezone(timezone.utc).isoformat() if args['due'] else None
            dedup=fingerprint([args['title'].strip(),source.get('source',source['id']),source.get('account'),due])
            frozen=dict(args,id=uuid.uuid4().hex,source=source,expected_result=expected,dedup_key=dedup)
            result=propose(token,'tasks.create',frozen,'Adicionar tarefa: '+args['title']+'\nOrigem: '+args['source_id']+'\nPrazo: '+(args['due'] or 'Sem prazo'),
                lambda row,cancel:inbox.create(row['title'],row['source'],row['due'] or None,identifier=row['id']),
                lambda row,value,cancel:TaskInbox.content_version(inbox.get(row['id']))==row['expected_result'],lambda row,cancel:enabled('tasks_enabled'))
            from dataclasses import replace
            return replace(result,resolves=('tasks:source-selection',))
        async def change_task(args,token):
            token.check()
            original=inbox.get(args['id']);version=fingerprint(original)
            frozen=dict(args,expected_version=version,expected_result=TaskInbox.content_version(dict(original,state=args['state'])))
            return propose(token,'tasks.state',frozen,'Alterar tarefa '+original['title']+'\nID: '+args['id']+'\nOrigem: '+original['source']+'\nPrazo: '+(original['due'] or 'Sem prazo')+'\nEstado: '+original['state']+' → '+args['state'],
                lambda row,cancel:inbox.set_state(row['id'],row['state'],version),
                lambda row,value,cancel:inbox.get(row['id'])['state']==row['state'],
                lambda row,cancel:enabled('tasks_enabled') and fingerprint(inbox.get(row['id']))==version)
        async def inspect_task(args,token):
            receipts=host._agent_store.operations(args['call_id'])
            if not receipts or receipts[0]['tool'] not in {'tasks.create','tasks.state'}:return ToolResult('blocked',message='Recibo de tarefa não encontrado.')
            receipt=receipts[0];target=next((row for row in receipt['result_refs'] if row.get('id') and row.get('expected_result')),None)
            if target is None:return ToolResult('blocked',message='Recibo sem identificador e versão esperada.')
            token.check();actual=inbox.get(target['id'])
            if TaskInbox.content_version(actual)!=target['expected_result']:return ToolResult('uncertain',message='Não confirmei o estado esperado da tarefa. Não repeti a alteração.',side_effect_state='uncertain')
            host._agent_store.finish(receipt['call_id'],'success',verified=True)
            return ToolResult('success',data=actual,evidence=({'id':'receipt:'+receipt['call_id'],'source':'recibo local reconciliado'},))
        inbox_schema=object_schema();inbox_schema['properties'].update(state=dict(type='string',enum=['pending','completed']),limit=dict(type='integer',minimum=1,maximum=10),offset=dict(type='integer',minimum=0,maximum=100000))
        registry.register(ToolSpec('list_inbox','Listar tarefas aprovadas com filtro e paginação; use next_offset para continuar.',inbox_schema,list_tasks,authorize=lambda args:enabled('tasks_enabled')))
        registry.register(ToolSpec('prepare_task','Preparar tarefa com origem selecionada ou user:current e prazo ISO explícito ou vazio.',object_schema(title=TEXT,source_id=dict(TEXT,description='ID de fonte completo consultado: gmail:<threadId> ou gmail:<messageId>; nunca ID sem prefixo. Use user:current para pedido humano atual.'),due=dict(type='string',maxLength=100)),add_task,effect='prepare',authorize=lambda args:enabled('tasks_enabled')))
        registry.register(ToolSpec('prepare_task_state','Preparar conclusão ou reabertura de tarefa.',object_schema(id=TEXT,state=dict(type='string',enum=['pending','completed'])),change_task,effect='prepare',authorize=lambda args:enabled('tasks_enabled')))
        registry.register(ToolSpec('tasks_inspect_result','Reconciliar tarefa local após resultado incerto, sem repetir escrita.',object_schema(call_id=TEXT),inspect_task,authorize=lambda args:enabled('tasks_enabled')))
