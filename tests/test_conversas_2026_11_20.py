"""Erros das conversas de 16 a 20/11/2026: cada teste reproduz um turno real que falhou."""
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
import threading
import time

from therion.agent.contracts import CancellationToken
from therion.agent.mailbox import mail_count_request, unread_count
from therion.autonomy.apps import ApplicationCatalog
from therion.core.voice_reminders import parse_reminder
from therion.interface.desktop import MainWindow
from therion.interface.pc_watch import PcWatch
from tests.test_agent_basic_questions import enable
from tests.test_pc_watch import Clock, pc
from tests.test_personal_context_flow import case  # noqa: F401  (fixture)


def test_repete_devolve_a_ultima_resposta_sem_o_modelo(case):
    host, provider, _, _ = case
    agent = enable(host)
    host._now_func = lambda: datetime(2026, 11, 18, 15, 4, 0)
    first = host.process_command('Que horas são?').message
    again = host.process_command('Repete, por favor.')
    assert again.status == 'success' and again.message == first
    assert not agent.observations and provider.mock_calls == []


def test_abre_o_email_depois_do_ultimo_email_abre_esse_email(case):
    host, _, _, _ = case
    agent = enable(host)
    host._gmail_current_context = dict(message_id='abc', session=host.session_id, deadline=time.monotonic() + 60)
    result = host.process_command('Abre o e-mail para mim.')
    assert result.ui_action == 'open_mail' and result.ui_payload == {'id': 'abc'}
    host._gmail_current_context = None
    result = host.process_command('Abre o meu último e-mail.')
    assert result.ui_action == 'open_mail' and result.ui_payload is None
    assert not agent.observations


class _Box:
    def __init__(self, pages):
        self.pages, self.io_lock, self.queries = pages, threading.Lock(), []

    def identity(self):
        return 'conta'

    def _check(self, account, token):
        pass

    @contextmanager
    def _adapter(self, account, token):
        box = self

        class Adapter:
            def search(self, query, page=None, limit=None):
                box.queries.append((query, page, limit))
                return box.pages[page]
        yield Adapter()


def test_quantos_emails_conta_os_nao_lidos_por_ids():
    assert mail_count_request('Quantas e-mails eu tenho?')
    assert mail_count_request('quantos e-mails não lidos eu tenho na caixa de entrada')
    assert not mail_count_request('quantos e-mails eu mandei pro João')
    box = _Box({None: dict(messages=[{'id': str(i)} for i in range(500)], next_page='p2'),
                'p2': dict(messages=[{'id': 'x'}] * 7)})
    assert unread_count(box, None) == (507, True)
    assert box.queries[0] == ('in:inbox is:unread', None, 500)


def test_lembrete_diario_aceita_a_6_como_a_voz_transcreve():
    now = datetime(2026, 11, 19, 15, 2)
    for phrase, hour in [('Therion, me lembra de tomar remédio todos os dias a 6.', 6),
                         ('Therion, me lembra todo dia de tomar o remédio a 5.', 5)]:
        parsed = parse_reminder(phrase, now)
        assert parsed.hour == hour and parsed.repeat is not None
    assert parse_reminder('me lembra de ir a 2 lojas', now).hour is None


def test_navegador_e_o_unico_navegador_do_catalogo():
    apps = [SimpleNamespace(id='chrome', name='chrome', aliases=()), SimpleNamespace(id='obs', name='Obsidian', aliases=())]
    catalog = SimpleNamespace(entries=lambda: apps)
    assert [a.name for a in ApplicationCatalog.resolve(catalog, 'navegador')] == ['chrome']
    apps.append(SimpleNamespace(id='edge', name='Edge', aliases=()))
    assert len(ApplicationCatalog.resolve(catalog, 'navegador')) == 2   # ambíguo: quem chama pede o nome


def test_resumo_da_partida_nao_se_repete_na_mesma_hora():
    clock = Clock()
    watch = PcWatch(clock=clock)
    for _ in range(3):
        watch.game(True)
        watch.check(pc(c=3), None)
        said = watch.game(False)
        if _ == 0:
            assert said == 'Senhor, na partida o disco C desceu a 3,0 GB.'
        else:
            assert said is None
    clock.now = 3601
    watch.game(True); watch.check(pc(c=3), None)
    assert watch.game(False) is not None


