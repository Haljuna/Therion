"""SKILL-002 — Planejar meu dia.

Skill read-only que fornece um panorama determinístico da agenda do dia.
Na versão atual (Em teste), consulta somente o calendário.
Notas pessoais de tarefas serão consultadas quando existir uma fonte
explicitamente definida e autorizada.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Optional

from therion.calendar.adapter import CalendarAdapter, CalendarError
from therion.calendar.dialogue import partition_events, event_start

_READ_ONLY_WARNING = "[Leitura apenas — nenhuma alteração foi realizada]"


@dataclass
class SkillResult:
    """Resultado estruturado de execução de uma Skill."""

    skill_id: str
    status: str  # "success" | "partial" | "unavailable"
    message: str
    data: Optional[dict] = field(default=None)


class PlanDaySkill:
    """Skill de planejamento diário read-only (SKILL-002)."""

    SKILL_ID = "SKILL-002"

    def __init__(
        self,
        calendar: Optional[CalendarAdapter],
        second_brain: None = None,
    ) -> None:
        self._calendar = calendar

    def execute(self, today: Optional[date] = None, *, now: Optional[datetime] = None) -> SkillResult:
        """Executa o planejamento diário.

        Args:
            today: Data de referência. Se None, usa o dia de now.
            now: Relógio com fuso configurado, injetável para classificação dos eventos.
        """
        now = now or datetime.now(ZoneInfo('America/Sao_Paulo'))
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo('America/Sao_Paulo'))
        if today is None:
            today = now.date()

        # --- Calendário ---
        events: list = []
        calendar_ok = True
        if self._calendar is None:
            calendar_ok = False
        else:
            try:
                events = self._calendar.list_events_for_day(today)
            except CalendarError:
                calendar_ok = False

        if not calendar_ok:
            return SkillResult(
                skill_id=self.SKILL_ID,
                status="partial",
                message=(
                    "Calendário não disponível.\n\n"
                    f"{_READ_ONLY_WARNING}"
                ),
            )

        # --- Montar mensagem ---
        sections: list[str] = []

        parts = partition_events(events, now)
        timed = sorted(parts['past'] + parts['ongoing'] + parts['future'], key=lambda e: event_start(e, now.tzinfo))
        all_day = parts['all_day']

        if timed:
            sections.append("Compromissos:")
            for i, evt in enumerate(timed, 1):
                t = event_start(evt, now.tzinfo)
                sections.append(f"{i}. {evt.summary} — {t.hour:02d}:{t.minute:02d}")

        if all_day:
            sections.append("Dia inteiro:")
            for i, evt in enumerate(all_day, 1):
                sections.append(f"{i}. {evt.summary} — Dia inteiro")

        next_commitment = ""
        if parts['ongoing']:
            next_commitment += '\nEm andamento: ' + ', '.join(e.summary for e in parts['ongoing'])
        if parts['future']:
            first = parts['future'][0]
            t = event_start(first, now.tzinfo)
            next_commitment += (
                f"\nPróximo compromisso: {first.summary} — "
                f"{t.hour:02d}:{t.minute:02d}"
            )
        else:
            next_commitment += '\nNenhum próximo compromisso com horário nos eventos consultados.'

        message = "\n".join(sections) if sections else "Nenhum evento para hoje."
        message += next_commitment
        message += f"\n\n{_READ_ONLY_WARNING}"

        return SkillResult(
            skill_id=self.SKILL_ID,
            status="success",
            message=message,
            data={
                "timed_events": len(timed),
                "all_day_events": len(all_day),
            },
        )
