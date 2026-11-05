"""Normalização de controle; nunca corrige nomes, caminhos ou descrições."""
import re
import unicodedata

# Vocativos da mesma família usados antes de comandos, nunca como alvo.
APP_VOCATIVE = r'(?:e?th?[ée]r(?:ion|io)|t[ée]nio|th?[ée]o)'


def control(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', text.casefold())
                   if unicodedata.category(c) != 'Mn')
    text = ' '.join(text.split()).strip().rstrip('.!?').strip()
    text = re.sub(r'^(?:therion[, ]+|por favor[, ]+)', '', text)
    return text


def query_control(text):
    text = control(text)
    # Lista fechada de erros de palavras de controle, somente em consultas.
    text = re.sub(r'\b(?:agnda|agendda)\b', 'agenda', text)
    text = re.sub(r'\bcalendairo\b', 'calendario', text)
    return text


def application_control(text):
    """Vocativos conhecidos antes da gramática de apps; não corrige alvos."""
    text=control(text)
    text=re.sub(r'^e[.,]\s*','',text)
    return re.sub(r'^'+APP_VOCATIVE+r'[, ]+'
                  r'(?=(?:o|a|confere|confira|veja|verifique|fecha|feche|fechar|abre|abra|abrir|abriu|fechou|agora|entao)\b)','',text)


def calendar_correction(text):
    """Remove um 'Não,' discursivo somente diante de pedido positivo de agenda."""
    match = re.match(
        r'^\s*n[ãa]o\s*,\s*((?:eu )?(?:preciso|quero|gostaria)(?: de)? que '
        r'(?:voc[eê] )?(?:me )?(?:marque|marca|marcar|agende|agenda|agendar|crie|cria|criar)\b.+)$',
        text, re.I)
    if not match:
        return text
    candidate = match[1]
    normalized = control(candidate)
    if (not re.search(r'\b(?:reuniao|evento|compromisso)\b', normalized)
            or re.search(r'\b(?:nao|nunca|nem|sem|talvez|se|caso|acho que)\b', normalized)):
        return text
    return candidate


def prohibited_action(text):
    text = control(calendar_correction(text))
    # Negação de dados ausentes e rejeição da proposta anterior não negam um novo pedido.
    text = re.sub(r'[, ]+(?:mas )?(?:ainda )?nao sei (?:a hora|o horario|a data)\b', '', text)
    text = re.sub(r',? nao o mesmo$', '', text)
    if re.match(r'^(?:monte|crie|faca|elabore) (?:um )?plano\b', text):
        return False
    return bool(re.search(r'\b(?:nao|nunca|nem|sem|talvez|acho que)\b', text)
                and re.search(r'\b(?:marqu\w*|marca\w*|agend\w*|cri\w*|adicion\w*|coloc\w*|conclu\w*|complet\w*|reabr\w*|abr\w*|execut\w*|cancel\w*)\b', text))


def explicit_user_item(text):
    """Uma declaração imediatamente anterior, nunca uma sugestão do assistente."""
    if any(char in text for char in '\n;?"') or re.search(r'\b(?:e depois|tambem|e tambem)\b', control(text)):
        return None
    match = re.fullmatch(r'(?:preciso|tenho que|vou|quero)\s+([\wÀ-ÿ]+\s+.+)', text.strip().rstrip('.'), re.I)
    if not match or re.search(r'\b(?:e|ou)\b', control(match[1])):
        return None
    if control(match[1]).split()[0] in {'que', 'saber', 'ver', 'consultar', 'buscar', 'marcar', 'agendar', 'criar', 'nao'}:
        return None
    return match[1]


def time_correction(text):
    """Interpreta uma correção explícita; horas de 1 a 12 por extenso exigem período."""
    clean = control(text)
    match = re.fullmatch(r'(?:passa|passe|muda|mude|troca|troque|altere|corrija)(?: o (?:horario|inicio))? para(?: as)? (.+)', clean)
    if not match:
        return None
    raw = match[1]
    words = {'uma': 1, 'duas': 2, 'tres': 3, 'quatro': 4, 'cinco': 5, 'seis': 6,
             'sete': 7, 'oito': 8, 'nove': 9, 'dez': 10, 'onze': 11, 'doze': 12,
             'treze': 13, 'quatorze': 14, 'catorze': 14, 'quinze': 15, 'dezesseis': 16,
             'dezessete': 17, 'dezoito': 18, 'dezenove': 19, 'vinte': 20}
    spoken = re.fullmatch(r'(' + '|'.join(words) + r')(?: horas?)?(?: (?:da|a) (manha|tarde|noite))?', raw)
    if spoken:
        hour, period = words[spoken[1]], spoken[2]
        if hour <= 12 and not period:
            return {'error': 'Qual horário exatamente? Informe no formato de 24 horas, por exemplo 04h ou 16h.'}
        if period:
            if hour > 12 or hour == 12 or (period == 'noite' and hour < 6):
                return {'error': 'Confirme o horário no formato de 24 horas para evitar ambiguidade.'}
            if period in {'tarde', 'noite'}:
                hour += 12
        return {'start_time': f'{hour:02d}:00'}
    if re.fullmatch(r'\d{1,2}(?:(?:h|:)\d{2}|h)', raw):
        return {'start_time': raw}
    if re.search(r'\b(?:as|horario|inicio)\b', clean):
        return {'error': 'Não reconheci o horário com segurança. Informe no formato de 24 horas.'}
    return None
