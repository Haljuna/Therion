"""Fluxos de busca natural, resumo aceito e leitura da fonte numerada."""
from unittest.mock import MagicMock
import pytest
from therion.core.ai_core import AICore
from therion.core.ai_provider import AIResponse
from therion.core.intent import IntentRecognizer
from therion.core.orchestrator import Orchestrator


@pytest.mark.parametrize('subject', ['Aetherion', 'Circuitos Lógicos'])
@pytest.mark.parametrize('prefix', ['informações sobre ', 'informacoes sobre ', 'materiais a respeito de ', 'sobre ', ''])
def test_natural_search_strips_only_request_introduction(subject, prefix):
    intent = IntentRecognizer().parse('Busque no Segundo Cérebro '+prefix+subject)
    assert intent.target == subject


@pytest.fixture
def assistant(tmp_path):
    vault = tmp_path/'vault';root=vault/'10 - Projetos'/'Therion';root.mkdir(parents=True)
    texts = ['# Aetherion\nProjeto inteiramente fictício para este teste.',
             '# Objetivos\nAetherion: experimentar progresso.', '# Perfil\nAetherion: estudo fictício.',
             '# Experiência\nAetherion: interação fictícia.',
             '# Personagem e Classes\nAetherion: representação de progresso.\n' + 'Introdução de teste. '*30 +
             '\nLista completa de classes fictícias: Explorador, Artífice e Guardião. São três classes.']
    names=['Aetherion.md','a-Objetivos.md','b-Perfil.md','c-Experiencia.md','d-Personagem e Classes.md']
    for name,text in zip(names,texts):(root/name).write_text(text,encoding='utf-8')
    provider=MagicMock();provider.describe_result.return_value='Encontrei cinco notas fictícias. Quer que eu resuma os trechos disponíveis?'
    provider.generate.return_value=AIResponse(type='chat',message='Três classes fictícias.',intent=None,arguments={})
    orch=Orchestrator(vault_root=str(vault),log_dir=str(tmp_path/'logs'),ai_core=AICore(provider,[]))
    yield orch,provider,root
    orch.close()


def test_yes_after_summary_offer_summarizes_read_only_results(assistant):
    orch,provider,_=assistant
    assert orch.process_command('Busque no Segundo Cérebro informações sobre Aetherion').status=='success'
    provider.describe_result.return_value='Os trechos tratam de progresso e personagens fictícios.'
    result=orch.process_command('sim')
    assert result.status=='success' and 'Resumo dos trechos' in result.message
    assert 'proposta pendente' not in result.message
    assert provider.describe_result.call_args.args[1]['kind']=='search'


@pytest.mark.parametrize('change',['source','scope','expire','clear'])
def test_summary_offer_cannot_reuse_stale_or_revoked_search(assistant,change):
    orch,provider,root=assistant
    orch.process_command('Busque no Segundo Cérebro Aetherion')
    if change=='source':(root/'Aetherion.md').write_text('Outra versão.',encoding='utf-8')
    elif change=='scope':orch.second_brain.allowed_roots=[]
    elif change=='expire':
        expired=orch._search_snapshot[2]+301
        orch._language_clock=lambda:expired
    else:orch.clear_session()
    provider.describe_result.reset_mock()
    result=orch.process_command('resuma os trechos disponíveis')
    assert result.status!='success'
    provider.describe_result.assert_not_called()


def test_numbered_detail_reads_full_note_before_answering_count(assistant):
    orch,provider,root=assistant
    orch.process_command('Busque no Segundo Cérebro Aetherion')
    provider.describe_result.return_value='A nota descreve três classes fictícias.'
    result=orch.process_command('fale mais sobre o trecho 5')
    assert result.status=='success'
    evidence=provider.describe_result.call_args.args[1]
    assert evidence['kind']=='note' and 'São três classes' in evidence['content']
    orch.process_command('Quantas classes tem no Aetherion?')
    assert 'São três classes' in provider.generate.call_args.kwargs['context']['last_tool_evidence']['content']


def test_related_search_requires_all_subject_words_and_does_not_rename_project(assistant):
    orch,_,_=assistant
    result=orch.process_command('Busque no Segundo Cérebro classes do Aetherion')
    assert 'Personagem e Classes.md' in result.message
    result=orch.process_command('Busque no Segundo Cérebro classes do Ethereum')
    assert 'não encontrei' in result.message and 'Personagem e Classes.md' not in result.message


def test_quoted_literal_is_not_cleaned_or_expanded(assistant):
    orch,_,_=assistant
    result=orch.process_command('Busque no Segundo Cérebro "informações sobre Aetherion"')
    assert 'não encontrei' in result.message
    assert orch.intent_recognizer.parse('Busque no Segundo Cérebro "sobre Aetherion"').target=='"sobre Aetherion"'


def test_yes_without_actual_offer_does_not_invoke_summary(assistant):
    orch,provider,_=assistant;provider.describe_result.return_value='Encontrei notas fictícias.'
    orch.process_command('Busque no Segundo Cérebro Aetherion');provider.describe_result.reset_mock()
    assert orch.process_command('sim').status=='cancelled'
    provider.describe_result.assert_not_called()
