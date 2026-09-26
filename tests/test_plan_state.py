"""Testes do estado efêmero de planos da sessão (E1/M3)."""

import unittest

from therion.core.plan_state import PlanSessionState


class TestPlanSessionState(unittest.TestCase):

    def test_single_candidate_created_with_stable_id(self):
        state = PlanSessionState()
        candidate_id = state.set_candidate("Plano de estudo A")
        self.assertIsNotNone(candidate_id)
        self.assertIsNotNone(state.candidate)
        self.assertEqual(state.candidate.candidate_id, candidate_id)
        self.assertEqual(state.candidate.text, "Plano de estudo A")
        first_read = state.candidate.candidate_id
        second_read = state.candidate.candidate_id
        self.assertEqual(first_read, second_read)

    def test_second_candidate_refused_without_replacing_first(self):
        state = PlanSessionState()
        first_id = state.set_candidate("Primeiro plano")
        self.assertIsNotNone(first_id)
        second_id = state.set_candidate("Segundo plano")
        self.assertIsNone(second_id)
        self.assertIsNotNone(state.candidate)
        self.assertEqual(state.candidate.candidate_id, first_id)
        self.assertEqual(state.candidate.text, "Primeiro plano")

    def test_registration_preserves_text_and_order(self):
        state = PlanSessionState()
        text_one = "Linha 1\nLinha 2 com acentuacao e caracteres especiais\n  fim  "
        text_two = "Segundo plano: bloco 1 / bloco 2 / bloco 3"
        id_one = state.set_candidate(text_one)
        res_one = state.register_candidate(id_one)
        id_two = state.set_candidate(text_two)
        res_two = state.register_candidate(id_two)
        self.assertEqual(res_one.status, "registered")
        self.assertEqual(res_two.status, "registered")
        plan_one = res_one.plan_id
        plan_two = res_two.plan_id
        self.assertIsNotNone(plan_one)
        self.assertIsNotNone(plan_two)
        self.assertEqual(state.order, (plan_one, plan_two))
        self.assertEqual(state.get_plan(plan_one).text, text_one)
        self.assertEqual(state.get_plan(plan_two).text, text_two)
        self.assertEqual(state.get_plan(plan_one).plan_id, plan_one)
        self.assertEqual(state.order[0], plan_one)

    def test_current_plan_id_points_to_latest_registration(self):
        state = PlanSessionState()
        self.assertIsNone(state.current_plan_id)
        id_one = state.set_candidate("Plano um")
        res_one = state.register_candidate(id_one)
        self.assertEqual(res_one.status, "registered")
        self.assertEqual(state.current_plan_id, res_one.plan_id)
        id_two = state.set_candidate("Plano dois")
        res_two = state.register_candidate(id_two)
        self.assertEqual(res_two.status, "registered")
        self.assertEqual(state.current_plan_id, res_two.plan_id)

    def test_clear_session_resets_all_state(self):
        state = PlanSessionState()
        id_one = state.set_candidate("Plano registrado um")
        plan_one = state.register_candidate(id_one).plan_id
        id_two = state.set_candidate("Plano registrado dois")
        plan_two = state.register_candidate(id_two).plan_id
        state.set_candidate("Candidate pendente")

        state.clear_session()

        self.assertIsNone(state.candidate)
        self.assertIsNone(state.get_plan(plan_one))
        self.assertIsNone(state.get_plan(plan_two))
        self.assertEqual(state.order, ())
        self.assertIsNone(state.current_plan_id)


