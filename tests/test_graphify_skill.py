import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from therion.skills.graphify import GraphifySkill, register_graphify_tools
from therion.skills.registry import get_skill
from therion.agent.registry import ToolRegistry, initial_tools
from therion.agent.contracts import CancellationToken, ToolCall, Cancelled
from therion.agent.proposals import ActionProposals
from therion.agent.store import SessionStore


def fixture(tmp_path):
    root=tmp_path/'app'
    (root/'therion').mkdir(parents=True)
    (root/'therion'/'sample.py').write_text('def greet(): return "hello"')
    (root/'therion'/'secret.md').write_text('private note')
    (root/'tmp').mkdir()
    (root/'tmp'/'hidden.py').write_text('password = "excluded"')
    return GraphifySkill(root, tmp_path/'graphify')


def test_registry_and_explicit_discovery():
    assert get_skill('graphify') is GraphifySkill
    assert 'graphify_query' in initial_tools('use Graphify no Therion')
    assert 'graphify_query' not in initial_tools('oi')


def test_only_code_and_versions(tmp_path):
    skill=fixture(tmp_path)
    assert list(skill.sources())==['therion/sample.py']
    version=skill.version()
    (skill.root/'therion'/'sample.py').write_text('def changed(): pass')
    assert skill.version()!=version


def test_no_graph_is_not_empty_result(tmp_path):
    skill=fixture(tmp_path)
    assert skill.query('greet',CancellationToken()).status=='unavailable'


def test_build_revalidates_before_execution(tmp_path):
    skill=fixture(tmp_path)
    with pytest.raises(ValueError,match='mudou'):
        skill.build('wrong',CancellationToken())
    assert not (skill.home/'graphs').exists()


def test_snapshot_and_stale_graph(tmp_path,monkeypatch):
    skill=fixture(tmp_path)
    commands=[]
    def run(args, token, cwd):
        commands.append(args)
        if args[0]=='extract':
            assert list(cwd.rglob('*.md'))==[]
            assert (cwd/'therion'/'sample.py').is_file()
            out=Path(args[-1])/'graphify-out'
            out.mkdir()
            (out/'graph.json').write_text('{}')
        return 'found greet'
    monkeypatch.setattr(skill,'run',run)
    result=skill.build(skill.version(),CancellationToken())
    assert Path(result['graph']).is_file()
    assert '--code-only' in commands[0]
    assert skill.query('greet',CancellationToken()).status=='success'
    (skill.root/'therion'/'sample.py').write_text('def new(): pass')
    assert skill.query('greet',CancellationToken()).status=='unavailable'
    assert len(commands)==2


def test_cancel_does_not_publish(tmp_path,monkeypatch):
    skill=fixture(tmp_path)
    token=CancellationToken();token.cancel()
    with pytest.raises(Cancelled):skill.build(skill.version(),token)
    assert not (skill.home/'therion-current.json').exists()


def test_no_execution_without_graphify_request(tmp_path,monkeypatch):
    import therion.skills.graphify as module
    skill=fixture(tmp_path)
    monkeypatch.setattr(module,'GraphifySkill',lambda:skill)
    registry=ToolRegistry()
    register_graphify_tools(registry,SimpleNamespace(),requested=False)
    names={s['function']['name'] for s in registry.schemas()}
    assert 'graphify_skill' in names
    assert 'graphify_prepare_build' not in names


def test_visual_confirmation_is_required(tmp_path,monkeypatch):
    import therion.skills.graphify as module
    skill=fixture(tmp_path)
    monkeypatch.setattr(skill,'available',lambda:True)
    monkeypatch.setattr(module,'GraphifySkill',lambda:skill)
    calls=[]
    def build(version, token):
        calls.append(version)
        graph=tmp_path/'confirmed.json';graph.write_text('{}')
        return {'graph':str(graph)}
    monkeypatch.setattr(skill,'build',build)
    proposals=ActionProposals(SessionStore(tmp_path/'history.sqlite3'),lambda:'one')
    registry=ToolRegistry()
    register_graphify_tools(registry,SimpleNamespace(_agent_proposals=proposals),requested=True)
    spec, blocked=registry.prepare(ToolCall('graphify_prepare_build',{}))
    assert blocked is None
    result=asyncio.run(spec.handler({},CancellationToken()))
    assert result.status=='awaiting_confirmation' and calls==[]
    row=next(row for row in proposals.list() if row.id==result.data['proposal_id'])
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='success'
    assert len(calls)==1
    assert proposals.approve_visual(row.id,row.digest,CancellationToken()).status=='blocked' 
