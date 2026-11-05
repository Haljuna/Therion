"""Barreira conservadora para anúncios de efeitos, além dos recibos por etapa."""
import re


CLAIMS=re.compile(r'\b(?:enviei|enviamos|mandei|foi enviad[oa]|salvei|salvamos|foi salv[oa]|foi abert[oa]|foram abert[oa]s|foi fechad[oa]|foram fechad[oa]s|fechei|fechamos|abrimos|abri|agendei|arquivei|marquei|adicionei|removi|excluí|exclui)\b',re.I)


def unsupported_claim(message,results):
    # Uma citação literal de e-mail lido não anuncia uma ação do assistente.
    # Só reconhecer trechos presentes nos resultados atuais e bem-sucedidos.
    from .gmail_presentation import readable_body,sender_name
    bodies={};headers=[]
    latest={source.get('id'):source.get('version') for _,row in results if row.status=='success' for source in row.evidence}
    for call,row in results:
        if row.status!='success' or not isinstance(row.data,dict):continue
        if not any(str(source.get('id','')).startswith('gmail:') and source.get('version') and latest.get(source['id'])==source['version'] for source in row.evidence):continue
        if call.name=='gmail_thread':
            for part in row.data.get('messages',[]):
                if isinstance(part.get('text'),str):bodies.setdefault((row.data.get('id'),row.data.get('version'),part.get('id')),[]).append(part['text'])
                fields=part.get('headers',{})
                if isinstance(fields,dict):headers.extend(['Assunto: '+str(fields.get('subject','')),'De: '+sender_name(fields.get('from',''))])
        elif call.name=='gmail_message_headers':
            for part in row.data.get('messages',[]):
                fields=part.get('headers',{})
                headers.extend(['Assunto: '+str(fields.get('subject','')),'De: '+sender_name(fields.get('from',''))])
    normalize=lambda value:' '.join(value.split())
    sources=[normalize(readable_body(''.join(parts))) for parts in bodies.values()]+[normalize(value) for value in headers]
    quoted=[];position=0
    for line in message.splitlines(keepends=True):
        value=normalize(line[2:]) if line.startswith('> ') else ''
        if value and any(value in source for source in sources):quoted.append((position,position+len(line)))
        position+=len(line)
    verified=[(call,row) for call,row in results if row.status=='success' and row.side_effect_state=='verified']
    operations={source.get('operation',call.name) for call,row in verified for source in (row.evidence or ({},))}
    for claim in CLAIMS.finditer(message):
        if any(start<=claim.start()<end for start,end in quoted):continue
        clause=re.split(r'[.!?;,\n]|\bmas\b|\be\b',message[:claim.start()],flags=re.I)[-1][-40:]
        if re.search(r'\b(?:não|nao|nunca)\b',clause,re.I):continue
        if not verified:return True
        value=claim.group().casefold()
        if ('abri' in value or 'abert' in value) and not any(operation in {'apps.open','open_app','prepare_existing_action'} for operation in operations):return True
        if ('fech' in value) and not any(operation in {'apps.close','close_app'} for operation in operations):return True
        if any(word in value for word in ('env','mandei')) and not any(operation in {'gmail.send_draft','mail.send'} for operation in operations):return True
        if any(word in value for word in ('arquiv','marquei','removi')) and 'gmail.modify' not in operations:return True
        # Exclusão não faz parte das capacidades desta entrega.
        if value in {'excluí','exclui'}:return True
    return False
