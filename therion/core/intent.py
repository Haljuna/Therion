"""Interpretação e representação de intenções da V0."""

import re
from dataclasses import dataclass
from typing import Optional
from therion.calendar.dialogue import extract_fields, query_request
from therion.context.note_references import reference_request
from therion.context.language import calendar_correction,APP_VOCATIVE


def search_term(text):
    """Remove apenas o introdutor do pedido, preservando o assunto e citações."""
    text = text.strip()
    if text.startswith(('"', "'", '“')):
        return text
    text = re.sub(r'^(?:nas? notas?|no segundo c[eé]rebro)\s+', '', text, flags=re.I)
    text = re.sub(r'\s+no segundo c[eé]rebro[.!?]*$', '', text, flags=re.I)
    return re.sub(r'^(?:(?:informaç[õo]es|informacoes|materiais|notas|conte[uú]dos|dados)\s+)?'
                  r'(?:sobre|a respeito de|acerca de)\s+', '', text, flags=re.I).strip()


@dataclass
class Intent:
    """Representação estruturada de uma intenção."""

    action: str
    target: str
    raw_command: str
    requires_confirmation: bool = True
    entities: Optional[dict] = None


class IntentRecognizer:
    """Reconhecedor determinístico de intenções para a V0."""

    _OPEN_APP_PATTERN = re.compile(
        r"^(?:"+APP_VOCATIVE+r"[,\s]+)?(?:(?:agora|então|entao)[,\s]+)?(?:abre|abra|abrir)[,\s]+(?:o\s+)?([a-zA-Z0-9_\-\.\sàáâãéêíóôõúç]+)\s*$",
        re.IGNORECASE,
    )

    _LIST_ALIASES_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:liste|lista|mostre|exiba|listar|mostrar|exibir)\s+(?:meus?\s+)?(?:aliases?|apelidos?)\s*$",
        re.IGNORECASE,
    )

    _ADD_ALIAS_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:adicione|adicionar|crie|criar)\s+um\s+alias\s*$",
        re.IGNORECASE,
    )

    _DELETE_ALIAS_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:exclua|excluir|remova|remover|apague|apagar)\s+um\s+alias\s*$",
        re.IGNORECASE,
    )

    _REPLACE_ALIAS_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:substitua|substituir|altere|alterar|troque|trocar)\s+um\s+alias\s*$",
        re.IGNORECASE,
    )

    _CONSULT_CONTEXT_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:leia|ler|consulte|consultar)\s+"
        r"(?:(?:no\s+)?(?:segundo\s+cérebro|2º?\s*cérebro)|(?:a\s+)?nota(?=\s+.+\.md\s*$))\s+"
        r"(.+)$",
        re.IGNORECASE,
    )

    _SEARCH_CONTEXT_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:procure|procurar|procura|busque|buscar|busca|pesquise|pesquisar|pesquisa)[,\s]+"
        r"(?:no\s+)?(?:segundo\s+c[eé]rebro|2º?\s*c[eé]rebro)[,\s]+"
        r"(.+)$",
        re.IGNORECASE,
    )

    _PLAN_DAY_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:"
        r"planeje\s+(?:meu\s+)?dia"
        r"|organize\s+(?:meu\s+)?dia"
        r"|prepare\s+(?:meu\s+)?dia"
        r")\s*[!.?]?\s*$",
        re.IGNORECASE,
    )

    _CALENDAR_TODAY_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:"
        r"(?:o\s+)?(?:que|qual|quais)\s+(?:tenho|ha|existe|está)\s+(?:hoje|neste\s+dia)"
        r"|(?:minha|a)\s+agenda(?:\s+de\s+hoje)?"
        r"|agenda\s+de\s+hoje"
        r"|compromissos?\s+(?:de\s+)?hoje"
        r"|eventos?\s+(?:de\s+)?hoje"
        r"|(?:resume|resuma)\s+(?:o\s+)?meu\s+dia"
        r")\s*[!.?]?\s*$",
        re.IGNORECASE,
    )

    _CREATE_EVENT_IMPERATIVE_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:marque|marca|marcar|agende|agenda|agendar|crie|cria|criar)\s+(.+)$",
        re.IGNORECASE,
    )

    _CREATE_EVENT_NATURAL_PATTERN = re.compile(
        r"^(?:therion[,\s]+)?(?:quero\s+|preciso\s+|vou\s+|pode\s+|gostaria\s+de\s+)?"
        r"(?:marque|marca|marcar|agende|agenda|agendar|crie|cria|criar)\s+"
        r"(?:um(?:a)?\s+)?"
        r"(?:evento|reunião|compromisso|calendário|agenda)"
        r"(?:(?:\s*[,.:]\s*|\s+)(.*))?$",
        re.IGNORECASE,
    )

    _ABSENCE_CLAUSES_PATTERN = re.compile(
        r"(?:[,.:]\s*|\s+)?(?:"
        r"mas\s+ainda\s+não\s+sei\s+o\s+horário|"
        r"mas\s+ainda\s+não\s+sei\s+a\s+hora|"
        r"ainda\s+não\s+sei\s+o\s+horário|"
        r"mas\s+não\s+sei\s+o\s+horário|"
        r"ainda\s+não\s+sei\s+a\s+hora|"
        r"mas\s+não\s+sei\s+a\s+hora"
        r")\s*$",
        re.IGNORECASE,
    )

    _REJECT_ARTIFACT_PATTERN = re.compile(
        r"^(?:um(?:a)?\s+)?(?:nota|arquivo|pasta|documento|plano|roteiro)\b",
        re.IGNORECASE,
    )

    VAGUE_TARGETS = {"isso", "aquilo"}

    def _extract_event_fields(self, rest: str, entities: dict) -> str:
        """Extrai start_time, date e title do texto restante. Retorna texto residual."""
        # Remover cláusula de horário desconhecido antes de interpretar campos.
        rest = self._ABSENCE_CLAUSES_PATTERN.sub('', rest).strip()
        rest, fields = extract_fields(rest)
        entities.update(fields)
        if 'start_time' in entities and re.fullmatch(r'\d{1,2}h', entities['start_time'], re.I):
            entities['start_time'] = entities['start_time'][:-1] + ':00'

        # remover "dia" solto
        rest = re.sub(r'\bdia\b\s*', '', rest, flags=re.IGNORECASE).strip()

        # remover termos genéricos do começo
        rest = re.sub(r'^(?:um\s+evento|uma\s+reunião|evento|reunião)\b\s*', '', rest, flags=re.IGNORECASE).strip()

        # remover cláusulas literais de ausência de horário no trecho final
        rest = self._ABSENCE_CLAUSES_PATTERN.sub('', rest).strip()

        # limpar pontuações residuais nas bordas
        rest = re.sub(r'^[,.:\s]+|[,.:\s]+$', '', rest).strip()
        if fields and rest.casefold() in {'para','pra','na','no','em','de'}:
            rest = ''
        if rest.casefold() in {'para mim', 'pra mim', 'por favor', 'para mim por favor', 'pra mim por favor'}:
            rest = ''

        return rest

    def parse(self, command: str) -> Optional[Intent]:
        """Extrai ação e alvo de um comando textual simples."""
        cleaned = command.strip()
        note_reference = reference_request(cleaned)
        if note_reference is not None and (note_reference[2] or note_reference[1] is not None):
            return Intent(action="selecionar nota", target="", raw_command=command, requires_confirmation=False)
        
        # Verificar padrão de listagem de aliases primeiro
        list_match = self._LIST_ALIASES_PATTERN.match(cleaned)
        if list_match:
            return Intent(
                action="listar aliases",
                target="",
                raw_command=command,
                requires_confirmation=False,
            )
        
        # Verificar padrão de adicionar alias
        add_match = self._ADD_ALIAS_PATTERN.match(cleaned)
        if add_match:
            return Intent(
                action="adicionar alias",
                target="",
                raw_command=command,
                requires_confirmation=False,
            )
        
        # Verificar padrão de excluir alias
        delete_match = self._DELETE_ALIAS_PATTERN.match(cleaned)
        if delete_match:
            return Intent(
                action="excluir alias",
                target="",
                raw_command=command,
                requires_confirmation=False,
            )
        
        # Verificar padrão de substituir alias
        replace_match = self._REPLACE_ALIAS_PATTERN.match(cleaned)
        if replace_match:
            return Intent(
                action="substituir alias",
                target="",
                raw_command=command,
                requires_confirmation=False,
            )
        
        # Verificar padrão de busca no Segundo Cérebro
        search_match = self._SEARCH_CONTEXT_PATTERN.match(cleaned)
        if search_match:
            return Intent(
                action="buscar segundo cérebro",
                target=search_term(search_match.group(1)),
                raw_command=command,
                requires_confirmation=False,
            )

        short_search = re.fullmatch(r'(?:therion[,\s]+)?(?:procure|procura|busque|busca)\s+(?:por\s+)?'
                                   r'(.+?)(?:\s+para mim)?[.!?]*', cleaned, re.I)
        if short_search and not re.search(r'\b(?:internet|google|web|online|sites?)\b', cleaned, re.I):
            return Intent(action='buscar segundo cérebro', target=search_term(short_search[1]),
                          raw_command=command, requires_confirmation=False)

        # Verificar padrão de consulta ao Segundo Cérebro
        consult_match = self._CONSULT_CONTEXT_PATTERN.match(cleaned)
        if consult_match:
            return Intent(
                action="consultar segundo cérebro",
                target=consult_match.group(1).strip(),
                raw_command=command,
                requires_confirmation=False,
            )

        # Verificar padrão de planejar dia (somente leitura)
        plan_day_match = self._PLAN_DAY_PATTERN.match(cleaned)
        if plan_day_match:
            return Intent(
                action="planejar dia",
                target="",
                raw_command=command,
                requires_confirmation=False,
            )

        # Verificar padrão de consulta de calendário (hoje)
        calendar_match = self._CALENDAR_TODAY_PATTERN.match(cleaned)
        if calendar_match:
            return Intent(
                action="calendário hoje",
                target="",
                raw_command=command,
                requires_confirmation=False,
            )

        calendar_query = (None if self._CREATE_EVENT_NATURAL_PATTERN.match(cleaned)
                          else query_request(cleaned))
        if calendar_query is not None:
            return Intent(action=('calendário hoje' if calendar_query == {'date': 'hoje', 'days': 1} else 'consultar agenda'), target='', raw_command=command,
                          requires_confirmation=False, entities=calendar_query)

        # Verificar padrão de criar evento no calendário
        # Variável local com pontuação removida — não altera cleaned nem outros recognizers
        _event_candidate = re.sub(r'[.!?]+$', '', calendar_correction(cleaned)).strip()
        _event_candidate = re.sub(
            r'^(?:na verdade[, ]+)?(?:eu )?(?:preciso|quero|gostaria)(?: de)? que '
            r'(?:voc[eê] )?(?:me )?(?=(?:marque|marca|marcar|agende|agenda|agendar|crie|cria|criar)\b)',
            '', _event_candidate, flags=re.I)

        # Padrão B: frase natural com keyword obrigatória (evento/reunião/compromisso/calendário/agenda)
        natural_match = self._CREATE_EVENT_NATURAL_PATTERN.match(_event_candidate)
        if natural_match:
            rest = (natural_match.group(1) or '').strip()
            entities = {}
            rest = self._extract_event_fields(rest, entities)
            if rest:
                entities['title'] = rest.capitalize() if rest.islower() else rest
            else:
                original_lower = natural_match.group(0).lower()
                if 'reunião' in original_lower:
                    entities['title'] = 'Reunião'
                elif 'evento' in original_lower and 'compromisso' not in original_lower:
                    pass  # Não atribuir título padrão para "quero criar um evento"
            return Intent(
                action="criar evento calendário",
                target="",
                raw_command=command,
                requires_confirmation=True,
                entities=entities,
            )

        # Padrão A: imperativo existente
        imperative_match = self._CREATE_EVENT_IMPERATIVE_PATTERN.match(_event_candidate)
        if imperative_match:
            rest = imperative_match.group(1).strip()

            # Rejeitar artefatos não-calendário
            if self._REJECT_ARTIFACT_PATTERN.match(rest):
                return None

            entities = {}
            rest = self._extract_event_fields(rest, entities)
            if rest:
                entities['title'] = rest.capitalize() if rest.islower() else rest
            else:
                original_rest = imperative_match.group(1).lower()
                if 'reunião' in original_rest:
                    entities['title'] = 'Reunião'
                elif 'evento' in original_rest:
                    entities['title'] = 'Evento'

            return Intent(
                action="criar evento calendário",
                target="",
                raw_command=command,
                requires_confirmation=True,
                entities=entities,
            )
        
        # Pontuação de fim de frase não faz parte do nome do aplicativo.
        # Normalização local: não altera comandos de arquivos, busca ou aliases.
        open_candidate = re.sub(r"[.!?]+$", "", cleaned).strip()
        match = self._OPEN_APP_PATTERN.match(open_candidate)
        if match:
            target_raw = match.group(1).strip()
            target_raw = re.sub(r'(?:,?\s+(?:pra|para)\s+mim(?:,?\s+por\s+favor)?|,?\s+por\s+favor)$','',target_raw,flags=re.I).strip()
            if not target_raw:return None
            window=re.fullmatch(r'(?:mais uma|uma nova|outra|uma) janela (?:do|da|de|no|na) (.+)',target_raw,re.I)
            if window:target_raw=window[1].strip()
            # Preserva capitalização amigável (ex: obsidian -> Obsidian)
            target = target_raw.capitalize() if target_raw.islower() else target_raw
            return Intent(
                action="abrir aplicativo",
                target=target,
                raw_command=command,
                requires_confirmation=True,
                entities={'new_window':True} if window else None,
            )
        return None
