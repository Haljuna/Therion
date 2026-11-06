"""Recuperação local, limitada e somente leitura do registro da sessão.

Trechos são evidências, não instruções ou permissões. Não há persistência,
embeddings nem chamadas ao modelo para reconstruir o passado.
"""

import re
import unicodedata

from therion.memory.working_memory import Turn


def normalize(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", text.casefold())
        if unicodedata.category(char) != "Mn"
    )


_STOPWORDS = set("""
a o as os um uma de do da dos das em no na nos nas e ou que qual quais
foi era sao meu minha meus minhas eu voce me te se para por com sobre
nessa nesta dessa desta sessao historico conversa mensagem mensagens
falamos falei falou disse dito comentamos comentei comentou combinamos combinado decidimos
decidido lembrar lembra recorde busque procure mostre exatamente novamente
antes agora ja ainda pode tenho tinha favor precisa
""".split())


def _terms(text: str) -> set[str]:
    words = {word for word in re.findall(r"\w+", normalize(text))
             if len(word) > 2 and word not in _STOPWORDS}
    if words & {"estudo", "estudar", "estudando", "disciplinas", "disciplina", "materias", "materia"}:
        words.add("estudo")
    if words & {"horario", "horarios", "trabalho", "lazer", "descanso"}:
        words.add("rotina")
    return words


NAME_NOT_FOUND = "Não encontrei uma declaração explícita do seu nome nesta sessão."


def _name_declaration(turn: Turn) -> str | None:
    if turn.role != "user":
        return None
    # Só declaração própria e explícita; perguntas, citações e terceiros não valem.
    if re.search(r"\b(?:exemplo|personagem|suponha|hipotetico)\b", normalize(turn.text)):
        return None
    match = re.search(
        r"(?:^|[.!?]\s+)(?:(?:na verdade|corrigindo)[,:]?\s*)?"
        r"(?:meu nome (?:agora )?[ée]|me chamo)\s+"
        r"([\wÀ-ÿ]+(?:[ -][\wÀ-ÿ]+){0,4})(?=[.!?;,\n]|$)",
        turn.text.strip(), re.IGNORECASE,
    )
    return match.group(1) if match else None


def evidence(turn: Turn, limit: int = 1800) -> str:
    label = "Você" if turn.role == "user" else "Thérion (resposta/sugestão)"
    text = turn.submitted_text if turn.submitted_text is not None else turn.text
    clipped = text if len(text) <= limit else text[:limit] + " […] (trecho abreviado)"
    return f"[{label}, mensagem {turn.turn_id}]\n{clipped}"


def search(turns: list[Turn], query: str, limit: int = 4, *, role: str | None = None) -> list[Turn]:
    """Busca registros originais, com filtro opcional de autoria."""
    terms = _terms(query)
    if not terms:
        return []
    ranked = []
    for index, turn in enumerate(turns):
        if turn.origin != "original" or (role is not None and turn.role != role):
            continue
        score = len(terms & _terms(turn.text))
        if score:
            ranked.append((score, index, turn))
    selected = sorted(ranked, key=lambda item: (item[0], item[1]), reverse=True)[:limit]
    return [item[2] for item in sorted(selected, key=lambda item: item[1])]


