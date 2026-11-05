"""Pedido composto em SDK fictício, sem contas ou efeitos pessoais."""
import asyncio
import pytest
from therion.agent import AgentDecision,ToolCall
from scripts.agent_workflow_fixture import run_personal_fixture
from tests.test_agent_runtime import ScriptedProvider


@pytest.mark.parametrize('repair_source',[False,True])
def test_read_email_prepare_task_reply_and_send_only_after_three_visual_reviews(tmp_path,repair_source):
    def call(name,**args):return AgentDecision('tools',calls=(ToolCall(name,args),))
    decisions=[call('gmail_search',query='Aurora'),call('gmail_thread',thread_id='t1'),
        call('gmail_prepare_draft',to='fixture@example.test',subject='Aurora',body='Vamos revisar Aurora.',draft_id='',source_thread_id='t1'),
        call('prepare_task',title='Revisar Aurora',source_id='gmail:t1',due=''),
        call('gmail_prepare_send',draft_id='draft1'),AgentDecision('final','Enviei a resposta e registrei a pendência revisada.')]
    if repair_source:decisions.insert(3,call('prepare_task',title='Revisar Aurora',source_id='t1',due=''))
    provider=ScriptedProvider(*decisions)
    data=asyncio.run(run_personal_fixture(tmp_path,provider));result=data['result']
    assert result.status=='completed',result
    assert data['approved']==3 and data['sent']==['draft1'] and len(data['tasks'])==1 and not data['errors']
    assert all(row['state']=='success' and row['verified'] for row in data['receipts'] if row['tool'] in {'gmail.save_draft','tasks.create','gmail.send_draft'})
