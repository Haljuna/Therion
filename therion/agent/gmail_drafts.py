"""Coleta delimitada de rascunho; publicação continua na prévia governada."""
import json
import re
import time

from .contracts import AgentDecision,AgentError,ToolCall
from .proposals import fingerprint
from therion.context.language import control
from therion.integrations.gmail import account_identity,address


def account_key(host):
    factory=getattr(host,'_gmail_adapter_factory',None)
    return fingerprint(['fixture',id(factory)]) if factory is not None else account_identity(host._agent_root/'credentials')


def draft_dialogue(host,command):
    text=control(command)
    start=bool(re.fullmatch(r'(?:escreve|escreva|crie|cria|prepare|prepara) (?:um )?rascunho(?: (?:pra|para) mim)?',text))
    state=host._gmail_draft_request
    if not start and state is None:return None
    if not host._agent_config.get('gmail_enabled'):
        host._gmail_draft_request=None
        return {'question':'Ative e conecte o Gmail antes de preparar um rascunho.'}
    key=account_key(host)
    if key is None:return {'question':'Não confirmei a conexão Gmail. Conecte a conta no painel Capacidades.'}
    if state is not None and (state['session']!=host.session_id or time.monotonic()>=state['deadline'] or state['account']!=key):
        host._gmail_draft_request=None
        return {'question':'A preparação anterior expirou ou a conta mudou. Peça um novo rascunho.'}
    if start:
        state={'session':host.session_id,'deadline':time.monotonic()+300,'account':key}
    elif text in {'cancelar','cancela','cancele','nao','no','desiste','desistir'}:
        host._gmail_draft_request=None
        return {'question':'Cancelei a preparação do rascunho. Nenhuma mensagem foi criada ou enviada.'}
    elif re.match(r'^(?:abre|abra|fecha|feche|qual|quais|que horas|resume meu dia|leia|le meu|envie|envia|apague|exclua)\b',text):
        host._gmail_draft_request=None
        return None
    changed=False
    if not start:
        if re.search(r'\b(?:para|pra) (?:eu mesmo|mim mesmo)\b',text):state['to']='self';changed=True
        addresses=re.findall(r'[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+',command)
        if len(addresses)==1:state['to']=address(addresses[0]);changed=True
        elif len(addresses)>1:return {'question':'Informe um único destinatário para esse rascunho.'}
        match=re.search(r'\bassunto\s*(?:(?:vai ser|será|é|e)\s+|:\s*)?(.+?)(?=,|;|\s+e\s+(?:eu|gostaria|quero|o texto|o corpo)\b|$)',command,re.I)
        if match:
            subject=match[1].strip(' .')
            if not subject or '\n' in subject or '\r' in subject or len(subject)>200:return {'question':'Informe um assunto de até 200 caracteres, em uma linha.'}
            state['subject']=subject;changed=True
        random=bool(re.search(r'\b(?:qualquer coisa|aleatori[oa]|texto de teste)\b',text))
        topic=re.search(r'\b(?:sobre|tema)\s+(.+?)\s*[.!?]*$',command,re.I)
        if topic and not start:
            theme=topic[1].strip(' .!?')
            if len(theme)>200:return {'question':'Diga um tema curto para a mensagem de teste.'}
            state['body']=f'Olá!\n\nEste é um e-mail de teste sobre {theme}. Que seja uma oportunidade de compartilhar ideias e bons momentos!\n\nAbraços.'
            changed=True
        elif random:
            state['body']='Olá!\n\nEsta é uma mensagem de teste preparada pelo Therion para conferir a criação de rascunhos. Tenha um ótimo dia!\n\nAbraços.'
            changed=True
        else:
            body=re.search(r'\b(?:texto|corpo|mensagem)\s*:\s*(.+)$',command,re.I|re.S)
            if body:state['body']=body[1].strip();changed=True
        if not changed and not re.fullmatch(r'(?:sim|pode|see|but|point)[,.!?]*',text):
            for field in ('to','subject','body'):
                if field not in state:
                    if field=='to':
                        return {'question':'Informe o e-mail do destinatário ou diga “para mim mesmo”.'}
                    state[field]=command.strip();break
    host._gmail_draft_request=state
    if not state.get('to'):return {'question':'Para quem será o rascunho? Diga o endereço ou “para mim mesmo”.'}
    if not state.get('subject'):return {'question':'Qual será o assunto do rascunho?'}
    if '\n' in state['subject'] or '\r' in state['subject'] or len(state['subject'])>200:
        state.pop('subject',None)
        return {'question':'Informe um assunto de até 200 caracteres, em uma linha.'}
    if not state.get('body'):return {'question':'O que você quer escrever? Pode informar um texto, tema ou pedir uma mensagem de teste.'}
    if len(state['body'])>16000:return {'question':'O texto excedeu o limite de 16000 caracteres. Envie uma versão menor.'}
    host._gmail_draft_request=None
    return {'draft':{key:state[key] for key in ('to','subject','body')}}


class DraftProvider:
    def __init__(self,data):self.data=dict(data);self.phase='start';self.usage={}
    async def decide(self,messages,tools,budget,token,emit):
        token.check()
        if self.phase=='start':
            if self.data['to']=='self':
                self.phase='profile'
                return AgentDecision('tools',calls=(ToolCall('gmail_profile',{}),))
            self.phase='prepare'
            return self.prepare()
        observation=next((json.loads(row['content']) for row in reversed(messages) if row.get('role')=='tool'),None)
        if observation is None:raise AgentError('Não recebi a prévia do rascunho.')
        if self.phase=='profile':
            if observation.get('status')!='success':return AgentDecision('final',observation.get('message') or 'Não confirmei seu endereço Gmail.')
            self.data['to']=address(observation['data']['email']);self.phase='prepare'
            return self.prepare()
        return AgentDecision('final',observation.get('message') or 'Revise a prévia do rascunho no painel Capacidades. Nenhum envio foi solicitado.')
    def prepare(self):
        return AgentDecision('tools',calls=(ToolCall('gmail_prepare_draft',dict(self.data,draft_id='')),))
