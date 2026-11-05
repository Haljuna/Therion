"""Apresentação extrativa do e-mail; o original permanece na fonte Gmail."""
import html
import re
from email.utils import parseaddr


def sender_name(value):
    name,address=parseaddr(value)
    return name.strip() or address or value.strip()


def readable_body(body,subject=''):
    text=html.unescape(body)
    text=re.sub(r'\[([^\]\n]+)\]\(https?://[^\s)]+\)',r'\1',text)
    text=re.sub(r'<https?://[^>\s]+>|https?://[^\s<>]+','',text)
    text=re.sub(r'\[(?:image|imagem):[^\]\n]*\]','',text,flags=re.I)
    paragraphs=[];pending=[]
    def flush():
        if pending:paragraphs.append(' '.join(pending));pending.clear()
    title=' '.join(subject.casefold().split())
    for raw in text.splitlines():
        line=' '.join(raw.split())
        if not line or re.fullmatch(r'[-_=─\s]{3,}',line):flush();continue
        if title and line.casefold()==title:continue
        if re.match(r'^(?:[►•▪]|[-*]\s)',line):
            flush();line=re.sub(r'^(?:[►•▪]|[-*])\s*','• ',line)
        elif re.match(r'^(?:aviso|coordena[çc][ãa]o(?: de projeto)?|design|edi[çc][ãa]o|produ[çc][ãa]o):',line,re.I):flush()
        pending.append(line)
    flush()
    return '\n\n'.join(paragraphs) or '(O e-mail não contém texto legível; confira links e imagens no original.)'


def format_message(fields,body):
    subject=fields.get('subject') or '(sem assunto)'
    text='Assunto: '+subject
    if fields.get('from'):text+='\nDe: '+sender_name(fields['from'])
    return text+'\n\n'+readable_body(body,subject)
