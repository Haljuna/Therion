"""Testes do parser de data do IntentRecognizer (correção C3B)."""

import unittest
from therion.core.intent import IntentRecognizer


class TestCalendarDateParsing(unittest.TestCase):
    """Valida extração correta de data em comandos de criação de evento."""

    def setUp(self):
        self.ir = IntentRecognizer()

    def test_1_full_date_with_dia_and_year(self):
        """1. 'dia 15/09/2026' → date=15/09/2026, title limpo."""
        intent = self.ir.parse("marque teste do therion dia 15/09/2026 as 23:30")
        e = intent.entities
        self.assertEqual(e["title"], "Teste do therion")
        self.assertEqual(e["date"], "15/09/2026")
        self.assertEqual(e["start_time"], "23:30")

    def test_2_numeric_date_with_year(self):
        """2. '15/09/2026' sem 'dia' → date=15/09/2026."""
        intent = self.ir.parse("marque reunião 15/09/2026 às 15h")
        e = intent.entities
        self.assertEqual(e["title"], "Reunião")
        self.assertEqual(e["date"], "15/09/2026")
        self.assertEqual(e["start_time"], "15:00")

    def test_3_dia_date_without_year(self):
        """3. 'dia 15/09' → date=15/09."""
        intent = self.ir.parse("marque reunião dia 15/09 às 15h")
        e = intent.entities
        self.assertEqual(e["title"], "Reunião")
        self.assertEqual(e["date"], "15/09")
        self.assertEqual(e["start_time"], "15:00")

    def test_4_dia_only_number(self):
        """4. 'dia 15' → date=dia 15 (formato suportado pelo orchestrator)."""
        intent = self.ir.parse("marque reunião dia 15 às 15h")
        e = intent.entities
        self.assertEqual(e["title"], "Reunião")
        self.assertEqual(e["date"], "dia 15")
        self.assertEqual(e["start_time"], "15:00")

    def test_5_amanha(self):
        """5. 'amanhã' → date=amanhã."""
        intent = self.ir.parse("marque reunião amanhã às 15h")
        e = intent.entities
        self.assertEqual(e["title"], "Reunião")
        self.assertEqual(e["date"], "amanhã")
        self.assertEqual(e["start_time"], "15:00")

    def test_6_hoje(self):
        """6. 'hoje' → date=hoje."""
        intent = self.ir.parse("marque reunião hoje às 15h")
        e = intent.entities
        self.assertEqual(e["title"], "Reunião")
        self.assertEqual(e["date"], "hoje")
        self.assertEqual(e["start_time"], "15:00")

    def test_7_time_h_normalized(self):
        """7. '15h' normalizado para '15:00'."""
        intent = self.ir.parse("marque teste amanhã às 15h")
        e = intent.entities
        self.assertEqual(e["start_time"], "15:00")

    def test_8_time_colon_preserved(self):
        """8. '14:30' preservado."""
        intent = self.ir.parse("marque teste amanhã às 14:30")
        e = intent.entities
        self.assertEqual(e["start_time"], "14:30")

    def test_9_no_title_leak(self):
        """9. Nenhuma parte da data vaza para o título."""
        intent = self.ir.parse("marque teste do therion dia 15/09/2026 às 23:30")
        title = intent.entities["title"]
        self.assertNotIn("/", title)
        self.assertNotIn("dia", title.lower())
        self.assertNotIn("15", title)

    def test_10_calendar_today_still_works(self):
        """10. Comandos de consulta de calendário continuam funcionando."""
        intent = self.ir.parse("o que tenho hoje")
        self.assertEqual(intent.action, "calendário hoje")

    def test_11_calendar_today_variations(self):
        """11. Variações de consulta continuam funcionando."""
        for cmd in ["minha agenda de hoje", "compromissos de hoje", "eventos de hoje"]:
            intent = self.ir.parse(cmd)
            self.assertEqual(intent.action, "calendário hoje", msg=f"Falhou: {cmd}")


if __name__ == "__main__":
    unittest.main()
