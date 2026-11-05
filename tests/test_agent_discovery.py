import asyncio
import inspect
import pytest
from therion.agent import CancellationToken,ToolCall,ToolResult,ToolSpec
from therion.agent.contracts import AgentError
from therion.agent.registry import ToolRegistry,object_schema


def registry():
    tools=ToolRegistry()
    for index in range(20):
        tools.register(ToolSpec('fixture_'+str(index),'Consulta técnica '+str(index)+' '+('Descrição '*40),object_schema(),
            lambda args,token:ToolResult('success'),authorize=lambda args:True))
    tools.enable_discovery({'fixture_0'});return tools


def invoke(tools,name,args):
    spec,blocked=tools.prepare(ToolCall(name,args));assert blocked is None
    result=spec.handler(args,CancellationToken())
    return asyncio.run(result) if inspect.isawaitable(result) else result


def test_tool_index_is_bounded_paged_and_queryable():
    tools=registry();first=invoke(tools,'tool_catalog',{}).data
    assert len(first['tools'])==6 and first['next_offset']==6 and first['partial']
    assert all(len(row['description'])<=200 for row in first['tools'])
    second=invoke(tools,'tool_catalog',{'offset':6}).data
    assert not {row['name'] for row in first['tools']} & {row['name'] for row in second['tools']}
    selected=invoke(tools,'tool_catalog',{'query':'fixture_19'}).data
    assert [row['name'] for row in selected['tools']]==['fixture_19']


def test_loading_new_group_evicts_extra_schemas_and_preserves_base():
    tools=registry();invoke(tools,'load_tools',{'names':['fixture_1','fixture_2']})
    invoke(tools,'load_tools',{'names':['fixture_3']})
    assert {'fixture_0','fixture_3'}<=tools.advertised and 'fixture_1' not in tools.advertised
    with pytest.raises(AgentError):tools.prepare(ToolCall('fixture_1',{}))
    invoke(tools,'load_tools',{'names':['fixture_1']})
    assert invoke(tools,'fixture_1',{}).status=='success'


def test_history_request_does_not_advertise_unrelated_notes_as_conversation_evidence():
    from therion.agent.registry import initial_tools
    assert initial_tools('Recupere no histórico a referência que decidimos para Aurora.')=={'search_history','search_session','search_memory'}
    assert {'procedure_index','procedure_read'}<=initial_tools('Consulte o procedimento ativo Aurora.')


def test_invalid_argument_feedback_identifies_tool_field_and_bounds_without_value():
    tools=ToolRegistry()
    tools.register(ToolSpec('page_read','Leitura paginada',object_schema(limit={'type':'integer','minimum':128,'maximum':6000}),
        lambda args,token:ToolResult('success'),authorize=lambda args:True))
    with pytest.raises(AgentError) as error:tools.prepare(ToolCall('page_read',{'limit':0}))
    assert 'page_read.arguments.limit' in str(error.value) and '[128, 6000]' in str(error.value)
    assert invoke(tools,'page_read',{'limit':6000}).status=='success'


def test_one_repair_feedback_includes_missing_and_unknown_fields_together():
    tools=ToolRegistry()
    tools.register(ToolSpec('thread_read','Leitura',object_schema(thread_id={'type':'string'}),lambda *args:ToolResult('success'),authorize=lambda args:True))
    with pytest.raises(AgentError) as error:tools.prepare(ToolCall('thread_read',{'id':'fictitious','limit':0}))
    assert 'thread_id' in str(error.value) and 'ausentes' in str(error.value) and 'desconhecidos' in str(error.value)
    assert 'fictitious' not in str(error.value)


@pytest.mark.parametrize('command',['Qual foi a referência da conversa anterior?','Na última conversa, qual referência escolhemos?','Recupere o que havia na sessão anterior.'])
def test_past_conversation_phrases_route_to_authorized_message_recovery(command):
    from therion.agent.registry import initial_tools
    assert initial_tools(command)=={'search_history','search_session','search_memory'}
