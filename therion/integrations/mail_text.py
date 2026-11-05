"""Leitura fiel de e-mails: estrutura HTML, ruído recolhível e prioridade conservadora."""
import base64
from email.message import Message
from email.header import decode_header,make_header
from email.utils import parseaddr
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit,urlunsplit,unquote


def _fold(value):
    return ''.join(c for c in unicodedata.normalize('NFD',value.casefold()) if unicodedata.category(c)!='Mn')


def sender_name(value):
    name,address=parseaddr(mail_header(value))
    return unescape(name or address or value or 'Remetente não informado')


def mail_header(value):
    try:return str(make_header(decode_header(str(value))))
    except (LookupError,UnicodeError,ValueError):return str(value)


ACTION=re.compile(r'\b(?:vencimento|vence|prazo|pagamento|pagar|fatura|boleto|comprovante|nota fiscal|'
                  r'codigo|verificacao|senha|seguranca|acesso|reuniao|entrevista|matricula|inscricao|'
                  r'confirmacao|confirme|cancelamento|entrega|documentos?|revisao|aprovacao|assinar|proposta)\b')


def mail_priority(row):
    labels=set(row.get('labels',()))
    if labels.intersection({'IMPORTANT','STARRED'}):return dict(essential=True,label='Marcado',reason='Marcado como importante ou com estrela no Gmail')
    if ACTION.search(_fold(row.get('subject','')+' '+row.get('snippet',''))):
        return dict(essential=True,label='Atenção',reason='Possível prazo, confirmação, pagamento ou ação; mantido por precaução')
    if 'CATEGORY_PROMOTIONS' in labels:return dict(essential=False,label='Promoção',reason='Categoria de promoções informada pelo Gmail')
    if 'CATEGORY_SOCIAL' in labels:return dict(essential=False,label='Social',reason='Categoria de notificações sociais informada pelo Gmail')
    return dict(essential=True,label='',reason='Sem indicação suficiente para recolher esta mensagem')


def _lines(text):
    text=text.replace('\r\n','\n').replace('\r','\n').replace('\xa0',' ').replace('\u200b','').replace('\ufeff','')
    text='\n'.join(re.sub(r'[ \t]+',' ',line).strip() for line in text.split('\n'))
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',text).strip()


class _MailHTML(HTMLParser):
    blocks={'p','div','section','article','h1','h2','h3','h4','h5','h6','table','ul','ol','blockquote'}
    void={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    excluded={'head','script','style','noscript','svg','iframe','object','template','canvas'}

    def __init__(self):
        super().__init__(convert_charrefs=True);self.chunks=[];self.stack=[];self.hidden=0;self.images=False

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        blocked=bool(self.hidden or tag in self.excluded or 'hidden' in attrs or
            re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden|mso-hide\s*:\s*all)',attrs.get('style',''),re.I))
        if not blocked:
            if tag in self.blocks:self.chunks.append('\n\n')
            elif tag in {'br','hr'} or (tag=='tr' and self.chunks and not self.chunks[-1].endswith('\n')):self.chunks.append('\n')
            elif tag=='li':self.chunks.append('\n• ')
            elif tag in {'td','th'} and self.chunks and not self.chunks[-1].endswith('\n'):self.chunks.append(' | ')
            if tag=='img':self.images=True
        if tag not in self.void:
            self.stack.append((tag,blocked,attrs.get('href','') if tag=='a' else '',len(self.chunks)))
            self.hidden+=int(blocked)

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.void:self.handle_endtag(tag)

    def handle_endtag(self,tag):
        index=next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==tag),None)
        if index is None:return
        row=self.stack[index];self.hidden-=sum(int(entry[1]) for entry in self.stack[index:]);del self.stack[index:]
        if not row[1] and not self.hidden:
            if tag=='a':
                url=row[2];label=' '.join(''.join(self.chunks[row[3]:]).split())
                try:safe=urlsplit(url).scheme.lower() in {'https','http','mailto'}
                except ValueError:safe=False
                if safe and url and url not in label and url.removeprefix('mailto:')!=label:self.chunks.append(' ('+url+')')
            if tag in self.blocks:self.chunks.append('\n\n')
            elif tag=='tr':self.chunks.append('\n')

    def handle_data(self,value):
        if self.hidden:return
        if not value.strip() and (not self.chunks or self.chunks[-1].endswith('\n')):return
        self.chunks.append(re.sub(r'\s+',' ',value))


def html_mail_text(html):
    parser=_MailHTML();parser.feed(html);parser.close();text=_lines(''.join(parser.chunks))
    return text or ('Mensagem composta por imagens; o painel não carrega imagens remotas.' if parser.images else '')


