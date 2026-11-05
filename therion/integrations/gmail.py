"""Gmail API em adapter dedicado. Leitura não altera mensagens."""
import base64
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
import json
import os
import re


def draft_preview(raw):
    """Prévia legível completa do corpo e destinatários; HTML fica como texto."""
    from email import policy
    from email.parser import BytesParser
    from email.utils import getaddresses
    if not isinstance(raw,str) or len(raw)>40_000_000:raise ValueError('Rascunho acima do limite de revisão.')
    message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw+'==='))
    recipients=getaddresses([str(value) for key in ('to','cc','bcc') for value in message.get_all(key,[])])
    if not recipients:raise ValueError('Rascunho sem destinatários.')
    for _,value in recipients:address(value)
    body=message.get_body(preferencelist=('plain','html'))
    text=body.get_content() if body is not None else ''
    if not isinstance(text,str) or len(text)>16000:raise ValueError('Corpo exige revisão completa no Gmail; não preparei envio parcial.')
    attachments=[]
    for item in message.iter_attachments():
        payload=item.get_payload(decode=True) or b''
        import hashlib
        attachments.append(f"{item.get_filename() or '(sem nome)'} — {item.get_content_type()} — {len(payload)} bytes — SHA-256 {hashlib.sha256(payload).hexdigest()}")
    headers='\n'.join(key+': '+', '.join(str(value) for value in message.get_all(key,[])) for key in ('From','To','Cc','Bcc','Subject'))
    return headers+'\n\n'+text+'\n\nAnexos:\n'+('\n'.join(attachments) if attachments else 'Nenhum')


def draft_matches(raw, expected):
    from email import policy
    from email.parser import BytesParser
    from email.utils import getaddresses
    message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw+'==='))
    recipients=getaddresses([str(value) for value in message.get_all('to',[])])
    body=message.get_body(preferencelist=('plain',))
    normalize=lambda value:value.replace('\r\n','\n').rstrip('\n')
    return (recipients==[('',expected['to'])] and not message.get_all('cc') and not message.get_all('bcc')
        and str(message.get('subject',''))==expected['subject'] and body is not None
        and normalize(body.get_content())==normalize(expected['body']) and not list(message.iter_attachments())
        and (not expected.get('_reply') or (str(message.get('In-Reply-To',''))==expected['_reply']['in_reply_to']
            and str(message.get('References',''))==expected['_reply']['references'])))


def validate_draft_replacement(raw):
    """O editor textual atual não substitui silenciosamente conteúdo MIME extra."""
    from email import policy
    from email.parser import BytesParser
    message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(raw+'==='))
    if list(message.iter_attachments()) or message.get_all('cc') or message.get_all('bcc'):
        raise ValueError('Este rascunho contém anexos ou cópias. Edite-o no Gmail para preservar esses dados; não substituí o conteúdo.')

from therion.agent.proposals import fingerprint
from therion.memory.knowledge import safe_path

SCOPES = {'read':'https://www.googleapis.com/auth/gmail.readonly',
          'compose':'https://www.googleapis.com/auth/gmail.compose',
          'modify':'https://www.googleapis.com/auth/gmail.modify'}


def reply_metadata(thread,subject):
    messages=thread.get('messages',[])
    if not messages:raise ValueError('Thread sem mensagem verificável para responder.')
    headers=messages[-1].get('headers',{})
    if subject!=headers.get('subject',''):
        raise ValueError('Para responder nesta thread, preserve o assunto original. Use composição independente para outro assunto.')
    identifier=headers.get('message-id','')
    if not re.fullmatch(r'<[^<>\s@]+@[^<>\s@]+>',identifier):
        raise ValueError('Mensagem sem Message-ID válido; prepare uma composição independente.')
    references=re.findall(r'<[^<>\s@]+@[^<>\s@]+>',headers.get('references',''))[-19:]
    if identifier not in references:references.append(identifier)
    return {'thread_id':thread['id'],'in_reply_to':identifier,'references':' '.join(references)}


def account_identity(root,filename='gmail-token.json'):
    """Identificador local opaco; refresh de access_token não muda a conta."""
    try:
        if filename not in {'gmail-token.json','token.json'}:return None
        path=safe_path(Path(root)/filename,(str(Path(root).absolute()),))
        if path.stat().st_nlink!=1 or path.stat().st_size>128000:return None
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data.get('client_id'),str) or not isinstance(data.get('refresh_token'),str):return None
        scopes=data.get('scopes',[])
        if not isinstance(scopes,list) or any(not isinstance(item,str) for item in scopes):return None
        return fingerprint([data['client_id'],data['refresh_token'],sorted(scopes)])
    except (OSError,ValueError,TypeError):return None


