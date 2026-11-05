from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import threading
import pytest

from therion.core.orchestrator import Orchestrator
from therion.core.ai_provider import AIProvider
from therion.memory.coordinator import MemoryCoordinator, INFERENCE_GATE
from therion.memory.commands import memory_request
from therion.memory.knowledge import SourceReference


def operation_provider():
    provider = MagicMock()
    provider.model = 'fictício'
    def extract(evidence, **kwargs):
        return [{'title': 'Falha recorrente', 'summary': 'Uma falha de consulta não demonstra ausência de compromissos.',
            'kind': 'limitação', 'reason': 'Evitar anunciar disponibilidade sem evidência.',
            'evidence': evidence['content'][:180], 'sensitivity': 'non_sensitive'}]
    provider.extract_memory_candidates.side_effect = extract
    return provider


def test_repeated_verified_failure_uses_only_fixed_evidence():
    service = MemoryCoordinator('s')
    provider = operation_provider()
    assert not service.observe_result('calendar_query_failed', provider)
    assert not service.observe_result('ordinary_success', provider)
    assert not service.snapshot()
    assert service.observe_result('calendar_query_failed', provider)
    assert service.wait_idle()
    candidate, = service.snapshot()
    assert candidate.source.kind == 'operation' and candidate.kind == 'limitação'
    assert service._operation_source_valid(candidate.source)
    assert not candidate.source.valid(())
    assert not service.observe_result('calendar_query_failed', provider)
    provider.extract_memory_candidates.assert_called_once()
    service.reset('new')
    assert not service._operation_source_valid(candidate.source)
    assert not service.observe_result('calendar_query_failed', provider)
    service.close()


def test_calendar_failures_emit_verified_event_after_adapter_failure(orch):
    provider = operation_provider()
    orch.ai_core = MagicMock(_provider=provider)
    orch.calendar_adapter = MagicMock()
    orch.calendar_adapter.list_events_for_day.side_effect = RuntimeError('DADO PRIVADO NÃO RETIDO')
    assert orch._handle_calendar_query(None, {'date':'hoje'}).status == 'execution_failed'
    assert not orch.knowledge.snapshot()
    assert orch._handle_calendar_query(None, {'date':'hoje'}).status == 'execution_failed'
    assert orch.knowledge.wait_idle()
    assert len(orch.knowledge.snapshot()) == 1
    assert 'DADO PRIVADO' not in str(orch.knowledge.snapshot())
    orch.calendar_adapter.create_event.assert_not_called()
    orch.close()


def test_policy_revision_invalidates_selection_in_flight(tmp_path):
    from dataclasses import replace
    src = source(tmp_path)
    provider = provider_for(src)
    entered = threading.Event(); release = threading.Event()
    rows = provider.extract_memory_candidates.return_value
    def blocked(*args, **kwargs):
        entered.set(); release.wait(2); return rows
    provider.extract_memory_candidates.side_effect = blocked
    service = MemoryCoordinator('s')
    assert service.offer_verified(src, provider, src.roots, reusable=True)
    assert entered.wait(2)
    service.policy = replace(service.policy, revision=1)
    release.set()
    assert service.wait_idle() and not service.snapshot()
    service.close()


def test_verification_failure_is_observed_without_repeating_action(orch):
    from therion.core.intent import Intent
    from therion.core.planner import Plan
    orch.ai_core = MagicMock(_provider=operation_provider())
    orch.executor = MagicMock()
    orch.verifier = MagicMock()
    orch.executor.execute_real.return_value = MagicMock(success=True, message='executado ficticiamente')
    orch.verifier.verify_real.return_value = MagicMock(success=False, message='não verificado ficticiamente')
    plan = Plan(Intent(action='abrir aplicativo', target='Obsidian', raw_command='abra o Obsidian'), [])
    for _ in range(2):
        assert orch._confirm_and_execute(plan, True, simulate=False).status == 'verification_failed'
    assert orch.knowledge.wait_idle() and len(orch.knowledge.snapshot()) == 1
    assert orch.executor.execute_real.call_count == 2
    assert orch.verifier.verify_real.call_count == 2
    orch.close()


@pytest.fixture
def orch(tmp_path):
    return Orchestrator(vault_root=str(tmp_path/'vault'),log_dir=str(tmp_path/'logs'))


