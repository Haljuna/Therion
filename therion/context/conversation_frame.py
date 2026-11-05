"""Contexto transitório da conversa; não é memória persistente nem autorização."""
import re
from dataclasses import dataclass
from therion.context.language import control,application_control
from therion.memory.session_recall import search


def has_explicit_action(command):
    return bool(re.search(r'\b(?:envie|enviar|mande|manda|salve|salvar|grave|gravar|apague|apagar|exclua|excluir|marque|marcar|agende|agendar|agenda|crie|criar|cria|abra|abre|abrir|execute|executar|instale|instalar)\b', control(command)))


def capabilities_request(command):
    return re.fullmatch(
        r'(?:(?:eu )?(?:queria|quero) saber |me (?:fala|fale|falam|diz|diga) )?(?:o que voce (?:pode|consegue) fazer|'
        r'o que voce faz|como voce pode me ajudar|'
        r'(?:voce )?(?:consegue|pode) abrir (?:(?:algum|alguns|um|os|seus) )?(?:aplicativos?|programas?)|'
        r'quais (?:sao )?(?:suas|as suas) (?:funcoes|capacidades))', control(command)) is not None


def email_capability_request(command):
    """Pergunta sobre capacidade Gmail, sem pedir acesso a uma mensagem."""
    return re.fullmatch(
        r'(?:(?:therion|terion|eterion)[, ]+)?'
        r'(?:(?:voce )?(?:consegue|pode) (?:acessar|consultar|ler)|'
        r'(?:voce )?tem acesso (?:a|ao|aos)) '
        r'(?:(?:o|os|meu|meus) )?(?:e[- ]?mails?|e meios?|gmail)',
        control(command),
    ) is not None


def current_date_request(command):
    return re.fullmatch(r'(?:que dia (?:e|que e) hoje|qual (?:e )?(?:o )?dia(?: de hoje)?|'
        r'qual (?:e )?a data(?: de hoje)?|que data e hoje)',control(command)) is not None


def app_status_request(command):
    """Consulta de processo; uma declaração não vira comando de abertura."""
    match=re.fullmatch(r'(?:(?:confere|confira|veja|verifique) se )?(?:o |a )?(.+?) '
                       r'(?:ja )?(?:esta|ta) abert[oa]',application_control(command))
    if not match or re.search(r'\b(?:nao|nunca|nem|talvez|se|e|ou|abra|abre|feche|fecha|apague|instale)\b',match[1]):
        return None
    return match[1]


def app_result_request(command):
    return application_control(command) in {'abriu','fechou','aberto','aberta','fechado','fechada'}


def app_close_request(command):
    match=re.fullmatch(r'(?:(?:therion|terion|terio|theo)[, ]+)?(?:(?:agora|entao)[, ]+)?'
                       r'(?:fecha|feche|fechar|fecho)[, ]+(?:o |a )?(.+?)(?: (?:pra|para) mim| por favor)?',application_control(command))
    if not match or re.search(r'\b(?:nao|nunca|nem|talvez|se|e|ou)\b',match[1]):return None
    return match[1]


def current_time_request(command):
    return re.fullmatch(
        r'(?:(?:me (?:diga|fale)|(?:voce )?pode me dizer) )?'
        r'(?:que horas?(?: sao| e)?|quantas horas(?: sao)?|qual (?:e )?(?:o )?horario|qual (?:e )?a hora)'
        r'(?: (?:agora|atual|nesse (?:exato )?momento|neste (?:exato )?momento|no momento))?'
        r'(?:,? por favor)?',control(command)) is not None


