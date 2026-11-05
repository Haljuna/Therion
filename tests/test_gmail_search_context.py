"""Transcrito de 22/10: buscas, recebimento, anterior e conteúdo citado."""
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from therion.agent.claims import unsupported_claim
from therion.agent.contracts import ToolCall,ToolResult
from therion.agent.gmail_searches import filtered_mail_request
from tests.test_gmail_explicit_queries import host
from tests.test_gmail_summary_offer import SummaryProvider


def prepare(host):
    orch,client=host
    orch._calendar_now=lambda:datetime(2026,10,22,1,30,tzinfo=ZoneInfo('America/Sao_Paulo'))
    orch._gmail_summary_provider=SummaryProvider()
    def metadata(identifier):
        return {'id':identifier,'internalDate':str(int(datetime(2026,10,21,23,30,tzinfo=ZoneInfo('America/Sao_Paulo')).timestamp()*1000)),
            'payload':{'headers':[{'name':'Subject','value':'Assunto '+identifier},
                                  {'name':'Date','value':'Mon, 01 Jan 2001 00:00:00 +0000'}]}}
    client.metadata.side_effect=metadata
    client.thread.side_effect=lambda identifier:{'id':identifier,'version':'v-'+identifier,
        'url':'https://mail.google.com/#all/'+identifier,'messages':[{
            'id':'m'+identifier[1:],'text':'Foi enviado um aviso. Eu enviei os documentos. A inscrição foi aberta.','attachments':[]}]}
    return orch,client


@pytest.mark.parametrize('command,day',[
    ('Lista os e-mails que eu recebi ontem.',21),
    ('Lista meus e-mails de hoje.',22),
    ('Liste os e-mails de ontem.',21),
])
def test_dates_become_epoch_filters_in_brasilia_not_search_terms(host,command,day):
    orch,client=prepare(host)
    result=orch.process_command(command)
    assert result.status=='success',result.message
    query=client.search.call_args.args[0]
    start=datetime(2026,10,day,tzinfo=ZoneInfo('America/Sao_Paulo'))
    assert f'after:{int(start.timestamp())}' in query
    assert 'hoje' not in query and 'ontem' not in query and 'onter' not in query
    assert f'{day:02}/10/2026' in result.message
    client.thread.assert_not_called()


def test_topic_search_and_scoped_empty_result(host):
    orch,client=prepare(host)
    result=orch.process_command('Tem algum e meio falando de prova.')
    assert result.status=='success',result.message
    client.search.assert_called_once_with('in:inbox "prova"')
    client.search.return_value={'messages':[]}
    result=orch.process_command('Tem algum e-mail falando de prova?')
    assert 'sobre prova' in result.message and 'não retornou mensagens' in result.message


def test_received_date_is_from_internal_date_not_body_or_date_header(host):
    orch,client=prepare(host)
    result=orch.process_command('Que dia eu recebi meu último e-mail?')
    assert result.status=='success',result.message
    assert '21/10/2026 às 23:30' in result.message and '2001' not in result.message
    client.thread.assert_not_called()


def test_received_followup_preserves_selected_mail_after_new_arrival(host):
    orch,client=prepare(host)
    orch.process_command('Qual foi o meu penúltimo e-mail?')
    client.search.return_value['messages'].insert(0,{'id':'new','threadId':'new-thread'})
    client.reset_mock()
    result=orch.process_command('Que dia eu recebi esse meio?')
    assert result.status=='success',result.message
    client.metadata.assert_called_once_with('m2')
    client.thread.assert_not_called()
    assert '21/10/2026' in result.message


def test_previous_is_relative_to_snapshot_not_new_inbox_positions(host):
    orch,client=prepare(host)
    orch.process_command('Qual foi o meu penúltimo e-mail?')
    orch.process_command('No.')
    client.search.return_value['messages'].insert(0,{'id':'new','threadId':'new-thread'})
    client.reset_mock()
    result=orch.process_command('E meio anterior.')
    assert result.status=='success',result.message
    client.metadata.assert_called_once_with('m3')
    client.thread.assert_called_once_with('t3')


