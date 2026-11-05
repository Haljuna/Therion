"""Política explícita do host para leitura ampla e memória supervisionada.

Este contrato não ativa configurações pessoais. Valores inválidos não concedem
acesso; o destino de memória é sempre a área canônica de RAS do cofre fornecido.
"""
from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from therion.memory.knowledge import MemoryPolicy, MemoryError, RAS_ROOT, safe_path


@dataclass(frozen=True)
class KnowledgeAccess:
    read_roots: tuple[str, ...]
    memory_policy: MemoryPolicy
    authorized: bool
    reason: str


def access_from_config(config, vault_root, now):
    """Lê somente knowledge_access; nunca interpreta uma nota como autorização."""
    vault = str(Path(vault_root).resolve())
    roots = (str(Path(vault)/'90 - Sistema da IA'), str(Path(vault)/'10 - Projetos'/'Therion'))
    disabled = KnowledgeAccess(roots, MemoryPolicy(read_roots=roots), False,
        'Acesso padrão; leitura ampla e gravação supervisionada não foram autorizadas.')
    values = config.get('knowledge_access') if isinstance(config, dict) else None
    if not isinstance(values, dict):
        return disabled
    required = {'read_all', 'supervised_memory', 'authorization', 'expires_at', 'revision'}
    if set(values) != required:
        return disabled
    if type(values['read_all']) is not bool or type(values['supervised_memory']) is not bool:
        return disabled
    if (not isinstance(values['authorization'], str) or not values['authorization'].strip()
            or len(values['authorization']) > 200 or type(values['revision']) is not int
            or values['revision'] < 1 or not isinstance(values['expires_at'], str)):
        return disabled
    try:
        expiry = datetime.fromisoformat(values['expires_at'])
        if expiry.tzinfo is None or now.tzinfo is None or expiry <= now:
            return disabled
        safe_path(vault, (vault,))
        destination = str(safe_path(Path(vault)/RAS_ROOT, (vault,)))
    except (ValueError, OSError, TypeError):
        return disabled
    roots = (vault,) if values['read_all'] else roots
    policy = MemoryPolicy(mode='authorized' if values['supervised_memory'] else 'preview',
        read_roots=roots, write_root=destination if values['supervised_memory'] else '',
        authorization=values['authorization'], expires_at=expiry, revision=values['revision'])
    return KnowledgeAccess(roots, policy, True,
        'Leitura seletiva autorizada; qualquer gravação depende de confirmação específica.')


class KnowledgeRuntime:
    """O host fornece a configuração atual; conteúdo do cofre não a modifica."""
    def __init__(self, vault_root, state_root, config_loader, clock=None, config_writer=None):
        self.vault_root = str(Path(vault_root).absolute())
        self.state_root = str(Path(state_root).absolute())
        self.config_loader = config_loader
        self.config_writer = config_writer
        self.custom_clock = clock is not None
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.snapshot = None

    def access(self):
        try:
            config = self.config_loader()
        except (OSError, ValueError, TypeError):
            config = {}
        return access_from_config(config, self.vault_root, self.clock())

    def guard(self):
        if self.snapshot is None or self.access() != self.snapshot:
            raise MemoryError('Política de conhecimento mudou ou venceu; repita a consulta no escopo atual.')

    def install(self, orchestrator):
        from therion.memory.repository import MarkdownMemoryRepository
        from therion.memory.supervised import MemoryEvidenceStore
        access = self.access()
        self.snapshot = access
        orchestrator.second_brain.allowed_roots = list(access.read_roots)
        orchestrator.second_brain.access_guard = self.guard
        orchestrator.knowledge.policy = access.memory_policy
        if self.custom_clock:
            orchestrator.knowledge.clock = self.clock
        orchestrator._knowledge_read_roots = access.read_roots
        repository = evidence = None
        if access.memory_policy.allows_write(self.clock()):
            repository = MarkdownMemoryRepository(access.memory_policy.write_root,
                policy_provider=lambda: self.access().memory_policy)
            evidence = MemoryEvidenceStore(Path(self.state_root)/'evidence')
        orchestrator._knowledge_repository = repository
        orchestrator._supervised_memory.repository = repository
        orchestrator._supervised_memory.evidence = evidence

    def synchronize(self, orchestrator):
        if self.access() != self.snapshot:
            # Conteúdo já lido não pode sobreviver silenciosamente à revogação.
            orchestrator.clear_session()
            self.install(orchestrator)
            orchestrator._knowledge_policy_epoch += 1

    def revoke(self, read_all=False):
        if self.config_writer is None:
            raise MemoryError('A configuração deste host não permite registrar revogação persistente.')
        config = deepcopy(self.config_loader())
        access = config.get('knowledge_access') if isinstance(config, dict) else None
        if not isinstance(access, dict):
            raise MemoryError('Não há política persistente de conhecimento neste host.')
        access['supervised_memory'] = False
        if read_all:
            access['read_all'] = False
        revision = access.get('revision', 0)
        access['revision'] = revision + 1 if type(revision) is int else 1
        try:
            self.config_writer(config)
            # Não tratar fallback de leitura como prova de persistência.
            fresh = self.config_loader()
            current = fresh.get('knowledge_access') if isinstance(fresh, dict) else None
            if (not isinstance(current, dict) or current != access
                    or current.get('supervised_memory') is not False
                    or (read_all and current.get('read_all') is not False)):
                raise ValueError('Configuração não confirmada.')
        except (OSError, ValueError, TypeError) as error:
            raise MemoryError('Não confirmei a revogação persistente. Verifique a configuração antes de continuar.') from error
