"""Referências efêmeras a resultados, sem conceder permissão de leitura."""
import re
import difflib
from pathlib import PurePosixPath
from dataclasses import dataclass

from therion.context.read_scope import ReadScope, _canonical, _contains
from therion.context.language import control


def normalize(text):
    return control(text)


_ORDINALS = {'primeira': 1, 'primeiro': 1, 'segunda': 2, 'segundo': 2,
             'terceira': 3, 'terceiro': 3, 'quarta': 4, 'quarto': 4,
             'quinta': 5, 'quinto': 5, 'ultima': -1, 'ultimo': -1}
_SELECTION = r'(?:\d+|' + '|'.join(_ORDINALS) + ')'


def selection(text):
    value = normalize(text)
    match = re.fullmatch(r'(?:a |o )?(' + _SELECTION + r')(?: nota| resultado| arquivo)?', value)
    if not match:
        return None
    value = match[1]
    return _ORDINALS[value] if value in _ORDINALS else int(value)


def named_reference_request(text):
    """Pedido de leitura por título; nunca uma busca nova ou execução do prompt."""
    text = normalize(text)
    if re.search(r'\b(?:nao|nunca|nem|talvez)\b', text):
        return None
    match = re.fullmatch(r'(?:(?:voce )?(?:consegue|pode) )?(?:me )?'
        r'(manda|mande|mandar|mostre|mostrar|exiba|leia|ler|resuma|resumir) '
        r'(?:(?:o que esta escrito|o texto original|o conteudo completo|o conteudo integral|o texto|o conteudo) '
        r'(?:no|na|do|da|de) |(?:o |a )?)(.+)', text)
    if not match:
        return None
    title = match[2]
    if not re.search(r'\b(?:nota|arquivo|prompt|documento)\b', title):
        return None
    # Referências numéricas e caminhos continuam no parser já existente.
    if reference_request(text) is not None or title.endswith('.md') or '/' in title or '\\' in title:
        return None
    raw = match[1] in {'manda','mande','mandar','mostre','mostrar','exiba'}
    raw |= bool(re.search(r'o que esta escrito|original|completo|integral', text))
    return ('raw' if raw else 'summary' if match[1] in {'resuma','resumir'} else 'read', title)


def title_candidates(title, paths):
    """Somente nomes já apresentados; no máximo uma palavra próxima de ASR."""
    stop = {'o','a','os','as','do','da','dos','das','de','no','na','um','uma','nota','arquivo','documento'}
    words = [w for w in re.findall(r'\w+', normalize(title)) if w not in stop]
    exact, near = [], []
    for i, path in enumerate(paths, 1):
        name = PurePosixPath(path.replace('\\','/')).stem
        available = set(re.findall(r'\w+', normalize(name)))
        missing = [word for word in words if word not in available]
        if words and not missing:
            exact.append(i)
        elif len(words) >= 2 and len(missing) == 1 and len(missing[0]) >= 4 and any(
                len(candidate) >= 4 and difflib.SequenceMatcher(None, missing[0], candidate).ratio() >= .72
                for candidate in available):
            near.append(i)
    return exact or near


def reference_request(text):
    """Retorna operação, índice e presença explícita de nota/resultado."""
    text = normalize(text)
    detail = re.fullmatch(r'(?:fale|explique|conte)(?: mais)? sobre (?:o |a )?(?:trecho|resultado|nota) (.+)', text)
    if detail:
        index = selection(detail[1])
        if index is not None:
            return 'read', index, 'note'
    original = re.fullmatch(r'(?:mostre|exiba|mostrar) (?:o )?(?:conteudo|texto) '
        r'(?:original|integral|completo) (?:da|do|de|dessa|desta) (.+)', text)
    if original:
        text = 'mostre ' + original[1]
    text = re.sub(r'^(?:quero|gostaria de)\s+(?:ver|ler)\s+', 'leia ', text)
    text = re.sub(r'^(?:me |pode |voce pode )', '', text)
    match = re.fullmatch(r'(leia|ler|le|abra|abre|abrir|mostre|mostra|mostrar|mosta|resuma|resume|resumir)\s+(.+)', text)
    if not match:
        return None
    target = match[2]
    explicit = ('note' if re.search(r'\b(nota|arquivo|trecho)\b', target) else
                'result' if re.search(r'\bresultado\b', target) else None)
    target = re.sub(r'^(?:a|o|essa|esse|esta|este|aquela|aquele)\s+', '', target)
    target = re.sub(r'^(?:nota|resultado|arquivo|trecho)\s+', '', target)
    target = re.sub(r'\s+(?:nota|resultado|arquivo|trecho)$', '', target)
    index = selection(target)
    if index is None and target not in {'isso', 'esse', 'essa', 'este', 'esta', 'aquela', 'aquele', 'nota', 'resultado', 'arquivo'}:
        return None
    return ('raw' if original else 'summary' if match[1] in {'resuma', 'resume', 'resumir'} else 'read', index, explicit)


@dataclass(frozen=True)
class NoteResults:
    paths: tuple[str, ...]
    roots: tuple[str, ...]

    def restricted_scope(self, task_id, current_roots):
        # Não recanonicalizar a raiz original: um link movido não deve mover a permissão.
        roots = []
        for original in self.roots:
            for current in map(_canonical, current_roots):
                narrower = current if _contains(original, current) else original if _contains(current, original) else None
                if narrower is not None and narrower not in roots:
                    roots.append(narrower)
        return ReadScope(task_id, tuple(roots))
