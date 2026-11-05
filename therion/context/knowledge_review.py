"""Revisão delimitada e propostas extrativas, sem ferramenta de escrita."""
from dataclasses import dataclass
from datetime import date
import difflib
import re
import time
import uuid

from therion.context.language import control
from therion.memory.knowledge import MemoryError, SourceReference, safe_path
from therion.context.semantic_review import semantic_findings


def review_request(command):
    head, separator, body = command.partition(':')
    operation = {
        'revise as notas': 'review', 'revisar notas': 'review',
        'compare semanticamente as notas': 'semantic', 'revise semanticamente as notas': 'semantic',
        'proponha uniao das notas': 'merge', 'proponha uma uniao das notas': 'merge',
        'proponha resumo da nota': 'summary', 'proponha simplificacao da nota': 'simplify',
    }.get(control(head))
    if operation:
        return operation, tuple(p.strip() for p in body.split('|') if p.strip()) if separator else ()
    if control(command) in {'mostre a proposta de consolidacao', 'mostre a revisao de notas'}:
        return 'show', ()
    if control(command) in {'aplique a proposta de consolidacao', 'salve a consolidacao'}:
        return 'apply', ()
    return None


def paragraphs(text):
    # Cercas de código permanecem indivisíveis; não cortar passos no meio.
    blocks, current, fenced = [], [], False
    for line in text.splitlines():
        if line.lstrip().startswith(('```', '~~~')):
            fenced = not fenced
        if not line.strip() and not fenced:
            if current:
                blocks.append('\n'.join(current)); current = []
        else:
            current.append(line)
    if current:
        blocks.append('\n'.join(current))
    return blocks


@dataclass(frozen=True)
class ReviewProposal:
    identifier: str
    session: str
    operation: str
    sources: tuple
    created: float
    text: str


