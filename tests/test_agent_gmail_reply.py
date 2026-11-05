import base64
from email import policy
from email.parser import BytesParser
from unittest.mock import Mock
import pytest
from therion.integrations.gmail import GmailAdapter,reply_metadata
from therion.agent.contracts import ToolCall
from therion.agent.store import SessionStore


def test_reply_preserves_thread_and_rfc_headers_without_sending():
    thread={'id':'t1','messages':[{'headers':{'subject':'Aurora','message-id':'<latest@example.test>','references':'<old@example.test>'}}]}
    service=Mock();adapter=GmailAdapter(service)
    adapter.save_draft({'to':'fixture@example.test','subject':'Aurora','body':'Resposta fictícia','_reply':reply_metadata(thread,'Aurora')})
    data=service.users.return_value.drafts.return_value.create.call_args.kwargs['body']['message']
    message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(data['raw']))
    assert data['threadId']=='t1' and message['In-Reply-To']=='<latest@example.test>'
    assert message['References']=='<old@example.test> <latest@example.test>'
    service.users.return_value.drafts.return_value.send.assert_not_called()


@pytest.mark.parametrize('headers',[
    {'subject':'Outro','message-id':'<a@example.test>'},
    {'subject':'Aurora','message-id':'a@example.test\r\nBcc: outro@example.test'},
    {'subject':'Aurora'},
])
def test_ambiguous_reply_is_blocked(headers):
    with pytest.raises(ValueError):reply_metadata({'id':'t1','messages':[{'headers':headers}]},'Aurora')


def test_uncertain_send_cannot_be_retried_with_another_draft_id(tmp_path):
    store=SessionStore(tmp_path/'state.sqlite3')
    first=ToolCall('gmail.send_draft',{'draft_id':'one','_account':'account','content_identity':'reviewed-content'})
    store.begin(first,'session','turn','external');store.finish(first.id,'uncertain')
    with pytest.raises(ValueError,match='incerta'):
        store.begin(ToolCall('gmail.send_draft',dict(first.arguments,draft_id='two')),'session','turn','external')
    # Outra conta não herda este resultado incerto.
    store.begin(ToolCall('gmail.send_draft',dict(first.arguments,_account='another')),'session','turn','external')