class TestRegisterCandidateResult(unittest.TestCase):

    def test_success_with_correct_id(self):
        state = PlanSessionState()
        text = "Linha 1\nLinha 2 acentuada  \n  fim  "
        candidate_id = state.set_candidate(text)
        result = state.register_candidate(candidate_id)
        self.assertEqual(result.status, "registered")
        self.assertIsNotNone(result.plan_id)
        self.assertIsNone(result.reason)
        self.assertEqual(state.get_plan(result.plan_id).text, text)
        self.assertIsNone(state.candidate)
        self.assertEqual(state.order, (result.plan_id,))
        self.assertEqual(state.current_plan_id, result.plan_id)

    def test_missing_candidate(self):
        state = PlanSessionState()
        result = state.register_candidate("qualquer-id")
        self.assertEqual(result.status, "displayed_not_registered")
        self.assertEqual(result.reason, "candidate_missing")
        self.assertIsNone(state.candidate)
        self.assertEqual(state.order, ())
        self.assertIsNone(state.current_plan_id)

    def test_wrong_id_preserves_real_candidate(self):
        state = PlanSessionState()
        candidate_id = state.set_candidate("Candidato real")
        result = state.register_candidate("id-errado")
        self.assertEqual(result.status, "displayed_not_registered")
        self.assertEqual(result.reason, "candidate_mismatch")
        self.assertIsNotNone(state.candidate)
        self.assertEqual(state.candidate.candidate_id, candidate_id)
        self.assertEqual(state.candidate.text, "Candidato real")
        self.assertEqual(state.order, ())
        self.assertIsNone(state.current_plan_id)

    def test_per_plan_limit_accepts_6000(self):
        state = PlanSessionState()
        candidate_id = state.set_candidate("a" * 6000)
        result = state.register_candidate(candidate_id)
        self.assertEqual(result.status, "registered")
        self.assertIsNotNone(result.plan_id)

    def test_per_plan_limit_rejects_6001(self):
        state = PlanSessionState()
        candidate_id = state.set_candidate("a" * 6001)
        result = state.register_candidate(candidate_id)
        self.assertEqual(result.status, "displayed_not_registered")
        self.assertEqual(result.reason, "per_plan_limit")
        self.assertIsNone(state.candidate)
        self.assertIsNone(state.current_plan_id)
        self.assertEqual(state.order, ())

    def test_count_limit_accepts_five(self):
        state = PlanSessionState()
        plan_ids = []
        for i in range(5):
            candidate_id = state.set_candidate(f"Plano {i}")
            result = state.register_candidate(candidate_id)
            self.assertEqual(result.status, "registered")
            plan_ids.append(result.plan_id)
        self.assertEqual(state.order, tuple(plan_ids))
        self.assertEqual(state.current_plan_id, plan_ids[4])

    def test_count_limit_rejects_sixth(self):
        state = PlanSessionState()
        for i in range(5):
            candidate_id = state.set_candidate(f"Plano {i}")
            state.register_candidate(candidate_id)
        order_before = state.order
        current_before = state.current_plan_id

        sixth_id = state.set_candidate("Sexto plano")
        result = state.register_candidate(sixth_id)

        self.assertEqual(result.status, "displayed_not_registered")
        self.assertEqual(result.reason, "count_limit")
        self.assertIsNone(state.candidate)
        self.assertIsNone(state.current_plan_id)
        self.assertEqual(state.order, order_before)
        self.assertEqual(len(state.order), 5)
        for plan_id in order_before:
            self.assertIsNotNone(state.get_plan(plan_id))
        self.assertEqual(current_before, order_before[4])

    def test_total_limit_accepts_exactly_15000(self):
        state = PlanSessionState()
        id_one = state.set_candidate("a" * 6000)
        state.register_candidate(id_one)
        id_two = state.set_candidate("b" * 3000)
        state.register_candidate(id_two)
        id_three = state.set_candidate("c" * 6000)
        result = state.register_candidate(id_three)
        self.assertEqual(result.status, "registered")
        self.assertIsNotNone(result.plan_id)
        total = sum(len(state.get_plan(p).text) for p in state.order)
        self.assertEqual(total, 15000)
        self.assertEqual(state.current_plan_id, result.plan_id)

    def test_total_limit_rejects_15001(self):
        state = PlanSessionState()
        id_one = state.set_candidate("a" * 6000)
        state.register_candidate(id_one)
        id_two = state.set_candidate("b" * 6000)
        state.register_candidate(id_two)
        order_before = state.order

        id_three = state.set_candidate("c" * 3001)
        result = state.register_candidate(id_three)

        self.assertEqual(result.status, "displayed_not_registered")
        self.assertEqual(result.reason, "total_limit")
        self.assertIsNone(state.candidate)
        self.assertIsNone(state.current_plan_id)
        self.assertEqual(state.order, order_before)
        self.assertEqual(len(state.order), 2)
        for plan_id in order_before:
            self.assertIsNotNone(state.get_plan(plan_id))

    def test_repeated_ack_after_terminal_rejection(self):
        state = PlanSessionState()
        candidate_id = state.set_candidate("a" * 6001)
        first = state.register_candidate(candidate_id)
        self.assertEqual(first.status, "displayed_not_registered")
        self.assertEqual(first.reason, "per_plan_limit")
        self.assertIsNone(state.candidate)

        second = state.register_candidate(candidate_id)
        self.assertEqual(second.status, "displayed_not_registered")
        self.assertEqual(second.reason, "candidate_missing")

        self.assertEqual(state.order, ())
        self.assertIsNone(state.current_plan_id)
        self.assertIsNone(first.plan_id)
        self.assertIsNone(second.plan_id)


