"""O runtime não deve ocultar o perfil nem ampliar seu acesso."""
import pytest
from tests.test_personal_context_flow import case
from tests.test_agent_runtime import ScriptedProvider


@pytest.mark.parametrize('command',['Leia meu perfil.','Faça um resumo sobre mim.','Quem sou eu?'])
def test_personal_questions_use_existing_authorized_resolver(case,command):
    host,provider,_,profile=case
    host._agent_config['enabled']=True
    agent=ScriptedProvider();host._agent_provider=agent
    original=profile.read_bytes()
    result=host.process_command(command)
    assert result.status=='success',result.message
    assert 'Engenharia Biomédica' in result.message and '01 - Pessoal/Perfil.md' in result.message
    assert profile.read_bytes()==original
    assert not agent.observations
    assert provider.describe_result.call_args.args[1]['kind']=='personal_context'


def test_personal_question_cannot_restore_revoked_profile_access(case):
    host,provider,_,_=case
    host._agent_config['enabled']=True
    host._agent_provider=ScriptedProvider()
    host.process_command('Quem sou eu?')
    provider.describe_result.reset_mock()
    host.second_brain.allowed_roots=[]
    result=host.process_command('Quem sou eu?')
    assert 'Engenharia Biomédica' not in result.message
    provider.describe_result.assert_not_called()
