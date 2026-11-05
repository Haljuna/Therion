"""Regressões da conversa por voz, com agenda e notas inteiramente fictícias."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.test_personal_context_flow import case
from tests.test_agent_runtime import ScriptedProvider
from therion.calendar.dialogue import extract_fields
from therion.context.second_brain import SecondBrainReader
from therion.interface.desktop import _CommandWorker


def enable(host):
    host._agent_root = Path(host.second_brain.vault_root).parent/'agent-state'
    host._agent_config['enabled'] = True
    host._agent_provider = ScriptedProvider()
    host._now_func = lambda: datetime(2026,10,20,12,tzinfo=ZoneInfo('America/Sao_Paulo'))


def send(host, text):
    worker = _CommandWorker(host,text)
    worker.run()
    assert not worker.failed
    return worker.result


def test_spoken_meeting_keeps_date_time_and_subject_until_confirmation(case):
    host,provider,calendar,_ = case
    enable(host)
    send(host,'Marca uma reunião pra mim.')
    send(host,'Dia vinte do dez de dois mil e vinte e seis.')
    result = send(host,'Às dezessete e quarenta.')
    assert result.status == 'awaiting_confirmation'
    assert '17:40' in result.message and 'Confirmar?' in result.message
    result = send(host,'O assunto da reunião é teste e o participante vai ser só eu.')
    assert result.status == 'awaiting_confirmation'
    assert host._pending_event_draft['title'] == 'Teste'
    assert host._pending_event_draft['date'] == '20/10/2026'
    assert host._pending_event_draft['start_time'] == '17:40'
    calendar.create_event.assert_not_called()
    assert not host._agent_provider.observations
    provider.generate.assert_not_called()
    assert send(host,'não').status == 'cancelled'
    calendar.create_event.assert_not_called()


def test_explicit_meeting_today_does_not_send_hoje_to_iso_schema(case):
    host,_,calendar,_ = case
    enable(host)
    result = send(host,'Marca uma reunião para mim hoje, às 18 horas.')
    assert result.status == 'awaiting_confirmation'
    assert '18:00' in result.message
    calendar.list_events_for_day.assert_not_called()
    calendar.create_event.assert_not_called()
    assert not host._agent_provider.observations


def test_production_decider_records_calendar_collection_and_cancellation(case):
    host,provider,calendar,_ = case
    enable(host)
    host._agent_provider = None
    result = send(host,'Marca uma reunião hoje às 18 horas.')
    assert result.status == 'awaiting_confirmation',result.message
    receipts = host._agent_store.operations()
    assert len(receipts)==1 and receipts[0]['state']=='awaiting_confirmation'
    assert send(host,'não').status=='cancelled'
    assert host._agent_store.operations(receipts[0]['call_id'])[0]['state']=='cancelled'
    provider.generate.assert_not_called()
    calendar.create_event.assert_not_called()


@pytest.mark.parametrize('command',['Marca uma reunião antes de 18 horas.',
                                  'Marca uma reunião hoje depois das 18h.'])
def test_relative_time_cannot_become_exact_start(case,command):
    host,_,calendar,_ = case
    enable(host)
    send(host,command)
    assert 'start_time' in host._pending_event_draft['_issues']
    assert not host._pending_event_draft.get('_presented')
    calendar.create_event.assert_not_called()


def test_summary_day_consults_calendar_instead_of_inventing_activity(case):
    host,provider,calendar,_ = case
    enable(host)
    calendar.list_events_for_day.return_value = []
    result = send(host,'Resume meu dia.')
    assert result.status == 'success'
    calendar.list_events_for_day.assert_called_once()
    assert not host._agent_provider.observations


def test_personal_course_search_uses_authorized_profile_and_revocation(case):
    host,provider,_,profile = case
    enable(host)
    result = send(host,'Procura qual a minha faculdade no segundo cérebro.')
    assert 'Engenharia Biomédica' in result.message and 'Perfil.md' in result.message
    assert not host._agent_provider.observations
    provider.describe_result.reset_mock()
    host.second_brain.allowed_roots = []
    result = send(host,'Procura qual a minha faculdade no segundo cérebro.')
    assert 'Engenharia Biomédica' not in result.message
    provider.describe_result.assert_not_called()


def test_explicit_note_search_uses_tools_without_llm_or_runtime_directories(case):
    host,provider,_,profile = case
    enable(host)
    host._agent_provider = None
    hidden = profile.parent/'.venv'/'Faculty.md'
    hidden.parent.mkdir()
    hidden.write_text('Faculdade proibida de teste',encoding='utf-8')
    before = profile.read_bytes()
    result = send(host,'Procura nas notas faculdade.')
    assert result.status == 'success',result.message
    assert 'Perfil.md' in result.message and '.venv' not in result.message
    assert profile.read_bytes() == before
    provider.generate.assert_not_called()
    provider.describe_result.assert_not_called()


def test_technical_directories_are_pruned_before_descent(tmp_path,monkeypatch):
    import os
    (tmp_path/'Faculdade.md').write_text('Faculdade fictícia',encoding='utf-8')
    # tmp/.obsidian/.trash: em 04/11 o cofre tinha ~22 mil fixtures em tmp e a busca passava de 30 s.
    for name in ('.venv','node_modules','.git','tmp','.obsidian','.trash'):
        directory = tmp_path/name
        directory.mkdir()
        (directory/'Faculdade.md').write_text('Dependência fictícia',encoding='utf-8')
    visited=[]
    original=os.walk
    def walk(*args,**kwargs):
        for row in original(*args,**kwargs):
            visited.append(row[0])
            yield row
    monkeypatch.setattr('therion.context.second_brain.os.walk',walk)
    reader=SecondBrainReader(str(tmp_path),[str(tmp_path)])
    rows=reader.search_notes('faculdade')
    assert len(rows)==1 and len(visited)==1


@pytest.mark.parametrize('text,expected',[
    ('Dia vinte e três do dez de dois mil e vinte e seis.', {'date':'23/10/2026'}),
    ('Às vinte e três e quarenta e três.', {'start_time':'23:43'}),
])
def test_accented_spoken_numbers(text,expected):
    assert extract_fields(text)[1]==expected


@pytest.mark.parametrize('answer,expected',[
    ('Dezessete cinquenta.', '17:50'),
    ('Dezessete e cinquenta.', '17:50'),
    ('À 5 horas e 50 minutos da tarde.', '17:50'),
    ('Dezoito.', '18:00'),
    ('Um oito zero zero.', '18:00'),
    ('Às vinte e três e quarenta e três.', '23:43'),
])
def test_bare_spoken_time_in_actual_collection_path(case,answer,expected):
    host,provider,calendar,_=case
    enable(host);host._agent_provider=None
    assert send(host,'Marca uma reunião hoje pra mim.').status=='awaiting_confirmation'
    result=send(host,answer)
    assert result.status=='awaiting_confirmation',result.message
    assert expected in result.message and 'Confirmar?' in result.message
    assert host._pending_event_draft['start_time']==expected
    provider.generate.assert_not_called()
    calendar.create_event.assert_not_called()


def test_invalid_time_and_repeated_corrections_never_abandon_meeting(case):
    host,provider,calendar,_=case
    enable(host);host._agent_provider=None
    send(host,'Marca uma reunião hoje.')
    for answer in ('25:99','não sei explicar esse horário','Dezessete cinquenta.',
                   'Dezessete e cinquenta.','À 5 horas e 50 minutos da tarde.'):
        result=send(host,answer)
        assert result.status=='awaiting_confirmation',result.message
        assert host._pending_event_draft is not None
    assert host._pending_event_draft['start_time']=='17:50'
    provider.generate.assert_not_called()
    calendar.create_event.assert_not_called()


def test_bare_spoken_date_stays_in_meeting(case):
    host,_,calendar,_=case
    enable(host)
    send(host,'Marca uma reunião.')
    result=send(host,'Vinte do dez de dois mil e vinte e seis.')
    assert host._pending_event_draft['date']=='20/10/2026'
    assert result.status=='awaiting_confirmation'
    calendar.list_events_for_day.assert_not_called()
    calendar.create_event.assert_not_called()


def test_next_days_and_tomorrow_use_local_clock_without_model(case):
    host,provider,calendar,_=case
    enable(host);host._agent_provider=None
    calendar.list_events_for_day.return_value=[]
    result=send(host,'Confere se eu tenho algum compromisso nos próximos dias.')
    dates=[call.args[0].isoformat() for call in calendar.list_events_for_day.call_args_list]
    assert dates==[f'2026-10-{day}' for day in range(20,27)]
    assert '20/10/2026 a 26/10/2026' in result.message
    calendar.list_events_for_day.reset_mock()
    result=send(host,'Amanhã.')
    assert calendar.list_events_for_day.call_args.args[0].isoformat()=='2026-10-21'
    assert '21/10/2026' in result.message and result.status=='success'
    provider.generate.assert_not_called()
    provider.describe_result.assert_not_called()
    calendar.create_event.assert_not_called()


def test_bare_date_does_not_consult_calendar_without_recent_context(case):
    host,_,calendar,_=case
    enable(host)
    assert host._calendar_followup_request('Amanhã.') is None
    host._calendar_query_context=('another-session',host._language_clock())
    assert host._calendar_followup_request('Amanhã.') is None
    host._calendar_query_context=(host.session_id,host._language_clock()-301)
    assert host._calendar_followup_request('Amanhã.') is None
    calendar.list_events_for_day.assert_not_called()


def test_calendar_followup_context_ends_on_topic_change(case):
    host,_,calendar,_=case
    enable(host)
    calendar.list_events_for_day.return_value=[]
    send(host,'Resume meu dia.')
    assert host._calendar_followup_request('Amanhã.') is not None
    send(host,'Que horas são?')
    assert host._calendar_followup_request('Amanhã.') is None


@pytest.mark.parametrize('command',[
    'Térion, olha a minha agenda pra mim, ver se eu tenho alguma coisa hoje.',
    'Olha a minha agenda hoje.',
    'Olhe minha agenda hoje, por favor.',
    'Você pode olhar a minha agenda hoje?',
    'Confere a minha agenda para mim hoje.',
])
def test_natural_calendar_request_bypasses_llm_and_uses_local_date(case,command):
    host,provider,calendar,_=case
    enable(host);host._agent_provider=None
    calendar.list_events_for_day.return_value=[]
    result=send(host,command)
    assert result.status=='success',result.message
    calendar.list_events_for_day.assert_called_once()
    assert calendar.list_events_for_day.call_args.args[0].isoformat()=='2026-10-20'
    assert 'comprimento fora' not in result.message
    provider.generate.assert_not_called()
    provider.describe_result.assert_not_called()
    calendar.create_event.assert_not_called()


@pytest.mark.parametrize('value,expected',[('hoje','2026-10-20'),('amanhã','2026-10-21'),
                                         ('20/10/2026','2026-10-20'),('2026-10-20','2026-10-20')])
def test_calendar_tool_normalizes_relative_dates_before_calling_adapter(case,value,expected):
    import asyncio
    from therion.agent.builtin import build_read_registry
    from therion.agent.contracts import ToolCall,CancellationToken
    host,_,calendar,_=case
    enable(host);calendar.list_events_for_day.return_value=[]
    registry=build_read_registry(host)
    arguments={'day':value}
    spec,blocked=registry.prepare(ToolCall('calendar_day',arguments))
    assert blocked is None
    result=asyncio.run(spec.handler(arguments,CancellationToken()))
    assert result.status=='success'
    assert calendar.list_events_for_day.call_args.args[0].isoformat()==expected


def test_invalid_calendar_tool_date_never_calls_adapter(case):
    import asyncio
    from therion.agent.builtin import build_read_registry
    from therion.agent.contracts import ToolCall,CancellationToken
    host,_,calendar,_=case
    enable(host)
    arguments={'day':'quando eu quiser'}
    spec,blocked=build_read_registry(host).prepare(ToolCall('calendar_day',arguments))
    assert blocked is None
    result=asyncio.run(spec.handler(arguments,CancellationToken()))
    assert result.status=='awaiting_clarification'
    calendar.list_events_for_day.assert_not_called()


def test_next_week_is_monday_to_sunday_from_local_clock(case):
    from datetime import date,timedelta
    host,provider,calendar,_=case
    enable(host);host._agent_provider=None
    calendar.list_events_for_day.return_value=[]
    result=send(host,'Tem algum evento na semana que vem?')
    assert result.status=='success',result.message
    assert [call.args[0] for call in calendar.list_events_for_day.call_args_list]==[
        date(2026,10,26)+timedelta(days=i) for i in range(7)]
    assert '26/10/2026 a 01/11/2026' in result.message
    provider.generate.assert_not_called()
    calendar.create_event.assert_not_called()


def test_followup_with_e_and_commitment_detail_requeries_same_period(case):
    from therion.calendar.models import CalendarEvent
    host,provider,calendar,_=case
    enable(host);host._agent_provider=None
    start=datetime(2026,10,21,18,tzinfo=ZoneInfo('America/Sao_Paulo'))
    event=CalendarEvent('fixture','Reunião fictícia',start,start.replace(hour=19),False)
    calendar.list_events_for_day.return_value=[event]
    send(host,'Resume o meu dia.')
    result=send(host,'E amanhã.')
    assert result.status=='success' and calendar.list_events_for_day.call_args.args[0].isoformat()=='2026-10-21'
    calendar.list_events_for_day.reset_mock()
    result=send(host,'Qual é o compromisso?')
    assert result.status=='success' and 'Reunião fictícia' in result.message
    assert calendar.list_events_for_day.call_args.args[0].isoformat()=='2026-10-21'
    provider.generate.assert_not_called()


def test_change_subject_collects_title_and_requires_new_confirmation(case):
    host,provider,calendar,_=case
    enable(host);host._agent_provider=None
    send(host,'Marca uma reunião hoje para mim.')
    send(host,'As 18.')
    before=host._confirmation_id
    result=send(host,'Muda o assunto.')
    assert 'novo assunto' in result.message and not host._pending_event_draft.get('_presented')
    result=send(host,'sim')
    assert 'novo assunto' in result.message
    result=send(host,'Teste de engenharia')
    assert 'Título: Teste de engenharia' in result.message and 'Confirmar?' in result.message
    assert host._confirmation_id!=before
    provider.generate.assert_not_called()
    calendar.create_event.assert_not_called()
    assert send(host,'não').status=='cancelled'


def test_title_edit_does_not_store_time_as_subject(case):
    host,_,calendar,_=case
    enable(host)
    send(host,'Marca uma reunião hoje às 18 horas.')
    send(host,'Muda o assunto.')
    result=send(host,'Às 18 horas.')
    assert 'novo assunto' in result.message
    assert host._pending_event_draft['title']=='Reunião'
    assert not host._pending_event_draft.get('_presented')
    calendar.create_event.assert_not_called()


def test_ambiguous_transcription_does_not_replace_valid_time(case):
    host,_,calendar,_=case
    enable(host)
    send(host,'Marca uma reunião hoje às 18 horas.')
    result=send(host,'Às dez oito horas')
    assert result.status=='awaiting_confirmation'
    assert host._pending_event_draft['start_time'] in {'18','18:00'}
    assert not host._pending_event_draft.get('_presented')
    calendar.create_event.assert_not_called()
