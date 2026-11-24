"""Barreira conservadora para anúncios de efeitos, além dos recibos por etapa."""
import re


CLAIMS=re.compile(r'\b(?:enviei|enviamos|mandei|foi enviad[oa]|salvei|salvamos|foi salv[oa]|foi abert[oa]|foram abert[oa]s|foi fechad[oa]|foram fechad[oa]s|fechei|fechamos|abrimos|abri|agendei|arquivei|marquei|adicionei|removi|excluí|exclui)\b',re.I)

# Sem nenhuma ferramenta bem-sucedida no turno, "foi registrado/encerrado" só pode ser invenção.
# Com leitura bem-sucedida a frase pode relatar o que a fonte mostra, então não entra aqui.
PASSIVE=re.compile(r'\b(?:foi|foram)\s+(?:registrad|aplicad|encerrad|conclu[ií]d|cancelad|agendad|marcad|adicionad|removid|apagad|exclu[ií]d|atualizad)[oa]s?\b',re.I)

# 23/11: "Estou registrando sua solicitação..." e "Espaço liberado. Modo de jogo ativo." sem ferramenta nenhuma.
ACTIVE=re.compile(r'\b(?:estou|estamos|vou)\s+(?:registrando|anotando|salvando|liberando|ativando|enviando|agendando|criando|abrindo|apagando)\b'
    r'|\b(?:registrei|anotei|salvei|liberei|ativei|enviei|agendei|criei|abri|apaguei)\b'
    r'|\bespa[çc]o liberado\b|\bmodo de jogo ativo\b|\b(?:conclu[ií]d[oa]|feito|liberado|ativado)\s+com sucesso\b',re.I)
# 24/11: "Hoje é 05 de abril de 2025" (a data também é do app).
DATE=re.compile(r'\bhoje (?:é|e)\s+(?:(?:segunda|ter[çc]a|quarta|quinta|sexta)(?:-feira)?|s[áa]bado|domingo)?,?\s*(?:dia\s+)?\d{1,2}(?:\s+de\s+[a-zç]+|/\d)',re.I)
# 23/11: também "São 15h21" / "Agora são 15h" no começo da frase ou depois de "agora" (não "15 horas de vídeo").
CLOCK=re.compile(r'\b(?:s[ãa]o\s+\d{1,2}:\d{2}|as horas s[ãa]o)|(?:^|[.!?]\s*|\bagora\s+)s[ãa]o\s+\d{1,2}h\d{0,2}\b',re.I)


def invented_clock(message):
    """A hora quem responde é o próprio app; o modelo só a inventaria (23/11: "15:21:05" falso)."""
    return CLOCK.search(message) is not None or DATE.search(message) is not None


def unsupported_claim(message,results):
    if not any(row.status=='success' for _,row in results):
        for claim in list(PASSIVE.finditer(message))+list(ACTIVE.finditer(message)):
            clause=re.split(r'[.!?;,\n]|\bmas\b|\be\b',message[:claim.start()],flags=re.I)[-1][-40:]
            if not re.search(r'\b(?:não|nao|nunca|nada|nenhum\w*)\b',clause,re.I):return True
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