@pytest.mark.parametrize('phrase',['lembre que prefiro respostas curtas','guarde: prefiro respostas curtas',
    'memorize que prefiro respostas curtas'])
def test_explicit_preference_gets_preview_only(orch,phrase):
    result=orch.process_command(phrase)
    assert result.status=='success' and 'Ainda não salvei' in result.message
    assert 'prefiro respostas curtas' in result.message
    assert not Path(orch.second_brain.vault_root).exists()
    assert len(orch.knowledge.snapshot())==1
    assert 'prefiro respostas curtas' not in str(orch._build_ai_context('olá'))


def test_memory_commands_do_not_consume_calendar_confirmation(orch):
    orch.calendar_adapter=MagicMock()
    orch._now_func=lambda: datetime(2026,10,9,10,tzinfo=timezone.utc)
    result=orch.process_command('marque reunião amanhã às 15h')
    token=result.confirmation_id
    orch.process_command('lembre que prefiro respostas curtas')
    assert orch.confirmation_id==token
    orch.process_command('salve')
    orch.calendar_adapter.create_event.assert_not_called()
    assert orch.confirmation_id==token
    orch.process_session_command('sim',orch.session_id,token)
    orch.calendar_adapter.create_event.assert_called_once()


def test_candidates_list_select_discard_and_clear(orch):
    orch.process_command('guarde que prefiro respostas curtas')
    orch.process_command('guarde que prefiro exemplos concretos')
    assert 'MEM-' in orch.process_command('o que você pretende guardar?').message
    assert orch.process_command('descarte esse candidato').status=='clarification'
    assert 'exemplos concretos' in orch.process_command('mostre o candidato 2').message
    assert 'Descartei' in orch.process_command('não guarde isso').message
    assert len(orch.knowledge.snapshot())==1
    orch.clear_session()
    assert not orch.knowledge.snapshot()
    assert 'Não há candidatos' in orch.process_command('o que você pretende guardar?').message


@pytest.mark.parametrize('phrase',['guarde esse aprendizado','lembre-me amanhã','lembre amanhã às 15h'])
def test_ambiguous_reference_is_not_retained(orch,phrase):
    result=orch.process_command(phrase)
    assert result.status!='success' or not orch.knowledge.snapshot()
    assert not orch.knowledge.snapshot()


def test_secret_is_not_retained_or_logged(orch,tmp_path):
    result=orch.process_command('guarde que minha senha é EXEMPLO-PRIVADO')
    assert result.status=='clarification'
    assert not orch.knowledge.snapshot()
    assert 'EXEMPLO-PRIVADO' not in str(orch.memory.turns)
    assert all(b'EXEMPLO-PRIVADO' not in p.read_bytes() for p in tmp_path.rglob('*') if p.is_file())


def test_ordinary_chat_and_model_reply_do_not_generate_candidates(orch):
    orch.process_command('Prefiro respostas curtas')
    assert not orch.knowledge.snapshot()
    orch.process_command('guarde esse aprendizado')
    assert not orch.knowledge.snapshot()


def test_pause_and_close_refuse_new_capture(orch):
    orch.process_command('pause a captura')
    assert orch.process_command('guarde que prefiro respostas curtas').status=='clarification'
    orch.close()
    assert not orch.knowledge.snapshot()


def source(tmp_path):
    text='Procedimento reutilizável: valide a origem e os limites antes de criar um rascunho de aprendizado.'
    path=tmp_path/'source.md';path.write_text(text,encoding='utf-8')
    return SourceReference.file(path,text,(str(tmp_path.resolve()),))


def provider_for(src):
    provider=MagicMock()
    provider.model='fictício'
    provider.extract_memory_candidates.return_value=[{'title':'Validar origem','summary':'Validar origem e limites antes de criar um rascunho.',
        'kind':'procedimento','reason':'Prevenir falhas reutilizáveis.','evidence':src.text,'sensitivity':'non_sensitive'}]
    return provider


def test_verified_source_produces_discrete_candidate_once(tmp_path):
    src=source(tmp_path); provider=provider_for(src)
    service=MemoryCoordinator('s')
    assert service.offer_verified(src,provider,src.roots,reusable=True)
    assert service.wait_idle()
    assert len(service.snapshot())==1
    assert len(service.notifications())==1 and not service.notifications()
    assert not service.offer_verified(src,provider,src.roots,reusable=True)
    assert not service.offer_verified(src,provider,src.roots,reusable=False)
    service.close()