def decode_mail_payload(payload):
    value=payload.get('body',{}).get('data','');data=base64.urlsafe_b64decode(value+'===')
    header=next((row.get('value','') for row in payload.get('headers',[]) if row.get('name','').lower()=='content-type'),'')
    message=Message();message['Content-Type']=header
    charset=message.get_content_charset() or 'utf-8'
    try:return data.decode(charset,errors='replace')
    except LookupError:return data.decode('utf-8',errors='replace')


def clean_mail_text(text):
    """Somente apresentação; o original continua disponível em Mensagem completa."""
    text=_lines(text);reasons=[]
    # Destinos técnicos entre sinais de menor/maior não fazem parte da leitura.
    # A mensagem completa conserva os endereços, inclusive links assinados.
    text,count=re.subn(r'<\s*(?:https?://|mailto:)[^<>\r\n]+>', '',text,flags=re.I)
    if count:
        reasons.append('endereços de links')
        text=_lines(text)
    # Só recolher histórico de resposta com introdução substancial. Encaminhamentos
    # e pedidos para conferir o texto abaixo conservam o conteúdo citado.
    quoted=re.search(r'(?im)^\s*(?:em .{8,200} escreveu:|on .{8,200} wrote:|-{3,}\s*(?:mensagem original|original message)\s*-*)\s*$',text)
    if quoted and len(text[:quoted.start()].strip())>=120 and not re.search(r'\b(?:abaixo|encaminh\w*|below|forward\w*)\b',_fold(text[:quoted.start()])):
        text=text[:quoted.start()].rstrip();reasons.append('histórico citado')
    kept=[]
    noise=re.compile(r'^(?:ver (?:este e-?mail )?no navegador|visualizar (?:este e-?mail )?no navegador|'
        r'abrir no navegador|view (?:this (?:e-?mail|message) )?in (?:your )?browser|'
        r'cancelar inscricao|descadastrar|unsubscribe|gerenciar (?:preferencias|inscricoes)|'
        r'manage (?:preferences|subscriptions)|atualizar preferencias|politica de privacidade|privacy policy|'
        r'voce (?:esta recebendo|recebeu) (?:este|esse) e-?mail porque|you (?:are receiving|received) this e-?mail because)\b')
    for block in text.split('\n\n'):
        concrete=bool(re.search(r'(?:R\$|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b)',block))
        greeting=bool(re.fullmatch(r'(?i:olá|ola|oi|hello|hi),\s+(?:[A-ZÀ-Ý][a-zà-ÿ]+(?:[ -][A-ZÀ-Ý][a-zà-ÿ]+){0,2}|(?i:pessoal|equipe|senhor|senhora))[.!:]?',block))
        signature=bool(re.match(r'(?i)^(?:atenciosamente|cordialmente|best regards|kind regards|regards)[,.]?\n',block)) and len(block)<180 and not re.search(r'\d|https?://|@',block)
        if (greeting or signature) and not ACTION.search(_fold(block)) and not concrete:
            reasons.append('saudação e assinatura');continue
        privacy=bool(re.match(r'^(?:politica de privacidade|privacy policy)',_fold(block)))
        control=re.sub(r'^(?:cancelar inscricao|descadastrar|unsubscribe|gerenciar (?:preferencias|inscricoes))\b','',_fold(block))
        if len(block)<1200 and noise.search(_fold(block)) and not ACTION.search(control) and not concrete and not (privacy and len(block)>240):
            reasons.append('rodapé e navegação');continue
        if re.fullmatch(r'[-_=* ]{4,}',block):continue
        kept.append(block)
    if kept:text='\n\n'.join(kept)
    else:reasons=[]
    def tracking(match):
        original=match[0];url=original.rstrip('.,;)');suffix=original[len(url):]
        try:
            parts=urlsplit(url);query=parts.query.split('&')
            keys=[unquote(part.split('=',1)[0]).lower() for part in query]
            if any(key in {'signature','sig','token','code','key','auth','x-amz-signature'} for key in keys):return original
            keep=[part for part,key in zip(query,keys) if not (key.startswith('utm_') or key in {'fbclid','gclid','mc_cid','mc_eid'})]
            if len(keep)==len(query):return original
            reasons.append('parâmetros de rastreamento')
            return urlunsplit((parts.scheme,parts.netloc,parts.path,'&'.join(keep),parts.fragment))+suffix
        except ValueError:return original
    text=re.sub(r'https?://[^\s<>]+',tracking,text)
    return dict(text=text,reasons=list(dict.fromkeys(reasons)))
