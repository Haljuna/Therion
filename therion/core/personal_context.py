"""Consultas pessoais somente de leitura, com fontes revalidadas e orçamento."""
import os
import re
from pathlib import Path
from therion.context.language import control
from therion.context.note_references import NoteResults
from therion.context.read_scope import effective_roots, _canonical
from therion.context.source_education import formation_context
from therion.memory.knowledge import SourceReference, MemoryError as KnowledgeError


def personal_summary_style(command):
    detailed = bool(re.search(r'\b(?:detalhad[oa]|complet[oa]|aprofundad[oa])\b',control(command)))
    return {'perspective':'user_second_person','max_words':180 if detailed else 60,
            'max_sentences':8 if detailed else 3}


def checked_personal_summary(text, style):
    if not isinstance(text,str) or not text.strip():
        return None
    normalized=control(text)
    if (re.search(r'\b(?:eu|meu|minha|meus|minhas)\b',normalized)
            or re.search(r'(?:^|[.!?]\s+|\n)\s*(?:sou|estou|tenho|conclui|atuo|concilio|desenvolvi|busco|quero|preciso)\b',normalized)):
        return None
    sentences=re.split(r'(?<=[.!?])\s+',text.strip())
    selected=[];words=0
    for sentence in sentences[:style['max_sentences']]:
        size=len(sentence.split())
        if words+size>style['max_words']:
            break
        selected.append(sentence);words+=size
    return ' '.join(selected) if selected else None


def context_excerpt(content, query, budget):
    if len(content) <= budget:
        return content, False
    terms = set(re.findall(r'\w{4,}', control(query))) - {
        'leia', 'perfil', 'explique', 'resumo', 'resuma', 'sobre', 'informacoes',
        'voce', 'faca', 'atualmente', 'disponiveis', 'pessoais'}
    blocks = []
    headings = []
    for part in re.split(r'(\n?^#{1,6}\s+[^\n]+\n?)', content, flags=re.M):
        heading = re.match(r'\s*(#{1,6})\s+', part)
        if heading:
            depth = len(heading[1])
            while headings and len(re.match(r'\s*(#+)', headings[-1])[1]) >= depth:
                headings.pop()
            headings.append(part.strip())
            continue
        for index, paragraph in enumerate(re.split(r'\n\s*\n', part)):
            if paragraph.strip():
                text = '\n'.join([*headings, paragraph.strip()])
                score = len(terms & set(re.findall(r'\w+', control(text))))
                blocks.append((text, score, index == 0))
    remaining = budget - 34
    selected = []
    for index in sorted(range(len(blocks)), key=lambda i: (-blocks[i][1], not blocks[i][2], i)):
        text = blocks[index][0]
        if len(text) + 2 <= remaining:
            selected.append(index)
            remaining -= len(text) + 2
    excerpt = '\n\n'.join(blocks[index][0] for index in sorted(selected))
    if not excerpt:
        excerpt = content[:max(0, budget - 34)].rsplit('\n', 1)[0]
    return excerpt + '\n[Conteúdo parcial da fonte]', True


