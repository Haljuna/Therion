"""Comandos de prévia não concedem escrita nem confirmam outras ações."""
import re
from therion.context.language import control


def memory_request(command):
    text = control(command)
    if text in {'revisoes de aprendizados','liste as revisoes de aprendizados','aprendizados para revisao'}:
        return {'operation':'list_reviews'}
    review=re.fullmatch(r'(mostre|descarte) (?:a )?revisao (rev-mem-[a-f0-9]{12})',text)
    if review:
        return {'operation':'show_review' if review[1]=='mostre' else 'discard_review','identifier':review[2].upper()}
    classify=re.fullmatch(r'classifique (?:a )?revisao (rev-mem-[a-f0-9]{12}) como nao sensivel',text)
    if classify:
        return {'operation':'classify_review','identifier':classify[1].upper()}
    correction = re.fullmatch(r'\s*(?:corrija|corrigir) (?:a )?mem[oó]ria '
        r'(RAS-\d{8}-\d{3})\s*:\s*(.+)', command.strip(), re.I | re.S)
    if correction:
        return {'operation':'correct', 'identifier':correction[1].upper(), 'text':correction[2].strip()}
    retirement = re.fullmatch(r'(?:desconsidere|desconsiderar) (?:a )?memoria (ras-\d{8}-\d{3})', text)
    if retirement:
        return {'operation':'retire', 'identifier':retirement[1].upper()}
    if re.match(r'^(?:corrija|corrigir|desconsidere|desconsiderar) (?:a )?memoria\b', text):
        return {'operation':'clarify_correction'}
    if text in {'revogue a gravacao de memoria', 'revogar gravacao de memoria', 'desative a gravacao de memoria'}:
        return {'operation': 'revoke_write'}
    if text in {'revogue a leitura ampliada', 'revogue o acesso ampliado', 'revogar acesso ampliado'}:
        return {'operation': 'revoke_access'}
    if text in {'modo da memória', 'modo da memoria', 'qual o modo da memoria', 'status da memoria'}:
        return {'operation': 'status'}
    if text in {'pause a memoria', 'pausar memoria', 'pause a captura', 'pare de guardar memorias'}:
        return {'operation': 'pause'}
    if text in {'o que voce pretende guardar', 'liste os candidatos de memoria', 'mostre os candidatos', 'candidatos de memoria'}:
        return {'operation': 'list'}
    if text in {'o que voce guardou', 'o que voce salvou na memoria'}:
        return {'operation': 'stored'}
    if text in {'nao guarde isso', 'nao salve isso', 'descarte esse candidato', 'descarte este candidato'}:
        return {'operation': 'discard', 'selector': None}
    match = re.fullmatch(r'(mostre|mostra|descarte|descartar) (?:o )?candidato (\d+|mem-[a-f0-9]{12})', text)
    if match:
        return {'operation': 'discard' if match[1] in {'descarte', 'descartar'} else 'show', 'selector': match[2]}
    if text in {'salve', 'salve isso', 'salve esse candidato', 'salvar candidato', 'grave esse candidato'}:
        return {'operation': 'save'}
    # Preservar os dados originais; normalização só identifica controle.
    match = re.fullmatch(r'\s*(?:por favor[, ]+)?(?:lembre|lembra|guarde|guarda|memorize)(?:\s+|:\s*)'
                         r'(?:(?:que|disso|isto|isso|esse aprendizado|este aprendizado|essa preferência)\s*:?\s*)?(.+)',
                         command.strip().rstrip('.!?'), re.I | re.S)
    if match:
        body = match[1].strip().lstrip(':').strip()
        if control(body) in {'isso', 'esse aprendizado', 'essa preferencia', 'este aprendizado'}:
            return {'operation': 'clarify'}
        if re.match(r'(?i)^(?:me|para mim)\b', body) or re.search(r'\b(?:amanha|hoje|as \d|daqui a|todo dia)\b', control(body)):
            return {'operation': 'ambiguous'}
        return {'operation': 'add', 'text': body}
    if re.fullmatch(r'(?:guarde|lembre|memorize)(?: (?:isso|esse aprendizado|essa preferencia))?', text):
        return {'operation': 'clarify'}
    if re.match(r'^(?:esqueca|apague|exclua) (?:essa |a |uma )?(?:memoria|lembranca|rascunho)\b', text):
        return {'operation': 'forget'}
    return None