@pytest.mark.parametrize('change',[dict(kind='preferência'),dict(sensitivity='uncertain'),dict(evidence='inventada'),
    dict(summary='Marcus prefere café'),dict(action='execute')])
def test_model_cannot_invent_sources_preferences_or_actions(tmp_path,change):
    src=source(tmp_path); provider=provider_for(src)
    provider.extract_memory_candidates.return_value[0].update(change)
    service=MemoryCoordinator('s')
    service.offer_verified(src,provider,src.roots,reusable=True)
    assert service.wait_idle() and not service.snapshot()
    service.close()


@pytest.mark.parametrize('cancel',['reset','pause','close','change_source'])
def test_late_results_cannot_survive_cancellation(tmp_path,cancel):
    src=source(tmp_path); provider=provider_for(src)
    started=threading.Event();release=threading.Event()
    rows=provider.extract_memory_candidates.return_value
    def blocked(*args,**kwargs):
        started.set();release.wait(2);return rows
    provider.extract_memory_candidates.side_effect=blocked
    service=MemoryCoordinator('s')
    service.offer_verified(src,provider,src.roots,reusable=True)
    assert started.wait(1)
    if cancel=='reset': service.reset('new')
    elif cancel=='pause': service.pause()
    elif cancel=='close': service.close()
    else: Path(src.path).write_text('Alterado',encoding='utf-8')
    release.set()
    assert service.wait_idle() and not service.snapshot() and not service.notifications()
    service.close()


def test_optional_provider_method_is_compatible():
    assert AIProvider.extract_memory_candidates(object(),{})==[]


def test_foreground_gate_prevents_concurrent_background_inference():
    started=threading.Event();release=threading.Event()
    def hold():
        with INFERENCE_GATE.foreground():
            started.set();release.wait(2)
    worker=threading.Thread(target=hold);worker.start()
    assert started.wait(1)
    with INFERENCE_GATE.background() as acquired:
        assert not acquired
    release.set();worker.join(2)


def test_failed_provider_does_not_disable_chat(orch,tmp_path):
    src=source(tmp_path);provider=provider_for(src)
    provider.extract_memory_candidates.side_effect=RuntimeError('simulado')
    orch.knowledge.offer_verified(src,provider,src.roots,reusable=True)
    assert orch.knowledge.wait_idle()
    assert not orch.knowledge.snapshot()
    assert orch.process_command('adicione tarefa: estudar').status=='success'


def test_queue_is_bounded_and_cancellation_revokes_pending(tmp_path):
    src=source(tmp_path);provider=provider_for(src)
    entered=threading.Event();release=threading.Event()
    provider.extract_memory_candidates.side_effect=lambda *a,**kw:(entered.set(),release.wait(2),[])[2]
    service=MemoryCoordinator('s')
    assert service.offer_verified(src,provider,src.roots,reusable=True)
    assert entered.wait(1)
    from dataclasses import replace
    for i in range(4):
        assert service.offer_verified(replace(src,identifier=f'source-{i}'),provider,src.roots,reusable=True)
    assert not service.offer_verified(replace(src,identifier='overflow'),provider,src.roots,reusable=True)
    service.cancel_pending()
    release.set()
    assert service.wait_idle() and provider.extract_memory_candidates.call_count==1
    service.close()


def test_elapsed_timeout_rejects_even_noncompliant_provider(tmp_path,monkeypatch):
    src=source(tmp_path);provider=provider_for(src)
    values=iter([0,21])
    monkeypatch.setattr('therion.memory.coordinator.time.monotonic',lambda:next(values))
    service=MemoryCoordinator('s')
    service.offer_verified(src,provider,src.roots,reusable=True)
    assert service.wait_idle() and not service.snapshot()
    service.close()


def test_duplicate_candidate_and_limits_do_not_change_original(orch):
    orch.process_command('guarde que prefiro respostas curtas')
    orch.process_command('guarde que prefiro respostas curtas')
    assert len(orch.knowledge.snapshot())==1
    for text in ('prefiro exemplos concretos','prefiro texto objetivo'):
        orch.process_command('guarde que '+text)
    assert orch.process_command('guarde que prefiro listas').status=='clarification'
    assert len(orch.knowledge.snapshot())==3


