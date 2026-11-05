"""Ordem da caixa e seleção de lista são relações distintas e verificadas."""
import pytest
from tests.test_gmail_explicit_queries import host
from tests.test_gmail_summary_offer import SummaryProvider
from therion.agent.gmail_queries import recent_mail_request,listed_mail_request


def prepare(host):
    orch,client=host
    orch._gmail_summary_provider=SummaryProvider()
    client.thread.side_effect=lambda identifier:{'id':identifier,'version':'version-'+identifier,
        'url':'https://mail.google.com/#all/'+identifier,'messages':[{
            'id':'m'+identifier[1:],'text':'Conteúdo exclusivo '+identifier,'attachments':[]}]}
    return orch,client


@pytest.mark.parametrize('command,expected',[
    ('Qual o meu penúltimo e-mail?',('summary',2)),
    ('Lê meu antepenúltimo e-mail.',('summary',3)),
    ('Leia meu penúltimo e-mail completo.',('body',2)),
    ('Qual meus últimos três e meios?',('headers',3)),
    ('Quais são os meus últimos 3 e-mails?',('headers',3)),
    ('Mostre meus últimos dois e-mails.',('headers',2)),
    ('Não leia meu penúltimo e-mail.',None),
    ('Leia meu penúltimo e-mail e envie uma resposta.',None),
])
def test_recent_variants(command,expected):
    assert recent_mail_request(command)==expected


@pytest.mark.parametrize('command,expected',[
    ('Leu o terceiro e-mail pra mim.',('summary',3)),
    ('Leia o segundo.',('summary',2)),
    ('Leia o terceiro e-mail completo.',('body',3)),
    ('Não leia o terceiro e-mail.',None),
    ('Leia o terceiro e-mail e apague.',None),
])
def test_list_variants(command,expected):
    assert listed_mail_request(command)==expected


def test_penultimate_reads_second_message_without_page_argument(host):
    orch,client=prepare(host)
    result=orch.process_command('Qual o meu penúltimo e-mail?')
    assert result.status=='success',result.message
    client.search.assert_called_once_with('in:inbox')
    client.metadata.assert_called_once_with('m2')
    client.thread.assert_called_once_with('t2')
    assert orch._gmail_read_offer['message_id']=='m2'


def test_short_spoken_list_uses_headers_only(host):
    orch,client=prepare(host)
    result=orch.process_command('Qual meus últimos três e meios?')
    assert result.status=='success',result.message
    assert 'Assunto m3' in result.message
    client.thread.assert_not_called()
    assert len(orch._gmail_list_context['messages'])==3


def test_third_refers_to_listed_message_despite_new_mail(host):
    orch,client=prepare(host)
    orch.process_command('Liste os assuntos dos meus três e-mails mais recentes.')
    client.search.return_value['messages'].insert(0,{'id':'new','threadId':'new-thread'})
    client.reset_mock()
    result=orch.process_command('Leu o terceiro e-mail pra mim.')
    assert result.status=='success',result.message
    client.metadata.assert_called_once_with('m3')
    client.thread.assert_called_once_with('t3')
    assert orch._gmail_read_offer['message_id']=='m3'
    assert 'Quer que eu leia' in result.message


def test_yes_after_third_reads_that_message_completely(host):
    orch,client=prepare(host)
    orch.process_command('Liste os assuntos dos meus três e-mails mais recentes.')
    orch.process_command('Leu o terceiro e-mail pra mim.')
    result=orch.process_command('Sim')
    assert result.status=='success' and 'Conteúdo exclusivo t3' in result.message
    assert 'Conteúdo exclusivo t1' not in result.message


@pytest.mark.parametrize('invalidate',['topic','expired','session','revoked'])
def test_list_is_not_reused_outside_scope(host,invalidate):
    orch,client=prepare(host)
    orch.process_command('Liste os assuntos dos meus três e-mails mais recentes.')
    if invalidate=='topic':orch.process_command('Que horas são?')
    elif invalidate=='expired':orch._gmail_list_context['deadline']=0
    elif invalidate=='session':orch._gmail_list_context['session']='other'
    else:orch._agent_config['gmail_enabled']=False
    client.reset_mock()
    result=orch.process_command('Leia o terceiro e-mail.')
    assert result.status in {'clarification','forbidden'}
    client.search.assert_not_called()


def test_missing_rank_or_list_position_never_selects_first_email(host):
    orch,client=prepare(host)
    client.search.return_value['messages']=[{'id':'m1','threadId':'t1'}]
    result=orch.process_command('Qual meu penúltimo e-mail?')
    assert 'nessa posição' in result.message
    client.metadata.assert_not_called()
    orch.process_command('Liste os assuntos dos meus três e-mails mais recentes.')
    client.reset_mock()
    assert orch.process_command('Leia o terceiro e-mail.').status=='clarification'
    client.search.assert_not_called()


def test_invalid_ordinal_discards_previous_read_offer(host):
    orch,client=prepare(host)
    orch.process_command('Liste os assuntos dos meus dois e-mails mais recentes.')
    orch.process_command('Leia o primeiro e-mail.')
    assert orch._gmail_read_offer is not None
    assert orch.process_command('Leia o terceiro e-mail.').status=='clarification'
    assert orch._gmail_read_offer is None
    client.reset_mock()
    orch.process_command('Sim')
    client.search.assert_not_called()
