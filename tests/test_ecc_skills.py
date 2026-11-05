import asyncio
import copy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from therion.agent.contracts import AgentError, CancellationToken, Cancelled, ToolCall
from therion.agent.registry import ToolRegistry, initial_tools
from therion.skills import ecc
from therion.skills.registry import get_skill


@pytest.fixture
def library(tmp_path, monkeypatch):
    manifest = copy.deepcopy(ecc.MANIFEST)
    for name, metadata in manifest['skills'].items():
        for reference, entry in metadata['files'].items():
            path = tmp_path/name/entry['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = f'# {name} {reference}\nProcedimento fictício; nenhum script.\n'.encode()
            path.write_bytes(raw)
            entry['sha256'] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(ecc, 'MANIFEST', manifest)
    return ecc.EccSkill(tmp_path)


def invoke(registry, name, args, token=None):
    spec, blocked = registry.prepare(ToolCall(name, args))
    assert blocked is None
    return asyncio.run(spec.handler(args, token or CancellationToken()))


def test_static_registry_and_provenance(library):
    assert get_skill('ecc') is ecc.EccSkill
    assert len(library.catalog()) == 11
    assert all(row['available'] for row in library.catalog())
    row = library.read('ecc-planning')
    assert row['state'] == 'testing' and len(row['sha256']) == 64
    assert row['commit'] == ecc.MANIFEST['commit']
    assert row['repository'].lower().endswith('/worldflowai/everything-claude-code')
    assert library.read('ecc-backend-patterns', 'technical')['reference'] == 'technical'


@pytest.mark.parametrize('command', [
    'Use ECC para planejar', '$ecc-code-review', 'Everything Claude Code',
    'Planeje uma integração de software', 'Revise meu código Python',
    'Verifique o build', 'Corrija esse bug', 'Avalie agentes de IA',
    'Escreva testes unitários', 'Refatore o backend',
])
def test_technical_discovery(command):
    assert {'ecc_catalog', 'ecc_read'} <= initial_tools(command)


@pytest.mark.parametrize('command', [
    'oi', 'planejar meu dia', 'planeje meu dia', 'verifique minha agenda',
    'abra o Discord', 'verifique meus e-mails', 'pesquise na internet',
    'consulte o procedimento ativo Aurora', 'qual é meu nome?',
])
def test_personal_routes_unchanged(command):
    assert 'ecc_read' not in initial_tools(command)


def test_existing_specific_skill_routes():
    assert initial_tools('use Graphify') == {'graphify_skill', 'graphify_prepare_build', 'graphify_query'}
    assert initial_tools('auditoria de segurança') == {'cybersecurity_catalog', 'cybersecurity_read'}


@pytest.mark.parametrize('name', ['../secret', 'ecc-planning/../../secret', 'unknown'])
def test_arbitrary_paths_rejected(library, name):
    with pytest.raises(ValueError):
        library.read(name)


def test_unknown_reference_and_changed_file(library):
    with pytest.raises(ValueError, match='Referência'):
        library.read('ecc-planning', 'technical')
    path = library.root/'ecc-planning/SKILL.md'
    path.write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='alterado'):
        library.read('ecc-planning')
    assert not next(row for row in library.catalog() if row['id'] == 'ecc-planning')['available']


def test_missing_and_character_byte_bounds(library):
    path = library.root/'ecc-planning/SKILL.md'
    path.unlink()
    with pytest.raises(OSError):
        library.read('ecc-planning')
    for raw in (b'x'*(ecc.MAX_BYTES+1), ('á'*(ecc.MAX_CHARS+1)).encode()):
        path.write_bytes(raw)
        with pytest.raises(ValueError, match='limite'):
            library.read('ecc-planning')


def test_hardlink_rejected(library):
    path = library.root/'ecc-planning/SKILL.md'
    (library.root/'other').hardlink_to(path)
    with pytest.raises(ValueError, match='vínculos'):
        library.read('ecc-planning')


