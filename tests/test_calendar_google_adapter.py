"""Testes unitários de GoogleCalendarAdapter (Bloco B1 - mockados).

Nenhum acesso real à internet ou Google Calendar.
Todos os testes usam mocks e patches controlados.
"""

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

from googleapiclient.errors import HttpError

from therion.calendar.adapter import CalendarError
from therion.calendar.google_adapter import GoogleCalendarAdapter
from therion.calendar.models import CalendarEvent


def _make_service_mock(items: list[dict]) -> MagicMock:
    """Cria mock do service Google Calendar retornando os itens fornecidos."""
    service = MagicMock()
    (
        service.events.return_value
        .list.return_value
        .execute.return_value
    ) = {"items": items}
    return service


def _make_timed_event(
    event_id: str,
    summary: str,
    start_iso: str,
    end_iso: str,
    description: str | None = None,
) -> dict:
    """Cria dict de evento com dateTime (evento com horário definido)."""
    item: dict = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if description is not None:
        item["description"] = description
    return item


def _make_allday_event(
    event_id: str,
    summary: str,
    start_date: str,
    end_date: str,
) -> dict:
    """Cria dict de evento de dia inteiro (all-day, usa 'date')."""
    return {
        "id": event_id,
        "summary": summary,
        "start": {"date": start_date},
        "end": {"date": end_date},
    }


class TestListEventsForDayTimedEvent(unittest.TestCase):
    """Valida conversão de evento com horário definido (dateTime)."""

    def test_evento_com_horario_retorna_calendar_event(self) -> None:
        """1. Evento com dateTime é convertido corretamente para CalendarEvent."""
        item = _make_timed_event(
            event_id="evt001",
            summary="Reunião de equipe",
            start_iso="2026-09-15T10:00:00-03:00",
            end_iso="2026-09-15T11:00:00-03:00",
            description="Pauta: planejamento do sprint",
        )
        service = _make_service_mock([item])

        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                events = adapter.list_events_for_day(date(2026, 9, 15))

        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertIsInstance(ev, CalendarEvent)
        self.assertEqual(ev.event_id, "evt001")
        self.assertEqual(ev.summary, "Reunião de equipe")
        self.assertEqual(ev.description, "Pauta: planejamento do sprint")
        self.assertFalse(ev.all_day)
        self.assertIsInstance(ev.start, datetime)
        self.assertIsInstance(ev.end, datetime)

    def test_evento_sem_summary_usa_sem_titulo(self) -> None:
        """2. Evento sem 'summary' usa '(sem título)' como fallback."""
        item = _make_timed_event(
            event_id="evt002",
            summary="",
            start_iso="2026-09-15T09:00:00Z",
            end_iso="2026-09-15T09:30:00Z",
        )
        item.pop("summary")  # remove o campo completamente
        service = _make_service_mock([item])

        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                events = adapter.list_events_for_day(date(2026, 9, 15))

        self.assertEqual(events[0].summary, "(sem título)")

    def test_evento_sem_description_e_none(self) -> None:
        """3. Evento sem 'description' resulta em description=None."""
        item = _make_timed_event(
            event_id="evt003",
            summary="Evento simples",
            start_iso="2026-09-15T14:00:00Z",
            end_iso="2026-09-15T15:00:00Z",
        )
        service = _make_service_mock([item])

        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                events = adapter.list_events_for_day(date(2026, 9, 15))

        self.assertIsNone(events[0].description)


class TestListEventsForDayAllDay(unittest.TestCase):
    """Valida conversão de evento de dia inteiro (all-day)."""

    def test_evento_allday_retorna_calendar_event_com_date(self) -> None:
        """4. Evento all-day é convertido com all_day=True e start/end como date."""
        item = _make_allday_event(
            event_id="evt_allday",
            summary="Feriado Nacional",
            start_date="2026-09-07",
            end_date="2026-09-08",
        )
        service = _make_service_mock([item])

        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                events = adapter.list_events_for_day(date(2026, 9, 7))

        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertTrue(ev.all_day)
        self.assertIsInstance(ev.start, date)
        self.assertIsInstance(ev.end, date)
        self.assertNotIsInstance(ev.start, datetime)
        self.assertEqual(ev.summary, "Feriado Nacional")


class TestListEventsForDayMultipleEvents(unittest.TestCase):
    """Valida retorno de múltiplos eventos."""

    def test_multiplos_eventos_retornam_lista_na_ordem_correta(self) -> None:
        """5. Múltiplos eventos retornam lista com todos os eventos na ordem recebida."""
        items = [
            _make_timed_event("e1", "Evento A", "2026-09-15T08:00:00Z", "2026-09-15T09:00:00Z"),
            _make_timed_event("e2", "Evento B", "2026-09-15T10:00:00Z", "2026-09-15T11:00:00Z"),
            _make_allday_event("e3", "Evento C (dia inteiro)", "2026-09-15", "2026-09-16"),
        ]
        service = _make_service_mock(items)

        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                events = adapter.list_events_for_day(date(2026, 9, 15))

        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].event_id, "e1")
        self.assertEqual(events[1].event_id, "e2")
        self.assertEqual(events[2].event_id, "e3")


