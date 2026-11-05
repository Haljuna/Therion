"""Pedidos cotidianos de Gmail em caixa fictícia, sem modelo ou conta real."""
import asyncio
from unittest.mock import Mock

import pytest

from therion.agent.gmail_queries import recent_mail_request,RecentMailProvider,GmailQueryContext
from therion.agent import AgentRuntime,TurnBudget
from therion.core.orchestrator import Orchestrator


@pytest.mark.parametrize('command,expected',[
    ('Liste os assuntos dos meus três e meios mais recentes.',('headers',3)),
    ('Lista dos assuntos dos meus três e meios mais recentes.',('headers',3)),
    ('Liste os assuntos dos meus três e-mails mais recentes.',('headers',3)),
    ('Qual foi o meu último e-mail?',('summary',1)),
    ('Lê meu último e-mail.',('summary',1)),
    ('Leu o meu último e-mail.',('summary',1)),
    ('Leia o meu último e-mail.',('summary',1)),
    ('Leia o meu último e-mail completo.',('body',1)),
    ('Não leia meu último e-mail.',None),
    ('Envie meu último e-mail.',None),
    ('Liste os assuntos dos meus três e-mails mais recentes e apague.',None),
    ('Três e meios de pagamento.',None),
    ('Liste os assuntos dos meus dez e-mails mais recentes.',None),
])
def test_bounded_request_recognition(command,expected):
    assert recent_mail_request(command)==expected


@pytest.fixture
def host(tmp_path):
    client=Mock()
    client.search.return_value={'messages':[{'id':f'm{i}','threadId':f't{i}'} for i in range(1,4)]}
    client.metadata.side_effect=lambda identifier:{'id':identifier,'internalDate':'1792512000000',
        'payload':{'headers':[{'name':'Subject','value':'Assunto '+identifier}]}}
    client.thread.return_value={'id':'t1','version':'version','url':'https://mail.google.com/#all/t1',
        'messages':[{'id':'m0','text':'OUTRA MENSAGEM PRIVADA','attachments':[]},
                    {'id':'m1','text':'TEXTO ORIGINAL AURORA. '*700,'attachments':[]}]}
    orch=Orchestrator(simulate=True,vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),
        agent_config={'enabled':True,'gmail_enabled':True,'context_tokens':5120,'output_tokens':4352},
        agent_state_root=tmp_path/'agent')
    orch._gmail_adapter_factory=lambda mode:client
    yield orch,client
    orch.close()


@pytest.mark.parametrize('command',[
    'Liste os assuntos dos meus três e-mails mais recentes.',
    'Liste os assuntos dos meus três e meios mais recentes.',
])
def test_real_host_uses_first_page_without_model(host,command):
    orch,client=host
    result=orch.process_command(command)
    assert result.status=='success',result.message
    assert 'Assunto m1' in result.message
    client.search.assert_called_once_with('in:inbox')
    client.thread.assert_not_called()
    assert isinstance(orch._agent_runtime.provider,RecentMailProvider)


def test_read_latest_message_paginates_and_excludes_other_messages(host):
    orch,client=host
    result=orch.process_command('Leia meu último e-mail completo.')
    assert result.status=='success',result.message
    assert result.message.count('TEXTO ORIGINAL AURORA.')==700
    assert 'OUTRA MENSAGEM PRIVADA' not in result.message
    client.search.assert_called_once_with('in:inbox')
    assert client.thread.call_count>1
    client.send_draft.assert_not_called()


def test_gmail_failure_is_not_claimed_as_empty(host):
    orch,client=host
    client.search.side_effect=OSError('fixture unavailable')
    result=orch.process_command('Qual foi o meu último e-mail?')
    assert result.status!='success'
    assert 'caixa vazia' not in result.message
    client.metadata.assert_not_called()


def test_no_result_does_not_fetch_message(host):
    orch,client=host
    client.search.return_value={'messages':[]}
    result=orch.process_command('Qual foi o meu último e-mail?')
    assert 'não retornou mensagens' in result.message
    client.metadata.assert_not_called()


def test_revoked_gmail_prevents_body_read(host):
    orch,client=host
    original=client.metadata.side_effect
    def revoke(identifier):
        data=original(identifier)
        orch._agent_config['gmail_enabled']=False
        return data
    client.metadata.side_effect=revoke
    result=orch.process_command('Leia meu último e-mail completo.')
    assert result.status!='success'
    client.thread.assert_not_called()


def test_changed_thread_is_not_combined_across_pages(host):
    orch,client=host
    original=client.thread.return_value
    calls=[]
    def changed(identifier):
        calls.append(identifier)
        return dict(original,version='version' if len(calls)==1 else 'changed')
    client.thread.side_effect=changed
    result=orch.process_command('Leia meu último e-mail completo.')
    assert result.status!='success'
    assert 'mudou durante a leitura' in result.message
    assert 'TEXTO ORIGINAL AURORA' not in result.message
