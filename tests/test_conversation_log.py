"""Registro local de conversas para análise de erros; nunca pode travar o Therion."""
import os
import time
from datetime import datetime

from therion.logging.conversation_log import ConversationLog

T0 = datetime(2026, 11, 3, 22, 43, 0)


def make(tmp_path, **kw):
    clock = iter([T0.replace(second=s) for s in range(0, 59)])
    return ConversationLog(tmp_path / 'conversas', now=lambda: next(clock), **kw)


def only_file(tmp_path):
    files = sorted((tmp_path / 'conversas').glob('*.md'))
    assert len(files) == 1
    return files[0].read_text(encoding='utf-8')


def test_writes_each_message_immediately(tmp_path):
    log = make(tmp_path)
    log.user('Qual é o compromisso?', channel='voz')
    text = only_file(tmp_path)  # já está no disco, sem fechar
    assert '· voz' in text and '**Você:** Qual é o compromisso?' in text


def test_spoken_text_only_when_it_differs_from_screen(tmp_path):
    log = make(tmp_path)
    log.user('agenda de amanhã', channel='texto')
    log.therion('Consultei seu calendário e encontrei 2 compromissos.')
    log.result(spoken='Amanhã você tem 2 compromissos: Reunião, às 15 horas.', status='success',
               route='consultar agenda', seconds=1.234)
    log.user('oi', channel='texto')
    log.therion('Olá.')
    log.result(spoken='Olá.', status='success', route=None, seconds=0.4)
    text = only_file(tmp_path)
    assert '**Therion (falou):** Amanhã você tem 2 compromissos' in text
    assert text.count('(falou)') == 1
    assert '`rota: consultar agenda · status: success · 1,2 s`' in text
    assert '`rota: IA/conversa · status: success · 0,4 s`' in text


def test_multiline_messages_stay_readable(tmp_path):
    log = make(tmp_path)
    log.therion('Eventos:\n1. A\n2. B')
    assert '**Therion (tela):** Eventos:\n> 1. A\n> 2. B' in only_file(tmp_path)


def test_rotate_starts_new_note(tmp_path):
    log = make(tmp_path)
    log.user('primeira', channel='texto')
    log.rotate()
    log.user('segunda', channel='texto')
    files = sorted((tmp_path / 'conversas').glob('*.md'))
    assert len(files) == 2
    assert 'primeira' in files[0].read_text(encoding='utf-8')
    assert 'segunda' in files[1].read_text(encoding='utf-8')


def test_rotate_without_messages_creates_nothing(tmp_path):
    log = make(tmp_path)
    log.rotate()
    assert not list((tmp_path / 'conversas').glob('*.md'))


def test_disabled_writes_nothing(tmp_path):
    log = make(tmp_path, enabled=False)
    log.user('x', channel='texto')
    log.therion('y')
    assert not (tmp_path / 'conversas').exists()


def test_disk_failure_never_raises(tmp_path):
    blocker = tmp_path / 'conversas'
    blocker.write_text('arquivo no lugar da pasta')
    log = ConversationLog(blocker, now=lambda: T0)
    log.user('x', channel='texto')  # não pode lançar
    log.therion('y')
    log.result(spoken='z', status='success', route=None, seconds=1)
    assert log.failed


def test_old_notes_are_pruned_but_other_files_kept(tmp_path):
    folder = tmp_path / 'conversas'
    folder.mkdir()
    old, recent, other = folder / '2026-08-01_10-00-00.md', folder / '2026-11-01_10-00-00.md', folder / 'leia-me.txt'
    for path in (old, recent, other):
        path.write_text('x')
    sixty_one_days = time.time() - 61 * 86400
    os.utime(old, (sixty_one_days, sixty_one_days))
    os.utime(other, (sixty_one_days, sixty_one_days))
    ConversationLog(folder, now=lambda: T0, keep_days=60)
    assert not old.exists() and recent.exists() and other.exists()
