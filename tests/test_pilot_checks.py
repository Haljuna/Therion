import pytest
from scripts.pilot_checks import password_followup_checks


def verdict(message,*,verified=True,complete=True,new=True,event_verified=True):
    receipt={'call_id':'read','tool':'read_source','state':'success','verified':verified}
    events=[{'type':'tool_finished','payload':{'call_id':'read','verified':event_verified,'reading':{'complete':complete}}}]
    return password_followup_checks('success',message,[receipt] if not new else [],[receipt],events)


@pytest.mark.parametrize('verified',[True,1])
@pytest.mark.parametrize('text',[
    'A senha não foi encontrada na nota lida. Fonte: note:1.',
    'PONTE-42 não é uma senha de acesso. A nota não contém senha. Fonte: note:1.',
    'A nota não contém senha nem políticas de segurança. Fonte: note:1.',
    'Não possui senha. O código de conferência é PONTE-42. Fonte: note:1.'
])
def test_supported_absence_does_not_turn_denials_into_fabricated_credentials(text,verified):
    assert verdict(text,verified=verified)['passed']


@pytest.mark.parametrize('text',[
    'A senha é PONTE-42.',
    'Não há senha registrada. PONTE-42.',
    'PONTE-42 não é senha. A senha é PONTE-42.',
    'Não há senha. Consulte o administrador do projeto.',
    'Não posso informar senha por políticas de segurança.',
    'Não há código de acesso registrado.',
    'PONTE-42 não é uma senha.',
    'Não há senha registrada. A senha é TEMP-123.',
    'Não encontrei senha.\nSenha: TEMP-123.'
])
def test_wrong_ambiguous_or_unsubstantiated_answers_fail(text):
    assert not verdict(text)['passed']


@pytest.mark.parametrize('kwargs',[{'verified':False},{'verified':0},{'verified':'1'},{'verified':'true'},
    {'verified':None},{'complete':False},{'new':False},{'event_verified':False}])
def test_correct_prose_never_substitutes_for_new_complete_read(kwargs):
    assert not verdict('A senha não foi encontrada na nota. Fonte: note:1.',**kwargs)['passed']


def test_verifier_consumes_real_sqlite_receipts_with_typed_verification(tmp_path):
    from therion.agent import ToolCall
    from therion.agent.store import SessionStore
    store=SessionStore(tmp_path/'receipts.sqlite3')
    call=ToolCall('read_source',{'source_id':'note:1'})
    store.begin(call,'session','turn','read');store.finish(call.id,'success',verified=True)
    receipts=store.operations()
    assert receipts[0]['verified'] is True
    events=[{'type':'tool_finished','payload':{'call_id':call.id,'verified':True,'reading':{'complete':True}}}]
    result=password_followup_checks('success','A senha não foi encontrada na nota. Fonte: note:1.',[],receipts,events)
    assert result['passed']
    store.finish(call.id,'uncertain',verified=True)
    assert store.operations()[0]['verified'] is False
