import os

from therion.autonomy.browser_windows import same_app

STUB = os.path.normcase(r'c:\users\u\appdata\local\google\gemini\gemini.exe')


def test_squirrel_app_folder_matches_registered_stub():
    assert same_app(STUB, os.path.normcase(r'c:\users\u\appdata\local\google\gemini\app-1.17.0\gemini.exe'))


def test_other_executables_do_not_match():
    assert same_app(STUB, STUB)
    assert not same_app(STUB, os.path.normcase(r'c:\users\u\appdata\local\google\gemini\app-1.17.0\geminiapplauncher.exe'))
    assert not same_app(STUB, os.path.normcase(r'c:\users\u\appdata\local\google\gemini\outra\gemini.exe'))
    assert not same_app(STUB, os.path.normcase(r'c:\temp\app-1\gemini.exe'))
