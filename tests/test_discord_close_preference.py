"""Preferência de saída testada em configurações fictícias, nunca no Discord real."""
import importlib.util
import json
from pathlib import Path

import pytest


spec=importlib.util.spec_from_file_location('configure_discord_close',Path(__file__).resolve().parents[1]/'scripts/configure-discord-close.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_preview_does_not_change_settings(tmp_path):
    path=tmp_path/'settings.json';path.write_text('{"audioSubsystem":"ficticio"}',encoding='utf-8')
    before=path.read_bytes()
    report=module.configure(path,running=lambda:False)
    assert report['after'] is False and not report['applied']
    assert path.read_bytes()==before
    assert list(tmp_path.iterdir())==[path]


def test_apply_changes_only_minimize_to_tray_and_keeps_private_backup(tmp_path):
    path=tmp_path/'settings.json'
    settings={'MINIMIZE_TO_TRAY':True,'audioSubsystem':'ficticio','WINDOW_BOUNDS':{'width':800}}
    path.write_text(json.dumps(settings),encoding='utf-8');before=path.read_bytes()
    result=module.configure(path,running=lambda:False,apply=True)
    expected=dict(settings,MINIMIZE_TO_TRAY=False)
    assert json.loads(path.read_text())==expected and result['applied']
    assert Path(result['backup']).parent==tmp_path and Path(result['backup']).read_bytes()==before


def test_running_discord_blocks_setting_write(tmp_path):
    path=tmp_path/'settings.json';path.write_text('{}')
    with pytest.raises(ValueError,match='Saia do Discord'):
        module.configure(path,running=lambda:True,apply=True)
    assert path.read_text()=='{}'


def test_discord_started_during_preparation_blocks_write(tmp_path):
    path=tmp_path/'settings.json';path.write_text('{}')
    state=iter([False,True])
    with pytest.raises(ValueError,match='mudou'):
        module.configure(path,running=lambda:next(state),apply=True)
    assert path.read_text()=='{}'


def test_setting_already_applied_does_not_create_more_backups(tmp_path):
    path=tmp_path/'settings.json';path.write_text('{"MINIMIZE_TO_TRAY": false}')
    result=module.configure(path,running=lambda:False,apply=True)
    assert not result['applied'] and list(tmp_path.iterdir())==[path]