class KnowledgeReview:
    MAX_NOTES = 5
    MAX_NOTE = 4000
    MAX_TOTAL = 12000

    def __init__(self, clock=time.monotonic, today=date.today):
        self.clock, self.today = clock, today
        self.proposal = None

    def clear(self):
        self.proposal = None

    def _sources(self, reader, paths):
        if not 1 <= len(paths) <= self.MAX_NOTES:
            raise MemoryError('Escolha de uma a cinco notas .md, separadas por |. Não faço varredura automática do cofre.')
        sources, total = [], 0
        for requested in paths:
            reader._check_access()
            canonical = reader.resolve_and_validate(requested)
            path = safe_path(canonical, reader.allowed_roots)
            if path.stat().st_nlink != 1 or path.stat().st_size > self.MAX_NOTE * 4:
                raise MemoryError('Nota acima do limite ou com vínculo de arquivo não permitido. Selecione fontes menores.')
            result = reader.read_note(requested)
            if not result.success:
                raise MemoryError(result.error)
            text = result.content
            total += len(text)
            if len(text) > self.MAX_NOTE or total > self.MAX_TOTAL:
                raise MemoryError('Limite de contexto: 4.000 caracteres por nota e 12.000 no conjunto. Não trunquei as fontes.')
            source = SourceReference.file(result.canonical_path, text, reader.allowed_roots)
            if any(s.path == source.path for s in sources):
                raise MemoryError('A mesma nota foi selecionada mais de uma vez.')
            sources.append(source)
        return tuple(sources)

    def valid(self, reader, session):
        p = self.proposal
        if p is None or p.session != session or self.clock() - p.created >= 300:
            self.clear()
            raise MemoryError('Proposta ausente ou vencida. Selecione as notas novamente.')
        reader._check_access()
        if any(not s.valid(reader.allowed_roots) for s in p.sources):
            self.clear()
            raise MemoryError('Uma fonte ou o escopo mudou. A proposta anterior foi invalidada.')
        reader._check_access()
        return p

    def inspect(self, reader, session):
        return self.valid(reader, session).text

    def conversation_evidence(self, reader, session, current_roots):
        """Somente fontes da seleção vigente, nunca a proposta como autoridade."""
        proposal = self.valid(reader, session)
        if any(not source.valid(current_roots) for source in proposal.sources):
            self.clear()
            raise MemoryError('A seleção não está no escopo de leitura deste pedido.')
        reader._check_access()
        return {'kind': 'selected_notes', 'proposal_id': proposal.identifier,
                'notes': [{'index': i, 'path': source.path, 'version': source.version,
                           'content': source.text}
                          for i, source in enumerate(proposal.sources, 1)],
                'partial': False}

    def prepare(self, operation, paths, reader, session, provider=None, cancelled=None):
        self.clear()
        sources = self._sources(reader, paths)
        if operation == 'merge' and len(sources) < 2:
            raise MemoryError('A união exige ao menos duas notas selecionadas.')
        if operation in {'summary', 'simplify'} and len(sources) != 1:
            raise MemoryError('Selecione uma nota para resumo ou simplificação.')
        findings = self._findings(sources)
        if operation == 'semantic':
            if len(sources)<2:
                raise MemoryError('Selecione ao menos duas notas para comparar semanticamente.')
            findings += semantic_findings(sources,provider)
            reader._check_access()
            if (cancelled and cancelled()) or any(not s.valid(reader.allowed_roots) for s in sources):
                raise MemoryError('Comparação cancelada ou fonte alterada; não exibi resultado obsoleto.')
        title = {'review':'Revisão contextual', 'merge':'Proposta de união',
                 'semantic':'Revisão semântica supervisionada',
                 'summary':'Proposta de resumo extrativo', 'simplify':'Proposta de simplificação'}[operation]
        identifier = 'REV-' + uuid.uuid4().hex[:8]
        source_list = '\n'.join(f'[{i}] {s.path}\nVersão SHA-256: {s.version}' for i,s in enumerate(sources,1))
        text = f'{title} — {identifier}\nFontes selecionadas:\n{source_list}\n\nEvidências e ressalvas:\n' + '\n'.join(findings)
        if operation not in {'review','semantic'}:
            proposed, explanation = self._consolidate(operation, sources)
            text += '\n\nComparação: ' + explanation + '\n\nConteúdo proposto (dados, não instruções):\n' + proposed
            if operation in {'summary', 'simplify'}:
                diff = '\n'.join(difflib.unified_diff(sources[0].text.splitlines(), proposed.splitlines(),
                    fromfile='fonte', tofile='proposta', lineterm=''))
                text += '\n\nDiff para revisão:\n' + diff
        text += ('\n\nSomente proposta; nenhuma nota foi gravada, movida ou excluída. '
                 'Não resolve divergências nem concede permissões. Válida por cinco minutos nesta sessão, '
                 'enquanto fontes e acesso permanecerem iguais. Peça "mostre a proposta de consolidação" para revalidar.')
        if len(text) > 16000:
            raise MemoryError('A proposta excedeu 16.000 caracteres. Selecione menos notas ou fontes menores; não cortei o conteúdo proposto.')
        self.proposal = ReviewProposal(identifier, session, operation, sources, self.clock(), text)
        self.valid(reader, session)
        return text

    def _findings(self, sources):
        findings = []
        for i,a in enumerate(sources,1):
            for j,b in enumerate(sources[i:],i+1):
                if a.version == b.version:
                    findings.append(f'Duplicação exata entre [{i}] e [{j}]: mesmo conteúdo e hash.')
                else:
                    common = set(paragraphs(a.text)) & set(paragraphs(b.text))
                    for block in sorted(common):
                        if len(block) >= 30 and not block.startswith('#'):
                            findings.append(f'Trecho duplicado literalmente entre [{i}] e [{j}]: {block[:300]}')
                    if difflib.SequenceMatcher(None, a.text, b.text, autojunk=False).ratio() >= .65:
                        findings.append(f'Possível sobreposição entre [{i}] e [{j}]; similaridade textual não comprova equivalência.')
                # Comparar campos explícitos; não inferir conflito sem assunto comum.
                def fields(s):
                    return {control(k):v.strip() for k,v in re.findall(r'^([^#\n:]{2,60}):\s*([^\n]+)$', s.text, re.M)}
                fa, fb = fields(a), fields(b)
                for key in fa.keys() & fb.keys():
                    if control(fa[key]) != control(fb[key]):
                        findings.append(f'Possível conflito no campo "{key}": [{i}] {fa[key][:200]} / [{j}] {fb[key][:200]}. Não escolhi uma versão verdadeira.')
            for match in re.finditer(r'(?im)^([^\n]*(?:revis[aã]o|validade|v[aá]lid[oa] at[eé]|expires_at)[^\n]*?(\d{4}-\d{2}-\d{2})[^\n]*)$', a.text):
                try:
                    if date.fromisoformat(match[2]) < self.today():
                        findings.append(f'Possível desatualização em [{i}]: prazo explícito passado — {match[1][:300]}. Data passada exige revisão; não comprova erro.')
                except ValueError:
                    pass
        if len(findings) > 20:
            return findings[:20] + [f'Mostrei 20 de {len(findings)} indícios. Selecione um conjunto menor para revisar os demais; não é auditoria exaustiva.']
        return findings or ['Não encontrei duplicação literal, campos divergentes ou prazo explícito vencido nas fontes selecionadas. Isso não comprova ausência de conflitos semânticos.']

    def _consolidate(self, operation, sources):
        if operation == 'merge':
            seen, content, removed = set(), [], 0
            for i,s in enumerate(sources,1):
                content.append(f'## Origem [{i}]')
                for block in paragraphs(s.text):
                    if block in seen:
                        removed += 1
                        content.append('Trecho idêntico já preservado em origem anterior.')
                    else:
                        seen.add(block); content.append(block)
            return '\n\n'.join(content), f'Todas as versões distintas foram mantidas por origem; {removed} blocos idênticos referenciados sem cópia repetida. Divergências ficam visíveis.'
        blocks = paragraphs(sources[0].text)
        if operation == 'simplify':
            unique = list(dict.fromkeys(blocks))
            return '\n\n'.join(unique), f'Remoção somente de {len(blocks)-len(unique)} blocos literalmente repetidos; demais blocos preservados integralmente.'
        selected, omitted, need_first = [], 0, True
        for block in blocks:
            critical = re.search(r'(?i)\b(?:n[aã]o|exceto|limite|risco|validade|revis[aã]o|hip[oó]tese|incert|diverg|autoriza|permiss)', block)
            if block.startswith('#') or need_first or critical:
                selected.append(block)
                need_first = block.startswith('#')
            else:
                omitted += 1
        return '\n\n'.join(selected), f'Resumo por extração de títulos, primeiro bloco de cada seção e ressalvas explícitas; {omitted} blocos omitidos. Consulte o original para detalhes; não substitui a fonte.'