def test_aviso_do_modo_jogo_sai_uma_vez_por_hora():
    said = []
    window = SimpleNamespace(_game_polls=0, _game_unloaded=False, _processing=False, _unload_model=lambda: None,
                             _orchestrator=SimpleNamespace(ai_core=SimpleNamespace(_provider=SimpleNamespace(unload=lambda: None))),
                             _focus_hold=lambda message: False, _append=lambda who, message: said.append(message))
    for _ in range(3):                      # entra e sai da tela cheia três vezes
        MainWindow._poll_game_mode(window, True); MainWindow._poll_game_mode(window, True)
        MainWindow._poll_game_mode(window, False)
    assert len(said) == 1


def test_registro_nomeia_a_rota_fixa_em_vez_de_ia(tmp_path):
    from therion.logging.conversation_log import ConversationLog
    log = ConversationLog(tmp_path / 'conversas', now=lambda: datetime(2026, 11, 20, 0, 8, 18))
    window = SimpleNamespace(_conversation_log=log, _command_started_at=None, _speech_text=None,
                             _command_worker=SimpleNamespace(_command='modo de jogo'))
    log.user('modo de jogo', channel='texto')
    MainWindow._log_result(window, SimpleNamespace(intent=None, status='success'))
    window._command_worker = SimpleNamespace(_command='me conta uma piada')
    MainWindow._log_result(window, SimpleNamespace(intent=None, status='success'))
    text = next((tmp_path / 'conversas').glob('*.md')).read_text(encoding='utf-8')
    assert '`rota: modo jogo · status: success' in text and '`rota: IA/conversa · status: success' in text


# --- Panorama lento (5,8 s): metadado de 10 e-mails um a um e dois workers do Gmail ---
from tests.test_mailbox_panel import mailbox  # noqa: E402,F401  (fixture)


def test_pagina_de_emails_pede_os_metadados_num_lote(mailbox):
    host, client = mailbox
    client.metadata_many = lambda ids: (client.calls.append(('metadata_many', tuple(ids))),
                                        {'messages': [client.metadata(i) for i in ids]})[1]
    view = host._mailbox.page('in:inbox', None, CancellationToken(), force=True)
    assert len(view['items']) == 10
    assert [c[0] for c in client.calls].count('metadata_many') == 1


def test_lote_que_falha_volta_para_um_por_um(mailbox):
    host, client = mailbox
    def broken(ids):
        raise ValueError('lote recusado')
    client.metadata_many = broken
    view = host._mailbox.page('in:inbox', None, CancellationToken(), force=True)
    assert len(view['items']) == 10 and sum(c[0] == 'metadata' for c in client.calls) == 10


def test_panorama_lista_e_conta_no_mesmo_worker(mailbox):
    from therion.agent.briefing import BriefingMarker, mail_since
    host, client = mailbox
    opened = []
    host._gmail_adapter_factory = lambda mode: (opened.append(mode), client)[1]
    BriefingMarker(host._agent_root, host._mailbox.identity()).write(1792843200000 - 3600000)
    result = mail_since(host, CancellationToken(), 1792843200000)
    assert result['page'] and len(result['page']['items']) == 10
    assert len(opened) == 1


# --- Itens 15 a 17 (respondidos pelo usuário em 20/11) ---
def _voz(confianca, pergunta=None, falado=''):
    return SimpleNamespace(_voice_pipeline=SimpleNamespace(last_confidence=confianca), _conversation_awaiting_response=False,
                           _last_conversation_spoken=falado,
                           _orchestrator=SimpleNamespace(confirmation_id=None, _conversation_frame=SimpleNamespace(question=pergunta)))


