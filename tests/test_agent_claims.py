from therion.agent.claims import unsupported_claim
from therion.agent.contracts import ToolCall,ToolResult
from tests.test_personal_context_flow import case
import pytest


def proof(operation):
    return [(ToolCall('prepare',{}),ToolResult('success',side_effect_state='verified',evidence=({'id':'receipt:fixture','operation':operation},)))]


def test_negation_of_one_effect_does_not_hide_another_claim():
    assert unsupported_claim('Não salvei, mas enviei a mensagem.',[])
    assert not unsupported_claim('Não enviei a mensagem.',[])


def test_verified_draft_does_not_prove_delivery_or_archival():
    assert unsupported_claim('Enviei a mensagem.',proof('gmail.save_draft'))
    assert unsupported_claim('Arquivei a mensagem.',proof('gmail.save_draft'))
    assert not unsupported_claim('Salvei o rascunho.',proof('gmail.save_draft'))
    assert not unsupported_claim('Enviei a mensagem.',proof('gmail.send_draft'))


def test_passive_opening_and_closing_require_matching_receipts():
    for message in ('O Obsidian foi aberto conforme solicitado.','O Obsidian foi fechado conforme solicitado.','Fechei o Obsidian.'):
        assert unsupported_claim(message,[])
        assert unsupported_claim(message,proof('gmail.save_draft'))
    assert not unsupported_claim('Não foi fechado.',[])
    assert not unsupported_claim('O Obsidian foi aberto.',proof('apps.open'))
    assert not unsupported_claim('O Obsidian foi fechado.',proof('apps.close'))


@pytest.mark.parametrize('message',['O Obsidian foi fechado conforme solicitado.','O Obsidian foi aberto conforme solicitado.'])
def test_legacy_chat_cannot_publish_passive_effect_without_receipt(case,message):
    from therion.core.ai_provider import AIResponse
    host,provider,_,_=case
    provider.generate.return_value=AIResponse(type='chat',message=message)
    result=host.process_command('Me conta uma novidade')
    assert result.status=='clarification',result.message
    assert 'Não há execução verificada' in result.message
    assert 'foi aberto' not in result.message and 'foi fechado' not in result.message
