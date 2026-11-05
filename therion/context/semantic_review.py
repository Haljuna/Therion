"""Validação de comparação semântica: o modelo sugere; fontes comprovam citações."""
import re
from therion.memory.knowledge import MemoryError
from therion.core.ai_provider import ProviderTransportError,ProviderTimeoutError


def semantic_findings(sources, provider):
    compare=getattr(provider,'compare_knowledge',None)
    if not callable(compare):
        raise MemoryError('Comparação semântica indisponível neste provider. A revisão textual continua disponível.')
    try:
        raw=compare({'notes':[{'index':i,'content':s.text} for i,s in enumerate(sources,1)]},timeout_seconds=20)
    except (ProviderTransportError,ProviderTimeoutError) as error:
        raise MemoryError('Comparação semântica indisponível ou fora do prazo; nenhuma conclusão foi aceita.') from error
    if raw is None:
        raise MemoryError('Comparação semântica indisponível neste provider.')
    if not isinstance(raw,dict) or set(raw)!={'comparisons'} or not isinstance(raw['comparisons'],list) or len(raw['comparisons'])>3:
        raise MemoryError('Resposta semântica fora do esquema; nenhuma conclusão aceita.')
    results=[];seen=set()
    for row in raw['comparisons']:
        keys={'left','right','relation','left_evidence','right_evidence','reason'}
        if not isinstance(row,dict) or set(row)!=keys:
            raise MemoryError('Comparação semântica inválida.')
        a,b=row['left'],row['right']
        if type(a) is not int or type(b) is not int or a==b or not (1<=a<=len(sources) and 1<=b<=len(sources)):
            raise MemoryError('Referência semântica não corresponde às notas escolhidas.')
        if row['relation'] not in {'possible_conflict','compatible','uncertain'}:
            raise MemoryError('O modelo não pode decidir qual nota é verdadeira.')
        for field in ('left_evidence','right_evidence','reason'):
            if not isinstance(row[field],str) or not row[field].strip() or len(row[field])>400:
                raise MemoryError('Faltam trechos ou motivo dentro do limite.')
        if row['left_evidence'] not in sources[a-1].text or row['right_evidence'] not in sources[b-1].text:
            raise MemoryError('Citação semântica inventada ou alterada; resultado rejeitado.')
        key=(a,b,row['left_evidence'],row['right_evidence'])
        if key in seen:continue
        seen.add(key)
        relation, reason = row['relation'], row['reason']
        def explicit_years(text):
            return set(re.findall(r'\b(?:em|durante|no ano de)\s+((?:19|20)\d{2})\b', text, re.I))
        years_a, years_b = explicit_years(row['left_evidence']), explicit_years(row['right_evidence'])
        if relation == 'possible_conflict' and len(years_a) == len(years_b) == 1 and years_a != years_b:
            relation = 'uncertain'
            reason = ('Os trechos indicam anos distintos. A diferença pode ser evolução temporal; '
                      'não está comprovado que as afirmações valem para o mesmo período.')
        label={'possible_conflict':'Possível conflito semântico','compatible':'Possível compatibilidade semântica',
               'uncertain':'Relação semântica inconclusiva'}[relation]
        results.append(f'{label} — hipótese da IA para revisão humana.\n[{a}] {row["left_evidence"]}\n'
            f'[{b}] {row["right_evidence"]}\nMotivo sugerido: {reason}\nNão escolhi uma versão verdadeira; confira objeto, contexto e vigência.')
    return results or ['O modelo não indicou relações neste conjunto. Isso não comprova ausência de conflitos semânticos.']
