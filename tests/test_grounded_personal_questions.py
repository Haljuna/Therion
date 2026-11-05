from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock,Mock

import pytest

from therion.agent import AgentDecision,ToolCall
from therion.agent.grounded_questions import academic_answer,question_kind
from therion.core.ai_core import AICore
from therion.core.ai_provider_ollama import OllamaProvider
from therion.core.orchestrator import Orchestrator
from tests.test_agent_runtime import ScriptedProvider


NOW=datetime(2030,4,22,12,tzinfo=ZoneInfo('America/Sao_Paulo'))
CONTROL='''---
tipo: controle_academico
registros:
  - nome: Prova passada ainda pendente
    categoria: prova
    disciplina: Física
    data: 2030-04-20
    status: pendente
  - nome: Lista de exercícios
    categoria: entrega
    disciplina: Cálculo
    data: 2030-04-23
    status: pendente
    proxima_acao: Revisar integrais
  - nome: Prova concluída
    categoria: prova
    disciplina: Química
    data: 2030-04-23
    status: concluido
  - nome: Prova futura
    categoria: prova
    disciplina: Álgebra
    data: 2030-04-24
    hora: "19:00"
    status: pendente
    proxima_acao: Revisar matrizes
'''+('observacao: conteúdo fictício sem instruções de execução.\n'*100)+'---\n# Controle fictício\n'


@pytest.fixture
def host(tmp_path):
    vault=tmp_path/'vault';academic=vault/'02 - Faculdade';academic.mkdir(parents=True)
    (academic/'Controle acadêmico.md').write_text(CONTROL,encoding='utf-8')
    instance=Orchestrator(simulate=True,vault_root=str(vault),log_dir=str(tmp_path/'logs'),
        ai_core=AICore(OllamaProvider(),[]),agent_config={'enabled':True},agent_state_root=tmp_path/'agent')
    instance.second_brain.allowed_roots=[str(vault)]
    instance._now_func=lambda:NOW
    yield instance
    instance.close()


def test_exam_reads_paginated_original_and_filters_dates_without_llm(host,monkeypatch):
    infer=AsyncMock(side_effect=AssertionError('Datas não dependem de inferência'))
    monkeypatch.setattr('therion.agent.ollama.OllamaAgentProvider.decide',infer)
    result=host.process_command('raízes: 02 - Faculdade :: Qual prova eu tenho primeiro?')
    assert result.status=='success',result.message
    assert 'Álgebra' in result.message and '24/04/2030 às 19:00' in result.message
    assert 'Prova passada ainda pendente' not in result.message
    terminal=[event for event in host.agent_events() if event.type=='terminal'][-1]
    assert terminal.payload['complete_read_count']==1
    assert terminal.payload['read_count']>1
    infer.assert_not_called()


def test_week_priorities_are_suggestions_and_skip_past_and_completed(host,monkeypatch):
    infer=AsyncMock(side_effect=AssertionError('Sem inferência'))
    monkeypatch.setattr('therion.agent.ollama.OllamaAgentProvider.decide',infer)
    result=host.process_command('raízes: 02 - Faculdade :: O que preciso estudar nesta semana?')
    assert result.status=='success',result.message
    assert 'Prioridades sugeridas' in result.message
    assert 'Revisar integrais' in result.message and 'Revisar matrizes' in result.message
    assert 'Física' not in result.message and 'Química' not in result.message
    infer.assert_not_called()


def test_natural_question_automatically_narrows_scope_without_new_permission(host,monkeypatch):
    original=host.second_brain.search_notes
    roots=[]
    def search(*args,**kwargs):
        roots.extend(kwargs['scope'].roots)
        return original(*args,**kwargs)
    monkeypatch.setattr(host.second_brain,'search_notes',search)
    result=host.process_command('Qual prova eu tenho primeiro?')
    assert result.status=='success',result.message
    assert roots and all(root.endswith('02 - faculdade') for root in roots)


