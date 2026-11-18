"""Limpeza segura: só temporários velhos, nunca atravessa junção, só com pedido ou "sim" dentro do prazo."""
import _winapi
import os
import time
from types import SimpleNamespace

import pytest

from therion.core import pc_cleanup
from therion.interface.desktop import _CommandWorker
from tests.test_agent_basic_questions import enable
from tests.test_personal_context_flow import case

MB = 1024 ** 2


def old(path, size=MB):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)
    os.utime(path, (time.time() - 3 * 86400,) * 2)
    return path


def test_clean_removes_only_old_items_and_never_goes_through_a_junction(tmp_path):
    temp = tmp_path / 'temp'
    old(temp / 'velho.tmp')
    old(temp / 'pasta' / 'dentro.bin', 2 * MB)
    os.utime(temp / 'pasta', (time.time() - 3 * 86400,) * 2)
    (temp / 'novo.tmp').write_bytes(b'x' * MB)                      # de hoje: fica
    keep = old(tmp_path / 'do-usuario' / 'importante.txt')
    cache = tmp_path / 'cache'
    old(cache / 'pedaco.bin')
    _winapi.CreateJunction(str(tmp_path / 'do-usuario'), str(cache / 'juncao'))   # sem idade mínima: só a junção salva
    moved = tmp_path / 'movida'
    _winapi.CreateJunction(str(tmp_path / 'do-usuario'), str(moved))   # pasta inteira movida para o F
    rows = [('Temp do usuário', str(temp), 24), ('Cache do pip', str(cache), 0), ('Cache do npm', str(moved), 0)]
    assert pc_cleanup.estimate(rows) == 4 * MB
    assert pc_cleanup.clean(rows) == {'Temp do usuário': 3 * MB, 'Cache do pip': MB}
    assert os.listdir(temp) == ['novo.tmp'] and os.listdir(cache) == ['juncao'] and keep.exists()


def test_report_lists_the_biggest_items_and_the_update_cache_only_as_information():
    GB = 1024 ** 3
    assert pc_cleanup.report({'Temp do usuário': 2 * GB, 'Cache do Chrome': GB, 'Crash dumps': MB}, 5.9 * GB, 6 * GB) == (
        'Limpei 3,0 GB: temp do usuário 2,0 GB, cache do chrome 1,0 GB. O disco C está com 5,9 GB livres. '
        'O F:\\WUDownloadCache tem 6,0 GB; esse só o senhor decide.')
    assert pc_cleanup.report({}, None) == 'Não havia temporários seguros para apagar.'


def test_yes_only_counts_for_the_next_sentence_within_two_minutes():
    host, ran = SimpleNamespace(), []
    runner = lambda: ran.append(1) or 'limpou'
    pc_cleanup.offer(host)
    assert pc_cleanup.answer('Sim, pode.', host, runner) == 'limpou'
    assert pc_cleanup.answer('sim', host, runner) is None            # oferta já usada
    pc_cleanup.offer(host)
    assert pc_cleanup.answer('que horas são', host, runner) is None   # outra frase cancela
    assert pc_cleanup.answer('sim', host, runner) is None
    pc_cleanup.offer(host)
    assert pc_cleanup.answer('Não', host, runner) == 'Tudo bem, não apaguei nada.'
    host._pc_cleanup_offer = time.monotonic() - 1                    # venceu
    assert pc_cleanup.answer('sim', host, runner) is None and ran == [1]


@pytest.mark.parametrize('command', ['Therion, libera espaço', 'libera espaço no disco C', 'limpa os temporários',
                                     'Pode liberar espaço, por favor', 'faz uma limpeza no disco'])
def test_asking_to_free_space_runs_without_an_offer(command):
    assert pc_cleanup.answer(command, SimpleNamespace(), lambda: 'limpou') == 'limpou'


@pytest.mark.parametrize('command', ['libera espaço pra mim no celular', 'o espaço está acabando?', 'limpa a mesa'])
def test_other_sentences_are_not_a_cleanup(command):
    assert pc_cleanup.answer(command, SimpleNamespace(), lambda: 'limpou') is None


@pytest.mark.parametrize('agent_enabled', [False, True])
def test_yes_reaches_the_cleanup_through_the_desktop_worker_without_the_model(case, agent_enabled, monkeypatch):
    host, provider, calendar, profile = case
    agent = enable(host) if agent_enabled else None
    monkeypatch.setattr(pc_cleanup, 'run', lambda: 'Limpei 1,0 GB.')
    pc_cleanup.offer(host)
    for command in ('Sim', 'Therion, libera espaço'):
        worker = _CommandWorker(host, command); worker.run()
        assert not worker.failed and worker.result.status == 'success' and worker.result.message == 'Limpei 1,0 GB.', command
    assert provider.mock_calls == []
    if agent:
        assert not agent.observations