class TestAckRegisteredPlanDisplayed(unittest.TestCase):
    """ack_registered_plan_displayed (E1/M6b)."""

    def test_existing_plan_id_updates_current(self) -> None:
        state = PlanSessionState()
        candidate_id = state.set_candidate("Plano A")
        plan_id = state.register_candidate(candidate_id).plan_id

        ok = state.ack_registered_plan_displayed(plan_id)

        self.assertTrue(ok)
        self.assertEqual(state.current_plan_id, plan_id)

    def test_missing_plan_id_keeps_state(self) -> None:
        state = PlanSessionState()
        id_one = state.set_candidate("Plano A")
        plan_one = state.register_candidate(id_one).plan_id
        id_two = state.set_candidate("Plano B")
        plan_two = state.register_candidate(id_two).plan_id
        current_before = state.current_plan_id
        order_before = state.order
        text_one = state.get_plan(plan_one).text
        text_two = state.get_plan(plan_two).text

        ok = state.ack_registered_plan_displayed("nao-existe")

        self.assertFalse(ok)
        self.assertEqual(state.current_plan_id, current_before)
        self.assertEqual(state.order, order_before)
        self.assertEqual(state.get_plan(plan_one).text, text_one)
        self.assertEqual(state.get_plan(plan_two).text, text_two)

    def test_preserves_candidate_order_and_plans(self) -> None:
        state = PlanSessionState()
        id_one = state.set_candidate("Primeiro plano")
        plan_one = state.register_candidate(id_one).plan_id
        id_two = state.set_candidate("Segundo plano")
        plan_two = state.register_candidate(id_two).plan_id
        self.assertEqual(state.current_plan_id, plan_two)
        pending_id = state.set_candidate("Candidate pendente")
        order_before = state.order
        plans_before = {p: state.get_plan(p).text for p in state.order}

        ok = state.ack_registered_plan_displayed(plan_one)

        self.assertTrue(ok)
        self.assertEqual(state.current_plan_id, plan_one)
        self.assertIsNotNone(state.candidate)
        self.assertEqual(state.candidate.candidate_id, pending_id)
        self.assertEqual(state.candidate.text, "Candidate pendente")
        self.assertEqual(state.order, order_before)
        self.assertEqual(
            {p: state.get_plan(p).text for p in state.order}, plans_before
        )
        self.assertEqual(len(state.order), 2)


