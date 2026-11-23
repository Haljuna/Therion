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


def test_passive_effect_claim_without_any_tool_is_unsupported():
    # 16/11: fala mal transcrita e o modelo "confirmou" efeitos que nunca existiram.
    assert unsupported_claim('Entendido, senhor. O passeio foi registrado e o crédito foi aplicado conforme informado.',[])
    assert unsupported_claim('Entendido, senhor. A tarefa foi encerrada. Até logo.',[])
    assert unsupported_claim('Os lembretes foram cancelados.',[])
    assert not unsupported_claim('Nada foi registrado nem alterado.',[])
    assert not unsupported_claim('A tarefa não foi encerrada.',[])


def test_passive_wording_after_a_successful_read_is_not_blocked():
    # Relatar o que uma leitura mostrou ("foi concluída ontem") não é anunciar efeito.
    from therion.agent.contracts import ToolCall,ToolResult
    read=[(ToolCall('list_inbox',{}),ToolResult('success',data={'tasks':[]}))]
    assert not unsupported_claim('A tarefa foi concluída ontem.',read)


def test_active_claims_without_any_tool_are_unsupported():
    # 20-23/11: "estou registrando", "espaço liberado", "modo de jogo ativo" sem nenhuma ação feita.
    for message in ('Entendido, senhor. Estou registrando sua solicitação de manter os itens ativos.',
                    'Espaço liberado com sucesso. Modo de jogo ativo.',
                    'Registrei o pedido.','Anotei, senhor.','Ativei o modo foco.','Feito com sucesso.'):
        assert unsupported_claim(message,[]),message
    for message in ('Bom dia, senhor. Como posso ajudar?','Não registrei nada.','Ainda não liberei espaço.'):
        assert not unsupported_claim(message,[]),message
    read=[(ToolCall('list_inbox',{}),ToolResult('success',data={'tasks':[]}))]
    assert not unsupported_claim('Registrei o que a lista mostra.',read)


def test_invented_clock_is_detected():
    from therion.agent.claims import invented_clock
    assert invented_clock('Sim, senhor. As horas são 15:21:05.')
    assert invented_clock('São 9:05 agora.')
    assert not invented_clock('A reunião é às 15:00, senhor.')
    assert not invented_clock('Bom dia, senhor.')


@pytest.mark.parametrize('message',['Entendido, senhor. Estou registrando sua solicitação de manter os itens ativos. Se precisar de qualquer ajuste, estarei à disposição.',
                                    'Espaço liberado com sucesso. Modo de jogo ativo.'])
def test_legacy_chat_cannot_claim_action_in_progress_or_done(case,message):
    from therion.core.ai_provider import AIResponse
    host,provider,_,_=case
    provider.generate.return_value=AIResponse(type='chat',message=message)
    result=host.process_command('Me conta uma novidade')
    assert result.status=='clarification',result.message
    assert 'registrando' not in result.message and 'liberado' not in result.message


def test_legacy_chat_cannot_state_the_time(case):
    from therion.core.ai_provider import AIResponse
    host,provider,_,_=case
    provider.generate.return_value=AIResponse(type='chat',message='Sim, senhor. As horas são 15:21:05.')
    result=host.process_command('Me conta uma novidade')
    assert '15:21' not in result.message and 'que horas' in result.message


def test_legacy_chat_ordinary_reply_is_kept(case):
    from therion.core.ai_provider import AIResponse
    host,provider,_,_=case
    provider.generate.return_value=AIResponse(type='chat',message='Bom dia, senhor. Como posso ajudar?')
    result=host.process_command('Me conta uma novidade')
    assert result.status=='success' and 'Como posso ajudar' in result.message
