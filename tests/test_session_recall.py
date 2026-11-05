"""Consulta da sessão: evidência literal, limites e separação de autoridade."""

import tempfile
from unittest.mock import MagicMock

import pytest

from therion.core.orchestrator import Orchestrator
from therion.memory.session_recall import context_turns, recall_answer, search, spoken_recall
from therion.memory.working_memory import Turn


def turns(*entries):
    return [Turn(role, text, index + 1) for index, (role, text) in enumerate(entries)]


def test_spoken_recall_preserves_authorship_and_authority_limits():
    history = turns(('user', 'Estou estudando Álgebra Linear.'),
                    ('therion', 'Sugiro revisar Álgebra Linear.'))
    visual = recall_answer(history, 'Mostre no histórico Álgebra Linear')
    spoken = spoken_recall(visual)
    assert '[Você, mensagem 1]' in visual
    assert 'mensagem 1' not in spoken
    assert 'Você disse: Estou estudando Álgebra Linear.' in spoken
    assert 'Eu respondi: Sugiro revisar Álgebra Linear.' in spoken
    assert 'não comprovam uma decisão ou autorização' in spoken


def test_spoken_name_uses_corrected_declaration_without_reading_citation():
    visual = recall_answer(turns(('user', 'Meu nome é Marcus.'),
                                ('user', 'Corrigindo: meu nome é Marcos.')), 'Qual é meu nome?')
    assert spoken_recall(visual) == 'Você me disse que seu nome é Marcos.'
    assert 'mensagem 2' in visual


def test_name_after_many_messages_and_correction():
    history = turns(("user", "Esta é a primeira mensagem. Meu nome é Marcus."))
    history += [Turn("user", f"Outro assunto {index}", index + 2) for index in range(100)]
    assert "Marcus" in recall_answer(history, "qual o meu nome?")
    history.append(Turn("user", "Corrigindo: meu nome é Marcos.", 102))
    answer = recall_answer(history, "Qual é meu nome?")
    assert "Marcos" in answer
    assert "Marcus" not in answer
    assert "mensagem 102" in answer


@pytest.mark.parametrize("text", [
    'O Thérion sugeriu: meu nome é João.',
    '"Meu nome é João."',
    'Qual é meu nome?',
    'Um exemplo. Meu nome é João.',
    'O nome do meu amigo é João.',
])
def test_non_declarations_are_not_personal_facts(text):
    assert "Não encontrei" in recall_answer(turns(("user", text)), "qual meu nome?")


def test_assistant_cannot_define_users_name():
    assert "Não encontrei" in recall_answer(
        turns(("therion", "Meu nome é Marcus.")), "qual meu nome?",
    )


def test_topic_recovery_quotes_both_sources_without_asserting_decision():
    history = turns(
        ("user", "Quero lazer das 18 às 19."),
        ("therion", "Sugiro lazer das 17 às 18."),
        ("user", "Decidimos manter lazer das 18 às 19."),
    )
    answer = recall_answer(history, "O que decidimos sobre lazer?")
    assert "Você, mensagem 3" in answer
    assert "resposta/sugestão" in answer
    assert "não comprova" in answer
    assert "18 às 19" in answer


def test_disciplines_recovered_from_original_declaration():
    answer = recall_answer(
        turns(("user", "Vou estudar Circuitos Lógicos e Álgebra Linear.")),
        "Quais são minhas disciplinas?",
    )
    assert "Circuitos Lógicos" in answer


def test_no_match_is_explicit_not_invented():
    assert "Não encontrei" in recall_answer(
        turns(("user", "Álgebra linear.")), "O que falamos sobre astronomia?",
    )


def test_context_bounded_and_original_unchanged():
    history = turns(("user", "Meu nome é Marcus."), ("user", "Estudo Álgebra Linear."))
    history += [Turn("therion", "x" * 10_000, index + 3) for index in range(80)]
    snapshot = context_turns(history, "Monte uma rotina de estudo.")
    assert len(snapshot) <= 5
    assert sum(len(turn["text"]) for turn in snapshot) <= 3000
    assert any("Marcus" in turn["text"] for turn in snapshot)
    assert any("Álgebra" in turn["text"] for turn in snapshot)
    assert any("abreviado" in turn["text"] for turn in snapshot)
    assert len(history[-1].text) == 10_000


def test_exact_quotes_can_be_requested_by_topic():
    history = turns(("user", "Estudo matrizes hoje."), ("user", "Outro tema."))
    answer = recall_answer(history, "Mostre exatamente no histórico o que disse sobre matrizes.")
    assert "Estudo matrizes hoje." in answer


def test_ordinary_action_is_not_a_recall_request():
    assert recall_answer([], "Abra o Obsidian.") is None
    assert recall_answer([], "Monte um plano de estudo.") is None


def test_search_is_local_and_returns_original_objects():
    history = turns(("user", "Lazer às 18."), ("user", "Estudo às 19."))
    assert search(history, "lazer")[0] is history[0]


