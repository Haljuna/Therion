"""Erros das conversas de 20 a 22/11/2026: cada teste reproduz um turno real que falhou."""
import pytest

import therion.core.pc_cleanup as pc_cleanup
from therion.agent.gmail_queries import recent_mail_request
from therion.core.local_reports import game_mode_request, report_request, vault_report
from therion.core.pc_cleanup import cleanup_then_game
from tests.test_agent_basic_questions import enable
from tests.test_personal_context_flow import case  # noqa: F401  (fixture)


@pytest.mark.parametrize('command', ['vai para o modo de jogo', 'vai pro modo jogo', 'bota no modo de jogo'])
def test_ir_para_o_modo_de_jogo_liga(command):
    assert game_mode_request(command) is True


def test_libera_espaco_e_vai_para_o_modo_de_jogo_faz_as_duas(case, monkeypatch):
    # 20/11 21:16: foi para a IA, que respondeu "Espaço liberado com sucesso" sem limpar nada.
    host, provider, _, _ = case
    agent = enable(host)
    monkeypatch.setattr(pc_cleanup, 'run', lambda: 'Limpei 1,0 GB.')
    result = host.process_command('libera espaço e vai para o modo de jogo')
    assert result.status == 'success' and result.message.startswith('Limpei 1,0 GB. Modo jogo ligado.'), result.message
    assert result.ui_action == 'game_mode' and result.ui_payload == {'on': True}
    assert provider.mock_calls == [] and not agent.observations


@pytest.mark.parametrize('command', ['libera espaço e vai pro mercado', 'abre o jogo e vai para o modo de jogo'])
def test_frase_dupla_so_quando_as_duas_partes_sao_conhecidas(command):
    assert cleanup_then_game(command) is None


@pytest.mark.parametrize('command,expected', [
    ('lista meu anti penultimo email', ('peek', 3)),       # 20/11 21:15: virou pergunta de volta
    ('lista meu antepenúltimo e-mail', ('peek', 3)),
    ('mostra meu penúltimo e-mail', ('peek', 2)),
])
def test_lista_o_penultimo_email_mostra_o_cabecalho(command, expected):
    assert recent_mail_request(command) == expected


def test_como_esta_o_segundo_cerebro_nao_vai_para_a_ia(tmp_path):
    # 20/11 21:13: a IA inventou "modo de espera, último acesso há 3 dias".
    assert report_request('como está o segundo cérebro?', projects={}) == ('vault',)
    entrada = tmp_path / '00 - Entrada'
    (entrada / 'Anexos para organizar').mkdir(parents=True)
    (entrada / 'Entrada.md').write_text('índice', encoding='utf-8')
    (entrada / 'nota solta.md').write_text('x', encoding='utf-8')
    (entrada / 'Anexos para organizar' / 'foto.png').write_bytes(b'x')
    assert vault_report(tmp_path) == 'No Segundo Cérebro, a Entrada tem 2 itens esperando organização.'
    (entrada / 'nota solta.md').unlink(); (entrada / 'Anexos para organizar' / 'foto.png').unlink()
    assert vault_report(tmp_path) == 'No Segundo Cérebro, a Entrada está vazia: nada esperando organização.'
    assert vault_report(tmp_path / 'nao existe') == 'Não encontrei a pasta do Segundo Cérebro.'


def test_falha_das_rotinas_guarda_o_traceback_no_pc(tmp_path):
    # 21/11: "Suspendi as rotinas por falha de estado (TypeError)" e nenhum registro da causa.
    from therion.interface.desktop import log_autonomy_error
    path = tmp_path / 'logs' / 'autonomia-erros.txt'
    try:
        len(None)
    except TypeError as error:
        log_autonomy_error(error, path)
    text = path.read_text(encoding='utf-8')
    assert 'TypeError' in text and 'test_falha_das_rotinas' in text
    path.write_text('x' * 30000, encoding='utf-8')
    log_autonomy_error(ValueError('y'), path)
    assert len(path.read_text(encoding='utf-8')) < 21000   # o arquivo não cresce sem fim


def test_oferta_vencida_nao_desliga_o_filtro_da_fala_de_fundo():
    import time
    from types import SimpleNamespace
    from therion.interface.desktop import MainWindow
    def voz(pendentes):
        return SimpleNamespace(_voice_pipeline=SimpleNamespace(last_confidence=-0.6), _conversation_awaiting_response=False,
                               _last_conversation_spoken='', _orchestrator=SimpleNamespace(confirmation_id=None,
                               _conversation_frame=SimpleNamespace(question=None), _pendings=lambda: pendentes))
    agora = time.monotonic()
    assert MainWindow._background_speech(voz([agora - 1, None, (agora - 1, 'pick', ())]), 'Boa logo!')
    assert not MainWindow._background_speech(voz([None, (agora + 60, 'pick', ())]), 'Boa logo!')
