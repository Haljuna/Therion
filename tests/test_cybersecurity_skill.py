import asyncio
from pathlib import Path
import pytest
from therion.skills.cybersecurity import CybersecuritySkill, SKILL_IDS, register_cybersecurity_tools
from therion.agent.registry import ToolRegistry, initial_tools
from therion.agent.contracts import CancellationToken, ToolCall, Cancelled
from therion.skills.registry import get_skill


def test_discovery_only_for_security_requests():
    assert get_skill('cybersecurity') is CybersecuritySkill
    for command in ('use a skill de cibersegurança', 'cybersecurity no Therion', 'auditoria de segurança'):
        assert 'cybersecurity_read' in initial_tools(command)
    assert 'cybersecurity_read' not in initial_tools('oi')


def test_read_and_evidence_without_execution(tmp_path):
    folder=tmp_path/SKILL_IDS[0];folder.mkdir()
    path=folder/'SKILL.md';path.write_text('# Example\nDo not run scripts.',encoding='utf-8')
    result=CybersecuritySkill(tmp_path).read(SKILL_IDS[0])
    assert 'Do not run' in result['instructions'] and len(result['sha256'])==64
    path.write_text('changed',encoding='utf-8')
    assert result['sha256']!=CybersecuritySkill(tmp_path).read(SKILL_IDS[0])['sha256']


@pytest.mark.parametrize('name', ['../secret', '../../secret', 'uninstalled'])
def test_no_arbitrary_file_access(tmp_path,name):
    with pytest.raises(ValueError):CybersecuritySkill(tmp_path).read(name)


def test_oversized_and_hardlinked_playbooks_rejected(tmp_path):
    folder=tmp_path/SKILL_IDS[0];folder.mkdir();path=folder/'SKILL.md'
    path.write_bytes(b'x'*100001)
    with pytest.raises(ValueError,match='limite'):CybersecuritySkill(tmp_path).read(SKILL_IDS[0])
    path.write_text('small');(folder/'link').hardlink_to(path)
    with pytest.raises(ValueError,match='vínculos'):CybersecuritySkill(tmp_path).read(SKILL_IDS[0])


def test_missing_and_cancelled_reads(tmp_path,monkeypatch):
    import therion.skills.cybersecurity as module
    monkeypatch.setattr(module,'CybersecuritySkill',lambda:CybersecuritySkill(tmp_path))
    registry=ToolRegistry();register_cybersecurity_tools(registry)
    spec,blocked=registry.prepare(ToolCall('cybersecurity_read',{'name':SKILL_IDS[0]}))
    assert blocked is None
    assert asyncio.run(spec.handler({'name':SKILL_IDS[0]},CancellationToken())).status=='unavailable'
    token=CancellationToken();token.cancel()
    with pytest.raises(Cancelled):asyncio.run(spec.handler({'name':SKILL_IDS[0]},token))
