"""Registry estático de Skills do Therion."""

from therion.skills.plan_day import PlanDaySkill

SKILLS: dict[str, type] = {
    "SKILL-002": PlanDaySkill,
}


def get_skill(skill_id: str) -> type:
    """Retorna a classe da Skill registrada.

    Raises:
        KeyError: Se skill_id não estiver registrado.
    """
    try:
        return SKILLS[skill_id]
    except KeyError:
        raise KeyError(f"Skill '{skill_id}' não registrada.") from None


def list_skills() -> list[str]:
    """Retorna IDs de todas as Skills registradas."""
    return list(SKILLS.keys())