class GmailSession:
    READ={'search','thread','draft','metadata','attachment','labels','profile'}
    WRITE={'save_draft':'compose','send_draft':'compose','modify':'modify'}
    def __init__(self,config):
        self.config=config
        if config.get('mode') not in SCOPES:raise ValueError('Modo Gmail inválido.')

    def dispatch(self,operation,args):
        if operation not in self.READ|set(self.WRITE):raise ValueError('Operação Gmail não registrada.')
        mode=self.config['mode']
        if operation in self.WRITE and mode!=self.WRITE[operation]:raise ValueError('Worker de leitura não executa alteração Gmail.')
        expected=self.config.get('account')
        if expected is not None and account_identity(self.config['credentials_root'])!=expected:raise ValueError('A conta Gmail mudou desde a preparação.')
        # Carregar novamente também revalida troca/revogação local das credenciais.
        adapter=GmailAdapter.from_token(self.config['credentials_root'],mode)
        try:
            if expected is not None and account_identity(self.config['credentials_root'])!=expected:raise ValueError('A conta Gmail mudou durante a autenticação.')
            return self._dispatch(adapter,operation,args)
        finally:
            close=getattr(adapter,'close',None)
            if callable(close):close()

    @staticmethod
    def _dispatch(adapter,operation,args):
        if operation=='profile':return adapter.profile()
        if operation=='labels':return adapter.labels()
        if operation=='search':return adapter.search(args['query'],args.get('page'))
        if operation in {'thread','draft','metadata','send_draft'}:return getattr(adapter,operation)(args['identifier'])
        if operation=='attachment':return {'base64':base64.b64encode(adapter.attachment(args['message_id'],args['attachment_id'])).decode()}
        if operation=='save_draft':return adapter.save_draft(args)
        return adapter.modify(args['identifier'],args['add'],args['remove'])

    def close(self):pass


class RemoteGmailAdapter:
    """Interface limitada para SDK em worker; nenhum cliente Google no processo Qt."""
    def __init__(self,worker,token):self.worker,self.token=worker,token
    def profile(self):return self.worker.call('profile',{},self.token)
    def labels(self):return self.worker.call('labels',{},self.token)
    def search(self,query,page=None):return self.worker.call('search',{'query':query,'page':page},self.token)
    def thread(self,identifier):return self.worker.call('thread',{'identifier':identifier},self.token)
    def draft(self,identifier):return self.worker.call('draft',{'identifier':identifier},self.token)
    def metadata(self,identifier):return self.worker.call('metadata',{'identifier':identifier},self.token)
    def save_draft(self,arguments):return self.worker.call('save_draft',arguments,self.token)
    def send_draft(self,identifier):return self.worker.call('send_draft',{'identifier':identifier},self.token)
    def modify(self,identifier,add,remove):return self.worker.call('modify',{'identifier':identifier,'add':add,'remove':remove},self.token)
    def attachment(self,message_id,attachment_id):
        row=self.worker.call('attachment',{'message_id':message_id,'attachment_id':attachment_id},self.token)
        return base64.b64decode(row['base64'],validate=True)


def address(value):
    if not isinstance(value,str) or '\r' in value or '\n' in value or parseaddr(value)[1] != value or not re.fullmatch(r'[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+',value):
        raise ValueError('Destinatário deve ser um endereço único e explícito.')
    return value