class TestResolvePlanReference(unittest.TestCase):
    """resolve_plan_reference — selectors positivos (E1/M7b2a)."""

    @staticmethod
    def _make_state_with_three_plans() -> tuple:
        state = PlanSessionState()
        plan_ids = []
        for i in range(3):
            candidate_id = state.set_candidate(f"Plano {i}")
            result = state.register_candidate(candidate_id)
            plan_ids.append(result.plan_id)
        return state, tuple(plan_ids)

    def test_first_returns_first_plan_id(self) -> None:
        state, plan_ids = self._make_state_with_three_plans()

        resolved = state.resolve_plan_reference("first")

        self.assertEqual(resolved, plan_ids[0])

    def test_second_returns_second_plan_id(self) -> None:
        state, plan_ids = self._make_state_with_three_plans()

        resolved = state.resolve_plan_reference("second")

        self.assertEqual(resolved, plan_ids[1])

    def test_last_returns_last_plan_id(self) -> None:
        state, plan_ids = self._make_state_with_three_plans()

        resolved = state.resolve_plan_reference("last")

        self.assertEqual(resolved, plan_ids[2])

    def test_same_returns_current_plan_id(self) -> None:
        state, plan_ids = self._make_state_with_three_plans()
        self.assertTrue(state.ack_registered_plan_displayed(plan_ids[1]))
        self.assertEqual(state.current_plan_id, plan_ids[1])

        resolved = state.resolve_plan_reference("same")

        self.assertEqual(resolved, plan_ids[1])

    def test_previous_returns_predecessor_of_current(self) -> None:
        state, plan_ids = self._make_state_with_three_plans()
        self.assertTrue(state.ack_registered_plan_displayed(plan_ids[2]))
        self.assertEqual(state.current_plan_id, plan_ids[2])

        resolved = state.resolve_plan_reference("previous")

        self.assertEqual(resolved, plan_ids[1])


class TestResolvePlanReferenceEdgeCases(unittest.TestCase):
    """resolve_plan_reference — impossíveis, ValueError e pureza (E1/M7b2b)."""

    @staticmethod
    def _register(state: PlanSessionState, text: str) -> str:
        candidate_id = state.set_candidate(text)
        return state.register_candidate(candidate_id).plan_id

    def test_empty_state_resolves_none(self) -> None:
        state = PlanSessionState()

        self.assertIsNone(state.resolve_plan_reference("first"))
        self.assertIsNone(state.resolve_plan_reference("last"))
        self.assertIsNone(state.resolve_plan_reference("same"))
        self.assertIsNone(state.resolve_plan_reference("previous"))

    def test_second_with_single_plan_resolves_none(self) -> None:
        state = PlanSessionState()
        self._register(state, "Plano único")

        self.assertIsNone(state.resolve_plan_reference("second"))

    def test_previous_on_first_plan_resolves_none(self) -> None:
        state = PlanSessionState()
        plan_one = self._register(state, "Primeiro plano")
        self._register(state, "Segundo plano")
        self.assertTrue(state.ack_registered_plan_displayed(plan_one))
        self.assertEqual(state.current_plan_id, plan_one)

        self.assertIsNone(state.resolve_plan_reference("previous"))

    def test_unknown_selector_raises_value_error(self) -> None:
        state = PlanSessionState()
        self._register(state, "Plano A")

        with self.assertRaises(ValueError):
            state.resolve_plan_reference("third")

    def test_resolution_does_not_mutate_state(self) -> None:
        state = PlanSessionState()
        plan_one = self._register(state, "Plano A")
        plan_two = self._register(state, "Plano B")
        plan_three = self._register(state, "Plano C")
        self.assertTrue(state.ack_registered_plan_displayed(plan_two))
        pending_id = state.set_candidate("Candidate pendente")

        order_before = state.order
        current_before = state.current_plan_id
        candidate_before = (state.candidate.candidate_id, state.candidate.text)
        plans_before = {p: state.get_plan(p).text for p in state.order}

        resolved = state.resolve_plan_reference("previous")

        self.assertEqual(resolved, plan_one)
        self.assertEqual(state.order, order_before)
        self.assertEqual(state.current_plan_id, current_before)
        self.assertIsNotNone(state.candidate)
        self.assertEqual(state.candidate.candidate_id, candidate_before[0])
        self.assertEqual(state.candidate.text, candidate_before[1])
        self.assertEqual(
            {p: state.get_plan(p).text for p in state.order}, plans_before
        )
        self.assertEqual(state.order, (plan_one, plan_two, plan_three))


if __name__ == "__main__":
    unittest.main()
