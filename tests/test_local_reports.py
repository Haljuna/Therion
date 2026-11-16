"""Resumo do dia, estado de projeto e saúde do PC: só leitura, sem modelo."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from therion.core import local_reports
from therion.core.local_reports import _conversations, day_report, pc_report, project_status, report_request
from therion.interface.desktop import _CommandWorker
from tests.test_agent_basic_questions import enable
from tests.test_personal_context_flow import case

GB = 1024 ** 3
PROJECTS = {'Prismion': 'F:\\Prismion'}


@pytest.mark.parametrize('command', ['O que eu fiz hoje?', 'o que a gente fez hoje', 'Me diga o que fiz hoje, por favor',
                                     'Resumo do meu dia', 'Como foi meu dia?'])
def test_day_phrases(command):
    assert report_request(command, {}) == ('day',)


@pytest.mark.parametrize('command', ['Por que o PC está lento?', 'o computador tá travando', 'Meu PC ficou muito lento',
                                     'Como está a memória do PC?', 'saúde do computador'])
def test_pc_phrases(command):
    assert report_request(command, {}) == ('pc',)


def test_project_phrases_only_match_registered_names_or_the_word_projeto():
    assert report_request('Como está o Prismion?', PROJECTS) == ('project', 'Prismion', 'F:\\Prismion')
    assert report_request('qual o status do projeto prismion', PROJECTS) == ('project', 'Prismion', 'F:\\Prismion')
    assert report_request('Como está o projeto Atlas?', PROJECTS) == ('unknown_project', ('Prismion',))
    # Sem a palavra "projeto" e sem nome cadastrado, a frase é de outra rota.
    for other in ('Como está o Chrome?', 'Como está a agenda?', 'O que eu tenho hoje?', 'O que eu fiz ontem?',
                  'Não me diga o que eu fiz hoje', 'O PC está ligado?'):
        assert report_request(other, PROJECTS) is None


def test_only_absolute_paths_are_accepted_as_projects():
    config = {'projects': {'Bom': 'F:\\Bom', 'Relativo': 'pasta', '': 'F:\\X', 'Numero': 3}}
    assert local_reports.configured_projects(config) == {'Bom': 'F:\\Bom'}
    assert local_reports.configured_projects({'projects': ['F:\\X']}) == {}


def fake_git(answers):
    return lambda path, *args: answers.get(args[0])


def test_project_status_reports_uncommitted_and_unpushed_work():
    git = fake_git({'rev-parse': 'master', 'status': ' M a.py\n?? b.py', 'rev-list': '3', 'log': '16/11 14:02 — fix: algo'})
    assert project_status('Prismion', 'F:\\Prismion', git) == (
        'Prismion: ramo master. 2 arquivos sem commit. 3 commits sem push. Último commit: 16/11 14:02 — fix: algo.')
    clean = fake_git({'rev-parse': 'master', 'status': '', 'rev-list': '0'})
    assert project_status('Prismion', 'F:\\Prismion', clean) == 'Prismion: ramo master. Tudo commitado. Tudo enviado.'
    assert 'não tem remoto' in project_status('P', 'F:\\P', fake_git({'rev-parse': 'x', 'status': ''}))
    assert 'Não consegui ler' in project_status('P', 'F:\\P', fake_git({}))


def test_conversation_notes_are_only_counted(tmp_path):
    day = datetime(2026, 11, 16, 20, 0)
    (tmp_path / '2026-11-16_08-00-00.md').write_text(
        '# Conversa\n\n## 08:00:01 · voz\n**Você:** segredo um\n`rota: hora · status: success · 0,1 s`\n'
        '\n## 08:01:00 · texto\n**Você:** segredo dois\n`rota: IA/conversa · status: failed · 3,0 s`\n', encoding='utf-8')
    (tmp_path / '2026-11-15_08-00-00.md').write_text('\n## 08:00:01 · voz\n**Você:** ontem\n', encoding='utf-8')
    assert _conversations(tmp_path, day) == (1, 2, 1)
    assert _conversations(tmp_path / 'ausente', day) is None


def test_day_report_joins_every_source_and_never_quotes_conversations():
    now = datetime(2026, 11, 16, 20, 0)
    event = lambda title, hour, all_day=False: SimpleNamespace(summary=title, start=datetime(2026, 11, 16, hour), all_day=all_day)
    calendar = SimpleNamespace(list_events_for_day=lambda day: [event('Dentista', 9), event('Jantar', 21), event('Feriado', 0, True)])
    tasks = [SimpleNamespace(description='Pagar boleto', completed=True), SimpleNamespace(description='Estudar', completed=False)]
    git = fake_git({'log': 'fix: dois\nfeat: um'})
    message = day_report(now, tasks=tasks, calendar=calendar, projects=PROJECTS, conversations=(2, 7, 1), git=git)
    assert message == ('Hoje, até agora. Você me fez 7 pedidos em 2 conversas; 1 não foi concluído. '
                       'Tarefas concluídas nesta conversa: Pagar boleto. Compromissos que já começaram hoje: Dentista. '
                       'Prismion: 2 commits hoje; o mais recente foi "fix: dois".')


def test_day_report_survives_a_broken_calendar_and_says_when_there_is_nothing():
    def broken(day):
        raise RuntimeError('agenda fora')
    message = day_report(datetime(2026, 11, 16, 20, 0), calendar=SimpleNamespace(list_events_for_day=broken),
                         projects={}, conversations=())
    assert message.startswith('Não encontrei registro de atividade hoje')


def measure(**changes):
    row = dict(ram_total=16 * GB, ram_free=8 * GB, commit_total=24 * GB, commit_free=12 * GB,
               disks={'C': 20 * GB}, top=[('chrome.exe', 3 * GB)])
    row.update(changes)
    return row


def test_pc_report_names_the_real_bottleneck():
    assert pc_report(measure()) == ('Não achei aperto agora: 8,0 GB de RAM livres de 16,0 GB, 12,0 GB de memória virtual livres '
                                    'e 20,0 GB livres no disco C. O que mais usa memória: chrome (3,0 GB).')
    tight = pc_report(measure(commit_free=1 * GB, ram_free=1 * GB, disks={'C': 2 * GB}, top=[]))
    assert tight.startswith('O PC está apertado: a memória virtual está quase esgotada (1,0 GB livres de 24,0 GB)')
    assert 'a memória RAM está quase cheia' in tight and 'o disco C está quase cheio (2,0 GB livres)' in tight


@pytest.mark.parametrize('agent_enabled', [False, True])
def test_reports_answer_through_the_desktop_worker_without_the_model(case, agent_enabled, monkeypatch, tmp_path):
    host, provider, calendar, profile = case
    host._now_func = lambda: datetime(2026, 11, 16, 20, 0)
    calendar.list_events_for_day.return_value = []
    agent = enable(host) if agent_enabled else None
    # Pasta inexistente: o git de verdade roda e falha, sem tocar em nenhum repositório real.
    monkeypatch.setattr(local_reports, 'configured_projects', lambda config=None: {'Prismion': str(tmp_path / 'ausente')})
    monkeypatch.setattr(local_reports, '_measure', lambda: measure())
    for command, start in (('O que eu fiz hoje?', ('Hoje, até agora.', 'Não encontrei registro')),
                           ('Por que o PC está lento?', ('Não achei aperto agora',)),
                           ('Como está o Prismion?', ('Não consegui ler o projeto Prismion',)),
                           ('Como está o projeto Atlas?', ('Não conheço esse projeto. Cadastrados: Prismion.',))):
        worker = _CommandWorker(host, command); worker.run()
        assert not worker.failed and worker.result.status == 'success', command
        assert worker.result.message.startswith(start), (command, worker.result.message)
    assert provider.mock_calls == []
    if agent:
        assert not agent.observations
