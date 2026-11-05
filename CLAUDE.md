# Therion

## Visão do código

O Therion é um assistente pessoal local em pt-BR para Windows (estilo Jarvis), com interface desktop em PySide6, voz (STT + TTS) e LLM local no Ollama. O desenho é determinístico primeiro: o modelo só classifica ou prepara, o código revalida tudo, e efeitos reais exigem confirmação humana. Também lê o cofre do Obsidian (Segundo Cérebro) e integra Google Calendar e Gmail, além de uma camada de agente opcional.

**Stack:** Python 3.14 (`.venv`), PySide6, Ollama (produção na :11435), faster-whisper/Parakeet (:3902), TTS Kokoro, Edge ou Jarvis/OmniVoice (:3901), Google API client, Playwright, pywinauto, SQLite e pytest.

**Estrutura:** `therion/core` (orquestrador, o hub), `interface` (UI Qt), `agent` + `integrations` (ferramentas em workers), `voice`, `memory`, `autonomy`, `context`, `calendar`, `skills`, `config`, `governance`, `actions` e `logging`. Os launchers ficam em `scripts/` e os testes em `tests/` (sem conftest).

Para a arquitetura completa, veja [docs/CODEBASE_MAP.md](docs/CODEBASE_MAP.md).

**Regras deste projeto:** siga o [AGENTS.md](AGENTS.md) (governança "Camada Zero"). Rode os testes com `.venv\Scripts\python.exe scripts\test-v4.py tests\...`.