class TestListEventsForDayEmpty(unittest.TestCase):
    """Valida retorno de agenda vazia."""

    def test_agenda_vazia_retorna_lista_vazia(self) -> None:
        """6. Nenhum evento no dia retorna lista vazia sem erro."""
        service = _make_service_mock([])

        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                events = adapter.list_events_for_day(date(2026, 9, 15))

        self.assertEqual(events, [])

    def test_resposta_sem_items_retorna_lista_vazia(self) -> None:
        """7. Resposta da API sem chave 'items' retorna lista vazia."""
        service = MagicMock()
        (
            service.events.return_value
            .list.return_value
            .execute.return_value
        ) = {}  # sem 'items'

        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                events = adapter.list_events_for_day(date(2026, 9, 15))

        self.assertEqual(events, [])


class TestListEventsForDayErrors(unittest.TestCase):
    """Valida conversão de erros em CalendarError."""

    def test_http_error_api_levanta_calendar_error(self) -> None:
        """8. HttpError da API é convertido em CalendarError."""
        http_resp = MagicMock()
        http_resp.status = 403
        http_resp.reason = "Forbidden"
        error = HttpError(resp=http_resp, content=b"Forbidden")

        service = MagicMock()
        (
            service.events.return_value
            .list.return_value
            .execute.side_effect
        ) = error

        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                with self.assertRaises(CalendarError) as ctx:
                    adapter.list_events_for_day(date(2026, 9, 15))

        self.assertIn("Erro da API Google Calendar", str(ctx.exception))

    def test_erro_generico_api_levanta_calendar_error(self) -> None:
        """9. Erro genérico ao chamar API é convertido em CalendarError."""
        service = MagicMock()
        (
            service.events.return_value
            .list.return_value
            .execute.side_effect
        ) = RuntimeError("conexão perdida")

        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                with self.assertRaises(CalendarError) as ctx:
                    adapter.list_events_for_day(date(2026, 9, 15))

        self.assertIn("Erro inesperado ao chamar API", str(ctx.exception))

    def test_erro_autenticacao_propaga_calendar_error(self) -> None:
        """10. CalendarError de autenticação é propagado sem alteração."""
        with patch(
            "therion.calendar.google_adapter.get_valid_credentials",
            side_effect=CalendarError("Token ausente"),
        ):
            adapter = GoogleCalendarAdapter()
            with self.assertRaises(CalendarError) as ctx:
                adapter.list_events_for_day(date(2026, 9, 15))

        self.assertIn("Token ausente", str(ctx.exception))

    def test_erro_build_service_levanta_calendar_error(self) -> None:
        """11. Falha ao criar service Google levanta CalendarError."""
        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch(
                "therion.calendar.google_adapter.build",
                side_effect=Exception("discovery falhou"),
            ):
                adapter = GoogleCalendarAdapter()
                with self.assertRaises(CalendarError) as ctx:
                    adapter.list_events_for_day(date(2026, 9, 15))

        self.assertIn("Falha ao criar serviço Google Calendar", str(ctx.exception))

    def test_evento_formato_invalido_levanta_calendar_error(self) -> None:
        """12. Evento sem 'dateTime' e sem 'date' levanta CalendarError."""
        item = {
            "id": "evt_invalido",
            "summary": "Evento inválido",
            "start": {},
            "end": {},
        }
        service = _make_service_mock([item])

        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                with self.assertRaises(CalendarError) as ctx:
                    adapter.list_events_for_day(date(2026, 9, 15))

        self.assertIn("Formato de evento inválido", str(ctx.exception))

    def test_timezone_invalida_levanta_calendar_error(self) -> None:
        """13. Fuso horário inválido levanta CalendarError controlado."""
        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build"):
                adapter = GoogleCalendarAdapter(time_zone="Fuso/Inexistente")
                with self.assertRaises(CalendarError) as ctx:
                    adapter.list_events_for_day(date(2026, 9, 15))

        self.assertIn("Fuso horário inválido ou não suportado", str(ctx.exception))


