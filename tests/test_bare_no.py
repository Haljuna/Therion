"""'Não' solto, sem proposta pendente (ex.: recusa a uma oferta da IA), é uma recusa educada."""
from therion.core.orchestrator import Orchestrator


def test_bare_no_without_proposal_is_polite():
    result = Orchestrator(simulate=True).process_command('Não.')
    assert (result.status, result.message) == ('success', 'Tudo bem.')


def test_bare_yes_without_proposal_still_explains():
    result = Orchestrator(simulate=True).process_command('Sim')
    assert 'proposta pendente' in result.message
