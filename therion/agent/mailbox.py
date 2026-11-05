"""Caixa de leitura compartilhada, com cache limitado em RAM e isolamento por conta."""
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
import re
import threading
import time
from .proposals import fingerprint
from therion.integrations.mail_text import mail_header

PAGE_SIZE=10
PAGE_TTL=300
BODY_TTL=120


def mail_window_request(command):
    from therion.context.language import control
    text=control(command)
    return bool(re.fullmatch(r'(?:(?:por favor|therion) )?(?:abra|abrir|abre|mostre|mostra|mostrar|exiba|quero ver) '
        r'(?:(?:a|o|as|os|uma|um) )?(?:(?:minha|meu|minhas|meus) )?(?:(?:janela|painel|caixa) (?:de |dos |dos meus |da |de minha )?)?'
        r'(?:e[- ]?mails?|correio|caixa de entrada)(?: por favor)?',text))


class Mailbox:
    def __init__(self,host,clock=time.monotonic):
        self.host=host;self.clock=clock;self.lock=threading.RLock();self.io_lock=threading.Lock()
        self.account=None;self.pages=OrderedDict();self.metadata=OrderedDict();self.threads=OrderedDict()
        self.focus=None;self.revision=0;self.email=None

    def identity(self):
        if self.host._agent_config.get('gmail_enabled') is not True:return None
        factory=getattr(self.host,'_gmail_adapter_factory',None)
        if factory is not None:return fingerprint(['fixture',id(factory)])
        from therion.integrations.gmail import account_identity
        return account_identity(self.host._agent_root/'credentials')

    def _sync(self):
        account=self.identity()
        with self.lock:
            if account!=self.account:
                self.pages.clear();self.metadata.clear();self.threads.clear();self.focus=None
                self.account=account;self.email=None;self.revision+=1
        return account

    def clear(self):
        with self.lock:
            self.pages.clear();self.metadata.clear();self.threads.clear();self.focus=None;self.email=None;self.revision+=1

    def status(self):
        account=self._sync()
        if account is None:
            state='disabled' if self.host._agent_config.get('gmail_enabled') is not True else 'disconnected'
            return dict(state=state,account=None,items=[],revision=self.revision,
                message='Ative Gmail em Capacidades.' if state=='disabled' else 'Conecte o Gmail em Capacidades.')
        with self.lock:
            page=self.pages.get(('in:inbox',None))
            result=deepcopy(page['view']) if page else dict(state='missing',items=[],message='Caixa ainda não carregada.')
            if page and self.clock()-page['at']>PAGE_TTL:result['state']='stale'
            return dict(result,account=account,account_email=self.email,revision=self.revision,
                        age_seconds=max(0.,self.clock()-page['at']) if page else None)

    def _check(self,account,token):
        token.check()
        if self._sync()!=account or account is None:raise PermissionError('A conta ou a autorização Gmail mudou.')

    @contextmanager
    def _adapter(self,account,token):
        factory=getattr(self.host,'_gmail_adapter_factory',None)
        if factory:
            adapter=factory('read')
            yield adapter
            return
        from therion.integrations.gmail import RemoteGmailAdapter
        from therion.integrations.rpc import OwnedWorker
        worker=OwnedWorker('gmail',{'credentials_root':str(self.host._agent_root/'credentials'),
            'mode':'read','account':account},max_response_chars=30_000_000)
        try:yield RemoteGmailAdapter(worker,token)
        finally:worker.close()

    def cached(self,operation,*args):
        account=self._sync()
        if account is None:return None
        with self.lock:
            if operation=='search':row=self.pages.get((args[0],args[1] if len(args)>1 else None));field='raw';ttl=PAGE_TTL
            elif operation=='metadata':row=self.metadata.get(args[0]);field='raw';ttl=PAGE_TTL
            elif operation=='thread':row=self.threads.get(args[0]);field='raw';ttl=BODY_TTL
            else:return None
            result=deepcopy(row[field]) if row and self.clock()-row['at']<=ttl else None
        return result if self._sync()==account else None

    def page(self,query,page,token,*,force=False):
        account=self._sync()
        if account is None:return self.status()
        if not isinstance(query,str) or not query.strip() or len(query)>1000:raise ValueError('Consulta inválida.')
        query=query.strip();page=page or None
        if page is not None and (not isinstance(page,str) or len(page)>4096):raise ValueError('Página inválida.')
        with self.io_lock:
            self._check(account,token)
            with self.lock:
                cached=self.pages.get((query,page))
                if cached and not force and self.clock()-cached['at']<=PAGE_TTL:return deepcopy(cached['view'])
                allowed={r['raw'].get('next_page') for (q,_),r in self.pages.items() if q==query}
                if page and page not in allowed:raise ValueError('Página não retornada por esta consulta.')
            with self._adapter(account,token) as adapter:
                from therion.integrations.gmail import address
                email=self.email or address(adapter.profile()['email'])
                raw=adapter.search(query,page) if page else adapter.search(query)
                messages=raw.get('messages',[])
                if not isinstance(messages,list) or len(messages)>PAGE_SIZE:raise ValueError('Página Gmail inválida.')
                next_page=raw.get('next_page') or None
                if next_page is not None and (not isinstance(next_page,str) or len(next_page)>4096 or next_page==page):
                    raise ValueError('A paginação Gmail não avançou.')
                with self.lock:
                    if page and (query,next_page) in self.pages and next_page is not None:
                        raise ValueError('A paginação Gmail repetiu uma página anterior.')
                entries=[];metadata=[];ids=set()
                for ref in messages:
                    self._check(account,token)
                    identifier,thread=ref.get('id'),ref.get('threadId')
                    if not isinstance(identifier,str) or not identifier or identifier in ids or not isinstance(thread,str) or not thread:
                        raise ValueError('Mensagem sem identidade verificável.')
                    ids.add(identifier);data=adapter.metadata(identifier)
                    if data.get('id')!=identifier or data.get('threadId')!=thread:raise ValueError('A mensagem mudou durante a consulta.')
                    headers={str(h.get('name','')).lower():mail_header(h.get('value',''))[:1000] for h in data.get('payload',{}).get('headers',[])
                             if str(h.get('name','')).lower() in {'subject','from','to','date'}}
                    entries.append(dict(id=identifier,thread=thread,subject=headers.get('subject') or '(sem assunto)',
                        sender=headers.get('from') or 'Remetente não informado',headers=headers,
                        received=data.get('internalDate'),snippet=str(data.get('snippet',''))[:500],
                        unread='UNREAD' in data.get('labelIds',[]),labels=list(data.get('labelIds',[]))))
                    metadata.append((identifier,data))
            self._check(account,token)
            view=dict(state='ready',account=account,account_email=email,items=entries,next_page=next_page,query=query,
                      refreshed_at=time.time(),message='' if entries else 'Nenhum e-mail nesta consulta.')
            with self.lock:
                stamp=self.clock()
                self.email=email
                if page is None:
                    for key in [k for k in self.pages if k[0]==query]:self.pages.pop(key)
                self.pages[(query,page)]=dict(at=stamp,raw=deepcopy(raw),view=deepcopy(view))
                while len(self.pages)>64:self.pages.popitem(last=False)
                for identifier,data in metadata:
                    old=self.metadata.get(identifier)
                    if old and old['raw'].get('historyId')!=data.get('historyId'):self.threads.pop(data['threadId'],None)
                    self.metadata[identifier]=dict(at=stamp,raw=deepcopy(data))
                while len(self.metadata)>512:self.metadata.popitem(last=False)
                self.revision+=1
            return view

    def body(self,identifier,token,*,force=False):
        account=self._sync();self._check(account,token)
        with self.lock:
            metadata=self.metadata.get(identifier)
            if metadata is None:raise ValueError('Selecione um e-mail retornado pela caixa atual.')
            thread=metadata['raw'].get('threadId')
        raw=None if force else self.cached('thread',thread)
        if raw is None:
            with self.io_lock:
                self._check(account,token)
                with self._adapter(account,token) as adapter:raw=adapter.thread(thread)
                self._check(account,token)
                if raw.get('id')!=thread or not raw.get('version'):raise ValueError('Conversa sem versão verificável.')
                size=sum(len(str(m.get('text','')))+len(str(m.get('html',''))) for m in raw.get('messages',[]))
                if size<=1_000_000:
                    with self.lock:
                        self.threads[thread]=dict(at=self.clock(),raw=deepcopy(raw))
                        self.threads.move_to_end(thread)
                        while len(self.threads)>8:self.threads.popitem(last=False)
        self._check(account,token)
        messages=[m for m in raw.get('messages',[]) if m.get('id')==identifier]
        if len(messages)!=1:raise ValueError('A mensagem selecionada não está nesta conversa.')
        message=messages[0];text=str(message.get('text',''))
        return dict(state='ready',account=account,id=identifier,headers=deepcopy(message.get('headers',{})),
            text=text[:200_000],html=str(message.get('html','')),partial=bool(message.get('partial')) or len(text)>200_000,
            attachments=deepcopy(message.get('attachments',[])),version=raw['version'])

    def focus_list(self,query,identifiers,selected=None,*,visible=True,touch=True):
        account=self._sync()
        with self.lock:
            ids=[i for i in identifiers[:500] if i in self.metadata]
            stamp=self.clock() if touch or not self.focus else self.focus['at']
            self.focus=dict(query=query,ids=ids,selected=selected if selected in ids else None,
                            visible=visible,at=stamp,account=account)

    def hide(self):
        with self.lock:
            if self.focus:self.focus['visible']=False

    def context(self):
        account=self._sync()
        with self.lock:
            focus=self.focus
            if not account or not focus or not focus['visible'] or focus['account']!=account:return None
            messages=[];sources=[]
            for identifier in focus['ids']:
                row=self.metadata.get(identifier)
                if not row:continue
                data=row['raw'];thread=data.get('threadId')
                messages.append(dict(message_id=identifier,thread=thread,query=focus['query'],origin='mailbox'))
                sources.append(dict(id='gmail:'+identifier,source='https://mail.google.com/mail/u/0/#all/'+identifier,
                                    version=fingerprint(data),account=account))
            snapshot=[dict(message_id=m['message_id'],thread=m['thread']) for m in messages]
            for row in messages:row['snapshot']=snapshot
            current=next((deepcopy(row) for row in messages if row['message_id']==focus['selected']),None)
            if current:
                cached=self.threads.get(current['thread'])
                if cached and self.clock()-cached['at']<=BODY_TTL:current['version']=cached['raw']['version']
            return dict(messages=messages,current=current,sources=sources,at=focus['at'])

    def references(self):
        """IDs já retornados pelo Gmail; expirar o conteúdo não inventa outro ID."""
        account=self._sync()
        with self.lock:
            return [dict(message_id=identifier,thread=row['raw']['threadId'])
                    for identifier,row in self.metadata.items()] if account else []

    def read_adapter(self,adapter):
        mailbox=self;account=self._sync()
        class CachedRead:
            def __getattr__(self,name):return getattr(adapter,name)
            def _read(self,operation,*args):
                if mailbox._sync()!=account:raise PermissionError('A conta Gmail mudou.')
                data=mailbox.cached(operation,*args)
                result=data if data is not None else getattr(adapter,operation)(*args)
                if mailbox._sync()!=account:raise PermissionError('A conta Gmail mudou.')
                return result
            def search(self,query,page=None):return self._read('search',query) if page is None else self._read('search',query,page)
            def metadata(self,identifier):return self._read('metadata',identifier)
            def thread(self,identifier):return self._read('thread',identifier)
        return CachedRead()