class TestListEventsApiParameters(unittest.TestCase):
    """Valida parâmetros passados à API Google Calendar."""

    def _call_and_capture(self, target_day: date, time_zone: str = "America/Sao_Paulo"):
        """Chama o adapter e retorna o mock do list() para inspeção dos parâmetros."""
        service = _make_service_mock([])
        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter(time_zone=time_zone)
                adapter.list_events_for_day(target_day)
        return service.events.return_value.list

    def test_usa_calendar_primary(self) -> None:
        """13. Chamada usa calendarId='primary'."""
        list_mock = self._call_and_capture(date(2026, 9, 15))
        _, kwargs = list_mock.call_args
        self.assertEqual(kwargs["calendarId"], "primary")

    def test_single_events_true(self) -> None:
        """14. Chamada usa singleEvents=True para expandir eventos recorrentes."""
        list_mock = self._call_and_capture(date(2026, 9, 15))
        _, kwargs = list_mock.call_args
        self.assertTrue(kwargs["singleEvents"])

    def test_order_by_start_time(self) -> None:
        """15. Chamada usa orderBy='startTime'."""
        list_mock = self._call_and_capture(date(2026, 9, 15))
        _, kwargs = list_mock.call_args
        self.assertEqual(kwargs["orderBy"], "startTime")

    def test_time_zone_passado_corretamente(self) -> None:
        """16. timeZone da chamada corresponde ao time_zone configurado no adapter."""
        list_mock = self._call_and_capture(date(2026, 9, 15), time_zone="America/Sao_Paulo")
        _, kwargs = list_mock.call_args
        self.assertEqual(kwargs["timeZone"], "America/Sao_Paulo")

    def test_time_min_e_time_max_cobrem_dia_inteiro(self) -> None:
        """17. timeMin e timeMax cobrem exatamente o dia especificado com offset adequado."""
        list_mock = self._call_and_capture(date(2026, 9, 15), time_zone="America/Sao_Paulo")
        _, kwargs = list_mock.call_args

        time_min_str = kwargs["timeMin"]
        time_max_str = kwargs["timeMax"]

        self.assertEqual("2026-09-15T00:00:00-03:00", time_min_str)
        self.assertEqual("2026-09-16T00:00:00-03:00", time_max_str)

    def test_time_min_menor_que_time_max(self) -> None:
        """18. timeMin é anterior a timeMax (intervalo válido)."""
        list_mock = self._call_and_capture(date(2026, 9, 15))
        _, kwargs = list_mock.call_args
        self.assertLess(kwargs["timeMin"], kwargs["timeMax"])


class TestAdapterDefaultTimeZone(unittest.TestCase):
    """Valida timezone padrão do adapter."""

    def test_timezone_default_e_america_sao_paulo(self) -> None:
        """19. Adapter sem time_zone explícito usa America/Sao_Paulo."""
        adapter = GoogleCalendarAdapter()
        self.assertEqual(adapter._time_zone, "America/Sao_Paulo")

    def test_timezone_customizado_e_respeitado(self) -> None:
        """20. Adapter com time_zone customizado preserva o valor."""
        adapter = GoogleCalendarAdapter(time_zone="Europe/London")
        self.assertEqual(adapter._time_zone, "Europe/London")