class PersonalContextSupport:
    def _answer_assistant_question(self, command):
        from therion.core.orchestrator import OrchestrationResult
        context = self._build_ai_context(command)
        context['last_tool_evidence'] = None
        evidence = {'kind': 'assistant_context', 'identity': context['assistant_identity'],
                    'capabilities': context['capabilities_summary'], 'dialogue': context['conversation_frame'],
                    'dialogue_act': 'decline' if control(command) in {'nao', 'nao obrigado'} else 'question'}
        self._last_tool_evidence = evidence
        self._pending_clarification = None
        text = self.ai_core.describe_result(command, evidence, context) if self.ai_core else None
        if not isinstance(text, str) or not text.strip():
            text = ('Tudo bem, deixo essa sugestão de lado.' if control(command) in {'nao', 'nao obrigado'}
                    else 'Não consegui compor a resposta sobre o Therion agora. Não vou inventar informações sobre sua criação ou suas capacidades.')
        return OrchestrationResult(status='success', message=text, speech_message=text)

    def _init_personal_context(self, profile_path, identity):
        self._user_profile_path = profile_path or '01 - Pessoal/Perfil.md'
        self._identity_facts = {'name': 'Thérion', 'role': 'assistente pessoal local',
                                'creator': None, 'created_at': None}
        if isinstance(identity, dict):
            for key in ('name', 'role', 'creator', 'created_at'):
                value = identity.get(key)
                if isinstance(value, str) and value.strip() and len(value) <= 200:
                    self._identity_facts[key] = value.strip()
        self._personal_snapshot = None
        self._personal_reply_active = False

    def _personal_sources_valid(self, scope=None):
        if self._personal_snapshot is None:
            return True
        sources, created = self._personal_snapshot
        roots = effective_roots(scope, self.second_brain.allowed_roots)
        return (self._language_clock() - created <= 300
                and all(source.valid(roots) for source in sources))

    def _clear_personal_context(self):
        self._personal_snapshot = None
        self._personal_reply_active = False
        if isinstance(self._last_tool_evidence, dict) and self._last_tool_evidence.get('kind') == 'personal_context':
            self._last_tool_evidence = None
            self._conversation_frame.clear()
            self._pending_clarification = None

    def _personal_flow_is_free(self):
        return not any(getattr(self, field, None) for field in (
            '_pending_event_draft', '_replace_alias_flow_step', '_delete_alias_flow_step',
            '_unknown_target_flow_step', '_open_app_flow_active', '_pending_memory_plan',
            '_alias_flow_step'))

    def _personal_candidates(self, profile, command, query, scope):
        """Links pertinentes da fonte primeiro; nunca seguem URLs ou instruções."""
        candidates = []
        terms = set(re.findall(r'\w{4,}', control(query or command))) - {
            'resumo', 'resuma', 'sobre', 'perfil', 'informacoes', 'voce', 'faca', 'disponiveis'}
        section = ''
        for line in profile.content.splitlines():
            if re.match(r'^\s*#+\s', line):
                section = line
            links = re.findall(r'\[\[([^\]|#]+)', line)
            links += re.findall(r'\]\(([^)]+\.md)\)', line)
            for link in links:
                if re.search(r'^[a-z]+://', link, re.I):
                    continue
                path = link if link.lower().endswith('.md') else link + '.md'
                score = len(terms & set(re.findall(r'\w+', control(line))))
                general = re.search(r'projetos|objetivos|conquistas|trajetoria|rotina|interesses', control(section))
                if not score and not general:
                    continue
                if '/' not in path and '\\' not in path:
                    path = str(Path(profile.canonical_path).parent / path)
                candidates.append((score, path))
        if len(candidates) < 3:
            search_query = query.strip() if isinstance(query, str) and query.strip() else 'Objetivos'
            for match in self.second_brain.search_notes(search_query, max_results=5, scope=scope):
                candidates.append((0, match.path))
        return [path for _, path in sorted(candidates, key=lambda item: -item[0])][:8]

    def _resolve_personal_context(self, purpose, command, scope, query=''):
        from therion.core.orchestrator import OrchestrationResult
        if not self._personal_flow_is_free():
            return OrchestrationResult(status='clarification', message='Conclua ou cancele o pedido pendente antes de consultar seu perfil.')
        self._clear_personal_context()
        roots = tuple(_canonical(root) for root in effective_roots(scope, self.second_brain.allowed_roots))
        try:
            # Validar antes de verificar existência: ausência não permite contornar escopo.
            resolved = self.second_brain.resolve_and_validate(self._user_profile_path, scope)
        except (ValueError, PermissionError, OSError):
            return OrchestrationResult(status='clarification', message='O Perfil configurado não está no escopo de leitura permitido. Não consultei suas informações pessoais; indique uma fonte autorizada ou ajuste o acesso.')
        profile = self.read_context(self._user_profile_path, scope)
        if not profile.success:
            if not Path(resolved).exists():
                matches = [match for match in self.second_brain.search_notes('Perfil', max_results=20, scope=scope)
                           if Path(match.path).stem.casefold() == 'perfil']
                if len(matches) > 1:
                    return OrchestrationResult(status='clarification', message='Há mais de um Perfil permitido. Qual devo usar?\n' + '\n'.join(match.path for match in matches))
                if len(matches) == 1:
                    profile = self.read_context(matches[0].path, scope)
            if not profile.success:
                return OrchestrationResult(status='clarification', message='Não consegui ler o Perfil configurado. Isso não significa que não existam informações sobre você. Indique a nota que devo consultar.')
        reads = [profile]
        omitted = []
        if purpose == 'personal_summary':
            try:
                candidates = self._personal_candidates(profile, command, query, scope)
                seen = {_canonical(profile.canonical_path)}
                for path in candidates:
                    if self._workflow_cancel_event.is_set():
                        break
                    read = self.read_context(path, scope)
                    if not read.success:
                        omitted.append(path)
                        continue
                    canonical = _canonical(read.canonical_path)
                    if canonical not in seen:
                        reads.append(read)
                        seen.add(canonical)
                    if len(reads) == 4:
                        break
            except (PermissionError, ValueError, OSError):
                omitted.append('Fontes complementares indisponíveis no escopo atual')
        try:
            sources = tuple(SourceReference.file(read.canonical_path, read.content, roots) for read in reads)
            self._personal_snapshot = (sources, self._language_clock())
            notes = []
            remaining = 12000
            for index, (read, source) in enumerate(zip(reads, sources)):
                budget = min(remaining, 8000 if index == 0 and len(reads) > 1 else remaining // (len(reads) - index))
                formation = formation_context(read.content, min(1400, budget // 3))
                content, partial = context_excerpt(read.content, query or command, budget - len(formation))
                remaining -= len(content) + len(formation)
                relative = os.path.relpath(read.canonical_path, self.second_brain.vault_root).replace('\\', '/')
                notes.append({'path': relative, 'content': content, 'formation_context': formation,
                              'partial': partial, 'version': source.version})
                if read.matched_root:
                    used = self._audit_relative_root(read.matched_root)
                    if used:
                        self.memory.add_used_root(used)
            evidence = {'kind': 'personal_context', 'purpose': purpose, 'notes': notes,
                        'partial': any(note['partial'] for note in notes), 'unavailable_sources': omitted}
            if purpose=='personal_summary':
                evidence['response_style']=personal_summary_style(command)
            if self._workflow_cancel_event.is_set() or not self._personal_sources_valid(scope):
                raise KnowledgeError('Leitura cancelada ou fontes alteradas antes da interpretação.')
            self._last_tool_evidence = evidence
            self._personal_reply_active = True
            self._language_focus = 'notes'
            self._conversation_frame.topic = 'personal'
            self._conversation_frame.updated = self._language_clock()
            self._note_results = NoteResults(tuple(note['path'] for note in notes), roots)
            self._note_results_created = self._language_clock()
            fallback = 'Não consegui compor a explicação agora. Li as fontes abaixo; tente novamente ou selecione uma nota para conferir o conteúdo.'
            summary = self._describe_read_result(command, evidence, fallback)
            if purpose=='personal_summary' and summary!=fallback:
                checked=checked_personal_summary(summary,evidence['response_style'])
                if checked is None and self.ai_core is not None and self._format_repair_budget['remaining']>0:
                    if self._workflow_cancel_event.is_set() or not self._personal_sources_valid(scope):
                        raise KnowledgeError('As fontes mudaram antes da correção do resumo.')
                    self._format_repair_budget['remaining']-=1
                    context=self._build_ai_context(command)
                    context['personal_summary_repair']=True
                    repaired=self.ai_core.describe_result(command,evidence,context)
                    checked=checked_personal_summary(repaired,evidence['response_style'])
                summary=checked or 'Não consegui compor um resumo breve e confiável do seu perfil agora.'
            self.second_brain._check_access()
            if self._workflow_cancel_event.is_set() or self._personal_snapshot is None or not self._personal_sources_valid(scope):
                raise KnowledgeError('A fonte, o acesso ou a versão mudou durante a resposta.')
        except (KnowledgeError, PermissionError, ValueError, OSError):
            self._clear_personal_context()
            return OrchestrationResult(status='cancelled', message='As fontes pessoais mudaram, venceram ou ficaram indisponíveis. Não exibi a interpretação anterior; faça o pedido novamente.')
        return OrchestrationResult(status='success', speech_message=summary,
            message=summary + '\n\nFontes:\n' + '\n'.join(f'- {note["path"]}' for note in notes)
                + ('\nA resposta usa conteúdo parcial das fontes.' if evidence['partial'] else ''))