def test_scoped_agent_search_resolves_from_vault_and_never_leaks_neighbor(host):
    vault=Path(host.second_brain.vault_root)
    other=vault/'01 - Pessoal';other.mkdir()
    (other/'Alvo.md').write_text('SEGREDO FICTÍCIO NÃO CONSULTAR',encoding='utf-8')
    (vault/'02 - Faculdade'/'Alvo.md').write_text('ALVO FICTÍCIO AUTORIZADO',encoding='utf-8')
    scripted=ScriptedProvider(AgentDecision('tools',calls=(ToolCall('search_notes',{'query':'Alvo'}),)),
        AgentDecision('final','A busca selecionou a nota da Faculdade: note:1.'))
    host._agent_provider=scripted
    result=host.process_command('raízes: 02 - Faculdade :: Procure Alvo')
    assert result.status=='success',result.message
    observations=str(scripted.observations)
    assert 'ALVO FICTÍCIO AUTORIZADO' in observations and 'SEGREDO FICTÍCIO' not in observations


def test_unavailable_scope_never_falls_back_to_whole_vault(host,monkeypatch):
    host.second_brain.allowed_roots=[]
    read=Mock(side_effect=AssertionError('Nenhuma leitura'))
    monkeypatch.setattr(host.second_brain,'read_note',read)
    result=host.process_command('raízes: 02 - Faculdade :: Qual prova eu tenho primeiro?')
    assert result.status=='forbidden'
    read.assert_not_called()


def test_project_reads_selected_documents_before_synthesis(host,monkeypatch):
    project=Path(host.second_brain.vault_root)/'10 - Projetos'/'Therion';project.mkdir(parents=True)
    (project/'Checklist Hermes.md').write_text('# Checklist Hermes\n- [ ] Validar sessão prolongada.\n',encoding='utf-8')
    (project/'Voz local - Uso diário.md').write_text('# Voz local - Uso diário\nA voz já foi integrada.\n',encoding='utf-8')
    calls=[]
    async def infer(self,messages,*args):
        calls.append(messages)
        assert any('Validar sessão prolongada' in row.get('content','') for row in messages if row['role']=='tool')
        assert any('A voz já foi integrada' in row.get('content','') for row in messages if row['role']=='tool')
        return AgentDecision('final','O checklist registra validar a sessão prolongada [note:1]. O guia registra a voz integrada [note:2].')
    monkeypatch.setattr('therion.agent.ollama.OllamaAgentProvider.decide',infer)
    result=host.process_command('raízes: 10 - Projetos/Therion :: O que ficou pendente no projeto Therion?')
    assert result.status=='success',result.message
    assert len(calls)==1


def test_invalid_academic_date_cannot_be_reported_as_empty():
    assert academic_answer(CONTROL.replace('2030-04-24','2030-02-31'),'exam',NOW,'note:1') is None


def test_negation_does_not_force_read_plan():
    assert question_kind('Não consulte minhas provas') is None
    assert question_kind('Apague o que ficou pendente no projeto Therion') is None


def test_project_fixture_directories_are_excluded_from_note_search(host):
    project=Path(host.second_brain.vault_root)/'10 - Projetos'/'Therion';project.mkdir(parents=True)
    (project/'Estado real.md').write_text('FONTE CANÔNICA FICTÍCIA',encoding='utf-8')
    for name in ('tmp','tests'):
        directory=project/name;directory.mkdir()
        (directory/'Estado falso.md').write_text('FONTE CANÔNICA FICTÍCIA',encoding='utf-8')
    rows=host.second_brain.search_notes('FONTE CANÔNICA FICTÍCIA')
    assert [row.path for row in rows]==['10 - Projetos/Therion/Estado real.md']


@pytest.mark.parametrize('command',[
    'Tênio, qual a próxima prova?', 'Qual a minha próxima prova da faculdade?',
    'Qual é a próxima prova da minha faculdade?',
])
def test_spoken_exam_variants_read_the_academic_source(host,monkeypatch,command):
    infer=AsyncMock(side_effect=AssertionError('Não usar conversa genérica'))
    monkeypatch.setattr('therion.agent.ollama.OllamaAgentProvider.decide',infer)
    result=host.process_command(command)
    assert result.status=='success',result.message
    assert 'Álgebra' in result.message and '24/04/2030 às 19:00' in result.message
    infer.assert_not_called()