@pytest.mark.parametrize("verb", ["falei", "disse", "comentei"])
def test_author_filters_and_retrieval_feedback(verb):
    history = turns(
        ("user", "Vou estudar Circuitos Lógicos e Álgebra Linear."),
        ("therion", "Plano de Álgebra Linear: estudar matrizes."),
        ("therion", "Álgebra Linear estuda vetores e matrizes."),
    )
    query = "Mostre no histórico o que falei sobre Álgebra Linear."
    recovered = recall_answer(history, query)
    history += [Turn("user", query, 4, origin="session_recall"),
                Turn("therion", recovered, 5, origin="session_recall")]
    answer = recall_answer(history, f"O que eu {verb} sobre Álgebra Linear?")
    assert "Você, mensagem 1" in answer
    assert "mensagem 4" not in answer
    assert "mensagem 5" not in answer
    assert "resposta/sugestão" not in answer.split("\n\n", 1)[1]
    assistant = recall_answer(history, "O que você disse sobre Álgebra Linear?")
    assert "mensagem 2" in assistant and "mensagem 3" in assistant
    assert "Você, mensagem 1" not in assistant
    both = recall_answer(history, "O que falamos sobre Álgebra Linear?")
    assert all(f"mensagem {index}" in both for index in (1, 2, 3))
    assert len(history) == 5


def test_original_history_word_and_empty_author_match():
    history = turns(("user", "Estudo o histórico da Álgebra Linear."))
    assert search(history, "Álgebra")[0] is history[0]
    assert "Não encontrei" in recall_answer(history, "O que você disse sobre Álgebra Linear?")


def test_context_excludes_recall_even_from_recent_window():
    history = turns(("user", "Meu nome é Marcus."))
    history += [Turn("user", "O que falei sobre astronomia?", 2, origin="session_recall"),
                Turn("therion", "Recuperação de astronomia.", 3, origin="session_recall")]
    assert search(history, "astronomia") == []
    assert context_turns(history, "astronomia") == [{"role": "user", "text": "Meu nome é Marcus."}]


def test_orchestrator_marks_recall_pairs_and_preserves_history():
    with tempfile.TemporaryDirectory() as folder:
        orch = Orchestrator(simulate=True, log_dir=folder)
        orch.memory.add_turn("user", "Vou estudar Circuitos Lógicos e Álgebra Linear.")
        orch.memory.add_turn("therion", "Plano de Álgebra Linear.")
        orch.memory.add_turn("therion", "Explicação de Álgebra Linear: matrizes e vetores.")
        orch.ai_core = MagicMock()
        orch.executor = MagicMock()
        orch.process_command("Mostre no histórico o que falei sobre Álgebra Linear.")
        answer = orch.process_command("O que eu falei sobre Álgebra Linear?").message
        assert "Você, mensagem 1" in answer
        assert "mensagem 2" not in answer and "mensagem 4" not in answer
        assert [turn.origin for turn in list(orch.memory.turns)[3:]] == ["session_recall"] * 4
        assert len(orch.memory.turns) == 7
        orch.process_command("qual meu nome?")
        orch.process_command("qual foi a primeira mensagem dessa sessão?")
        assert all(turn.origin == "session_recall" for turn in list(orch.memory.turns)[7:])
        assert orch.ai_core.mock_calls == [] and orch.executor.mock_calls == []
        orch.clear_session()
        assert not orch.memory.turns


def test_integration_no_ai_or_executor_and_clear_removes_facts():
    with tempfile.TemporaryDirectory() as folder:
        orch = Orchestrator(simulate=True, log_dir=folder)
        orch.memory.add_turn("user", "Meu nome é Marcus.")
        for _ in range(60):
            orch.memory.add_turn("therion", "Outro assunto.")
        orch.ai_core = MagicMock()
        orch.executor = MagicMock()
        assert "Marcus" in orch.process_command("qual meu nome?").message
        assert "Marcus" in orch.process_command("Mostre no histórico o que falei sobre nome.").message
        assert orch.ai_core.mock_calls == []
        assert orch.executor.mock_calls == []
        orch.clear_session()
        assert "Não encontrei" in orch.process_command("qual meu nome?").message


def test_pending_interactive_flow_precedes_recall():
    with tempfile.TemporaryDirectory() as folder:
        orch = Orchestrator(simulate=True, log_dir=folder)
        orch.memory.add_turn("user", "Meu nome é Marcus.")
        orch._alias_flow_step = "awaiting_keyword"
        assert "último nome" not in orch.process_command("qual meu nome?").message


def test_context_keeps_corrected_name_instead_of_old_name():
    history = turns(("user", "Meu nome é Marcus."), ("user", "Meu nome é Marcos."))
    history += [Turn("therion", "Outro assunto.", index + 3) for index in range(30)]
    texts = "\n".join(turn["text"] for turn in context_turns(history, "Como posso estudar?"))
    assert "Marcos" in texts
    assert "Marcus" not in texts


def test_retrieval_payloads_keep_limits_and_data_outside_system():
    from therion.core.ai_provider_ollama import OllamaProvider
    provider = OllamaProvider()
    declaration = 'Meu nome é PessoaExclusivaDoHistorico.'
    context = {"session_retrieval": True,
               "recent_turns": [{"role": "user", "text": declaration}]}
    for payload, size in (
        (provider._build_payload("Olá", context, []), 4096),
        (provider._build_plan_payload("Plano", context), 2048),
    ):
        assert payload["options"]["num_ctx"] == size
        assert 'PessoaExclusivaDoHistorico' not in payload["messages"][0]["content"]
        assert "histórico" in payload["messages"][0]["content"].lower()
        assert payload["messages"][1] == {"role": "user", "content": declaration}
