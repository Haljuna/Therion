"""Paginação determinística de texto, preservando a localização original."""
def validate_interval(offset,limit):
    if type(offset) is not int or offset<0 or type(limit) is not int or not 128<=limit<=6000:
        raise ValueError('Intervalo de leitura inválido.')


def excerpt(sections,offset=0,limit=6000):
    validate_interval(offset,limit)
    total=sum(len(row['text']) for row in sections)
    if offset>total:raise ValueError('Intervalo fora do conteúdo; consulte o tamanho e a versão atuais.')
    rows=[];position=0;end=min(offset+limit,total)
    for section in sections:
        size=len(section['text'])
        left=max(offset,position);right=min(end,position+size)
        if right>left:
            rows.append(dict(section,text=section['text'][left-position:right-position],section_offset=left-position))
            if len(rows)>=20:
                end=right
                break
        position+=size
    return {'sections':rows,'offset':offset,'total_characters':total,
            'partial':offset>0 or end<total,'next_offset':end if end<total else None}