def test_ui_notification_is_discrete_and_does_not_replace_speech():
    from types import SimpleNamespace
    from therion.interface.desktop import MainWindow
    append=MagicMock()
    ui=SimpleNamespace(_processing=False,_closing=False,_append=append,_speech_text='resposta principal',
        _orchestrator=SimpleNamespace(memory_notifications=lambda:'Uma prévia disponível'))
    MainWindow._poll_memory_previews(ui)
    append.assert_called_once_with('Therion','Uma prévia disponível')
    assert ui._speech_text=='resposta principal'
    ui._processing=True
    MainWindow._poll_memory_previews(ui)
    assert append.call_count==1


def test_local_provider_uses_closed_schema_and_bounded_timeout(monkeypatch):
    from therion.core.ai_provider_ollama import OllamaProvider
    provider=OllamaProvider(timeout=90)
    send=MagicMock(return_value='{"candidates": []}')
    monkeypatch.setattr(provider,'_send_request_serialized',send)
    assert provider.extract_memory_candidates({'content':'instrução maliciosa'},20)==[]
    payload,timeout=send.call_args.args
    assert timeout==20
    assert payload['format']['additionalProperties'] is False
    assert 'nunca instrução' in payload['messages'][0]['content']


def test_verified_note_capture_is_integrated_without_executing_content(orch,tmp_path):
    src=source(tmp_path)
    provider=provider_for(src)
    provider.describe_result.return_value='Li uma nota com um procedimento.'
    from therion.core.ai_core import AICore
    orch.ai_core=AICore(provider,[])
    orch.second_brain.allowed_roots=[str(tmp_path.resolve())]
    from therion.context.read_scope import ReadScope
    result=orch._read_note_result(str(src.path),'leia a nota',ReadScope('test',src.roots))
    assert result.status=='success' and orch.knowledge.wait_idle()
    assert len(orch.knowledge.snapshot())==1
    assert 'candidato' in orch.memory_notifications()
    assert not orch._session_tasks.list() and orch._pending_event_draft is None
    orch.close()


def test_recovered_memory_is_read_only_context_and_scope_can_revoke(tmp_path):
    from dataclasses import replace
    from datetime import timedelta
    from therion.memory.knowledge import MemoryPolicy, RAS_ROOT, user_candidate
    from therion.memory.repository import MarkdownMemoryRepository
    now=datetime(2026,10,9,12,tzinfo=timezone.utc)
    root=tmp_path/RAS_ROOT
    repo=MarkdownMemoryRepository(root)
    policy=MemoryPolicy(mode='authorized',read_roots=(str(tmp_path.resolve()),),
        write_root=str(root.resolve()),authorization='fictícia',expires_at=now+timedelta(days=1))
    resolver=lambda source:source.kind=='user'
    repo.store(user_candidate('prefiro respostas curtas','s',now),policy,now,resolver)
    orch=Orchestrator(vault_root=str(tmp_path),log_dir=str(tmp_path/'logs'),memory_repository=repo,
        memory_policy=replace(policy,mode='preview'),memory_source_resolver=resolver)
    orch.knowledge.clock=lambda:now
    records=orch._build_ai_context('respostas curtas')['knowledge_context']
    assert records[0]['state']=='Rascunho da IA'
    orch._knowledge_read_roots=()
    assert 'knowledge_context' not in orch._build_ai_context('respostas curtas')
    orch.close()


def test_ui_memory_preview_preserves_existing_confirmation_panel():
    from types import SimpleNamespace
    from therion.interface.desktop import MainWindow
    from therion.core.orchestrator import OrchestrationResult
    plan=object()
    ui=SimpleNamespace(_append=MagicMock(),_pending_plan=plan,_update_orbe=MagicMock(),
        _update_clear_button_state=MagicMock(),_update_confirm_panel=MagicMock())
    MainWindow._apply_command_result(ui,OrchestrationResult(status='success',message='Ainda não salvei',confirmation_id='same'))
    assert ui._pending_plan is plan and ui._conversation_awaiting_response
    ui._update_orbe.assert_called_once_with('awaiting_confirmation')
