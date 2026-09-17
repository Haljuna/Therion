"""Testes do parser de criação de evento do IntentRecognizer (A2.10)."""

import unittest
from therion.core.intent import IntentRecognizer


class TestCreateEventParsing(unittest.TestCase):
    """Valida reconhecimento, rejeição e extração de eventos incompletos."""

    def setUp(self):
        self.ir = IntentRecognizer()

    # --- Compatibilidade com comandos já suportados ---

    def test_imperative_full_with_fields(self):
        """"crie Teste amanhã às 15h" preserva title, date, start_time."""
        intent = self.ir.parse("crie Teste amanhã às 15h")
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities["title"], "Teste")
        self.assertEqual(intent.entities["date"], "amanhã")
        self.assertEqual(intent.entities["start_time"], "15:00")

    def test_imperative_calendar_keyword(self):
        """"marque reunião amanhã às 10h" extrai corretamente."""
        intent = self.ir.parse("marque reunião amanhã às 10h")
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities["title"], "Reunião")
        self.assertEqual(intent.entities["date"], "amanhã")
        self.assertEqual(intent.entities["start_time"], "10:00")

    def test_imperative_agende_dentista(self):
        """"agende o dentista" gera evento local com título "O Dentista"."""
        intent = self.ir.parse("agende o dentista")
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities["title"], "O dentista")

    def test_imperative_agende_compromisso(self):
        """"agende um compromisso" gera evento sem campos."""
        intent = self.ir.parse("agende um compromisso")
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertNotIn("title", intent.entities)

    # --- Frases naturais com keyword ---

    def test_natural_quero_criar_evento(self):
        """"quero criar um evento" inicia coleta vazia."""
        intent = self.ir.parse("quero criar um evento")
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities, {})

    def test_natural_preciso_agendar_reuniao(self):
        """"preciso agendar uma reunião" gera título padrão "Reunião"."""
        intent = self.ir.parse("preciso agendar uma reunião")
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities["title"], "Reunião")

    def test_natural_vou_marcar_compromisso(self):
        """"vou marcar um compromisso" inicia coleta vazia."""
        intent = self.ir.parse("vou marcar um compromisso")
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertNotIn("title", intent.entities)

    def test_natural_pode_criar_evento_punctuation(self):
        """"pode criar um evento?" aceita pontuação final e preserva raw_command."""
        intent = self.ir.parse("pode criar um evento?")
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.raw_command, "pode criar um evento?")

    def test_natural_gostaria_agendar(self):
        """"gostaria de agendar um evento" inicia coleta vazia."""
        intent = self.ir.parse("gostaria de agendar um evento")
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertNotIn("title", intent.entities)

    # --- Rejeição de artefatos não-calendário ---

    def test_reject_nota(self):
        """"crie uma nota" → None."""
        self.assertIsNone(self.ir.parse("crie uma nota"))

    def test_reject_nota_with_text(self):
        """"crie uma nota sobre OAuth" → None."""
        self.assertIsNone(self.ir.parse("crie uma nota sobre OAuth"))

    def test_reject_arquivo(self):
        """"crie um arquivo" → None."""
        self.assertIsNone(self.ir.parse("crie um arquivo"))

    def test_reject_documento_with_text(self):
        """"crie um documento do projeto" → None."""
        self.assertIsNone(self.ir.parse("crie um documento do projeto"))

    def test_reject_pasta_with_text(self):
        """"crie uma pasta para testes" → None."""
        self.assertIsNone(self.ir.parse("crie uma pasta para testes"))

    def test_reject_criar_arquivo(self):
        """"criar arquivo" → None."""
        self.assertIsNone(self.ir.parse("criar arquivo"))

    # --- Preservação de raw_command ---

    def test_raw_command_preserved_with_punctuation(self):
        """raw_command preserva texto original incluindo pontuação."""
        intent = self.ir.parse("pode criar um evento?")
        self.assertEqual(intent.raw_command, "pode criar um evento?")

    def test_raw_command_preserved_imperative(self):
        """raw_command preserva texto original do imperativo."""
        intent = self.ir.parse("crie Teste amanhã às 15h")
        self.assertEqual(intent.raw_command, "crie Teste amanhã às 15h")


if __name__ == "__main__":
    unittest.main()
