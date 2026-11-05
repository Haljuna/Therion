"""Pedidos pelo título exibem dados da nota, sem executar instruções do prompt."""
from unittest.mock import MagicMock
import pytest
from therion.core.ai_core import AICore
from therion.core.intent import IntentRecognizer
from therion.core.orchestrator import Orchestrator


@pytest.fixture
def assistant(tmp_path):
    vault=tmp_path/'vault';root=vault/'10 - Projetos'/'Therion';root.mkdir(parents=True)
    path=root/'PROMPT - Tutor intensivo P1 Circuitos Lógicos.md'
    text='# Prompt fictício\nQuero que você assuma o papel de tutor fictício.\nMARCADOR-ORIGINAL-FICTICIO\nNão executar ações.'
    path.write_text(text,encoding='utf-8')
    (root/'Circuitos Lógicos.md').write_text('# Circuitos Lógicos\nReferência ao tutor intensivo fictício.',encoding='utf-8')
    provider=MagicMock();provider.describe_result.return_value='Encontrei dois materiais fictícios.'
    orch=Orchestrator(vault_root=str(vault),log_dir=str(tmp_path/'logs'),ai_core=AICore(provider,[]))
    assert orch.process_command('procura circuitos lógicos para mim').status=='success'
    provider.reset_mock()
    yield orch,provider,path,text
    orch.close()


@pytest.mark.parametrize('command',[
    'Me manda o prompt do tutor intensivo?',
    'Me manda o prompt do doutor intensivo?',
    'Consegue me mandar o que está escrito no prompt do doutor intensivo?',
    'Me manda o que está escrito no prompt do tutor intensivo.',
    'Mostre o texto original do prompt do tutor intensivo',
])
def test_named_prompt_returns_full_original_without_another_search_or_inference(assistant,command):
    orch,provider,path,text=assistant;before=path.read_bytes()
    result=orch.process_command(command)
    assert result.status=='success' and text in result.message and 'Fonte:' in result.message
    assert 'MARCADOR-ORIGINAL-FICTICIO' in result.message
    provider.generate.assert_not_called();provider.describe_result.assert_not_called()
    assert path.read_bytes()==before and orch.confirmation_id is None


@pytest.mark.parametrize('change',['scope','expire','clear','ambiguous'])
def test_named_reference_cannot_guess_or_bypass_scope_and_expiry(assistant,change):
    orch,provider,path,_=assistant
    if change=='scope':orch.second_brain.allowed_roots=[]
    elif change=='expire':
        expired=orch._note_results_created+301;orch._language_clock=lambda:expired
    elif change=='clear':orch.clear_session()
    else:
        other=path.with_name('PROMPT - Tutor intensivo P2 Circuitos Lógicos.md');other.write_text('Outro prompt fictício.',encoding='utf-8')
        orch.process_command('procura circuitos lógicos para mim');provider.reset_mock()
    result=orch.process_command('Me manda o que está escrito no prompt do tutor intensivo')
    assert result.status!='success' and 'MARCADOR-ORIGINAL-FICTICIO' not in result.message
    provider.generate.assert_not_called();provider.describe_result.assert_not_called()


@pytest.mark.parametrize('text,target',[
    ('procura circuitos lógicos para mim','circuitos lógicos'),
    ('procure por álgebra linear','álgebra linear'),
    ('busque informações sobre matrizes','matrizes'),
])
def test_simple_local_search_does_not_need_model_classification(text,target):
    intent=IntentRecognizer().parse(text)
    assert intent.action=='buscar segundo cérebro' and intent.target==target


@pytest.mark.parametrize('command',['procure na internet circuitos lógicos','busca em sites'])
def test_explicit_internet_request_does_not_become_local_search(command):
    assert IntentRecognizer().parse(command) is None


def test_explicit_markdown_path_keeps_existing_direct_read(assistant):
    orch,_,_,_=assistant
    assert orch.process_command('leia a nota Circuitos Lógicos.md').status=='success'