def test_redirected_ancestor_rejected(library, monkeypatch):
    original = Path.is_junction
    parent = library.root/'ecc-planning'
    monkeypatch.setattr(Path, 'is_junction', lambda path: path == parent or original(path))
    with pytest.raises(ValueError, match='Redirecionamento'):
        library.read('ecc-planning')


def test_tools_discovery_cancellation_and_no_execution(library, monkeypatch):
    monkeypatch.setattr(ecc, 'EccSkill', lambda: library)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('No execution allowed'))
    tools = ToolRegistry()
    ecc.register_ecc_tools(tools)
    tools.enable_discovery(initial_tools('oi'))
    with pytest.raises(AgentError):
        tools.prepare(ToolCall('ecc_read', {'name': 'ecc-planning'}))
    catalog = invoke(tools, 'tool_catalog', {'query': 'ecc'})
    assert {row['name'] for row in catalog.data['tools']} == {'ecc_catalog', 'ecc_read'}
    invoke(tools, 'load_tools', {'names': ['ecc_catalog', 'ecc_read']})
    assert len(invoke(tools, 'ecc_catalog', {}).data['skills']) == 11
    before = {p: p.read_bytes() for p in library.root.rglob('*') if p.is_file()}
    row = invoke(tools, 'ecc_read', {'name': 'ecc-planning'})
    assert row.status == 'success' and row.evidence[0]['version'] == row.data['sha256']
    assert 'não resultado' in row.message and row.side_effect_state != 'verified'
    assert before == {p: p.read_bytes() for p in before}
    token = CancellationToken()
    token.cancel()
    with pytest.raises(Cancelled):
        invoke(tools, 'ecc_read', {'name': 'ecc-planning'}, token)
    with pytest.raises(AgentError):
        tools.prepare(ToolCall('ecc_read', {'name': '../secret'}))
    (library.root/'ecc-planning/SKILL.md').unlink()
    assert invoke(tools, 'ecc_read', {'name': 'ecc-planning'}).status == 'unavailable'


def test_host_registers_tools_with_scripted_provider(case):
    from therion.agent import AgentDecision
    from tests.test_agent_runtime import ScriptedProvider
    host, _, _, _ = case
    host._agent_config['enabled'] = True
    provider = ScriptedProvider(
        AgentDecision('tools', calls=(ToolCall('ecc_catalog', {}),)),
        AgentDecision('final', 'Consultei o catálogo de procedimentos; nenhum teste foi executado.'),
    )
    host._agent_provider = provider
    result = host.process_command('Liste as skills ECC')
    assert result.status == 'success', result
    assert any('ecc-planning' in json.dumps(row, ensure_ascii=False, default=str) for row in provider.observations)


from tests.test_personal_context_flow import case


def test_host_read_revalidates_exact_source_and_hash(case, library, monkeypatch):
    from therion.agent import AgentDecision
    from tests.test_agent_runtime import ScriptedProvider
    host, _, _, _ = case
    monkeypatch.setattr(ecc, 'EccSkill', lambda:library)
    host._agent_config['enabled'] = True
    host._agent_provider = ScriptedProvider(
        AgentDecision('tools', calls=(ToolCall('ecc_read', {'name':'ecc-planning'}),)),
        AgentDecision('final', 'Procedimento consultado: ecc:ecc-planning:main. Nenhum teste foi executado.'),
    )
    result = host.process_command('Use ECC para planejar a implementação de software')
    assert result.status == 'success', result
    row=library.read('ecc-planning')
    proof={'id':'ecc:ecc-planning:main','source':row['source'],'version':row['sha256']}
    assert host._history_sources_allowed([proof])
    assert not host._history_sources_allowed([dict(proof,source=str(library.root/'secret'))])
    assert not host._history_sources_allowed([dict(proof,id='ecc:../../secret:main')])
    assert not host._history_sources_allowed([dict(proof,version='0'*64)])
    path=library.root/'ecc-planning/SKILL.md'
    path.write_text('changed',encoding='utf-8')
    assert not host._history_sources_allowed([proof])
