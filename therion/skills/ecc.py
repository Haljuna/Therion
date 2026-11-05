"""Static, read-only access to the reviewed ECC adaptations; no upstream execution."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from therion.agent.contracts import ToolResult, ToolSpec
from therion.agent.registry import object_schema


MANIFEST = json.loads(Path(__file__).with_name('ecc_manifest.json').read_text(encoding='utf-8'))
SKILL_IDS = tuple(MANIFEST['skills'])
MAX_CHARS = 6000
MAX_BYTES = MAX_CHARS * 4
NOTICE = ('Procedimento revisado em teste supervisionado, não resultado de execução. '
          'Use apenas capacidades e escopo autorizados; confirme efeitos pelas evidências '
          'e recibos existentes. Não executa scripts, instala dependências, carrega modelos '
          'ou grava memória. Para aprendizado, requer pedido humano explícito.')


def explicit_ecc_request(text):
    return bool(re.search(r'\b(?:ecc|everything claude code)\b', text))


def technical_ecc_request(text):
    """Only technical intent; daily planning and personal verification retain their routes."""
    if explicit_ecc_request(text):
        return True
    technical = re.search(r'\b(?:codigo|software|programacao|api|apis|backend|frontend|react|nextjs|'
                          r'typescript|javascript|python|build|bug|bugs|refatoracao|tdd|'
                          r'testes? (?:unitarios|de integracao)|agentes? de ia)\b', text)
    activity = re.search(r'\b(?:planej\w*|implement\w*|revis\w*|verifi\w*|corrij\w*|'
                         r'corrig\w*|refator\w*|test\w*|aval\w*|anal\w*|desenvolv\w*)\b', text)
    return bool(technical and activity)


class EccSkill:
    SKILL_ID = 'ecc'

    def __init__(self, root=None):
        self.root = Path(root) if root is not None else Path.home()/'.codex'/'skills'

    def read(self, name, reference='main'):
        if name not in SKILL_IDS:
            raise ValueError('Procedimento fora do catálogo ECC revisado.')
        metadata = MANIFEST['skills'][name]
        if reference not in metadata['files']:
            raise ValueError('Referência não cadastrada para este procedimento.')
        entry = metadata['files'][reference]
        path = self.root/name/entry['path']
        # Validate every ancestor as well as the leaf; no arbitrary paths or dynamic discovery.
        for part in (path, *path.parents):
            if part.is_symlink() or part.is_junction():
                raise ValueError('Redirecionamento de procedimento não permitido.')
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Procedimento fora da raiz instalada.')
        before = path.stat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError('Procedimento deve ser arquivo regular sem múltiplos vínculos.')
        if before.st_size > MAX_BYTES:
            raise ValueError('Procedimento acima do limite de leitura.')
        with path.open('rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)):
                raise ValueError('Procedimento mudou durante a leitura.')
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Procedimento acima do limite de leitura.')
        instructions = raw.decode('utf-8')
        if len(instructions) > MAX_CHARS:
            raise ValueError('Procedimento acima do limite de caracteres.')
        digest = hashlib.sha256(raw).hexdigest()
        if digest != entry['sha256']:
            raise ValueError('Procedimento alterado desde a revisão; integração ECC requer revisão manual.')
        return {'id': name, 'reference': reference, 'instructions': instructions,
                'source': str(path), 'sha256': digest, 'repository': MANIFEST['repository'],
                'commit': MANIFEST['commit'], 'state': 'testing',
                'invocation': metadata['invocation']}

    def catalog(self):
        rows = []
        for name, metadata in MANIFEST['skills'].items():
            try:
                self.read(name)
                available = True
            except (OSError, ValueError):
                available = False
            rows.append({'id': name, 'title': metadata['title'], 'trigger': metadata['trigger'],
                         'invocation': metadata['invocation'], 'available': available,
                         'references': list(metadata['files'])})
        return rows


def register_ecc_tools(registry):
    skill = EccSkill()

    async def catalog(args, token):
        token.check()
        rows = skill.catalog()
        token.check()
        return ToolResult('success', data={'skills': rows, 'commit': MANIFEST['commit']}, message=NOTICE)

    async def read(args, token):
        token.check()
        try:
            result = skill.read(args['name'], args.get('reference', 'main'))
        except (OSError, ValueError) as exc:
            return ToolResult('unavailable', message=str(exc))
        token.check()
        return ToolResult('success', data=result, message=NOTICE,
                          evidence=({'id': 'ecc:'+result['id']+':'+result['reference'],
                                     'source': result['source'], 'version': result['sha256']},))

    registry.register(ToolSpec('ecc_catalog', 'Listar procedimentos ECC revisados: planejamento técnico, revisão, testes, verificação e gatilhos. Não executa procedimentos.',
                              object_schema(), catalog, authorize=lambda args: True))
    schema = object_schema(name=dict(type='string', enum=list(SKILL_IDS)))
    schema['properties']['reference'] = dict(type='string', enum=['main', 'technical'])
    registry.register(ToolSpec('ecc_read', 'Ler um procedimento ECC pelo ID do catálogo ou sua referência técnica. Leitura não é execução nem teste. Aprendizado somente por pedido humano explícito.',
                              schema, read, authorize=lambda args: True))