def test_yes_reads_quoted_email_without_turning_its_words_into_effect_claims(host):
    orch,client=prepare(host)
    orch.process_command('Qual foi meu último e-mail?')
    result=orch.process_command('Sim.')
    assert result.status=='success',result.message
    assert 'Eu enviei os documentos' in result.message
    assert '> ' in result.message
    assert '> ' not in result.speech_message
    client.send_draft.assert_not_called()


def test_message_and_thread_ids_do_not_mix_body_or_source_references(host):
    orch,client=prepare(host)
    client.search.return_value={'messages':[{'id':'m1','threadId':'t1'},{'id':'new-message','threadId':'old-thread'}]}
    client.thread.side_effect=lambda identifier:{'id':identifier,'version':'v','url':'https://mail.google.com/#all/old-thread',
        'messages':[{'id':'old-message','text':'CONTEUDO DE OUTRA MENSAGEM','attachments':[]},
                    {'id':'new-message','text':'CONTEUDO CORRETO','attachments':[]}]}
    result=orch.process_command('Qual meu penúltimo e-mail?')
    assert result.status=='success',result.message
    assert 'gmail:new-message' in result.message
    assert 'gmail:old-thread' not in result.message
    assert 'OUTRA MENSAGEM' not in str(orch._gmail_summary_provider.messages)
    assert 'CONTEUDO CORRETO' in str(orch._gmail_summary_provider.messages)


def test_invalid_internal_date_is_not_guessed_from_old_header(host):
    orch,client=prepare(host)
    client.metadata.side_effect=lambda identifier:{'id':identifier,'payload':{'headers':[{'name':'Date','value':'2001'}]}}
    result=orch.process_command('Que dia eu recebi meu último e-mail?')
    assert result.status!='success' and 'Não confirmei a data' in result.message


def test_unknown_mail_query_clarifies_instead_of_inventing_absence(host):
    orch,client=prepare(host)
    result=orch.process_command('Lista os meus e-mails da semana passada.')
    assert result.status=='clarification'
    client.search.assert_not_called()


def test_quote_exemption_requires_verified_current_source_and_exact_text():
    call=ToolCall('gmail_thread',{'thread_id':'t'})
    result=ToolResult('success',data={'id':'t','version':'v','messages':[{'id':'m','text':'Eu enviei o formulário.'}]},
        evidence=({'id':'gmail:m','source':'Gmail','version':'v'},))
    assert not unsupported_claim('> Eu enviei o formulário.',[(call,result)])
    assert unsupported_claim('Enviei o formulário.',[(call,result)])
    assert unsupported_claim('> Eu enviei dinheiro.',[(call,result)])
    assert unsupported_claim('> Eu enviei o formulário.',[])
    assert unsupported_claim('> Eu enviei o formulário.\nEnviei outro e-mail.',[(call,result)])


@pytest.mark.parametrize('command',['Lista, meus emis.','Lista, meus e meus.'])
def test_ambiguous_transcription_never_claims_memory_or_mail_is_empty(host,command):
    orch,client=prepare(host)
    result=orch.process_command(command)
    assert result.status=='clarification' and 'Você quis dizer' in result.message
    client.search.assert_not_called()


def test_whole_reported_conversation_stays_in_verified_mail_flow(host):
    orch,client=prepare(host)
    commands=[
        'Qual foi meu último e-mail?','Sim.',
        'Tem algum e meio falando de prova.',
        'Qual foi meu penúltimo e-mail?','E meio anterior.',
        'Lista os e-mails que eu recebi ontem.',
        'Lista Meus e-mail.','Lista meus e-mails de hoje.',
        'Qual foi meu último e-mail?','Que dia eu recebi esse meio?',
        'Que dia eu recebi meu último e-mail?',
    ]
    for command in commands:
        result=orch.process_command(command)
        assert result.status=='success',(command,result.message)
        assert 'orçamento' not in result.message and 'recibo verificado' not in result.message
    client.send_draft.assert_not_called();client.save_draft.assert_not_called()
