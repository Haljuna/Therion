"""Erros da conversa de 24/11/2026: cada teste reproduz um turno real que falhou."""
import pytest

import therion.core.pc_cleanup as pc_cleanup
from therion.agent.claims import invented_clock
from therion.context.conversation_frame import current_date_request, current_time_request
from therion.core.focus import focus_request
from therion.core.local_reports import game_mode_request
from tests.test_agent_basic_questions import enable
from tests.test_personal_context_flow import case  # noqa: F401  (fixture)


@pytest.mark.parametrize('command', ['E que dia é hoje?', 'Hoje é que dia?', 'Em que dia estamos?', 'que dia é hoje', 'Qual a data de hoje?'])
def test_que_dia_e_hoje_e_do_app(command):
    # 16:07: "E que dia é hoje?" foi para a IA, que respondeu "05 de abril de 2025".
    assert current_date_request(command)


def test_e_que_horas_sao_tambem():
    assert current_time_request('E que horas são?')


def test_data_inventada_pela_ia_nao_passa():
    assert invented_clock('Hoje é 05 de abril de 2025.')
    assert invented_clock('Hoje é dia 5/4.')
    assert not invented_clock('Hoje é um bom dia para estudar.')


@pytest.mark.parametrize('command', [
    'Abre o modo de jogo', 'abrir modo de jogo', 'pode ligar o modo de jogo pra mim', 'quero o modo de jogo',
    'deixa no modo de jogo', 'coloca o pc em modo de jogo', 'faz funcionar o modo de jogo', 'manda o modo game',
    'ativar modo de jogo agora'])
def test_qualquer_jeito_de_ligar_o_modo_de_jogo(command):
    # 16:13: "Abre o modo de jogo" foi tratado como abrir um aplicativo.
    assert game_mode_request(command) is True


@pytest.mark.parametrize('command,expected', [
    ('fecha o modo de jogo', False), ('para o modo de jogo', False), ('termina o modo de jogo', False),
    ('o que é o modo de jogo', None), ('como funciona o modo de jogo', None), ('não abre o modo de jogo', None),
    ('o modo de jogo está ligado?', None)])
def test_desligar_ou_perguntar_nao_liga(command, expected):
    assert game_mode_request(command) is expected


def test_libera_espaco_e_abre_o_modo_de_jogo(case, monkeypatch):
    # 16:12: a IA respondeu "Operação não autorizada".
    host, provider, _, _ = case
    agent = enable(host)
    monkeypatch.setattr(pc_cleanup, 'run', lambda: 'Limpei 1,0 GB.')
    result = host.process_command('Libera espaço e abre o modo de jogo')
    assert result.message.startswith('Limpei 1,0 GB. Modo jogo ligado.'), result.message
    assert result.ui_action == 'game_mode' and provider.mock_calls == [] and not agent.observations


def test_abre_o_modo_de_jogo_nao_vai_para_o_catalogo(case):
    host, provider, _, _ = case
    agent = enable(host)
    result = host.process_command('Abre o modo de jogo')
    assert result.ui_action == 'game_mode' and result.ui_payload == {'on': True}, result.message
    assert provider.mock_calls == [] and not agent.observations


@pytest.mark.parametrize('command', ['Foco em estudos', 'modo foco nos estudos', 'ativa o foco em matemática'])
def test_foco_em_um_assunto_liga_o_foco(command):
    # 16:12: "Foco em estudos" foi para a IA ("Foco estabelecido: estudos") e o foco não ligou.
    assert focus_request(command) == ('start', None)


def test_foco_com_duracao_continua_igual():
    assert focus_request('foco em 30 minutos') == ('start', 30)
    assert focus_request('foco em') == ('ask_duration',)


@pytest.mark.parametrize('command', ['Fecha o modo de jogo', 'fechar modo de jogo', 'pode desligar o modo de jogo', 'apaga o modo de jogo'])
def test_fechar_o_modo_de_jogo_desliga(command):
    # 16:36: "Fecha o modo de jogo" virou "fechar aplicativo".
    from therion.context.conversation_frame import app_close_request
    assert game_mode_request(command) is False and app_close_request(command) is None


def test_fecha_o_modo_de_jogo_desliga_de_verdade(case):
    host, provider, _, _ = case
    enable(host)
    result = host.process_command('Fecha o modo de jogo')
    assert result.ui_action == 'game_mode' and result.ui_payload == {'on': False}, result.message


@pytest.mark.parametrize('command,expected', [
    ('30 minutos de foco', ('start', 30)), ('meia hora de foco', ('start', 30)), ('abre o modo foco', ('start', None)),
    ('fecha o foco', ('stop',)), ('fecha o modo foco', ('stop',))])
def test_foco_abre_fecha_e_duracao_antes(command, expected):
    # 16:40: "30 minutos de foco" foi para a IA, que fingiu ligar o foco.
    assert focus_request(command) == expected


def test_ia_nao_finge_ligar_o_foco():
    from therion.agent.claims import unsupported_claim
    assert unsupported_claim('Foco de 30 minutos, até as 17h00. Seguro meus avisos até lá.', [])


@pytest.mark.parametrize('command,minutes', [
    ('3 minutos de foco', 3), ('um minuto de foco', 1), ('quero 20 minutos de foco', 20), ('me dá 10 minutos de foco', 10),
    ('coloca 10 minutos de foco', 10), ('faz 25 minutos de foco', 25), ('liga 5 minutos de foco', 5)])
def test_qualquer_tempo_de_foco(command, minutes):
    # 24/11: ele quer o tempo que pedir, inclusive menos de 5 minutos.
    assert focus_request(command) == ('start', minutes)


def test_foco_de_3_minutos_liga(tmp_path, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    import therion.core.focus as focus
    monkeypatch.setattr(focus, '_shared', focus.FocusStore(tmp_path / 'foco.json'))
    text, payload = focus.answer('3 minutos de foco', SimpleNamespace(desktop_timers=True), datetime(2026, 11, 24, 17, 0))
    assert payload['minutes'] == 3 and text.startswith('Foco de 3 minutos'), text


@pytest.mark.parametrize('command', ['Encerro o modo de julgo', 'desligo o modo de jogo', 'saio do modo de jogo'])
def test_encerrar_ouvido_torto_desliga(command):
    # 17:21: Whisper ouviu "Encerro o modo de julgo"; foi para a IA, que disse "Modo de jogo desligado" sem desligar.
    assert game_mode_request(command) is False


def test_ia_nao_finge_mudar_o_modo_de_jogo():
    from therion.agent.claims import unsupported_claim
    assert unsupported_claim('Modo de jogo desligado. A placa de vídeo foi desligada.', [])
    assert unsupported_claim('Modo jogo ligado.', [])


@pytest.mark.parametrize('command', ['encerro o modo de jogo', 'desligo o modo de julgo', 'cancelo o modo de jogo', 'apago o modo de jogo'])
def test_verbo_de_desligar_nunca_liga(command):
    assert game_mode_request(command) is not True
