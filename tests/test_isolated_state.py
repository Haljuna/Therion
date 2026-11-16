"""Os testes nunca usam a configuração, as contas nem os logs reais do usuário."""
import os


def test_appdata_and_temp_point_to_test_folders():
    for variable in ('APPDATA', 'LOCALAPPDATA', 'TEMP', 'TMP'):
        assert 'v4-tests' in os.environ[variable], variable
