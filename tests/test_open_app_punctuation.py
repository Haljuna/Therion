"""Pontuação de frase na abertura, sem ampliar permissões."""
import pytest

from therion.core.intent import IntentRecognizer
from therion.governance.permissions import PermissionManager


@pytest.mark.parametrize("command", [
    "Abra o Obsidian", "Abra o Obsidian.", "Abra o Obsidian!",
    "Abra o Obsidian?", "abre o obsidian...", "  Abra o Obsidian.  ",
    "Therion, abra o Obsidian!", "Abra o Obsidian?!",
])
def test_abertura_com_pontuacao_preserva_alvo_e_confirmacao(command):
    intent = IntentRecognizer().parse(command)
    permissions = PermissionManager()
    assert intent.action == "abrir aplicativo"
    assert intent.target == "Obsidian"
    assert intent.raw_command == command
    assert intent.requires_confirmation
    assert permissions.is_allowed(intent)
    assert permissions.requires_confirmation(intent)


@pytest.mark.parametrize("command,target", [
    ("Abra o Calculadora.", "Calculadora"),
    ("Abra o obsidian.exe.", "Obsidian.exe"),
    ("Abra o meu.alias!", "Meu.alias"),
])
def test_alvos_desconhecidos_continuam_bloqueados_e_ponto_interno_preservado(command, target):
    intent = IntentRecognizer().parse(command)
    assert intent.target == target
    assert not PermissionManager().is_allowed(intent)


def test_pontuacao_sem_nome_nao_cria_abertura():
    assert IntentRecognizer().parse("Abra ...") is None


def test_busca_preserva_pontuacao_do_termo():
    intent = IntentRecognizer().parse("Busque no segundo cérebro relatorio.pdf.")
    assert intent.target == "relatorio.pdf."
