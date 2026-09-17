"""SKILL-002 — Planejar meu dia.

Skill read-only que fornece um panorama determinístico da agenda do dia.
Na versão atual (Em teste), consulta somente o calendário.
Notas pessoais de tarefas serão consultadas quando existir uma fonte
explicitamente definida e autorizada.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from therion.calendar.adapter import CalendarAdapter, CalendarError

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

    def execute(self, today: Optional[date] = None) -> SkillResult:
        """Executa o planejamento diário.

        Args:
            today: Data de referência. Se None, usa date.today().
        """
        if today is None:
            today = date.today()

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

        timed = [e for e in events if not e.all_day]
        all_day = [e for e in events if e.all_day]

        timed.sort(key=lambda e: e.start)

        if timed:
            sections.append("Compromissos:")
            for i, evt in enumerate(timed, 1):
                t = evt.start
                sections.append(f"{i}. {evt.summary} — {t.hour:02d}:{t.minute:02d}")

        if all_day:
            sections.append("Dia inteiro:")
            for i, evt in enumerate(all_day, 1):
                sections.append(f"{i}. {evt.summary} — Dia inteiro")

        next_commitment = ""
        if timed:
            first = timed[0]
            t = first.start
            next_commitment = (
                f"\nPróximo compromisso: {first.summary} — "
                f"{t.hour:02d}:{t.minute:02d}"
            )

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