class TestCreateEvent(unittest.TestCase):
    """Valida criação de evento via GoogleCalendarAdapter."""

    def _make_insert_mock(self, event_id: str = "new_evt") -> MagicMock:
        service = MagicMock()
        (
            service.events.return_value
            .insert.return_value
            .execute.return_value
        ) = {
            "id": event_id,
            "summary": "Reunião",
            "start": {"dateTime": "2026-09-15T10:00:00-03:00", "timeZone": "America/Sao_Paulo"},
            "end": {"dateTime": "2026-09-15T11:00:00-03:00", "timeZone": "America/Sao_Paulo"},
        }
        return service

    def _tz(self, offset_hours: int = -3):
        return timezone(timedelta(hours=offset_hours))

    def test_create_event_usa_calendar_primary(self) -> None:
        """21. create_event usa calendarId='primary'."""
        service = self._make_insert_mock()
        insert_mock = service.events.return_value.insert
        start = datetime(2026, 9, 15, 10, 0, tzinfo=self._tz())
        end = datetime(2026, 9, 15, 11, 0, tzinfo=self._tz())
        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                adapter.create_event("Reunião", start, end)
        _, kwargs = insert_mock.call_args
        self.assertEqual(kwargs["calendarId"], "primary")

    def test_create_event_payload_summary(self) -> None:
        """22. Payload contém summary."""
        service = self._make_insert_mock()
        insert_mock = service.events.return_value.insert
        start = datetime(2026, 9, 15, 10, 0, tzinfo=self._tz())
        end = datetime(2026, 9, 15, 11, 0, tzinfo=self._tz())
        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                adapter.create_event("Stand-up", start, end)
        _, kwargs = insert_mock.call_args
        self.assertEqual(kwargs["body"]["summary"], "Stand-up")

    def test_create_event_start_end(self) -> None:
        """23. Payload contém start e end dateTime."""
        service = self._make_insert_mock()
        insert_mock = service.events.return_value.insert
        start = datetime(2026, 9, 15, 14, 0, tzinfo=self._tz())
        end = datetime(2026, 9, 15, 15, 0, tzinfo=self._tz())
        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                adapter.create_event("Reunião", start, end)
        _, kwargs = insert_mock.call_args
        self.assertIn("2026-09-15T14:00:00", kwargs["body"]["start"]["dateTime"])
        self.assertIn("2026-09-15T15:00:00", kwargs["body"]["end"]["dateTime"])

    def test_create_event_timezone(self) -> None:
        """24. Payload contém timeZone correto."""
        service = self._make_insert_mock()
        insert_mock = service.events.return_value.insert
        start = datetime(2026, 9, 15, 10, 0, tzinfo=self._tz())
        end = datetime(2026, 9, 15, 11, 0, tzinfo=self._tz())
        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter(time_zone="America/Sao_Paulo")
                adapter.create_event("Reunião", start, end)
        _, kwargs = insert_mock.call_args
        self.assertEqual(kwargs["body"]["start"]["timeZone"], "America/Sao_Paulo")
        self.assertEqual(kwargs["body"]["end"]["timeZone"], "America/Sao_Paulo")

    def test_create_event_execute_chamado(self) -> None:
        """25. execute() é chamado."""
        service = self._make_insert_mock()
        insert_mock = service.events.return_value.insert
        start = datetime(2026, 9, 15, 10, 0, tzinfo=self._tz())
        end = datetime(2026, 9, 15, 11, 0, tzinfo=self._tz())
        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                adapter.create_event("Reunião", start, end)
        insert_mock.return_value.execute.assert_called_once()

    def test_create_event_retorna_calendar_event(self) -> None:
        """26. Resposta convertida para CalendarEvent."""
        service = self._make_insert_mock(event_id="evt_abc")
        start = datetime(2026, 9, 15, 10, 0, tzinfo=self._tz())
        end = datetime(2026, 9, 15, 11, 0, tzinfo=self._tz())
        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                result = adapter.create_event("Reunião", start, end)
        self.assertIsInstance(result, CalendarEvent)
        self.assertEqual(result.event_id, "evt_abc")
        self.assertEqual(result.summary, "Reunião")
        self.assertFalse(result.all_day)

    def test_create_event_summary_vazio_rejeitado(self) -> None:
        """27. Summary vazio levanta CalendarError."""
        start = datetime(2026, 9, 15, 10, 0, tzinfo=self._tz())
        end = datetime(2026, 9, 15, 11, 0, tzinfo=self._tz())
        adapter = GoogleCalendarAdapter()
        with self.assertRaises(CalendarError) as ctx:
            adapter.create_event("", start, end)
        self.assertIn("vazio", str(ctx.exception))

    def test_create_event_start_sem_timezone_rejeitado(self) -> None:
        """28. Datetime sem timezone rejeitado."""
        start = datetime(2026, 9, 15, 10, 0)
        end = datetime(2026, 9, 15, 11, 0, tzinfo=self._tz())
        adapter = GoogleCalendarAdapter()
        with self.assertRaises(CalendarError) as ctx:
            adapter.create_event("Reunião", start, end)
        self.assertIn("timezone", str(ctx.exception))

    def test_create_event_end_menor_igual_start(self) -> None:
        """29. end <= start rejeitado."""
        start = datetime(2026, 9, 15, 11, 0, tzinfo=self._tz())
        end = datetime(2026, 9, 15, 10, 0, tzinfo=self._tz())
        adapter = GoogleCalendarAdapter()
        with self.assertRaises(CalendarError) as ctx:
            adapter.create_event("Reunião", start, end)
        self.assertIn("posterior", str(ctx.exception))

    def test_create_event_http_error_levanta_calendar_error(self) -> None:
        """30. HttpError é convertido em CalendarError."""
        service = MagicMock()
        http_resp = MagicMock()
        http_resp.status = 403
        http_resp.reason = "Forbidden"
        error = HttpError(resp=http_resp, content=b"Forbidden")
        service.events.return_value.insert.return_value.execute.side_effect = error
        start = datetime(2026, 9, 15, 10, 0, tzinfo=self._tz())
        end = datetime(2026, 9, 15, 11, 0, tzinfo=self._tz())
        with patch("therion.calendar.google_adapter.get_valid_credentials"):
            with patch("therion.calendar.google_adapter.build", return_value=service):
                adapter = GoogleCalendarAdapter()
                with self.assertRaises(CalendarError) as ctx:
                    adapter.create_event("Reunião", start, end)
        self.assertIn("Erro da API Google Calendar", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