def test_next_academic_activity_includes_delivery_before_exam(host,monkeypatch):
    infer=AsyncMock(side_effect=AssertionError('Sem inferência'))
    monkeypatch.setattr('therion.agent.ollama.OllamaAgentProvider.decide',infer)
    result=host.process_command('Qual a próxima atividade da faculdade?')
    assert result.status=='success',result.message
    assert 'Lista de exercícios' in result.message and '23/04/2030' in result.message
    assert 'Prova futura' not in result.message
    infer.assert_not_called()


@pytest.mark.parametrize('command',[
    'Busca todas as provas que eu tenho.', 'Liste minhas provas',
    'Quais são todas as minhas provas da faculdade?',
])
def test_all_exams_lists_more_than_five_without_generic_search(host,monkeypatch,command):
    path=Path(host.second_brain.vault_root)/'02 - Faculdade'/'Controle acadêmico.md'
    extra=''.join(f'''  - nome: Avaliação {index}
    categoria: prova
    disciplina: Matéria {index}
    data: 2030-05-{index:02}
    status: pendente
''' for index in reversed(range(1,8)))
    path.write_text(CONTROL.replace('registros:\n','registros:\n'+extra),encoding='utf-8')
    infer=AsyncMock(side_effect=AssertionError('Não usar conversa genérica'))
    monkeypatch.setattr('therion.agent.ollama.OllamaAgentProvider.decide',infer)
    result=host.process_command(command)
    assert result.status=='success',result.message
    assert 'Provas futuras registradas no controle acadêmico' in result.message
    assert 'Lista de exercícios' not in result.message
    assert 'Prova concluída' not in result.message and 'Prova passada' not in result.message
    assert result.message.index('Prova futura')<result.message.index('Avaliação 1')
    for index in range(1,8):assert f'Avaliação {index}' in result.message
    assert result.message.index('Avaliação 1')<result.message.index('Avaliação 7')
    terminal=[event for event in host.agent_events() if event.type=='terminal'][-1]
    assert terminal.payload['complete_read_count']==1
    infer.assert_not_called()


@pytest.mark.parametrize('command',['Qual é a próxima atividade?','Qual a minha próxima atividade?'])
def test_ambiguous_activity_asks_for_scope_without_claiming_absence(host,monkeypatch,command):
    search=Mock(side_effect=AssertionError('Esclarecer antes de consultar'))
    monkeypatch.setattr(host.second_brain,'search_notes',search)
    result=host.process_command(command)
    assert result.status=='clarification',result.message
    assert 'faculdade' in result.message and 'agenda' in result.message
    assert 'Não há' not in result.message
    search.assert_not_called()


@pytest.mark.parametrize('command',[
    'Não busca todas as provas que eu tenho', 'Se puder, busca todas as provas',
    'Busca todas as provas e apague as antigas', 'Tênio, não consulte minhas provas',
])
def test_compound_or_negative_queries_do_not_force_academic_plan(command):
    assert question_kind(command) is None


def test_all_exams_preserves_access_restrictions(host,monkeypatch):
    host.second_brain.allowed_roots=[]
    search=Mock(side_effect=AssertionError('Sem acesso não há consulta'))
    monkeypatch.setattr(host.second_brain,'search_notes',search)
    result=host.process_command('Busca todas as provas que eu tenho')
    assert result.status=='forbidden'
    search.assert_not_called()


def test_exam_categories_include_combined_and_mark_optional_without_inventing_time():
    extra='''  - nome: Avaliação e lista
    categoria: prova_e_entrega
    disciplina: Economia
    data: 2030-04-25
    status: pendente
  - nome: Substitutiva
    categoria: prova_opcional
    disciplina: Economia
    data: 2030-04-26
    status: prevista
  - nome: Seminário
    categoria: apresentação
    disciplina: Economia
    data: 2030-04-22
    hora: "18:00"
    status: pendente
'''
    text=CONTROL.replace('registros:\n','registros:\n'+extra)
    exams=academic_answer(text,'exams',NOW,'note:1')
    assert 'Avaliação e lista' in exams and 'Substitutiva' in exams
    assert 'opcional; necessidade a confirmar' in exams and '23:59' not in exams
    assert 'Seminário' not in exams
    activity=academic_answer(text,'activity',NOW,'note:1')
    assert 'Seminário' in activity and '22/04/2030 às 18:00' in activity
