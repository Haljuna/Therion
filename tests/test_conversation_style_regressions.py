"""Regressões observadas na conversa falada de 23/10."""
import asyncio

import pytest

from therion.agent.context import ContextBuilder
from therion.agent.contracts import AgentDecision
from therion.agent.registry import ToolRegistry, initial_tools
from therion.agent.runtime import AgentRuntime, TurnBudget
from therion.context.response_style import normalize_model_greeting
from tests.test_gmail_explicit_queries import host


@pytest.mark.parametrize('command,model_reply,expected', [
    ('Fala até aí.', 'Bom dia, senhor. Como posso ajudar?', 'Olá, senhor. Como posso ajudar?'),
    ('Boa noite.', 'Bom dia, senhor. Estou aqui.', 'Boa noite, senhor. Estou aqui.'),
    ('Etérion, o que é a verdade pra você?', 'Bom dia, senhor.\n\nA verdade exige exame.', 'A verdade exige exame.'),
    ('Tem mais alguma coisa desse assunto?', 'Boa tarde, senhor. Há outras perspectivas.', 'Há outras perspectivas.'),
    # 03/11: "Olá, senhor." abria toda resposta, mesmo sem saudação do usuário.
    ('Banuichi', 'Olá, senhor. Pode me informar o que deseja saber?', 'Pode me informar o que deseja saber?'),
    ('Nessas últimas semanas, a internet parou.', 'Olá, senhor. Isso é um fato recente?', 'Isso é um fato recente?'),
    ('Oi Therion', 'Olá, senhor! Em que posso ajudar?', 'Olá, senhor. Em que posso ajudar?'),
    ('Boa noite', 'Olá, senhor. Estou aqui.', 'Boa noite, senhor. Estou aqui.'),
])
def test_generated_reply_does_not_invent_or_repeat_time_greeting(command, model_reply, expected):
    assert normalize_model_greeting(command, model_reply) == expected


def test_quoted_story_greeting_is_not_edited():
    quoted='"Bom dia, senhor", disse o personagem.'
    assert normalize_model_greeting('Me conta uma história.', quoted) == quoted


def test_simple_story_fits_small_agent_context_without_unrelated_tools():
    registry=ToolRegistry()
    registry.enable_discovery(initial_tools('Me conta uma história.'))
    seen=[]

    class StoryProvider:
        async def decide(self,rows,schemas,budget,*args):
            seen.append((rows,schemas,budget))
            assert ContextBuilder().estimate(rows,schemas)+budget.output_tokens<=budget.context_tokens
            return AgentDecision('final','Era uma vez um viajante que encontrou uma biblioteca.')

    result=asyncio.run(AgentRuntime(StoryProvider(),registry).run(
        'Me conta uma história.',session_id='historia-ficticia',
        budget=TurnBudget(context_tokens=5120,output_tokens=4352),
        history=[{'role':'user','content':'O que você pode fazer?'},
                 {'role':'assistant','content':'Posso consultar notas autorizadas, agenda e aplicativos. '*45}]))
    assert result.status=='completed',result.message
    assert len(seen)==1
    assert all(row['function']['name'] not in {'calendar_day','prepare_existing_action'}
               for row in seen[0][1])


def test_email_capability_answer_uses_configuration_without_reading_mail(host):
    orch,client=host
    result=orch.process_command('Você consegue acessar meu e meio?')
    assert result.status=='success'
    assert 'Gmail está habilitado' in result.message
    assert 'senhor' in result.message
    client.search.assert_not_called()
    client.thread.assert_not_called()


def test_agent_host_removes_stray_greeting_before_display_and_speech(host):
    orch,_=host

    class ChatProvider:
        async def decide(self,rows,schemas,budget,*args):
            return AgentDecision('final','Bom dia, senhor. A verdade exige exame.')

    orch._agent_provider=ChatProvider()
    result=orch.process_command('Etérion, o que é a verdade pra você?')
    assert result.status=='success',result.message
    assert result.message=='A verdade exige exame.'
    assert result.speech_message=='A verdade exige exame.'


def test_search_topic_followup_advertises_web_tools(host):
    orch,_=host
    orch._agent_config['web_enabled']=True
    seen=[]

    class SearchProvider:
        async def decide(self,rows,schemas,budget,*args):
            seen.extend(row['function']['name'] for row in schemas)
            return AgentDecision('final','Posso examinar fontes sobre a verdade.')

    orch._agent_provider=SearchProvider()
    orch.memory.add_turn('therion','Qual assunto deseja pesquisar?')
    orch._agent_waiting_for_answer=True
    result=orch.process_command('Sobre o que é a verdade.')
    assert result.status=='success',result.message
    assert 'web_search' in seen
