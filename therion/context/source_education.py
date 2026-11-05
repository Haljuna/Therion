"""Campos literais de formação, com sua seção; não decide a situação do usuário."""
import re


def formation_context(content, budget=1400):
    groups = []
    headings = []
    rows = []
    has_course = False
    fence = None

    def finish():
        if has_course:
            groups.append('\n'.join([*headings, *rows]))

    for line in content.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            run = marker[1]
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        heading = re.match(r'^ {0,3}(#{1,6})\s+.+', line)
        if heading:
            finish()
            rows = []
            has_course = False
            depth = len(heading[1])
            while headings and len(re.match(r'^\s*(#+)', headings[-1])[1]) >= depth:
                headings.pop()
            headings.append(line)
            continue
        plain = re.sub(r'\*\*|__', '', line)
        if re.match(r'^\s*[-*]?\s*(?:Curso(?: técnico)?\s*(?::|em)|Situação\s*:|Período(?: letivo atual)?\s*:)', plain, re.I):
            rows.append(line)
            has_course = has_course or bool(re.match(r'^\s*[-*]?\s*Curso\b', plain, re.I))
    finish()
    result = '\n\n'.join(groups)
    if len(result) <= budget:
        return result
    # Limite explícito em linhas completas, sem fabricar situação ausente.
    result = result[:max(0, budget - 40)].rsplit('\n', 1)[0]
    return result + '\n[Contexto de formação parcial]'
