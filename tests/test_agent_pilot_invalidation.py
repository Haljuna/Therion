from types import SimpleNamespace
from therion.autonomy.integration import implementation_version
from therion.autonomy.routines import RoutineService,RoutineSpec
from therion.calendar.google_adapter import GoogleCalendarAdapter


def test_runtime_and_voice_profile_changes_invalidate_execution_version():
    config={};runtime=SimpleNamespace(loader=lambda:config)
    original=implementation_version(runtime,{'target':'fixture'})
    config['agent']={'protocol':'native','think':False}
    changed=implementation_version(runtime,{'target':'fixture'});assert changed!=original
    config['tts']={'voice':'fixture_voice'}
    spoken=implementation_version(runtime,{'target':'fixture'});assert spoken!=changed
    # A config de STT mora em "voice"; trocar o reconhecedor derruba as permissões.
    config['voice']={'provider':'parakeet_http'}
    assert implementation_version(runtime,{'target':'fixture'})!=spoken


def test_calendar_account_switch_changes_routine_scope_without_api(tmp_path,monkeypatch):
    account=['one'];monkeypatch.setattr('therion.integrations.calendar.account_key',lambda host:account[0])
    host=SimpleNamespace(calendar_adapter=GoogleCalendarAdapter(),second_brain=SimpleNamespace(vault_root=str(tmp_path)))
    runtime=SimpleNamespace(loader=lambda:{})
    service=RoutineService(host,runtime);spec=RoutineSpec('fixture','daily_summary',8,0)
    first=service.version(spec);account[0]='another'
    assert service.version(spec)!=first
