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


def _conversa(texto_ate_a_fala, *, confianca=-0.06, pendentes=(), modo=True, aberta_em=100.0, captura_em=105.0):
    from types import SimpleNamespace
    pipeline = SimpleNamespace(last_confidence=confianca, speech_started_after=texto_ate_a_fala)
    return SimpleNamespace(_voice_pipeline=pipeline, _conversation_awaiting_response=False, _last_conversation_spoken='',
                           _conversation_mode=modo, _conversation_heard_at=aberta_em, _conversation_capture_started_at=captura_em,
                           _orchestrator=SimpleNamespace(confirmation_id=None, _conversation_frame=SimpleNamespace(question=None),
                                                         _pendings=lambda: list(pendentes)))


def test_conversa_aberta_so_responde_ao_nome_ou_ate_8_s_depois_da_resposta():
    # 22/11, escolha A: "amanhã vai chover lá em casa..." veio da sala com confiança -0,06 e foi respondida.
    import time
    from therion.interface.desktop import MainWindow
    fundo = MainWindow._background_speech
    frase = 'Ah, eu acho que amanhã vai chover lá em casa, sabe?'
    assert not fundo(_conversa(2.0), frase)                     # começou a falar 7 s depois: ainda é com ele
    assert fundo(_conversa(4.0), frase)                         # 9 s depois, sem o nome: conversa de fundo
    assert fundo(_conversa(40.0), 'libera espaço')              # nem regra fixa passa fora da janela
    assert not fundo(_conversa(40.0), 'Therion, libera espaço')  # com o nome, sempre
    assert not fundo(_conversa(40.0, pendentes=[time.monotonic() + 60]), 'sim')   # resposta a uma oferta viva
    assert not fundo(_conversa(40.0, modo=False), frase)        # fora da conversa (tecla): fala clara é pedido


def test_sem_medida_do_inicio_da_fala_a_janela_nao_ignora():
    from therion.interface.desktop import MainWindow
    assert not MainWindow._background_speech(_conversa(None), 'Ah, eu acho que amanhã vai chover lá em casa, sabe?')


def test_captura_diz_quando_a_fala_comecou():
    import numpy as np
    from therion.voice.capture import AudioCaptureService
    from tests.test_voice_capture import FakeInputStream
    streams = []
    def factory(**kwargs):
        streams.append(FakeInputStream(**kwargs)); return streams[-1]
    voz = iter([False, False, True, True, True])
    service = AudioCaptureService(stream_factory=factory, activity_factory=lambda: (lambda s: next(voz, False)))
    service.start(automatic=True)
    assert service.speech_started_after is None
    for _ in range(5):
        streams[0].feed(1280, 0.0)
    assert abs(service.speech_started_after - 0.16) < 1e-6   # dois blocos de 80 ms antes da voz
    service.stop()
    assert abs(service.speech_started_after - 0.16) < 1e-6   # continua valendo para quem trata o texto depois
