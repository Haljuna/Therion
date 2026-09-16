"""Abstração de adapter de calendário e exceção controlada."""

from abc import ABC, abstractmethod
from datetime import date, datetime

from therion.calendar.models import CalendarEvent


class CalendarError(Exception):
    """Exceção controlada para erros de calendário."""


class CalendarAdapter(ABC):
    """Interface para adapters de calendário."""

    @abstractmethod
    def list_events_for_day(self, day: date) -> list[CalendarEvent]:
        """Retorna eventos de um dia específico.
        
        Raises:
            CalendarError: Se houver erro ao acessar o calendário.
        """

    @abstractmethod
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