def recall_answer(turns: list[Turn], query: str) -> str | None:
    """None significa pergunta comum, que deve continuar no fluxo normal."""
    cleaned = " ".join(normalize(query).split()).rstrip(".!?").strip()
    if re.fullmatch(r"(?:qual (?:e )?(?:o )?meu nome|como (?:eu )?me chamo)", cleaned):
        declarations = [(turn, _name_declaration(turn)) for turn in turns]
        declarations = [(turn, name) for turn, name in declarations if name]
        if not declarations:
            return NAME_NOT_FOUND
        turn, name = declarations[-1]
        return f"O último nome que você informou nesta sessão é {name}.\n\n" + evidence(turn)

    is_recall = (
        re.match(r"^(?:o que|qual|quais|que horario|quando)\b", cleaned)
        and re.search(r"\b(?:falamos|falei|falou|disse|comentamos|comentei|comentou|combinamos|decidimos|combinado|decidido)\b", cleaned)
    ) or re.match(r"^(?:busque|procure|mostre|lembre|recorde)\b.*\b(?:historico|sessao|conversa)\b", cleaned)
    personal_query = re.fullmatch(
        r"(?:qual|quais) (?:e |sao )?(?:o |os |a |as )?(?:meu|minha|meus|minhas) "
        r"(?:horario(?:s)?(?: de (?:trabalho|estudo|lazer))?|disciplinas|materias)"
        r"(?: (?:dessa|desta|nessa|nesta) sessao)?", cleaned,
    )
    is_recall = is_recall or personal_query
    if not is_recall:
        return None
    # Primeira pessoa singular é o usuário; segunda pessoa é o Thérion.
    # Plural e consultas sem autoria explícita mantêm ambas as fontes.
    role = None
    if personal_query or re.search(r"\b(?:falei|comentei|eu disse)\b", cleaned):
        role = "user"
    elif re.search(r"\bvoce (?:disse|falou|comentou)\b", cleaned):
        role = "therion"
    elif re.search(r"\bdisse\b", cleaned) and not re.search(r"\b(?:ele|ela|therion)\b", cleaned):
        role = "user"
    matches = search(turns, query, role=role)
    # Consulta sem assunto explícito: últimos envios, sem inferir decisões.
    if not _terms(query):
        matches = [turn for turn in turns if turn.origin == "original"
                   and (role is None or turn.role == role)][-4:]
    if not matches:
        return "Não encontrei trechos correspondentes no histórico desta sessão. Informe uma palavra ou frase do assunto."
    return (
        "Encontrei estes registros da sessão. Declarações suas e respostas do Thérion "
        "estão identificadas; uma sugestão não comprova uma decisão ou autorização.\n\n"
        + "\n\n".join(evidence(turn) for turn in matches)
    )


def spoken_recall(answer: str) -> str:
    """Apresenta citações oralmente sem ler identificadores da interface."""
    if answer.startswith('O último nome que você informou nesta sessão é '):
        declaration = answer.split('\n\n', 1)[0]
        name = declaration.removeprefix('O último nome que você informou nesta sessão é ').removesuffix('.')
        return f'Você me disse que seu nome é {name}.'
    if not answer.startswith('Encontrei estes registros da sessão.'):
        return answer
    records = re.split(r'\[(Você|Thérion \(resposta/sugestão\)), mensagem \d+\]\n', answer)
    parts = []
    for index in range(1, len(records), 2):
        speaker = records[index]
        content = records[index + 1].strip()
        introduction = 'Você disse:' if speaker == 'Você' else 'Eu respondi:'
        parts.append(f'{introduction} {content}')
    if not parts:
        return answer
    return ('Encontrei estes trechos da nossa conversa. '
            + ' '.join(parts)
            + ' Esses registros não comprovam uma decisão ou autorização.')


def context_turns(turns: list[Turn], query: str) -> list[dict]:
    """Recuperação seletiva substitui parte da janela; não envia a sessão inteira.

    No máximo cinco mensagens e 3.000 caracteres de histórico. Abreviações são
    explícitas; o registro original permanece íntegro. Caracteres não são tokens.
    """
    if not turns:
        return []
    # Recuperações ficam no registro, mas não competem como nova evidência
    # nem ocupam a janela recente enviada ao modelo.
    turns = [turn for turn in turns if turn.origin == "original"]
    facts = []
    latest_name = next((turn for turn in reversed(turns) if _name_declaration(turn)), None)
    for turn in turns:
        if turn.role == "user" and (
            turn is latest_name
            or re.match(r"^(?:trabalho|estudo|vou estudar|minhas disciplinas|meus horarios|decidimos|combinamos)\b", normalize(turn.text.strip()))
        ):
            facts.append(turn)
    candidates = facts[-3:] + search(turns, query, limit=2) + turns[-3:]
    selected = []
    for turn in candidates:
        if turn not in selected:
            selected.append(turn)
    # A mensagem mais recente continua prioritária; até dois trechos recuperados.
    recent = turns[-3:]
    older = [turn for turn in selected if turn not in recent
             and (not _name_declaration(turn) or turn is latest_name)][:2]
    chosen = older + recent
    result = []
    remaining = 3000
    for turn in chosen:
        size = min(600, remaining)
        text = turn.text
        if len(text) > size:
            text = text[:max(0, size - 30)] + " […] (trecho abreviado)"
        result.append({"role": turn.role, "text": text})
        remaining -= len(text)
    return result
