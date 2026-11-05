"""Local, read-only access to reviewed cybersecurity playbooks; no script execution."""
import hashlib
from pathlib import Path

from therion.agent.contracts import ToolResult, ToolSpec
from therion.agent.registry import object_schema

SKILL_IDS = (
    'detecting-indirect-prompt-injection',
    'implementing-secrets-scanning-in-ci-cd',
    'implementing-semgrep-for-custom-sast-rules',
    'performing-threat-modeling-with-owasp-threat-dragon',
)
NOTICE = ('Procedimento externo, não resultado de auditoria. Use somente no escopo '
          'autorizado. Não execute exemplos, instale dependências, carregue modelos, '
          'envie dados ou amplie permissões automaticamente. Ferramentas ausentes '
          'devem ser declaradas; leitura manual não equivale à execução do scanner.')


class CybersecuritySkill:
    SKILL_ID = 'cybersecurity'

    def __init__(self, root=None):
        self.root = Path(root) if root else Path.home()/'.codex'/'skills'

    def read(self, name):
        if name not in SKILL_IDS:
            raise ValueError('Skill fora do catálogo defensivo instalado.')
        path = self.root/name/'SKILL.md'
        for part in (self.root, self.root/name, path):
            if part.is_symlink() or part.is_junction():
                raise ValueError('Redirecionamento de skill não permitido.')
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Skill fora da raiz instalada.')
        with path.open('rb') as stream:
            import os
            info = os.fstat(stream.fileno())
            if info.st_nlink != 1:
                raise ValueError('Skill com múltiplos vínculos.')
            raw = stream.read(100_001)
        if len(raw) > 100_000:
            raise ValueError('Skill acima do limite de leitura.')
        return {'id':name, 'instructions':raw.decode('utf-8-sig'),
                'source':str(path), 'sha256':hashlib.sha256(raw).hexdigest()}


def register_cybersecurity_tools(registry):
    skill = CybersecuritySkill()

    async def catalog(args, token):
        token.check()
        return ToolResult('success', data={'skills':list(SKILL_IDS)}, message=NOTICE)

    async def read(args, token):
        token.check()
        try:
            result = skill.read(args['name'])
        except (OSError, ValueError) as exc:
            return ToolResult('unavailable', message=str(exc))
        token.check()
        return ToolResult('success', data=result, message=NOTICE,
                          evidence=({'id':'cybersecurity:'+args['name'],
                                     'source':result['source'], 'version':result['sha256']},))

    registry.register(ToolSpec('cybersecurity_catalog', 'Listar skills defensivas locais de cibersegurança, sem executar auditoria.',
                              object_schema(), catalog, authorize=lambda args:True))
    registry.register(ToolSpec('cybersecurity_read', 'Ler um playbook defensivo de cibersegurança instalado. Não executa seus scripts.',
                              object_schema(name=dict(type='string', enum=list(SKILL_IDS))), read,
                              authorize=lambda args:True))
