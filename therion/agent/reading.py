"""Cobertura de leitura vem das ferramentas, nunca da prosa do modelo."""
import re
import unicodedata

READERS = frozenset({'read_source', 'document_read', 'web_read_source'})


def read_range(call, result):
    if call.name not in READERS or result.status != 'success' or not isinstance(result.data, dict):
        return None
    data = result.data
    start, total = data.get('offset'), data.get('total_characters')
    if type(start) is not int or type(total) is not int or not 0 <= start <= total <= 20_000_000:
        return None
    text = data.get('text')
    if not isinstance(text, str):
        sections = data.get('sections')
        if not isinstance(sections, list) or any(not isinstance(row, dict) or not isinstance(row.get('text'), str) for row in sections):
            return None
        size = sum(len(row['text']) for row in sections)
    else:
        size = len(text)
    end = start + size
    if end > total or type(data.get('partial')) is not bool:
        return None
    if data.get('next_offset') != (end if end < total else None):
        return None
    return {'offset': start, 'end': end, 'total': total,
            'coverage_limited': data.get('coverage_limited') is True or bool(data.get('warnings'))}


def complete_reads(results):
    groups = {}
    latest = {source.get('source'): source.get('version') for _, result in results if result.status == 'success'
        for source in result.evidence if isinstance(source.get('source'), str) and isinstance(source.get('version'), str)}
    for call, result in results:
        span = read_range(call, result)
        if span is None or span['coverage_limited']:
            continue
        for source in result.evidence:
            if (not isinstance(source.get('source'), str) or not isinstance(source.get('id'), str)
                    or not isinstance(source.get('version'), str) or not source['version']
                    or latest.get(source['source']) != source['version']):
                continue
            key = (source.get('id'), source['source'], source['version'], span['total'])
            groups.setdefault(key, []).append((span['offset'], span['end']))
    complete = set()
    for (identifier, _, _, total), intervals in groups.items():
        cursor = 0
        for start, end in sorted(intervals):
            if start > cursor:
                break
            cursor = max(cursor, end)
        if cursor == total:
            complete.add(identifier)
    return complete


def reading_required(request, answer, *, cited_read_source=False):
    def normal(value):
        return ''.join(ch for ch in unicodedata.normalize('NFD', value.casefold()) if unicodedata.category(ch) != 'Mn')
    question, response = normal(request), normal(answer)
    resource = r'\b(?:nota|notas|fonte|fontes|documento|documentos|arquivo|arquivos|pdf)\b'
    clauses=re.split(r'(?<=[.!?;])\s+|\n',question)
    explicit = any(re.search(r'\b(?:leia|ler|releia|reler)\b', clause)
        and (re.search(resource, clause) or re.search(r'\b[\w-]+\.(?:md|txt|pdf|docx|csv|xlsx)\b', clause))
        and re.search(r'\b(?:inteir[oa]|integral|complet[oa]|original|novamente|releia|reler)\b', clause)
        and not re.search(r'\bnao\s+(?:leia|ler|releia)\b', clause) for clause in clauses)
    absence = (cited_read_source or re.search(resource, response)) and re.search(
        r'\b(?:nao (?:consta|contem|ha|possui|inclui|existem?|encontrei|localizei|identifiquei)|nao (?:esta|foi) (?:encontrad[oa]|localizad[oa]|registrad[oa]|presente)|nenhum[ae]? informacao|nada consta|nada foi encontrad[oa])\b', response)
    complete_claim = re.search(r'\b(?:revisao completa|leitura (?:completa|integral)|li (?:toda|inteira|integralmente))\b', response)
    if complete_claim and re.search(r'\b(?:nao|nunca)\b', response[max(0, complete_claim.start()-35):complete_claim.start()]):
        complete_claim = None
    return bool(explicit or absence or complete_claim)


def missing_reading(request, answer, results, cited, *, historical_ids=()):
    cited_reads = {identifier for identifier in cited if identifier.startswith(('note:', 'web:', 'document:'))}
    question=request.casefold()
    recall=bool(re.search(r'\b(?:era|eram|repita|relembre|recapitule|resposta anterior|'
        r'voc[eê] (?:disse|falou|informou|citou)|combinamos|qual foi)\b',question))
    fresh_history=bool(cited_reads.intersection(historical_ids)) and not recall
    if not (fresh_history or reading_required(request, answer, cited_read_source=bool(cited_reads))):
        return False
    complete = complete_reads(results)
    if not complete or cited_reads - complete:
        return True
    files = re.findall(r'\b[\w-]+\.(?:md|txt|pdf|docx|csv|xlsx)\b', request.casefold())
    read_paths = [str(source.get('source', '')).replace('\\', '/').casefold()
        for _, result in results if result.status == 'success' for source in result.evidence
        if source.get('id') in complete]
    question=request.casefold()
    return any(not any(path.endswith('/' + filename)
        or (path.rsplit('/',1)[-1] in question and path.rsplit('/',1)[-1].endswith(' '+filename))
        for path in read_paths) for filename in files)
