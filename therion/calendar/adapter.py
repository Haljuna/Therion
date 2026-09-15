"""Abstração de adapter de calendário e exceção controlada."""

from abc import ABC, abstractmethod
from datetime import date

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
