"""Modelos de dados para o módulo de calendário."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Union


@dataclass
class CalendarEvent:
    """Representação mínima de um evento de calendário."""

    event_id: str
    summary: str
    start: Union[date, datetime]
    end: Union[date, datetime]
    all_day: bool
    description: str | None = None
