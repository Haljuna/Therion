"""SKILL-002 — Planejar meu dia.

Skill read-only que combina eventos do calendário com contexto do
Segundo Cérebro para fornecer um panorama do dia.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from therion.calendar.adapter import CalendarAdapter, CalendarError
from therion.context.second_brain import SecondBrainReader

_READ_ONLY_WARNING = "[Leitura apenas — nenhuma alteração foi realizada]"

_SEARCH_TERMS = ("prioridades", "tarefas")
_MAX_RESULTS_PER_TERM = 3


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
        second_brain: SecondBrainReader,
    ) -> None:
        self._calendar = calendar
        self._second_brain = second_brain

    def execute(self, today: Optional[date] = None) -> SkillResult:
        """Executa o planejamento diário.

        Args:
            today: Data de referência. Se None, usa date.today().
        """
        if today is None:
            today = date.today()

        calendar_ok = True
        events: list = []
        context_results: list[str] = []

        # --- 1. Calendário ---
        if self._calendar is None:
            calendar_ok = False
        else:
            try:
                events = self._calendar.list_events_for_day(today)
            except CalendarError:
                calendar_ok = False

        # --- 2. Segundo Cérebro ---
        second_brain_ok = True
        for term in _SEARCH_TERMS:
            try:
                results = self._second_brain.search_notes(
                    term, max_results=_MAX_RESULTS_PER_TERM
                )
                for r in results:
                    context_results.append(f"- {r.snippet}")
            except Exception:
                second_brain_ok = False

        # --- 3. Avaliar status ---
        if not calendar_ok and not second_brain_ok:
            return SkillResult(
                skill_id=self.SKILL_ID,
                status="unavailable",
                message=(
                    "Calendário e Segundo Cérebro indisponíveis. "
                    "Nenhum dado disponível para planejamento.\n\n"
                    f"{_READ_ONLY_WARNING}"
                ),
            )

        partial = not calendar_ok or not second_brain_ok

        # --- 4. Montar mensagem ---
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

        if context_results:
            sections.append("Contexto:")
            sections.extend(context_results)

        next_commitment = ""
        if timed:
            first = timed[0]
            t = first.start
            next_commitment = (
                f"\nPróximo compromisso: {first.summary} — "
                f"{t.hour:02d}:{t.minute:02d}"
            )

        status_label = "partial" if partial else "success"

        message = "\n".join(sections) if sections else "Nenhum evento para hoje."
        message += next_commitment
        message += f"\n\n{_READ_ONLY_WARNING}"

        return SkillResult(
            skill_id=self.SKILL_ID,
            status=status_label,
            message=message,
            data={
                "timed_events": len(timed),
                "all_day_events": len(all_day),
                "context_snippets": len(context_results),
            },
        )
