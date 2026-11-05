"""Resumo e continuação de leitura com e-mail fictício, sem inferência real."""
from unittest.mock import Mock
import pytest
from therion.agent import AgentDecision
from tests.test_gmail_explicit_queries import host


class SummaryProvider:
    def __init__(self):self.messages=[]
    async def decide(self,messages,tools,budget,*args):
        assert not tools and budget.output_tokens<=512
        self.messages.append(messages)
        return AgentDecision('final','É um boletim sobre o projeto Aurora e a entrega do relatório até sexta-feira.')


def prepare(host):
    orch,client=host
    client.thread.return_value['messages']=[{'id':'m1','text':'Boletim: o projeto Aurora exige entregar o relatório até sexta-feira. Créditos: equipe fictícia.','attachments':[]}]
    orch._gmail_summary_provider=SummaryProvider()
    return orch,client


@pytest.mark.parametrize('command',['Lê meu último e-mail.','Leu o meu último e-mail.','Qual foi o meu último e-mail?'])
def test_default_interprets_then_offers_reading(host,command):
    orch,client=prepare(host)
    result=orch.process_command(command)
    assert result.status=='success',result.message
    assert 'boletim sobre o projeto Aurora' in result.message
    assert 'Quer que eu leia o e-mail para você?' in result.message
    assert 'Créditos:' not in result.message
    assert orch._gmail_read_offer['message_id']=='m1'
    assert len(orch._gmail_summary_provider.messages)==1
    assert 'sexta-feira' in str(orch._gmail_summary_provider.messages)


def test_yes_reads_offered_email_even_when_newer_email_arrives(host):
    orch,client=prepare(host)
    assert orch.process_command('Lê meu último e-mail.').status=='success'
    client.search.return_value['messages'].insert(0,{'id':'new','threadId':'new-thread'})
    result=orch.process_command('Sim')
    assert result.status=='success',result.message
    assert 'Créditos: equipe fictícia' in result.message
    assert 'Quer que eu leia' not in result.message
    assert client.metadata.call_args.args==('m1',)
    assert orch._gmail_read_offer is None


def test_no_does_not_query_mail_again(host):
    orch,client=prepare(host)
    orch.process_command('Lê meu último e-mail.')
    client.reset_mock()
    assert 'Não vou ler' in orch.process_command('Não').message
    client.search.assert_not_called()
    assert orch._gmail_read_offer is None


def test_other_topic_and_session_end_clear_offer(host):
    orch,client=prepare(host)
    orch.process_command('Lê meu último e-mail.')
    orch.process_command('Que horas são?')
    assert orch._gmail_read_offer is None
    orch.process_command('Lê meu último e-mail.')
    orch.close_agent()
    assert orch._gmail_read_offer is None


def test_changed_email_cannot_be_read_under_old_offer(host):
    orch,client=prepare(host)
    orch.process_command('Lê meu último e-mail.')
    client.thread.return_value['version']='changed'
    result=orch.process_command('Pode ler')
    assert result.status!='success' and 'mudou durante a leitura' in result.message


def test_expired_offer_does_not_read_mail(host):
    orch,client=prepare(host)
    orch.process_command('Lê meu último e-mail.')
    orch._gmail_read_offer['deadline']=0
    client.reset_mock()
    orch.process_command('Sim')
    client.search.assert_not_called()


def test_summary_failure_does_not_dump_email(host):
    orch,client=prepare(host)
    class Failed:
        async def decide(self,*args):raise OSError('fixture offline')
    orch._gmail_summary_provider=Failed()
    result=orch.process_command('Lê meu último e-mail.')
    assert 'Não consegui concluir a interpretação' in result.message
    assert 'Quer que eu leia' in result.message
    assert 'Créditos:' not in result.message
