"""Rascunho fictício: coleta, perfil e prévia; nenhuma publicação pessoal."""
import pytest
from tests.test_gmail_explicit_queries import host
from tests.test_gmail_summary_offer import prepare
from therion.agent.gmail_queries import recent_mail_request,listed_mail_request
from therion.integrations.gmail import GmailAdapter,GmailSession
from unittest.mock import Mock


def test_spoken_variants_are_bounded():
    assert recent_mail_request('Lista dos e-mails mais recentes.')==('headers',3)
    assert listed_mail_request('Leiam o terceiro e-mail para mim.')==('summary',3)
    assert listed_mail_request('Não leiam o terceiro e-mail para mim.') is None


def test_unclear_reply_keeps_offer_without_guessing_yes(host):
    orch,client=prepare(host)
    orch.process_command('Lê meu último e-mail.')
    client.reset_mock()
    result=orch.process_command('See.')
    assert result.status=='clarification' and 'Diga sim ou não' in result.message
    assert orch._gmail_read_offer is not None
    client.thread.assert_not_called()
    assert orch.process_command('No.').status=='success'
    assert orch._gmail_read_offer is None
    client.thread.assert_not_called()


def test_draft_to_self_with_random_test_body_creates_only_proposal(host):
    orch,client=host
    client.profile.return_value={'email':'self@example.test'}
    first=orch.process_command('Escreve um rascunho pra mim.')
    assert first.status=='clarification' and 'Para quem' in first.message
    result=orch.process_command('Vai ser para eu mesmo, o assunto vai ser teste e eu gostaria que você escrevesse qualquer coisa aleatória no texto.')
    assert result.status=='awaiting_confirmation',result.message
    proposal=orch._agent_proposals.list()[0]
    assert proposal.operation=='gmail.save_draft'
    assert 'Salvar rascunho para self@example.test' in proposal.preview
    assert 'Assunto: teste' in proposal.preview
    assert 'mensagem de teste' in proposal.preview
    client.profile.assert_called_once_with()
    client.save_draft.assert_not_called();client.send_draft.assert_not_called()


def test_subject_and_recipient_survive_topic_reply(host):
    orch,client=host
    client.profile.return_value={'email':'self@example.test'}
    orch.process_command('Escreve um rascunho pra mim.')
    result=orch.process_command('Vai ser para eu mesmo, o assunto vai ser teste.')
    assert result.status=='clarification' and 'quer escrever' in result.message
    result=orch.process_command('Sim, fa sobre carnaval.')
    assert result.status=='awaiting_confirmation',result.message
    preview=orch._agent_proposals.list()[0].preview
    assert 'self@example.test' in preview and 'Assunto: teste' in preview
    assert 'carnaval' in preview
    client.save_draft.assert_not_called();client.send_draft.assert_not_called()


def test_explicit_recipient_does_not_need_account_profile(host):
    orch,client=host
    orch.process_command('Prepare um rascunho.')
    result=orch.process_command('Para fixture@example.test, assunto: teste, texto: Olá, equipe!')
    assert result.status=='awaiting_confirmation',result.message
    client.profile.assert_not_called()
    assert 'Olá, equipe!' in orch._agent_proposals.list()[0].preview


@pytest.mark.parametrize('change',['topic','session','expiry','revoke'])
def test_draft_collection_does_not_leak_to_other_contexts(host,change):
    orch,client=host
    orch.process_command('Prepare um rascunho.')
    if change=='topic':
        orch.process_command('Que horas são?')
        assert orch._gmail_draft_request is None
    else:
        if change=='session':orch._gmail_draft_request['session']='other'
        elif change=='expiry':orch._gmail_draft_request['deadline']=0
        else:orch._agent_config['gmail_enabled']=False
        assert orch.process_command('Para mim mesmo').status=='clarification'
        assert orch._gmail_draft_request is None
    client.save_draft.assert_not_called();client.send_draft.assert_not_called()


def test_no_cancels_draft_without_effect(host):
    orch,client=host
    orch.process_command('Prepare um rascunho.')
    assert 'Cancelei' in orch.process_command('No').message
    assert orch._gmail_draft_request is None
    client.profile.assert_not_called();client.save_draft.assert_not_called()


def test_profile_adapter_returns_only_verified_address():
    service=Mock();service.users.return_value.getProfile.return_value.execute.return_value={
        'emailAddress':'self@example.test','messagesTotal':900,'historyId':'private'}
    adapter=GmailAdapter(service)
    assert adapter.profile()=={'email':'self@example.test'}
    assert GmailSession._dispatch(adapter,'profile',{})=={'email':'self@example.test'}


def test_visual_approval_saves_one_draft_and_never_sends(host):
    import base64
    from email.message import EmailMessage
    from therion.agent import CancellationToken
    orch,client=host
    client.profile.return_value={'email':'self@example.test'}
    def save(data):
        assert data['to']=='self@example.test' and data['subject']=='teste'
        message=EmailMessage();message['To']=data['to'];message['Subject']=data['subject'];message.set_content(data['body'])
        client.draft.return_value={'message':{'raw':base64.urlsafe_b64encode(message.as_bytes()).decode()}}
        return {'id':'fixture-draft'}
    client.save_draft.side_effect=save
    orch.process_command('Prepare um rascunho.')
    orch.process_command('Para mim mesmo, assunto: teste, texto: Olá, equipe!')
    proposal=orch._agent_proposals.list()[0]
    client.save_draft.assert_not_called()
    result=orch._agent_proposals.approve_visual(proposal.id,proposal.digest,CancellationToken())
    assert result.status=='success'
    assert orch._agent_proposals.approve_visual(proposal.id,proposal.digest,CancellationToken()).status=='blocked'
    client.save_draft.assert_called_once()
    client.send_draft.assert_not_called()
