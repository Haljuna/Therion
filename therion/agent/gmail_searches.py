"""Filtros Gmail calculados localmente; datas não viram termos da busca."""
import re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from therion.context.language import control


MAIL=r'(?:e[- ]?mails?|e meios?)'


def filtered_mail_request(command,now=None):
    text=control(command)
    match=re.fullmatch(r'(?:lista|liste|listar|mostra|mostre)(?:,)? (?:os |dos )?(?:meus )?'+MAIL+
        r'(?: que (?:eu )?recebi)?(?: de)? (hoje|ontem)',text)
    if match:
        now=now or datetime.now(ZoneInfo('America/Sao_Paulo'))
        local=now.astimezone(ZoneInfo('America/Sao_Paulo'))
        day=local.date()-timedelta(days=match[1]=='ontem')
        start=datetime.combine(day,datetime.min.time(),ZoneInfo('America/Sao_Paulo'))
        query=f'in:inbox after:{int(start.timestamp())} before:{int((start+timedelta(days=1)).timestamp())}'
        return ('headers',3,{'query':query,'label':f'de {match[1]} ({day:%d/%m/%Y})'})
    match=re.fullmatch(r'(?:tem|ha|existe)(?: algum| algum outro| um)? '+MAIL+
        r' (?:falando de|falando sobre|sobre|a respeito de) ([\w -]{1,100})',text)
    if match:return ('headers',3,{'query':'in:inbox "'+match[1]+'"','label':'sobre '+match[1]})
    match=re.fullmatch(r'(?:que dia|quando)(?: (?:eu )?recebi| foi recebido) (?:o )?(?:meu )?ultimo '+MAIL,text)
    if match:return ('received',1)
    if re.fullmatch(r'(?:lista|liste|listar|mostra|mostre)(?:,)? (?:os |dos )?(?:meus )?e[- ]?mails?',text):
        return ('headers',3)
    return None


def contextual_mail_request(command):
    text=control(command)
    if re.fullmatch(r'(?:me )?(?:leia|le|ler|resuma|resume|explique) (?:esse |este |o )?e[- ]?mail(?: (?:selecionado|aberto))?(?: (?:completo|inteiro|na integra))?(?: para mim)?',text):
        return 'body' if re.match(r'^(?:me )?(?:leia|le|ler)\b',text) else 'summary'
    if re.fullmatch(r'(?:(?:o que diz|do que fala) (?:esse|este|o)|qual (?:e )?o assunto (?:desse|deste|do)) e[- ]?mail(?: (?:selecionado|aberto))?',text):return 'summary'
    if re.fullmatch(r'(?:que dia|quando)(?: (?:eu )?recebi| foi recebido) (?:esse|este|esse meu) (?:e[- ]?mail|e meio|meio)',text):return 'received'
    if re.fullmatch(r'(?:o )?(?:e[- ]?mail|e meio) anterior',text):return 'previous'
    return None


def is_mail_query(command):
    text=control(command)
    if re.search(r'\b(?:segundo cerebro|nas notas|na memoria)\b',text):return False
    return bool(re.match(r'^(?:tem|ha|existe|lista|liste|listar|mostra|mostre|qual|quais|quando|que dia|busca|busque|procura|procure|le|leia|leu|leiam)\b',text)
        and re.search(r'\b(?:e[- ]?mails?|gmail|e meios?)\b',text))


def ambiguous_mail_list(command):
    return bool(re.fullmatch(r'(?:lista|liste),? (?:os )?meus (?:emis|e meus)',control(command)))
