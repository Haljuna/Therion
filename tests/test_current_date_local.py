from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo
import pytest
from therion.core.orchestrator import Orchestrator
from therion.context.conversation_frame import capabilities_request,current_date_request


@pytest.mark.parametrize('command',['Que dia que é hoje?','Qual é o dia de hoje?','Que dia é hoje?','Qual é a data de hoje?'])
def test_date_uses_local_clock_without_calendar_or_ai(tmp_path,command):
    calendar=MagicMock()
    core=MagicMock()
    instance=Orchestrator(log_dir=str(tmp_path),calendar_adapter=calendar,ai_core=core)
    instance._now_func=lambda:datetime(2026,10,20,12,tzinfo=ZoneInfo('America/Sao_Paulo'))
    try:
        result=instance.process_command(command)
        assert result.status=='success' and result.message=='Hoje é terça-feira, 20/10/2026.'
        assert calendar.mock_calls==[] and core.mock_calls==[]
    finally:instance.close()


@pytest.mark.parametrize('command',['O que tenho na agenda hoje?','Marque uma reunião hoje.','Qual dia você pode abrir o Chrome?'])
def test_date_does_not_replace_actions_or_calendar_queries(command):
    assert not current_date_request(command)


def test_spoken_capabilities_variant():
    assert capabilities_request('Me falam o que você consegue fazer.')
    assert not capabilities_request('Me fala como abrir o Chrome.')