class GmailAdapter:
    def __init__(self, service=None,*,transport=None):
        self.service = service
        self._transport=transport

    def close(self):
        if self._transport:self._transport.close()

    @classmethod
    def from_token(cls, root, mode='read'):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        root = Path(root).absolute()
        path = safe_path(root/'gmail-token.json',(str(root),))
        data = json.loads(path.read_text(encoding='utf-8'))
        scopes = data.get('scopes', [])
        if SCOPES[mode] not in scopes and SCOPES['modify'] not in scopes:
            raise ValueError('Gmail requer autorização OAuth para esta capacidade.')
        credentials = Credentials.from_authorized_user_info(data,scopes=scopes)
        if credentials.expired and credentials.refresh_token:
            request=Request()
            def bounded_request(*args,**kwargs):
                kwargs['timeout']=30
                return request(*args,**kwargs)
            credentials.refresh(bounded_request)
            import tempfile
            descriptor,name=tempfile.mkstemp(prefix='.gmail-token-',suffix='.tmp',dir=root)
            temp=Path(name)
            try:
                with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                    stream.write(credentials.to_json());stream.flush();os.fsync(stream.fileno())
                original_account=fingerprint([data.get('client_id'),data.get('refresh_token'),sorted(scopes)])
                if account_identity(root)!=original_account:raise ValueError('A conta mudou durante a renovação; preservei o token atual.')
                safe_path(path,(str(root),));os.replace(temp,path)
            finally:
                if temp.exists():temp.unlink()
        if not credentials.valid:
            raise ValueError('Gmail requer autenticação.')
        from google_auth_httplib2 import AuthorizedHttp
        from .google_transport import GoogleTransport
        transport=GoogleTransport()
        try:return cls(build('gmail','v1',http=AuthorizedHttp(credentials,http=transport,max_refresh_attempts=0),cache_discovery=False),transport=transport)
        except Exception:transport.close();raise

    def labels(self):
        result=self.service.users().labels().list(userId='me').execute()
        return {'labels':[{'id':row['id'],'name':row['name'],'type':row.get('type','user')} for row in result.get('labels',[])]}

    def profile(self):
        row=self.service.users().getProfile(userId='me').execute()
        return {'email':address(row['emailAddress'])}

    def search(self, query, page=None):
        if len(query)>1000:
            raise ValueError('Consulta acima do limite.')
        row=self.service.users().messages().list(userId='me',q=query,maxResults=10,pageToken=page).execute()
        return {'messages':row.get('messages',[]),'next_page':row.get('nextPageToken')}

    def thread(self, identifier):
        row=self.service.users().threads().get(userId='me',id=identifier,format='full').execute()
        messages=[]
        def parts(payload):
            if payload.get('filename') and payload.get('body',{}).get('attachmentId'):return
            from .mail_text import decode_mail_payload
            body=payload.get('body',{})
            if payload.get('mimeType')=='text/plain' and body.get('data'):
                yield decode_mail_payload(payload)
            elif payload.get('mimeType')=='text/html' and body.get('data'):
                from .mail_text import html_mail_text
                yield html_mail_text(decode_mail_payload(payload))
            children=payload.get('parts',[])
            if payload.get('mimeType')=='multipart/alternative':
                plain=[child for child in children if child.get('mimeType')=='text/plain']
                children=plain[:1] or children[-1:]
            for child in children:
                yield from parts(child)
        def attachments(payload):
            if payload.get('filename') and payload.get('body',{}).get('attachmentId'):
                yield {'name':payload['filename'],'id':payload['body']['attachmentId'],
                    'size':payload['body'].get('size',0),'mime':payload.get('mimeType','')}
            for child in payload.get('parts',[]):yield from attachments(child)
        def original_html(payload):
            # HTML original só para o leitor visual do painel; o agente continua lendo `text`.
            if payload.get('filename') and payload.get('body',{}).get('attachmentId'):return ''
            if payload.get('mimeType')=='text/html' and payload.get('body',{}).get('data'):
                from .mail_text import decode_mail_payload
                return decode_mail_payload(payload)
            return next((html for html in map(original_html,payload.get('parts',[])) if html),'')
        for item in row.get('messages',[]):
            payload=item.get('payload',{})
            headers={h['name'].lower():h['value'] for h in payload.get('headers',[]) if h['name'].lower() in {'from','to','subject','date','message-id','references'}}
            text='\n'.join(parts(payload))
            html=original_html(payload)
            messages.append({'id':item['id'],'headers':headers,'text':text,'html':html if len(html)<=1_000_000 else '','partial':False,
                             'labels':item.get('labelIds',[]),'attachments':list(attachments(payload))})
        return {'id':identifier,'messages':messages,'version':fingerprint([row.get('historyId'),messages]),
                'url':'https://mail.google.com/mail/u/0/#all/'+identifier}

    def draft(self, identifier):
        return self.service.users().drafts().get(userId='me',id=identifier,format='raw').execute()

    def metadata(self,identifier):
        return self.service.users().messages().get(userId='me',id=identifier,format='metadata',metadataHeaders=['Subject','From','To','Date']).execute()

    def attachment(self,message_id,attachment_id):
        result=self.service.users().messages().attachments().get(userId='me',messageId=message_id,id=attachment_id).execute()
        if result.get('size',0)>20_000_000 or len(result.get('data',''))>27_000_000:
            raise ValueError('Anexo acima do limite de leitura.')
        return base64.urlsafe_b64decode(result['data']+'===')

    def save_draft(self, arguments):
        message=EmailMessage()
        message['To']=address(arguments['to'])
        subject=arguments['subject']
        if not isinstance(subject,str) or '\n' in subject or '\r' in subject:
            raise ValueError('Assunto inválido.')
        message['Subject']=subject
        reply=arguments.get('_reply')
        if reply:
            message['In-Reply-To']=reply['in_reply_to']
            message['References']=reply['references']
        message.set_content(arguments['body'])
        body={'message':{'raw':base64.urlsafe_b64encode(message.as_bytes()).decode()}}
        if reply:body['message']['threadId']=reply['thread_id']
        if arguments.get('draft_id'):
            body['id']=arguments['draft_id']
            return self.service.users().drafts().update(userId='me',id=arguments['draft_id'],body=body).execute()
        return self.service.users().drafts().create(userId='me',body=body).execute()

    def send_draft(self, identifier):
        return self.service.users().drafts().send(userId='me',body={'id':identifier}).execute()

    def modify(self, identifier, add=(), remove=()):
        allowed={'INBOX','UNREAD','STARRED','IMPORTANT'}
        if any(label not in allowed and not re.fullmatch(r'Label_\d+',label) for label in (*add,*remove)):
            raise ValueError('Rótulo inválido; exclusão e configurações não são suportadas.')
        return self.service.users().messages().modify(userId='me',id=identifier,
            body={'addLabelIds':list(add),'removeLabelIds':list(remove)}).execute()
