"""Ferramentas visuais e documentos com prévias e escopos explícitos."""
import asyncio
import os
from pathlib import Path

from .documents import DocumentAdapter
from .rpc import OwnedWorker
from therion.agent.contracts import ToolResult, ToolSpec
from therion.agent.registry import TEXT, object_schema
from therion.agent.execution import cooperative_call
from therion.agent.proposals import fingerprint
from .verification import EXPECTATION,expectation,protected_action


def register_visual_tools(registry,host):
    config=host._agent_config
    proposals=host._agent_proposals
    scope_keys=('documents_enabled','document_read_roots','document_write_roots','browser_enabled','browser_domains','desktop_enabled','desktop_targets','web_enabled','source_cache_enabled','browser_channel')
    def access_key():return fingerprint({key:host._agent_config.get(key) for key in scope_keys})
    access=access_key()
    def enabled(key):return host._agent_config.get(key) is True and access_key()==access
    def owned_worker(key,kind,configuration):
        worker=host._agent_workers.get(key)
        if worker is not None and not isinstance(worker,OwnedWorker):return worker
        current=configuration()
        if worker is not None and worker.config!=current:worker.close();worker=None
        if worker is None:
            worker=OwnedWorker(kind,current);host._agent_workers[key]=worker
        return worker
    def propose(token,name,args,preview,execute,verify,revalidate):
        def verify_scope(row,value,cancel):
            if access_key()!=access:return False
            confirmed=verify(row,value,cancel)
            return confirmed is True and access_key()==access
        row=proposals.prepare(name,args,preview,execute,verify_scope,revalidate,token_aware=True,preparation_token=token)
        return ToolResult('awaiting_confirmation',data={'proposal_id':row.id},
            message='Preparei a prévia: '+preview.splitlines()[0][:300]+'\nRevise o conteúdo completo no painel Capacidades.',side_effect_state='pending')

    if config.get('documents_enabled') is True:
        def adapter():return DocumentAdapter(host._agent_config.get('document_read_roots',()),host._agent_config.get('document_write_roots',()))
        documents=owned_worker('documents','documents',lambda:{'read_roots':config.get('document_read_roots',[]),'write_roots':config.get('document_write_roots',[]),'cache_enabled':config.get('source_cache_enabled') is True})
        async def read(args,token):
            data=await cooperative_call(documents.call,'read',args,token,token=token);token.check()
            return ToolResult('success',data=data,evidence=({'id':data['path'],'source':data['path'],'version':data['version']},))
        async def write(args,token):
            token.check();original=adapter().version(args['path'],True)
            preview='Salvar documento: '+args['path']+'\n'+args['text']
            if original:
                import difflib
                source=await cooperative_call(adapter().read,args['path'],token=token)
                if source['partial'] or source['coverage_limited']:return ToolResult('blocked',message='Documento grande demais para revisar a substituição completa. Crie outro arquivo ou edite manualmente.')
                old='\n'.join(row['text'] for row in source['sections'])
                diff='\n'.join(difflib.unified_diff(old.splitlines(),args['text'].splitlines(),fromfile='Original — texto extraído',tofile='Novo conteúdo',lineterm=''))
                target=Path(args['path']);copy=target.with_name(target.stem+'.therion-original-'+original[:12]+target.suffix)
                preview='Substituir documento: '+args['path']+'\nCópia integral do original: '+str(copy)+'\nFormatação será recriada a partir do novo texto.\n\nComparação:\n'+diff+'\n\nNovo conteúdo completo:\n'+args['text']
            return propose(token,'documents.write',dict(args,expected_version=original),preview,
                lambda row,cancel:documents.call('write',dict(row,expected_version=original),cancel),
                lambda row,value,cancel:adapter().version(row['path'],True)==value['version'],
                lambda row,cancel:enabled('documents_enabled') and adapter().version(row['path'],True)==original)
        schema=object_schema(path=TEXT)
        schema['properties'].update(offset=dict(type='integer',minimum=0,maximum=20000000),limit=dict(type='integer',minimum=128,maximum=6000))
        registry.register(ToolSpec('document_read','Ler trecho do documento com páginas/seções. Use next_offset para continuar; confira avisos de cobertura e OCR.',schema,read,authorize=lambda args:enabled('documents_enabled')))
        registry.register(ToolSpec('document_prepare_write','Preparar novo documento ou substituição para revisão.',object_schema(path=TEXT,text=dict(type='string',maxLength=100000)),write,effect='prepare',authorize=lambda args:enabled('documents_enabled')))

    def register_surface(kind):
        key=kind+'_enabled'
        if not enabled(key):return
        def configuration():
            channel=config.get('browser_channel','chromium')
            return ({'profile':str(host._agent_root/('browser-profile' if channel=='chromium' else 'browser-profile-msedge')),'domains':config.get('browser_domains',[]),
                            'download_roots':config.get('document_write_roots',[]),'channel':channel} if kind=='browser'
                           else {'targets':config.get('desktop_targets',{}),'blocked_pids':[os.getpid()]})
        worker=owned_worker(kind,kind,configuration)
        def setup(kind=kind,key=key,worker=worker):
            async def read(args,token):
                data=await cooperative_call(worker.call,'read',args,token,token=token);token.check()
                return ToolResult('success',data=data,evidence=({'id':kind+':current','source':data.get('url',data.get('title','')),'version':data['version'],'browser_channel':config.get('browser_channel','chromium')},))
            async def open_page(args,token):
                data=await cooperative_call(worker.call,'open',args,token,token=token);token.check()
                return ToolResult('success',data=data,evidence=({'id':'browser:current','source':data['url'],'version':data['version'],'browser_channel':config.get('browser_channel','chromium')},))
            async def action(args,token):
                token.check()
                read_args={} if kind=='browser' else {'target_id':args['target_id']}
                before=await cooperative_call(worker.call,'read',read_args,token,token=token)
                if before['version']!=args['version']:return ToolResult('blocked',message='Página/janela mudou. Leia novamente.')
                control=next((row for row in before['controls'] if row['id']==args['control_id']),None)
                if not control:return ToolResult('blocked',message='Controle não selecionado.')
                operation=args['operation']
                if operation=='click':expectation(args,browser=kind=='browser')
                preview=f"{operation}: {control['text']}\nOrigem: {before.get('url',before.get('title'))}\nTexto: {args.get('text','')}\nVerificação: {args['expect'] if operation=='click' else 'Valor exato do campo após preencher'}"
                label=control.get('text','')
                if control.get('tag')=='button' or control.get('input_type') in {'submit','button','reset'}:label+=' '+control.get('value','')
                if control.get('protected') or protected_action(label):return ToolResult('blocked',message='Credenciais, segurança, compras, pagamentos e exclusão não estão disponíveis nesta capacidade.')
                if kind=='browser' and control.get('form_index',-1)>=0:
                    form=before['forms'][control['form_index']]
                    if form['protected'] or not form['review_complete']:return ToolResult('blocked',message='Formulário protegido ou incompleto; revise e conclua manualmente no navegador.')
                    fields=[row['text']+': '+row.get('value','') for row in before['controls'] if row.get('form_index')==control['form_index']]
                    details='\n'.join(fields)
                    if len(details)>8000:return ToolResult('blocked',message='Formulário excede o limite de revisão; conclua manualmente no navegador.')
                    preview+='\nFormulário: '+form['method'].upper()+' '+form['action']+'\nCampos atuais:\n'+details
                return propose(token,kind+'.'+operation,args,preview,
                    lambda row,cancel:worker.call(row['operation'],row,cancel),
                    lambda row,value,cancel:value.get('action_observed') is True or value.get('already_satisfied') is True,
                    lambda row,cancel:enabled(key) and worker.call('read',read_args,cancel)['version']==before['version'])
            parameters={} if kind=='browser' else {'target_id':TEXT}
            registry.register(ToolSpec(kind+'_read','Ler página/janela autorizada e seus controles.',object_schema(**parameters),read,authorize=lambda args:enabled(key)))
            if kind=='browser':
                registry.register(ToolSpec('browser_open','Abrir URL nos domínios escolhidos.',object_schema(url=TEXT),open_page,authorize=lambda args:enabled(key)))
                def download_adapter():return DocumentAdapter((),host._agent_config.get('document_write_roots',[]))
                async def download(args,token):
                    before=await cooperative_call(worker.call,'read',{},token,token=token)
                    if before['version']!=args['version']:return ToolResult('blocked',message='Página mudou. Leia novamente antes de baixar.')
                    control=next((row for row in before['controls'] if row['id']==args['control_id']),None)
                    if control is None:return ToolResult('blocked',message='Controle de download não selecionado.')
                    original=download_adapter().version(args['path'],True)
                    if not Path(args['path']).parent.is_dir():return ToolResult('blocked',message='Escolha uma pasta de destino existente.')
                    preview=f"Baixar: {control['text']}\nOrigem: {before['url']}\nDestino: {args['path']}\nArquivo existente: {'substituir versão '+original if original else 'não'}"
                    return propose(token,'browser.download',args,preview,
                        lambda row,cancel:worker.call('download',dict(row,expected_version=original),cancel),
                        lambda row,value,cancel:download_adapter().version(row['path'],True)==value.get('version'),
                        lambda row,cancel:enabled(key) and worker.call('read',{},cancel)['version']==before['version'] and download_adapter().version(row['path'],True)==original)
                registry.register(ToolSpec('browser_prepare_download','Preparar download de controle observado para pasta aprovada, sem execução do arquivo.',
                    object_schema(control_id=TEXT,version=TEXT,path=TEXT),download,effect='prepare',authorize=lambda args:enabled(key)))
            registry.register(ToolSpec(kind+'_prepare_action','Preparar clique/preenchimento em controle e versão observados.',object_schema(**parameters,
                control_id=TEXT,version=TEXT,operation=dict(type='string',enum=['click','fill']),text=dict(type='string',maxLength=4000),expect=EXPECTATION),action,effect='prepare',authorize=lambda args:enabled(key)))
        setup()
    for kind in ('browser','desktop'):register_surface(kind)

    if config.get('web_enabled') is True:
        web=owned_worker('web','browser',lambda:{'research':True,'domains':['*'],'channel':config.get('browser_channel','chromium')})
        async def search_web(args,token):
            from therion.memory.knowledge import sensitive
            # Consulta externa contém somente texto escolhido no pedido atual.
            if args['query'] not in host._agent_original_request or sensitive(args['query']):
                return ToolResult('blocked',message='Informe uma consulta pública explícita; não transmito trechos recuperados de dados pessoais.')
            data=await cooperative_call(web.call,'search',args,token,token=token);token.check()
            return ToolResult('success',data=data,evidence=tuple({'id':row['id'],'source':row['url']} for row in data['results']))
        async def read_web(args,token):
            data=await cooperative_call(web.call,'read_source',args,token,token=token);token.check()
            return ToolResult('success',data=data,evidence=({'id':data['id'],'source':data['url'],'version':data['version'],'accessed_at':data['accessed_at']},))
        registry.register(ToolSpec('web_search','Pesquisar consulta pública literal do pedido, sem conta pessoal.',object_schema(query=TEXT),search_web,authorize=lambda args:enabled('web_enabled')))
        web_schema=object_schema(source_id=TEXT)
        web_schema['properties'].update(offset=dict(type='integer',minimum=0,maximum=2000000),limit=dict(type='integer',minimum=128,maximum=6000))
        registry.register(ToolSpec('web_read_source','Ler trecho da fonte pública selecionada, com URL/data/versão. Use next_offset para continuar; não é leitura integral quando partial=true.',web_schema,read_web,authorize=lambda args:enabled('web_enabled')))
