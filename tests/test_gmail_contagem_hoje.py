"""\"Quantos e-mails eu tenho hoje?\" responde pela regra local, sem o modelo e sem página de 10."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from therion.agent.mailbox import mail_count_request, mail_today_request
from tests.test_agent_basic_questions import enable
from tests.test_personal_context_flow import case  # noqa: F401  (fixture)

HOJE = ['Quantos e-mails eu tenho hoje?', 'Quantos e-mails chegaram hoje?',
        'Quantos e-mails eu recebi hoje?', 'Quantos emails tenho hoje?']


@pytest.mark.parametrize('phrase', HOJE)
def test_frases_com_hoje_caem_na_regra_de_contagem(phrase):
    assert mail_count_request(phrase) and mail_today_request(phrase)


def test_sem_hoje_continua_contando_nao_lidos():
    assert mail_count_request('Quantos e-mails eu tenho?') and not mail_today_request('Quantos e-mails eu tenho?')
    assert not mail_count_request('quantos e-mails eu mandei hoje pro João')


class _Client:
    """Caixa falsa: 'hoje' tem 507 ids (mais que uma página de 500), 3 deles sem ler."""
    def __init__(self):
        self.queries = []

    def search(self, query, page=None, limit=None):
        self.queries.append((query, page, limit))
        if 'is:unread' in query:
            return dict(messages=[{'id': str(i)} for i in range(3)])
        if page is None:
            return dict(messages=[{'id': str(i)} for i in range(500)], next_page='p2')
        return dict(messages=[{'id': 'x'}] * 7)


def _host(case, client):
    host, provider, _, _ = case
    agent = enable(host)
    host._agent_config['gmail_enabled'] = True
    host._gmail_adapter_factory = lambda mode: client
    host._now_func = lambda: datetime(2026, 11, 22, 15, 4, 0)
    return host, agent, provider


def test_hoje_da_os_dois_numeros_e_nao_para_em_10(case):
    client = _Client()
    host, agent, provider = _host(case, client)
    result = host.process_command('Quantos e-mails eu tenho hoje?')
    assert result.status == 'success'
    assert result.message == 'Chegaram 507 e-mails hoje; 3 ainda não foram lidos.'
    assert not agent.observations and provider.mock_calls == []
    assert all(limit == 500 for _, _, limit in client.queries)
    midnight = int(datetime(2026, 11, 22).astimezone(host._calendar_now().tzinfo).timestamp())
    assert client.queries[0][0] == f'in:inbox after:{midnight}'
    assert client.queries[-1][0] == f'in:inbox after:{midnight} is:unread'


def test_hoje_sem_nada_e_tudo_lido(case):
    client = SimpleNamespace(search=lambda q, page=None, limit=None: dict(messages=[]))
    host, _, _ = _host(case, client)
    assert host.process_command('Quantos e-mails chegaram hoje?').message == 'Nenhum e-mail chegou hoje.'
    client.search = lambda q, page=None, limit=None: dict(messages=[{'id': 'a'}] * (0 if 'unread' in q else 12))
    assert host.process_command('Quantos e-mails recebi hoje?').message == 'Chegaram 12 e-mails hoje; todos já foram lidos.'
