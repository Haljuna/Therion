"""Testes da CLI — ACK pós-exibição de plano (E1/M5c5c)."""

import unittest
from unittest.mock import MagicMock, patch

from therion.interface.cli import main, run_interaction

_WARNING = (
    "Este plano foi exibido, mas não pôde ser registrado nesta sessão. Por isso, "
    "ele não poderá ser recuperado depois por referências como “mesmo plano”, "
    "“plano anterior” ou “primeiro plano”."
)


class TestCliAckAfterDisplay(unittest.TestCase):
    """ACK do plan_candidate_id somente após o print de result.message."""

    @staticmethod
    def _make_orchestrator(candidate_id: str) -> MagicMock:
        orchestrator = MagicMock()
        orchestrator.process_command.return_value = MagicMock(
            status="success",
            message="Texto do plano.",
            plan=None,
            plan_candidate_id=candidate_id,
        )
        orchestrator.ack_plan_displayed.return_value = MagicMock(
            status="registered"
        )
        return orchestrator

    @staticmethod
    def _record_ack_into(events):
        def _record_ack(candidate_id):
            events.append(("ack", candidate_id))
            return MagicMock(status="registered")

        return _record_ack

    @staticmethod
    def _record_print_into(events):
        def _record_print(*args, **kwargs):
            events.append(("print", args[0] if args else ""))

        return _record_print

    def test_run_interaction_prints_message_before_ack(self) -> None:
        orchestrator = self._make_orchestrator("abc123")
        events = []
        orchestrator.ack_plan_displayed.side_effect = self._record_ack_into(events)

        with patch("therion.interface.cli.Orchestrator", return_value=orchestrator):
            with patch("builtins.print", side_effect=self._record_print_into(events)):
                run_interaction("gere um plano de estudo", "", simulate=True)

        orchestrator.ack_plan_displayed.assert_called_once_with("abc123")
        self.assertEqual(
            events,
            [
                ("print", "Usuário:\ngere um plano de estudo\n"),
                ("print", "Therion:"),
                ("print", "Texto do plano."),
                ("ack", "abc123"),
            ],
        )

    def test_main_prints_message_before_ack(self) -> None:
        orchestrator = self._make_orchestrator("abc123")
        events = []
        orchestrator.ack_plan_displayed.side_effect = self._record_ack_into(events)

        with patch("sys.argv", ["cli"]):
            with patch("therion.interface.cli.Orchestrator", return_value=orchestrator):
                with patch("builtins.input", return_value="gere um plano de estudo"):
                    with patch("builtins.print", side_effect=self._record_print_into(events)):
                        main()

        orchestrator.ack_plan_displayed.assert_called_once_with("abc123")
        self.assertEqual(
            events,
            [
                (
                    "print",
                    "Therion V0 - Interface de Texto (Modo Real Controlado (Windows))",
                ),
                ("print", "\nTherion:"),
                ("print", "Texto do plano."),
                ("ack", "abc123"),
            ],
        )

    def test_run_interaction_rejected_prints_warning(self) -> None:
        orchestrator = self._make_orchestrator("abc123")
        orchestrator.ack_plan_displayed.return_value = MagicMock(
            status="displayed_not_registered",
            reason="count_limit",
        )
        events = []

        with patch("therion.interface.cli.Orchestrator", return_value=orchestrator):
            with patch("builtins.print", side_effect=self._record_print_into(events)):
                run_interaction("gere um plano de estudo", "", simulate=True)

        orchestrator.ack_plan_displayed.assert_called_once_with("abc123")
        printed = [e[1] for e in events if e[0] == "print"]
        self.assertEqual(printed[2], "Texto do plano.")
        self.assertEqual(printed[3], _WARNING)
        self.assertEqual(len(printed), 4)
        for text in printed:
            self.assertNotIn("count_limit", text)

    def test_main_without_candidate_skips_ack(self) -> None:
        orchestrator = self._make_orchestrator(None)
        events = []

        with patch("sys.argv", ["cli"]):
            with patch("therion.interface.cli.Orchestrator", return_value=orchestrator):
                with patch("builtins.input", return_value="gere um plano de estudo"):
                    with patch("builtins.print", side_effect=self._record_print_into(events)):
                        main()

        orchestrator.ack_plan_displayed.assert_not_called()
        printed = [e[1] for e in events if e[0] == "print"]
        self.assertEqual(len(printed), 3)
        self.assertNotIn(_WARNING, printed)

    @staticmethod
    def _record_ack_registered_into(events):
        def _record_ack(plan_id):
            events.append(("ack_registered", plan_id))
            return True

        return _record_ack

    @staticmethod
    def _make_orchestrator_with_registered_plan() -> MagicMock:
        orchestrator = TestCliAckAfterDisplay._make_orchestrator(None)
        orchestrator.process_command.return_value.registered_plan_id = "plan-123"
        return orchestrator

    def _assert_registered_plan_flow(self, orchestrator, events) -> None:
        orchestrator.ack_registered_plan_displayed.assert_called_once_with("plan-123")
        orchestrator.ack_plan_displayed.assert_not_called()
        orchestrator.confirm_and_execute.assert_not_called()
        print_index = events.index(("print", "Texto do plano."))
        ack_index = events.index(("ack_registered", "plan-123"))
        self.assertLess(print_index, ack_index)

    def test_run_interaction_registered_plan_ack_after_print(self) -> None:
        orchestrator = self._make_orchestrator_with_registered_plan()
        events = []
        orchestrator.ack_registered_plan_displayed.side_effect = (
            self._record_ack_registered_into(events)
        )

        with patch("therion.interface.cli.Orchestrator", return_value=orchestrator):
            with patch("builtins.print", side_effect=self._record_print_into(events)):
                run_interaction("mostrar o plano registrado", "", simulate=True)

        self._assert_registered_plan_flow(orchestrator, events)

    def test_main_registered_plan_ack_after_print(self) -> None:
        orchestrator = self._make_orchestrator_with_registered_plan()
        events = []
        orchestrator.ack_registered_plan_displayed.side_effect = (
            self._record_ack_registered_into(events)
        )

        with patch("sys.argv", ["cli"]):
            with patch("therion.interface.cli.Orchestrator", return_value=orchestrator):
                with patch("builtins.input", return_value="mostrar o plano registrado"):
                    with patch("builtins.print", side_effect=self._record_print_into(events)):
                        main()

        self._assert_registered_plan_flow(orchestrator, events)


if __name__ == "__main__":
    unittest.main()
