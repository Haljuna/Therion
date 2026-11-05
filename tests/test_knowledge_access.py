from datetime import datetime, timedelta, timezone

import pytest

from therion.memory.knowledge import RAS_ROOT
from therion.memory.runtime import access_from_config


NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


def settings():
    return {'knowledge_access':dict(read_all=True, supervised_memory=True,
        authorization='consentimento-ficticio', expires_at=(NOW+timedelta(days=30)).isoformat(), revision=1)}


def test_explicit_policy_separates_full_read_from_bounded_write(tmp_path):
    access = access_from_config(settings(), tmp_path, NOW)
    assert access.authorized and access.read_roots == (str(tmp_path.resolve()),)
    assert access.memory_policy.write_root == str((tmp_path/RAS_ROOT).resolve())
    assert access.memory_policy.allows_write(NOW)
    assert not (tmp_path/RAS_ROOT).exists()  # Ler configuração não escreve nem ativa a interface.


@pytest.mark.parametrize('change', [dict(read_all='true'), dict(supervised_memory=1),
    dict(authorization=''), dict(revision=True), dict(revision=0), dict(expires_at=NOW.isoformat()),
    dict(expires_at='2026-11-01T00:00:00'), dict(expires_at='inválida'), dict(extra='grant')])
def test_invalid_configuration_never_grants_full_read_or_write(tmp_path, change):
    config = settings(); config['knowledge_access'].update(change)
    access = access_from_config(config, tmp_path, NOW)
    assert not access.authorized and str(tmp_path.resolve()) not in access.read_roots
    assert not access.memory_policy.allows_write(NOW)


def test_read_permission_does_not_enable_write(tmp_path):
    config = settings(); config['knowledge_access']['supervised_memory'] = False
    access = access_from_config(config, tmp_path, NOW)
    assert access.read_roots == (str(tmp_path.resolve()),)
    assert not access.memory_policy.allows_write(NOW)


def test_missing_configuration_preserves_previous_scope(tmp_path):
    access = access_from_config({}, tmp_path, NOW)
    assert len(access.read_roots) == 2
    assert not access.authorized and not access.memory_policy.allows_write(NOW)
