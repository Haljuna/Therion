from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import pytest
from therion.context.conversation_frame import current_time_request
from therion.interface.desktop import _CommandWorker
from tests.test_agent_basic_questions import enable
from tests.test_personal_context_flow import case


@pytest.mark.parametrize('command',[
    'Quantas horas?','Que horas são?','Que hora é agora?',
    'Qual é o horário nesse exato momento?','Qual o horário atual?',
    'Me diga que horas são, por favor.','Você pode me dizer que horas são agora?'])
@pytest.mark.parametrize('agent_enabled',[False,True])
def test_clock_through_desktop_worker_without_ai_calendar_or_files(case,command,agent_enabled):
    host,provider,calendar,profile=case
    host._now_func=lambda:datetime(2026,10,20,17,5,9,tzinfo=timezone.utc)
    host._calendar_tz=ZoneInfo('America/Sao_Paulo')
    agent=enable(host) if agent_enabled else None
    before=profile.read_bytes()
    worker=_CommandWorker(host,command);worker.run()
    assert not worker.failed
    assert worker.result.status=='success' and worker.result.message=='Agora são 14:05:09.'
    assert worker.result.speech_message=='Agora são 14 horas, 5 minutos e 9 segundos.'
    assert calendar.mock_calls==[] and provider.mock_calls==[]
    assert profile.read_bytes()==before
    if agent:assert not agent.observations


@pytest.mark.parametrize('command',[
    'Quantas horas faltam para a prova?','Quantas horas devo estudar?',
    'Qual é o horário da minha aula?','Que horas são em Lisboa?',
    'Marque uma reunião agora.','Não me diga que horas são.'])
def test_duration_events_other_zones_and_negations_are_not_current_local_time(command):
    assert not current_time_request(command)


def test_each_query_reads_new_time_instead_of_reusing_previous_answer(case):
    host,_,_,_=case
    enable(host)
    times=iter([datetime(2026,10,20,14,5,9),datetime(2026,10,20,14,6,10)])
    host._now_func=lambda:next(times)
    assert host.process_command('Que horas são?').message=='Agora são 14:05:09.'
    assert host.process_command('Que horas são?').message=='Agora são 14:06:10.'