def test_fala_de_fundo_com_confianca_baixa_e_ignorada():
    fundo = MainWindow._background_speech
    assert fundo(_voz(-0.6), 'Boa logo!') and fundo(_voz(-0.72), 'opa aí, gostei')
    assert not fundo(_voz(-0.3), 'Boa logo!')                       # confiança boa: responde
    assert not fundo(_voz(-0.6), 'Therion, boa logo')                # chamou pelo nome
    assert not fundo(_voz(-0.57), 'Libere espaço.')                  # comando conhecido
    assert not fundo(_voz(-0.51, falado='Para que horas?'), 'Cinco horas.')   # resposta a uma pergunta
    assert not fundo(_voz(-0.51, pergunta='Para que horas?'), 'Cinco horas.')
    assert not fundo(_voz(None), 'Boa logo!')                        # sem medida: responde


def test_busca_nas_notas_ignora_pastas_de_agentes(tmp_path):
    from therion.context.second_brain import SecondBrainReader
    root = tmp_path / '10 - Projetos' / 'Therion'
    for folder in ('.opencode/agents', '.agents', '.claude', 'docs'):
        (root / folder).mkdir(parents=True)
        (root / folder / 'nota.md').write_text('Prismion status do projeto', encoding='utf-8')
    found = SecondBrainReader(str(tmp_path), [str(root)]).search_notes('Prismion')
    paths = [getattr(row, 'path', str(row)) for row in found]
    assert len(paths) == 1 and 'docs' in paths[0]


def test_status_do_projeto_traz_fase_e_proximo_passo_da_nota(tmp_path):
    from therion.core.local_reports import project_note, project_status
    note = tmp_path / '10 - Projetos' / 'Prismion' / 'Prismion.md'
    note.parent.mkdir(parents=True)
    note.write_text('---\ntipo: projeto\npainel_fase: Servidor no ar\npainel_proxima_acao: Testar com o grupo\n'
                    'painel_bloqueio: Não informado\n---\n# Prismion\n', encoding='utf-8')
    props = project_note('Prismion', tmp_path)
    assert props == {'painel_fase': 'Servidor no ar', 'painel_proxima_acao': 'Testar com o grupo'}
    git = lambda path, *args: {'rev-parse': 'main', 'status': '', 'rev-list': '0', 'log': ''}[args[0]]
    text = project_status('Prismion', 'F:\Prismion', git, note=props)
    assert text.startswith('Prismion: Servidor no ar. Próximo passo: Testar com o grupo.') and 'Ramo main' in text
    assert project_note('Outro', tmp_path) == {}


def test_anota_que_aceita_o_nome_do_therion_antes():
    from therion.memory.commands import memory_request
    assert memory_request('Therion, anota que a reunião mudou.') == {'operation': 'add', 'text': 'a reunião mudou'}
    assert memory_request('Terion anota que o teste passou') == {'operation': 'add', 'text': 'o teste passou'}


def test_tira_a_print_salva_a_tela_sem_o_modelo(tmp_path):
    from therion.core.screenshot import screenshot_request, take_screenshot
    for phrase in ('Tira a print, tira a print, tira a print.', 'Therion, tira um print', 'tira print da tela',
                   'faz uma captura de tela', 'printa a tela'):
        assert screenshot_request(phrase), phrase
    assert not screenshot_request('a impressora não imprime')
    saved = []
    image = SimpleNamespace(save=lambda path: (saved.append(path), path.write_bytes(b'png')))
    path = take_screenshot(tmp_path, grab=lambda: image, now=lambda: datetime(2026, 11, 20, 15, 4, 5))
    assert path == tmp_path / 'Therion 2026-11-20 15-04-05.png' and path.exists()


def test_tira_a_print_pelo_orquestrador_sem_o_modelo(case, monkeypatch, tmp_path):
    import therion.core.screenshot as screenshot
    host, provider, _, _ = case
    agent = enable(host)
    monkeypatch.setattr(screenshot, 'default_folder', lambda: tmp_path)
    monkeypatch.setattr(screenshot, 'take_screenshot', lambda: tmp_path / 'Therion x.png')
    result = host.process_command('Tira a print, tira a print.')
    assert result.status == 'success' and result.message == f'Print salvo em {tmp_path.name}: Therion x.png.'
    assert result.speech_message == 'Print salvo.' and not agent.observations and provider.mock_calls == []
    memo = host.process_command('Therion, anota que o teste passou.')
    assert 'teste passou' in memo.message and provider.mock_calls == []
