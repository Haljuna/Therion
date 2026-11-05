"""Condições observáveis declarativas; nenhum JavaScript ou expressão executável."""
from urllib.parse import urlsplit
import re
import unicodedata


def protected_action(label):
    text=''.join(char for char in unicodedata.normalize('NFKD',str(label).casefold()) if not unicodedata.combining(char))
    return bool(re.search(r'\b(?:pagar|pagamento|payment|compra|comprar|compre|purchase|checkout|pay|senha|password|security|seguranca|captcha|mfa|otp|login|sign in|log in|excluir|apagar|delete|erase)\b',text)
        or re.search(r'\b(?:excluir|apagar|remover|delete|erase|remove)\b.*\b(?:permanentemente|permanently|conta|account)\b',text))

EXPECTATION={'type':'object','properties':{'kind':{'type':'string','enum':['text_present','url_equals']},
    'value':{'type':'string','minLength':1,'maxLength':1000}},'required':['kind','value'],'additionalProperties':False}


def expectation(args, *, browser=False):
    value=args.get('expect')
    if not isinstance(value,dict) or set(value)!={'kind','value'} or not isinstance(value['value'],str) or not 0<len(value['value'])<=1000:
        raise ValueError('Clique exige condição observável explícita na prévia.')
    if value['kind'] not in ({'text_present','url_equals'} if browser else {'text_present'}):raise ValueError('Condição não suportada.')
    if value['kind']=='url_equals' and (urlsplit(value['value']).scheme not in {'http','https'} or not urlsplit(value['value']).hostname):
        raise ValueError('URL de verificação inválida.')
    return value


def matches(snapshot, expected):
    if expected['kind']=='url_equals':return snapshot.get('url')==expected['value']
    text=snapshot.get('text','')+'\n'+'\n'.join(item.get('text','') for item in snapshot.get('controls',[]))
    return expected['value'] in text
