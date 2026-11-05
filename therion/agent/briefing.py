"""Panorama solicitado pelo usuário; metadados de leitura, sem ações no Gmail."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import time
import uuid
from .contracts import CancellationToken, Cancelled
from .security import restrict_directory
from therion.memory.knowledge import safe_path


def briefing_command(command):
    from therion.context.language import control
    text=re.sub(r'[,;:]',' ',control(command));text=' '.join(text.split())
    match=re.fullmatch(r'(?:(?:fala|oi|ola|e ai|ei) )?(?:(?:therion|terion|eterion) )?(bom dia|boa tarde|boa noite)(?: (?:therion|terion|eterion|senhor))?',text)
    if match:return match[1].capitalize()
    if re.fullmatch(r'(?:por favor )?(?:mostre|mostra|mostrar|abra|abrir|quero ver) (?:o |meu |o meu )?panorama(?: do dia)?(?: por favor)?',text):return 'Olá'
    return None


class DeadlineToken(CancellationToken):
    def __init__(self,parent,seconds=30):
        super().__init__(parent=parent);self.deadline=time.monotonic()+seconds

    def check(self):
        super().check()
        if time.monotonic()>=self.deadline:raise TimeoutError('Prazo do panorama excedido.')


class BriefingMarker:
    """Somente marco temporal por conta, separado de histórico e conteúdo."""
    def __init__(self,root,account):
        self.root=Path(root)/'briefing'
        self.path=self.root/(sha256(account.encode()).hexdigest()+'.json')

    def read(self):
        safe_path(self.path,(str(self.root.absolute()),))
        if not self.path.exists():return None
        if self.path.stat().st_nlink!=1:raise ValueError('Marco com vínculo não permitido.')
        row=json.loads(self.path.read_text(encoding='utf-8'))
        stamp=row.get('cutoff_ms')
        if row.get('version')!=1 or type(stamp) is not int or stamp<=0:raise ValueError('Marco de panorama inválido; arquivo preservado.')
        return stamp

    def write(self,stamp):
        safe_path(self.path,(str(self.root.absolute()),))
        if self.path.exists() and self.path.stat().st_nlink!=1:raise ValueError('Marco com vínculo não permitido.')
        self.root.mkdir(parents=True,exist_ok=True);restrict_directory(self.root)
        temporary=self.root/(uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('x',encoding='utf-8') as stream:
                json.dump({'version':1,'cutoff_ms':stamp},stream);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.path)
        finally:
            if temporary.exists():temporary.unlink()


def mail_since(host,token,cutoff):
    box=host._mailbox;account=box.identity()
    if account is None:return box.status()
    marker=BriefingMarker(host._agent_root,account)
    previous=marker.read()
    page=box.page('in:inbox',None,token,force=True)
    result=dict(state='ready',page=page,account=account,cutoff_ms=cutoff,first=previous is None,count=0,complete=True)
    if previous is None:return result
    if previous>cutoff:raise ValueError('O relógio está anterior ao último panorama. Marco preservado.')
    query=f'in:inbox after:{max(0,previous//1000-1)} before:{math.ceil(cutoff/1000)+1}'
    seen=set();pages=set();next_page=None
    try:
        with box.io_lock:
            with box._adapter(account,token) as adapter:
                while True:
                    token.check();box._check(account,token)
                    row=adapter.search(query,next_page) if next_page else adapter.search(query)
                    for ref in row.get('messages',[]):
                        token.check();identifier=ref['id']
                        if identifier in seen:continue
                        seen.add(identifier);metadata=adapter.metadata(identifier)
                        received=int(metadata['internalDate'])
                        if previous<=received<cutoff and 'INBOX' in metadata.get('labelIds',[]):result['count']+=1
                    next_page=row.get('next_page')
                    if not next_page:break
                    if next_page in pages:raise ValueError('Paginação repetida; contagem incompleta.')
                    pages.add(next_page)
        box._check(account,token)
    except Cancelled:raise
    except (OSError,ValueError,TimeoutError,KeyError,TypeError):
        result.update(state='partial',complete=False,message='A contagem de e-mails está incompleta; o marco anterior foi preservado.')
    return result


def collect(host,command,token,progress=None):
    from therion.interface.dashboard_data import DashboardSource
    token.check();source=DashboardSource(host);identity=source.identity();account=host._mailbox.identity()
    cutoff=int(time.time()*1000);day=host._calendar_now().date();rows={}
    context=dict(session=host.session_id,account=account,calendar_account=identity[1])
    if progress:progress('open_briefing',dict(context,greeting=briefing_command(command)+', senhor.'))
    calls={'calendar':lambda:source.calendar(day,DeadlineToken(token)),
           'tasks':lambda:source.tasks(token),
           'mail':lambda:mail_since(host,DeadlineToken(token),cutoff)}
    with ThreadPoolExecutor(max_workers=3,thread_name_prefix='therion-briefing') as executor:
        futures={executor.submit(fn):kind for kind,fn in calls.items()}
        for future in as_completed(futures):
            token.check();kind=futures[future]
            try:row=future.result()
            except Cancelled:raise
            except Exception:row=dict(state='error',message='Consulta indisponível. O resultado não significa ausência de dados.')
            current=source.identity()
            if identity[:2]!=current[:2] or identity[3:]!=current[3:] or host._mailbox.identity()!=account:
                raise Cancelled('O contexto do panorama mudou.')
            rows[kind]=row
            if progress:progress('briefing_part',dict(context,kind=kind,result=row))
    token.check();mail=rows['mail'];parts=[briefing_command(command)+', senhor.']
    if mail.get('first'):parts.append('Estou começando o acompanhamento dos e-mails a partir deste panorama.')
    elif mail.get('state') in {'ready','partial'}:
        noun='e-mail' if mail['count']==1 else 'e-mails'
        parts.append(('Encontrei pelo menos ' if not mail.get('complete') else 'Recebeu ')+str(mail['count'])+' '+noun+' desde o último panorama.')
    else:parts.append('Não consegui consultar os novos e-mails. Confira o estado da conexão na caixa de entrada.')
    agenda=rows['calendar'];tasks=rows['tasks']
    if agenda.get('state')=='ready':
        events=agenda.get('items',[]);noun='compromisso' if len(events)==1 else 'compromissos'
        parts.append(f'A agenda tem {len(events)} {noun} hoje.' if events else 'Sua agenda está livre hoje.')
        now=host._calendar_now().strftime('%H:%M')
        upcoming=next((item for item in events if item['time']!='Dia inteiro' and item['time']>=now),None)
        if upcoming:parts.append('Próximo: '+upcoming['title'][:120]+', às '+upcoming['time']+'.')
    else:parts.append('A agenda está indisponível neste momento.')
    pending=[r for r in tasks.get('saved',[]) if r.get('state')!='completed']
    pending += [r for r in tasks.get('temporary',[]) if not r.get('completed')]
    if tasks.get('state')=='ready':
        parts.append('Tem uma tarefa pendente.' if len(pending)==1 else f'Tem {len(pending)} tarefas pendentes.')
        if pending:parts.append('Em destaque: '+'; '.join(r['title'][:80] for r in pending[:3])+'.')
    else:parts.append('As tarefas salvas estão indisponíveis; confira o painel para as tarefas da conversa.')
    candidate=uuid.uuid4().hex
    host._briefing_pending=dict(id=candidate,session=host.session_id,account=account,cutoff_ms=cutoff,
                               complete=mail.get('complete') is True and mail.get('state')=='ready')
    return dict(parts=rows,day=day.isoformat(),account=account,session=host.session_id,calendar_account=identity[1],
                candidate=candidate,message=' '.join(parts))


def acknowledge(host,identifier):
    row=getattr(host,'_briefing_pending',None)
    if not row or row['id']!=identifier or row['session']!=host.session_id or row['account']!=host._mailbox.identity():return False
    host._briefing_pending=None
    if not row['complete'] or not row['account']:return False
    BriefingMarker(host._agent_root,row['account']).write(row['cutoff_ms']);return True
