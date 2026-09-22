"""ReadScope — filtro temporário de leitura por tarefa (DEC-033).

ReadScope NÃO é fonte de permissão: apenas restringe as raízes base
(`allowed_roots`), nunca as amplia, nunca as muta e nunca herda roots
de tarefa anterior. A interseção é calculada por chamada, sem cache.
"""

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence


def _canonical(path: str) -> str:
    """Canonicalização por chamada: normcase(abspath(realpath(...)))."""
    return os.path.normcase(os.path.abspath(os.path.realpath(path)))


def _contains(parent: str, child: str) -> bool:
    """True se child é subcaminho estrito ou igual a parent (ambos canônicos)."""
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


@dataclass(frozen=True)
class ReadScope:
    """Escopo de leitura imutável e efêmero de uma única tarefa."""

    task_id: str
    roots: tuple[str, ...]


def effective_roots(
    scope: Optional[ReadScope],
    allowed_roots: Sequence[str],
) -> List[str]:
    """Interseção scope ∩ allowed_roots — só restringe, nunca amplia.

    Regras (DEC-033):
    - scope=None → preserva as roots atuais (cópia, sem mutação);
    - scope.roots=() → zero roots efetivas (deny-by-default efetivo);
    - scope presente → cada root do escopo é mantida apenas se contida em
      alguma root permitida; root do escopo mais ampla que a permitida é
      reduzida à root permitida; root fora de todas as permitidas é
      descartada. O resultado nunca cobre nada além de allowed_roots.

    Não modifica as entradas. Não usa cache.
    """
    if scope is None:
        return list(allowed_roots)

    allowed_canon = [_canonical(r) for r in allowed_roots]
    effective: List[str] = []

    for raw_root in scope.roots:
        scope_root = _canonical(raw_root)
        if any(_contains(a, scope_root) for a in allowed_canon):
            # Escopo mais restrito que a root permitida: mantém o escopo.
            match = scope_root
        else:
            # Root do escopo mais ampla: reduz à permissão que contém.
            containing = next(
                (a for a in allowed_canon if _contains(scope_root, a)), None
            )
            if containing is None:
                # Fora de allowed_roots: nunca amplia acesso.
                continue
            match = containing
        if match not in effective:
            effective.append(match)

    return effective
