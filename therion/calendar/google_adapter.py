"""Adapter Google Calendar para listar e criar eventos."""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from therion.calendar.adapter import CalendarAdapter, CalendarError
from therion.calendar.auth import get_valid_credentials
from therion.calendar.models import CalendarEvent


class GoogleCalendarAdapter(CalendarAdapter):
    """Adapter Google Calendar."""

    def __init__(self, time_zone: str = "America/Sao_Paulo") -> None:
        self._time_zone = time_zone

    def _get_service(self):
        """Retorna serviço Google Calendar autenticado."""
        try:
            creds = get_valid_credentials()
        except CalendarError:
            raise
        except Exception as e:
            raise CalendarError(f"Erro de autenticação: {e}") from e

        try:
            return build("calendar", "v3", credentials=creds, cache_discovery=False)
        except Exception as e:
            raise CalendarError(f"Falha ao criar serviço Google Calendar: {e}") from e

    def _get_tz(self):
        """Retorna ZoneInfo do timezone configurado."""
        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            return ZoneInfo(self._time_zone)
        except ZoneInfoNotFoundError as e:
            raise CalendarError(f"Fuso horário inválido ou não suportado: '{self._time_zone}'.") from e

    def list_events_for_day(self, day: date) -> list[CalendarEvent]:
        """Lista eventos de um dia específico.
        
        Args:
            day: Data para buscar eventos.
        
        Returns:
            Lista de CalendarEvent ordenados por startTime.
        
        Raises:
            CalendarError: Em erro de autenticação, API, ou conversão.
        """
        service = self._get_service()
        tz = self._get_tz()

        start_of_day = datetime.combine(day, datetime.min.time(), tzinfo=tz)
        end_of_day = start_of_day + timedelta(days=1)

        time_min = start_of_day.isoformat()
        time_max = end_of_day.isoformat()

        try:
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=time_min,
                    timeMax=time_max,
                    timeZone=self._time_zone,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except HttpError as e:
            raise CalendarError(f"Erro da API Google Calendar: {e}") from e
        except Exception as e:
            raise CalendarError(f"Erro inesperado ao chamar API: {e}") from e

        items = events_result.get("items", [])
        return [self._convert_event(item) for item in items]

    def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
    ) -> CalendarEvent:
        """Cria um evento no calendário.
        
        Args:
            summary: Título do evento (obrigatório, não vazio).
            start: Data/hora de início (timezone-aware).
            end: Data/hora de término (timezone-aware, deve ser posterior a start).
        
        Returns:
            CalendarEvent criado com event_id preenchido.
        
        Raises:
            CalendarError: Se summary vazio, datetimes sem timezone,
                          end <= start, ou erro ao acessar o calendário.
        """
        if not summary or not summary.strip():
            raise CalendarError("Título do evento não pode ser vazio.")
        
        if start.tzinfo is None:
            raise CalendarError("Data/hora de início deve conter timezone.")
        
        if end.tzinfo is None:
            raise CalendarError("Data/hora de término deve conter timezone.")
        
        if end <= start:
            raise CalendarError("Data/hora de término deve ser posterior ao início.")
        
        service = self._get_service()
        
        body = {
            "summary": summary.strip(),
            "start": {
                "dateTime": start.isoformat(),
                "timeZone": self._time_zone,
            },
            "end": {
                "dateTime": end.isoformat(),
                "timeZone": self._time_zone,
            },
        }
        
        try:
            result = service.events().insert(
                calendarId="primary",
                body=body,
            ).execute()
        except HttpError as e:
            raise CalendarError(f"Erro da API Google Calendar: {e}") from e
        except Exception as e:
            raise CalendarError(f"Erro inesperado ao criar evento: {e}") from e
        
        return self._convert_event(result)

    def _convert_event(self, item: dict[str, Any]) -> CalendarEvent:
        """Converte evento da API Google para CalendarEvent."""
        event_id = item.get("id", "")
        summary = item.get("summary", "(sem título)")
        description = item.get("description")

        start = item.get("start", {})
        end = item.get("end", {})

        if "dateTime" in start:
            start_dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00"))
            all_day = False
        elif "date" in start:
            start_dt = date.fromisoformat(start["date"])
            end_dt = date.fromisoformat(end["date"])
            all_day = True
        else:
            raise CalendarError(f"Formato de evento inválido: {item}")

        return CalendarEvent(
            event_id=event_id,
            summary=summary,
            start=start_dt,
            end=end_dt,
            all_day=all_day,
            description=description,
        )