def personal_request(command,*,voice=False):
    text = control(command)
    if voice and re.fullmatch(r'exume (?:quem sou eu|quem eu sou)',text):
        text='resume '+text.split(' ',1)[1]
    if re.search(r'\b(?:nao|nunca)\s+(?:leia|ler|resuma|resume|faca)\b', text):
        return None
    if has_explicit_action(command):
        return None
    if re.fullmatch(r'(?:qual (?:e )?(?:o )?meu nome|como (?:eu )?me chamo|voce sabe (?:o )?meu nome)',text):
        return 'profile_read'
    if re.fullmatch(r'(?:(?:procura|procure|busca|busque) )?qual (?:(?:e )?a minha (?:faculdade|graduacao)|'
                   r'(?:faculdade|curso) (?:eu )?(?:estou|to) (?:fazendo|cursando))'
                   r'(?: no segundo cerebro)?',text):
        return 'profile_read'
    if re.search(r'\b(?:leia|ler|consulte|explique|resuma)\s+(?:(?:o|sobre o)\s+)?meu perfil\b', text):
        return 'profile_read'
    if (re.search(r'\b(?:resumo|resume|resuma|resumir)\b', text)
            and re.search(r'\b(?:sobre mim|a meu respeito|quem eu sou|quem sou eu|minha trajetoria)\b', text)):
        return 'personal_summary'
    if re.fullmatch(r'(?:o )?que (?:voce )?(?:sabe|conhece) (?:sobre mim|a meu respeito)', text):
        return 'personal_summary'
    if re.search(r'\bquem (?:eu sou|sou eu)\b', text) and re.match(r'^(?:conte|fale|explique|descreva|quem)\b', text):
        return 'personal_summary'
    return None


def conversation_turns(turns, query):
    """Seis turnos contíguos têm prioridade sobre até quatro recuperados."""
    turns = [turn for turn in turns if turn.origin == 'original']
    recent = turns[-6:]
    older = search(turns[:-6], query, limit=4)
    chosen = []
    remaining = 6000
    for turn in reversed(recent):
        text = turn.text[:800]
        if len(turn.text) > 800:
            text += ' […] (trecho abreviado)'
        chosen.append((turn, text))
        remaining -= len(text)
    for turn in reversed(older):
        if remaining <= 40:
            break
        size = min(600, remaining - 24)
        text = turn.text[:size]
        if len(turn.text) > size:
            text += ' […] (trecho abreviado)'
        chosen.append((turn, text))
        remaining -= len(text)
    order = {id(turn): index for index, turn in enumerate(turns)}
    return [{'role': turn.role, 'text': text} for turn, text in
            sorted(chosen, key=lambda item: order[id(item[0])])]


@dataclass
class ConversationFrame:
    topic: str | None = None
    question: str | None = None
    kind: str | None = None
    updated: float | None = None

    def clear(self):
        self.topic = self.question = self.kind = self.updated = None

    def snapshot(self, now):
        if self.updated is None or now - self.updated > 300:
            self.clear()
        return {'topic': self.topic, 'question': self.question, 'kind': self.kind}

    def reply(self, text, now):
        state = self.snapshot(now)
        return bool(state['question']) and control(text) in {'sim', 'nao', 'pode sim', 'pode', 'nao obrigado'}

    def topic_for(self, command, now):
        self.snapshot(now)
        text = control(command)
        if personal_request(command):
            return 'personal'
        if re.search(r'\b(?:therion|assistente|voce|te|seu)\b', text) and re.search(
                r'\b(?:melhor|melhorar|melhoria|implementar|performance|criou|criado|idade|anos|nome)\b', text):
            return 'assistant'
        if text in {'sim', 'nao', 'nao obrigado', 'pode'} or self.reply(command, now) or re.search(r'\b(?:isso|essa|esse|para voce|e voce|por que|porque)\b', text):
            return self.topic
        if (self.topic == 'assistant' and re.search(r'\b(?:dica|sugestao|implementar)\b', text)
                and not re.search(r'\b(?:estudo|estudar|faculdade|disciplina|minha rotina)\b', text)):
            return 'assistant'
        return None

    def finish(self, command, message, now, *, protected=False, clarification=False):
        topic = self.topic_for(command, now)
        questions = re.findall(r'[^.!?\n]*\?', message)
        self.topic = topic
        self.question = questions[-1].strip()[:500] if questions and not protected else None
        self.kind = ('clarification' if clarification else 'offer') if self.question else None
        self.updated = now
