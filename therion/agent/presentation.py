"""Fala breve a partir da resposta pública; números e horários ficam intactos."""
def event_detail(event):
    payload=event.payload
    if event.type=='tool_started':return 'Iniciando: '+str(payload.get('name',''))
    if event.type=='decision_rejected':return 'Verificação: '+str(payload.get('reason',''))
    if event.type=='tool_finished':
        text=str(payload.get('name',''))+' — '+str(payload.get('status',''))
        text+='; verificação '+('confirmada' if payload.get('verified') is True else 'não confirmada')
        reading=payload.get('reading')
        if isinstance(reading,dict):
            text+=f"; caracteres {reading['offset']}–{reading['end']} de {reading['total']}"
            text+='; leitura completa' if reading.get('complete') is True else '; leitura parcial ou cobertura limitada'
        return text
    if event.type=='terminal':
        text='Turno — '+str(payload.get('status',''))
        if payload.get('read_count')==0:text+='; nenhuma nova leitura neste turno'
        elif 'complete_read_count' in payload:text+='; fontes com leitura completa: '+str(payload['complete_read_count'])
        return text
    return ''


def speech_text(status,message):
    import re
    text=message.split('\n\nFontes consultadas:\n',1)[0].strip()
    text=re.sub(r'\s*\[gmail:[^\]\s]+\]','',text).strip()
    text=re.sub(r'^>\s?', '',text,flags=re.M).strip()
    if status=='uncertain':
        return 'Não consegui confirmar o resultado. Confira os recibos e os detalhes no painel antes de repetir a operação.'
    # Recusas parciais sem nada feito ("Não consegui…", "Não há recibo…") não são "parte do pedido".
    prefix='Concluí apenas parte do pedido. ' if status=='partial' and not text.startswith('Não ') else ''
    if len(prefix+text)<=1800:return prefix+text
    paragraphs=text.split('\n\n');selected=[];size=0
    for paragraph in paragraphs:
        if size+len(paragraph)>1200:break
        selected.append(paragraph);size+=len(paragraph)+2
    if not selected:return prefix+'A resposta completa está no painel, com os detalhes e as fontes.'
    return prefix+'\n\n'.join(selected)+'\nOs detalhes e as fontes estão no painel.'
