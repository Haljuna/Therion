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

    # --- Delimitadores e cláusulas de ausência de horário ---

    def test_natural_evento_com_virgula_e_clausula_ausencia(self):
        """"Quero criar um evento, mas ainda não sei a hora." entra no fluxo sem title."""
        intent = self.ir.parse("Quero criar um evento, mas ainda não sei a hora.")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities, {})

    def test_natural_evento_com_ponto(self):
        """"Quero criar um evento." entra no fluxo sem title."""
        intent = self.ir.parse("Quero criar um evento.")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities, {})

    def test_natural_evento_virgula_com_data_e_hora(self):
        """"Quero criar um evento, amanhã às 15h." extrai data e hora sem inventar title."""
        intent = self.ir.parse("Quero criar um evento, amanhã às 15h.")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities["date"], "amanhã")
        self.assertEqual(intent.entities["start_time"], "15:00")
        self.assertNotIn("title", intent.entities)

    def test_natural_evento_dois_pontos_com_titulo_data_e_hora(self):
        """"Quero criar um evento: Prova de circuitos amanhã às 15h." preserva title."""
        intent = self.ir.parse("Quero criar um evento: Prova de circuitos amanhã às 15h.")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities["title"], "Prova de circuitos")
        self.assertEqual(intent.entities["date"], "amanhã")
        self.assertEqual(intent.entities["start_time"], "15:00")

    def test_natural_evento_sem_horario_preserva_titulo(self):
        """"Quero criar um evento: Sem Horário" preserva "Sem Horário" como título."""
        intent = self.ir.parse("Quero criar um evento: Sem Horário")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities.get("title"), "Sem Horário")

    def test_natural_evento_titulo_e_clausula_ausencia(self):
        """"Quero criar um evento Prova, mas ainda não sei a hora" preserva "Prova"."""
        intent = self.ir.parse("Quero criar um evento Prova, mas ainda não sei a hora")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities.get("title"), "Prova")

    def test_reject_eventoabc(self):
        """"eventoabc" isolado e no fluxo natural continuam rejeitados."""
        self.assertIsNone(self.ir.parse("eventoabc"))
        self.assertIsNone(self.ir.parse("Quero criar um eventoabc"))

    def test_imperative_preserves_eventoabc(self):
        """"crie um eventoabc" é interpretado pelo fluxo imperativo com título "Um eventoabc"."""
        intent = self.ir.parse("crie um eventoabc")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "criar evento calendário")
        self.assertEqual(intent.entities.get("title"), "Um eventoabc")

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


class TestPlanDayParsing(unittest.TestCase):
    """Valida reconhecimento da intent planejar dia (SKILL-002)."""

    def setUp(self):
        self.ir = IntentRecognizer()

    def test_planeje_meu_dia(self):
        """'planeje meu dia' retorna action='planejar dia'."""
        intent = self.ir.parse("planeje meu dia")
        self.assertEqual(intent.action, "planejar dia")
        self.assertEqual(intent.target, "")
        self.assertFalse(intent.requires_confirmation)
        self.assertEqual(intent.raw_command, "planeje meu dia")

    def test_organize_meu_dia(self):
        """'organize meu dia' retorna action='planejar dia'."""
        intent = self.ir.parse("organize meu dia")
        self.assertEqual(intent.action, "planejar dia")
        self.assertEqual(intent.target, "")
        self.assertFalse(intent.requires_confirmation)

    def test_prepare_meu_dia(self):
        """'prepare meu dia' retorna action='planejar dia'."""
        intent = self.ir.parse("prepare meu dia")
        self.assertEqual(intent.action, "planejar dia")
        self.assertEqual(intent.target, "")
        self.assertFalse(intent.requires_confirmation)

    def test_with_therion_prefix(self):
        """'Therion, planeje meu dia' é reconhecido."""
        intent = self.ir.parse("Therion, planeje meu dia")
        self.assertEqual(intent.action, "planejar dia")
        self.assertEqual(intent.raw_command, "Therion, planeje meu dia")

    def test_with_punctuation(self):
        """'planeje meu dia.' aceita pontuação final."""
        intent = self.ir.parse("planeje meu dia.")
        self.assertEqual(intent.action, "planejar dia")

    def test_planeje_meu_trabalho_not_recognized(self):
        """'planeje meu trabalho' não é reconhecido."""
        self.assertIsNone(self.ir.parse("planeje meu trabalho"))

    def test_organize_sem_dia_not_recognized(self):
        """'organize minhas tarefas' não é reconhecido."""
        self.assertIsNone(self.ir.parse("organize minhas tarefas"))


class TestOpenAppFlexion(unittest.TestCase):
    """Valida flexão 'abre' e targets vagos no IntentRecognizer."""

    def setUp(self):
        self.ir = IntentRecognizer()

    def test_abre_aquilo(self):
        """'abre aquilo' → abrir aplicativo / Aquilo."""
        intent = self.ir.parse("abre aquilo")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")
        self.assertEqual(intent.target, "Aquilo")

    def test_abre_isso(self):
        """'abre isso' → abrir aplicativo / Isso."""
        intent = self.ir.parse("abre isso")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")
        self.assertEqual(intent.target, "Isso")

    def test_abra_aquilo_mantido(self):
        """'abra aquilo' continua funcionando."""
        intent = self.ir.parse("abra aquilo")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")
        self.assertEqual(intent.target, "Aquilo")

    def test_abrir_isso_mantido(self):
        """'abrir isso' continua funcionando."""
        intent = self.ir.parse("abrir isso")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")
        self.assertEqual(intent.target, "Isso")

    def test_abre_obsidian(self):
        """'abre Obsidian' → abrir aplicativo / Obsidian."""
        intent = self.ir.parse("abre Obsidian")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "abrir aplicativo")
        self.assertEqual(intent.target, "Obsidian")

    def test_vague_targets_list(self):
        """VAGUE_TARGETS contém apenas 'isso' e 'aquilo'."""
        self.assertEqual(self.ir.VAGUE_TARGETS, {"isso", "aquilo"})


if __name__ == "__main__":
    unittest.main()
