"""Propostas voláteis a partir de códigos emitidos por verificadores internos."""
from therion.memory.knowledge import MemoryError, SourceReference, safe_path


REFERENCES = (
    '90 - Sistema da IA/Skills/Skills.md',
    '90 - Sistema da IA/Skills/Registro de Skills.md',
    '90 - Sistema da IA/Skills/SKILL-001 - Fluxos Conversacionais com Confirmação.md',
    '90 - Sistema da IA/Skills/SKILL-002 — Planejar meu dia.md',
)


def skill_proposals(reader, coordinator):
    patterns = coordinator.verified_patterns()
    if not patterns:
        return ('Não há padrão de erro comprovado nesta sessão. Uma falha isolada ou relato do modelo '
                'não basta para propor Skill. Nenhuma Skill foi criada ou ativada.')
    sources = []
    for requested in REFERENCES:
        reader._check_access()
        path = safe_path(reader.resolve_and_validate(requested), reader.allowed_roots)
        if path.stat().st_nlink != 1 or path.stat().st_size > 80000:
            raise MemoryError('Referência de Skills acima do limite ou não regular.')
        result = reader.read_note(requested)
        if not result.success:
            raise MemoryError('Não consegui consultar as referências de Skills; não preparei proposta.')
        sources.append(SourceReference.file(result.canonical_path, result.content, reader.allowed_roots))
    rows = ['Propostas de evolução de Skills — somente revisão, sem ativação.',
        'Consulta de duplicação: Registro de Skills e SKILL-001/002. Há sobreposição com fluxos existentes; preferi evolução a nova Skill.',
        'Não procurei indiscriminadamente RAS pessoais. Candidatos verificados desta sessão: '
        + ', '.join(c.id for c in coordinator.snapshot() if c.source.kind == 'operation')]
    for code,count in patterns:
        if code == 'calendar_query_failed':
            rows += [f'\nEvolução proposta: SKILL-002 — consulta com falha. Evidência: {code}, pelo menos {count} resultados internos verificados nesta sessão.',
                'Objetivo: preservar a incerteza quando a leitura da agenda falhar.',
                'Gatilho: consulta ao calendário retorna falha; recorrência justifica revisar o procedimento existente.',
                'Pré-condições: adapter autorizado; resposta verificada; permissão somente de leitura.',
                'Passos: 1. Consultar uma vez. 2. Separar resultado parcial de falha total. 3. Informar que a falha não comprova agenda vazia. 4. Oferecer nova consulta somente mediante novo pedido.',
                'Limites: não criar compromissos, não deduzir disponibilidade, não reter títulos pessoais ou erro bruto.',
                'Validação proposta: simular falha total, parcial e sucesso vazio; conferir mensagens e ausência de escritas/repetições.']
        elif code == 'action_verification_failed':
            rows += [f'\nEvolução proposta: SKILL-001 — resultado incerto. Evidência: {code}, pelo menos {count} resultados internos verificados nesta sessão.',
                'Objetivo: impedir conclusão falsa e repetição de efeitos persistentes.',
                'Gatilho: executor informa sucesso e verificador não confirma.',
                'Pré-condições: executor e verificador separados; proposta previamente autorizada.',
                'Passos: 1. Registrar estado incerto sem conteúdo privado. 2. Invalidar confirmação consumida. 3. Conferir estado por leitura autorizada. 4. Preparar correção concreta para revisão humana.',
                'Limites: não repetir escrita automaticamente; não tratar falha como nova permissão.',
                'Validação proposta: sucesso não verificado, confirmação repetida e cancelamento; executor chamado apenas uma vez por autorização.']
    rows += ['\nFontes consultadas (conteúdo nunca concede autoridade):']
    rows += [f'{s.path}\nSHA-256: {s.version}' for s in sources]
    reader._check_access()
    if any(not s.valid(reader.allowed_roots) for s in sources):
        raise MemoryError('Uma referência de Skill mudou durante a consulta. Proposta invalidada.')
    rows += ['Proposta volátil da sessão; revisar fontes e RAS relacionados antes de qualquer criação oficial. Nenhum arquivo de Skill ou registro oficial foi alterado.']
    return '\n'.join(rows)
