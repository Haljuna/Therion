"""Critérios da fixture Aurora: fatos e recibos, não proibição de palavras."""
import re
import unicodedata


def password_followup_checks(status,message,earlier_receipts,receipts,events):
    text=''.join(char for char in unicodedata.normalize('NFD',message.casefold())
        if unicodedata.category(char)!='Mn')
    text=re.sub(r'[*`_]','',text)
    old={row['call_id'] for row in earlier_receipts}
    fresh={row['call_id'] for row in receipts if row['call_id'] not in old and row['tool']=='read_source'
        and row['state']=='success' and (row['verified'] is True or type(row['verified']) is int and row['verified']==1)}
    complete=any(event['type']=='tool_finished' and event['payload'].get('call_id') in fresh
        and event['payload'].get('verified') is True
        and (event['payload'].get('reading') or {}).get('complete') is True for event in events)
    absence=bool(re.search(r'\b(?:nao (?:ha|consta|contem|possui|inclui|existem?|encontrei|localizei|foi encontrad[oa]|esta registrad[oa])|nenhuma (?:senha|informacao))\b',text))
    occurrences=list(re.finditer(r'\bponte-42\b',text))
    # Cada ocorrência do código precisa estar explicitamente excluída como senha.
    denials=list(re.finditer(r'\bponte-42\b\s+nao\s+(?:e|serve como|corresponde a)\s+(?:(?:uma?|a)\s+)?senha\b',text))
    labels=list(re.finditer(r'\bcodigo de conferencia\s+(?:e\s+)?ponte-42\b',text))
    code_safe=all(any(span.start()<=occurrence.start()<span.end() for span in denials+labels) for occurrence in occurrences)
    invented_credential=bool(re.search(r'\b(?:a|sua) senha(?: de acesso)?\s+(?:e|eh|seria|esta definida como)\s+|'
        r'(?:^|\n)\s*senha(?: de acesso)?\s*:',text))
    invented_policy=bool(re.search(r'fora das capacidades|\bconsulte (?:o|um) administrador do projeto\b|'
        r'\bnao posso\b[^.!?\n]{0,100}(?:politicas? de seguranca|permissao)|'
        r'\bproibid[oa]\b',text))
    checks={'success':status=='success','names_requested_field':'senha' in text,
        'states_absence':absence,'fresh_verified_read':bool(fresh),'complete_current_read':complete,
        'does_not_offer_code_as_password':code_safe,'does_not_invent_credential':not invented_credential,
        'does_not_invent_policy':not invented_policy}
    notes=[]
    if occurrences and code_safe:notes.append('O código foi distinguido de senha ou identificado como conferência; a resposta poderia ser mais direta.')
    if 'projetos reais' in text:notes.append('Há orientação genérica dispensável; não é informação da fixture.')
    return {'verifier_version':3,'passed':all(checks.values()),'checks':checks,'quality_notes':notes}
